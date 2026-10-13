"""
服务端账号与 App 本地账号的对接。

## 这一段锁定的真实故障（2026-10-13）

App 的账号体系是**纯本地**的（`AuthService` 存在手机文件里），
而额度记在服务端（`.cache/accounts.json`）。两边从来没接通过，
后果是：

    用户在 App 里明明登录了，点「上传并分析」却收到「请先登录」。

而且这句提示**完全指不出问题在哪** —— 用户会去反复检查登录状态，
而真正的原因是服务端根本不认识这个账号（它只认自己注册过的）。

更隐蔽的是：`submitAnalysis` 的 payload 里压根没有 username 字段，
所以哪怕用户在服务端注册过，也一样提交不了。

## 修法

1. App 侧：把当前用户的 username 带进提交（见 upload_page / app_shell）
2. 服务端：首次见到某个 username 时**自动建号**

第 2 条的信任级别与服务本身一致 —— 它本来就是「无认证、仅供局域网内
短期使用」（启动时会打印 WARN），手机上存密码并不会让它更安全。
额度仍由服务端裁定并累计，客户端改不了。
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.server import app as server_app  # noqa: E402


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """独立的上传目录与账号文件 —— 不污染开发数据。"""
    monkeypatch.setattr(server_app, "UPLOAD_DIR", tmp_path / "uploads")
    server_app.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server_app, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(server_app, "ACCOUNTS",
                        server_app.AccountStore(tmp_path / "accounts.json"))
    monkeypatch.setattr(server_app, "KEYFRAMES_ROOT", tmp_path / "keyframes")
    server_app.KEYFRAMES_ROOT.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_app.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _post(url: str, data: bytes, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def _upload(base: str) -> str:
    """上传一段占位内容，拿到服务端生成的 video_id。

    内容不必是真视频 —— 这个测试只关心**账号检查那一步**，
    它在读文件之前就返回了。
    """
    blob = b"\x00" * 2048
    code, body = _post(f"{base}/api/videos", blob,
                       {"Content-Type": "application/octet-stream",
                        "X-Filename": "x.mp4"})
    assert code == 201, f"上传失败：{code} {body}"
    return body["video_id"]


def _analyze(base: str, username: str | None, video_id: str) -> tuple[int, dict]:
    payload = {"video_id": video_id}
    if username is not None:
        payload["username"] = username
    return _post(f"{base}/api/analyze", json.dumps(payload).encode(),
                 {"Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# 没有 username —— 必须仍然拒绝
# ---------------------------------------------------------------------------

def test_missing_username_still_rejected(server):
    """没有 username 就不能提交 —— 额度按账号记，没账号无从扣减。"""
    vid = _upload(server)
    code, body = _analyze(server, None, vid)
    assert code == 401
    assert "登录" in body["error"]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_username_rejected(server, blank):
    """空白用户名与缺失同义，不能建出一个空名账号。"""
    vid = _upload(server)
    code, body = _analyze(server, blank, vid)
    assert code == 401
    assert "登录" in body["error"]


def test_blank_username_does_not_create_account(server):
    """
    空白用户名不该在账号表里留下任何东西。

    否则账号表会被垃圾键污染（`""` 这种键还能被 get 命中，
    变成一个"人人可用"的共享账号，额度就形同虚设）。
    """
    vid = _upload(server)
    _analyze(server, "   ", vid)
    assert server_app.ACCOUNTS.get("") is None
    assert server_app.ACCOUNTS.get("   ") is None


# ---------------------------------------------------------------------------
# 首次提交自动建号
# ---------------------------------------------------------------------------

def test_unknown_username_creates_account(server):
    """
    App 的本地账号在服务端不存在时，首次提交自动建号。

    这是本次修复的核心：App 账号是纯本地的，服务端从没见过它。
    旧行为是一律回 401，导致「登录了却说没登录」。

    调用拿到的应当是 202（已受理）—— 说明账号检查、视频检查、
    扣额度全都走过了，任务已起。

    ⚠️ 上传的是**占位内容**而非真视频，所以后台任务随后会失败
       （"无法打开视频"）。这没关系：账号与额度在这一刻已经成立，
       而任务失败与否是另一条链路的事。
       另注意服务端**不会**因任务失败退还额度（见 app.py 扣额度处
       的注释），所以下面的断言是稳定的。
    """
    vid = _upload(server)
    code, body = _analyze(server, "appuser", vid)
    assert code == 202, f"自动建号后应当受理，实际 {code} {body}"

    acc = server_app.ACCOUNTS.get("appuser")
    assert acc is not None, "首次提交应当自动建号"
    assert acc.tier == "free"
    assert acc.used_this_month == 1, "受理一次应当扣一次额度"


def test_auto_created_account_is_reusable(server):
    """
    自动建的号能被后续请求复用，不会每次都新建。

    先建号、记下额度，再用同一个名字提交一次：
    额度应当累计到 2，而不是被重置。
    """
    vid = _upload(server)

    assert _analyze(server, "reuse", vid)[0] == 202
    acc = server_app.ACCOUNTS.get("reuse")
    assert acc.used_this_month == 1

    # 第二次提交前把 used 记下来，验证它是累加而不是重置
    assert _analyze(server, "reuse", vid)[0] == 202
    acc = server_app.ACCOUNTS.get("reuse")
    assert acc.used_this_month == 2, "额度应当累计"


def test_second_user_gets_own_account(server):
    """不同用户名各建各的号，额度互不影响。"""
    vid = _upload(server)
    _analyze(server, "alice", vid)
    _analyze(server, "bob", vid)

    a = server_app.ACCOUNTS.get("alice")
    b = server_app.ACCOUNTS.get("bob")
    assert a is not None and b is not None
    assert a.username != b.username
    assert a.used_this_month == 1
    assert b.used_this_month == 1


def test_existing_account_not_overwritten(server):
    """
    已存在的账号不能被自动建号覆盖。

    否则用户用兑换码升的会员等级，会在下次提交时被打回 free ——
    这类"静默降级"极难排查。
    """
    code, body = _post(
        f"{server}/api/auth/register",
        json.dumps({"username": "vip", "password": "password123"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 201

    acc = server_app.ACCOUNTS.get("vip")
    acc.tier = "premium"
    server_app.ACCOUNTS.upsert(acc)

    vid = _upload(server)
    _analyze(server, "vip", vid)

    after = server_app.ACCOUNTS.get("vip")
    assert after.tier == "premium", "自动建号不得覆盖已有账号的等级"


def test_auto_created_quota_is_still_enforced(server):
    """
    自动建的号同样受额度限制。

    这条是"自动建号"没有变成"无限额度后门"的保证：
    免费额度用完后必须被拒（402），而不是每次建个新号绕过去。
    """
    vid = _upload(server)
    assert _analyze(server, "quota_user", vid)[0] == 202   # 触发建号并扣一次

    acc = server_app.ACCOUNTS.get("quota_user")
    assert acc is not None

    # 把额度耗光
    acc.used_this_month = acc.quota()
    server_app.ACCOUNTS.upsert(acc)

    code, body = _analyze(server, "quota_user", vid)
    assert code == 402, f"额度用尽应当返回 402，实际 {code} {body}"
    assert "额度" in body["error"]
