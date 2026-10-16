"""
分析服务端的测试。

覆盖两类：
  1. 不需要模型的接口行为（健康检查、参数校验、路径穿越防护）
     —— 这些必须能快速、独立地测
  2. 完整的"上传 → 分析 → 取报告"流程
     —— 这条走真模型，慢（约 10 秒），单独标记

为什么路径穿越防护要单独测：
    /api/analyze 接受 video_id，服务端据此在自己目录里找文件。
    如果不校验，调用方可以传 "../../../Windows/System32/config/SAM"
    让服务读取任意文件并当作视频返回 —— 这台机器上的一切都能被读走。
    服务默认监听 0.0.0.0（局域网可访问），所以这是一条真实的安全边界。
"""

from __future__ import annotations

import json
import sys
import threading
import time
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
    """
    起一个测试用的服务实例。

    用独立的临时上传目录，避免污染真实的上传目录 ——
    否则跑一次测试就会把开发机上待分析的素材删掉。
    """
    monkeypatch.setattr(server_app, "UPLOAD_DIR", tmp_path / "uploads")
    server_app.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 账号文件也要隔离 —— 否则测试会往真实的 .cache/accounts.json 里
    # 写测试账号，跑一次测试就污染一次开发数据。
    monkeypatch.setattr(server_app, "ACCOUNTS_FILE",
                        tmp_path / "accounts.json")
    monkeypatch.setattr(server_app, "ACCOUNTS",
                        server_app.AccountStore(tmp_path / "accounts.json"))

    # 关键帧目录同样隔离
    monkeypatch.setattr(server_app, "KEYFRAMES_ROOT",
                        tmp_path / "keyframes")
    monkeypatch.setattr(server_app, "DATASET_ROOT", tmp_path / "dataset")
    server_app.KEYFRAMES_ROOT.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_app.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    yield f"http://127.0.0.1:{port}"

    httpd.shutdown()
    httpd.server_close()


#: 测试账号。分析接口现在要求登录，测试要带一个账号。
_TEST_USER = "tester"
_TEST_PASS = "test123456"


def _register(base: str, username: str = _TEST_USER,
              password: str = _TEST_PASS) -> dict:
    """注册一个测试账号，返回 account 字段。"""
    code, body = _post(
        f"{base}/api/auth/register",
        json.dumps({"username": username, "password": password}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 201, f"注册测试账号失败：{code} {body}"
    return body["account"]


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


def _post(url: str, data: bytes, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body}


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

def test_manual_review_http_and_dataset(server, tmp_path):
    from backend.tests.test_manual_timing import make_video, review
    source = tmp_path / "source.avi"
    make_video(source)
    code, upload = _post(f"{server}/api/videos", source.read_bytes(), {"X-Filename": "source.avi"})
    assert code == 201
    video_id = upload["video_id"]
    code, meta = _get(f"{server}/api/videos/{video_id}/metadata")
    assert code == 200 and meta["fps"] == 240
    with urllib.request.urlopen(f"{server}/api/videos/{video_id}/frames/96") as response:
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.read().startswith(b"\xff\xd8")
    assert _get(f"{server}/api/videos/{video_id}/frames/9999")[0] == 400
    params = {"username": "manualtester", "video_id": video_id,
              "view": "side", "camera_followed": False,
              "analysis_mode": "manual_side_v1", "manual_review": review(),
              "target_selection": {"protocol": "athlete_lock_v1", "frame": 0, "end_frame": 143,
                                   "bbox": [.1,.1,.3,.9], "confirmed": True}}
    params["manual_review"]["all_contacts_confirmed"] = False
    code, _ = _post(f"{server}/api/analyze", json.dumps(params).encode())
    assert code == 400
    assert server_app.ACCOUNTS.get("manualtester").used_this_month == 0
    params["manual_review"] = review()
    code, body = _post(f"{server}/api/analyze", json.dumps(params).encode())
    assert code == 202, body
    job = server_app.JOBS.get(body["job_id"])
    deadline = time.time() + 10
    while job.status not in ("done", "failed") and time.time() < deadline:
        time.sleep(.01)
    assert job.status == "done", job.error
    archive = server_app.DATASET_ROOT / job.job_id
    assert (archive / "video.avi").read_bytes() == source.read_bytes()
    assert json.loads((archive / "review.json").read_text(encoding="utf-8"))["review"] == review()
    assert json.loads((archive / "review.json").read_text(encoding="utf-8"))["target_selection"] == params["target_selection"]
    assert (archive / "report.json").is_file()
    assert len(job.report["keyframes"]) == 6
    assert server_app.ACCOUNTS.get("manualtester").used_this_month == 1


@pytest.mark.parametrize("changes", [
    {"frame": True}, {"frame": -1}, {"end_frame": 999},
    {"confirmed": False}, {"bbox": [0,0,float("nan"),1]},
    {"bbox": [1,1,0,0]},
])
def test_bad_target_selection_does_not_consume_quota(server, tmp_path, changes):
    from backend.tests.test_manual_timing import make_video
    source = tmp_path / "source.avi"
    make_video(source)
    code, upload = _post(f"{server}/api/videos", source.read_bytes(), {"X-Filename": "source.avi"})
    assert code == 201
    params = {"username": "targettester", "video_id": upload["video_id"],
              "view": "side", "camera_followed": False,
              "target_selection": {"protocol": "athlete_lock_v1", "frame": 0, "end_frame": 143,
                                   "bbox": [.1,.1,.3,.9], "confirmed": True, **changes}}
    code, body = _post(f"{server}/api/analyze", json.dumps(params).encode())
    assert code == 400, body
    assert server_app.ACCOUNTS.get("targettester").used_this_month == 0

@pytest.mark.parametrize("options", [
    {},
    {"estimator": "yolo", "model": "yolov8s-pose.pt", "imgsz": 1280},
    {"estimator": "rtm", "rtm_mode": "balanced"},
])
def test_model_selection_reaches_pipeline(server, monkeypatch, options):
    from backend.analysis import analyze
    from backend.analysis.pose_options import pose_options_from_params
    received = {}

    def fake_pipeline(**kwargs):
        received.update(kwargs)
        return {"versions": {"model_version": "test"}}

    monkeypatch.setattr(analyze, "run_pipeline", fake_pipeline)
    upload_code, upload = _post(f"{server}/api/videos", b"test" * 512,
                                {"X-Filename": "test.mp4"})
    assert upload_code == 201, upload
    code, body = _post(f"{server}/api/analyze", json.dumps({
        "username": "modeltester", "video_id": upload["video_id"], **options,
    }).encode(), {"Content-Type": "application/json"})
    assert code == 202, body
    job = server_app.JOBS.get(body["job_id"])
    deadline = time.time() + 5
    while job.status not in ("done", "failed") and time.time() < deadline:
        time.sleep(0.01)
    assert job.status == "done", job.error
    for key, value in pose_options_from_params(options).items():
        assert received[key] == value


@pytest.mark.parametrize("options", [
    {"estimator": "unknown"}, {"model": "../../other.pt"},
    {"imgsz": 641}, {"imgsz": 960.5}, {"imgsz": True},
    {"rtm_mode": "unknown"},
    {"estimator": "rtm", "model": "yolov8n-pose.pt"},
])
def test_invalid_model_options_do_not_consume_quota(server, options):
    _register(server)
    upload_code, upload = _post(f"{server}/api/videos", b"test" * 512,
                                {"X-Filename": "test.mp4"})
    assert upload_code == 201, upload
    code, body = _post(f"{server}/api/analyze", json.dumps({
        "username": _TEST_USER, "video_id": upload["video_id"], **options,
    }).encode(), {"Content-Type": "application/json"})
    assert code == 400, body
    assert server_app.ACCOUNTS.get(_TEST_USER).used_this_month == 0


@pytest.mark.parametrize("options", [
    {"complete_run": "true"}, {"athlete_age": True}, {"athlete_age": -1},
    {"athlete_age": float("nan")}, {"running_condition": "heavy"},
    {"running_condition": "resisted"},
    {"running_condition": "unloaded", "load_protocol": "vdec_20pct"},
])
def test_invalid_reference_options_do_not_consume_quota(server, options):
    _register(server)
    code, _ = _post(f"{server}/api/analyze", json.dumps({
        "username": _TEST_USER, **options,
    }).encode(), {"Content-Type": "application/json"})
    assert code == 400
    assert server_app.ACCOUNTS.get(_TEST_USER).used_this_month == 0


@pytest.mark.parametrize("population,confirmed", [
    ({}, False),
    ({"gender": "female", "level": "amateur", "event": "200m"}, True),
])
def test_reference_options_reach_pipeline(server, monkeypatch, population, confirmed):
    from backend.analysis import analyze
    received = {}

    def fake_pipeline(**kwargs):
        received.update(kwargs)
        return {}

    monkeypatch.setattr(analyze, "run_pipeline", fake_pipeline)
    code, upload = _post(f"{server}/api/videos", b"test" * 512,
                          {"X-Filename": "test.mp4"})
    assert code == 201
    code, body = _post(f"{server}/api/analyze", json.dumps({
        "username": "reftester", "video_id": upload["video_id"],
        "athlete_age": 23, "running_condition": "resisted",
        "load_protocol": "vdec_20pct", "complete_run": True, **population,
    }).encode(), {"Content-Type": "application/json"})
    assert code == 202
    job = server_app.JOBS.get(body["job_id"])
    deadline = time.time() + 5
    while job.status not in ("done", "failed") and time.time() < deadline:
        time.sleep(.01)
    assert job.status == "done", job.error
    assert received["population_confirmed"] is confirmed
    assert received["athlete_age"] == 23
    assert received["running_condition"] == "resisted"
    assert received["load_protocol"] == "vdec_20pct"
    assert received["complete_run"] is True


def test_health_reports_engine_status(server):
    code, body = _get(f"{server}/api/health")
    assert code == 200
    assert body["ok"] is True
    assert body["api_version"] == server_app.API_VERSION

    engine = body["engine"]
    # 引擎状态是 App 判断"这台服务器能不能用"的依据 ——
    # 没有 CUDA 时分析会慢到不可接受，App 应该据此提示用户。
    assert "cuda_available" in engine
    assert "torch" in engine


def test_unknown_path_returns_404(server):
    code, body = _get(f"{server}/api/nope")
    assert code == 404
    assert "error" in body


def test_missing_job_returns_404_with_actionable_message(server):
    """
    任务不存在时的提示必须说清"可能已重启，请重新提交" ——
    只回一句 404 会让 App 无法给出有用的提示。
    """
    code, body = _get(f"{server}/api/jobs/deadbeef")
    assert code == 404
    assert "重启" in body["error"] or "重新提交" in body["error"]


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------

def test_upload_rejects_tiny_payload(server):
    """过小的内容显然不是视频，应当明确拒绝而不是存下来。"""
    code, body = _post(f"{server}/api/videos", b"x" * 10)
    assert code == 400
    assert "error" in body


def test_upload_accepts_valid_payload(server):
    payload = b"\x00" * 4096
    code, body = _post(f"{server}/api/videos", payload,
                       {"X-Filename": "run.mp4"})
    assert code == 201
    assert body["size_bytes"] == len(payload)
    assert body["filename"] == "run.mp4"

    # 文件必须真的落盘，且扩展名保留
    files = list(server_app.UPLOAD_DIR.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".mp4"
    assert files[0].stat().st_size == len(payload)


def test_upload_normalizes_unknown_extension(server):
    """非法扩展名归一到 .mp4，避免落盘一个引擎不认的文件。"""
    code, body = _post(f"{server}/api/videos", b"\x00" * 4096,
                       {"X-Filename": "run.exe"})
    assert code == 201
    files = list(server_app.UPLOAD_DIR.iterdir())
    assert files[0].suffix == ".mp4"


# ---------------------------------------------------------------------------
# 安全边界：路径穿越
# ---------------------------------------------------------------------------

def test_analyze_rejects_path_traversal(server):
    """
    ⚠️ 安全边界测试。不能省。

    /api/analyze 用 video_id 在上传目录里找文件。若不校验，
    调用方可以传 ../ 跳出目录，让服务读取机器上任意文件。

    本服务默认监听 0.0.0.0（局域网可访问），所以这是真实风险。

    断言只要求"被拒绝"，不锁死具体状态码：
        400 = 格式非法（更准确，因为 video_id 本来就有固定格式）
        404 = 找不到
    两者都是正确的拒绝方式，锁死其中一个会让实现失去合理的调整空间。
    真正要保证的是**不能读到上传目录之外的文件**。
    """
    _register(server)
    for evil in (
        "../../../Windows/System32/drivers/etc/hosts",
        "..%2F..%2Fetc%2Fpasswd",
        "/etc/passwd",
        "....//....//config",
        "a" * 16 + "/../../etc/passwd",   # 前缀合法但后面带路径
    ):
        code, body = _post(
            f"{server}/api/analyze",
            json.dumps({"username": _TEST_USER,
                        "video_id": evil}).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        assert code in (400, 404), (
            f"video_id={evil!r} 得到 {code}，路径穿越未被拦住"
        )
        assert "error" in body
        # 响应里绝不能出现任何文件内容 —— 那意味着真的读到了
        assert "root:" not in json.dumps(body)
        assert "localhost" not in json.dumps(body)


def test_analyze_rejects_non_hex_video_id(server):
    """
    video_id 必须是服务自己生成的 16 位十六进制。

    用**白名单精确匹配**而不是过滤危险字符 ——
    后者总会漏掉某种编码方式（URL 编码、Unicode 归一化、符号链接等）。
    """
    _register(server)
    for bad in ("ZZZZZZZZZZZZZZZZ", "short", "a" * 15, "a" * 17, "", "中文"):
        code, body = _post(
            f"{server}/api/analyze",
            json.dumps({"username": _TEST_USER,
                        "video_id": bad}).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        assert code in (400, 404), f"video_id={bad!r} 未被拒绝"


def test_analyze_requires_login(server):
    """
    未登录不能提交分析。

    额度是按账号记的 —— 没有账号就无从扣减，也就无法限制用量。
    """
    code, body = _post(f"{server}/api/analyze", b"{}",
                       {"Content-Type": "application/json"})
    assert code == 401
    assert "登录" in body["error"]


def test_analyze_requires_video_id(server):
    _register(server)
    code, body = _post(f"{server}/api/analyze",
                       json.dumps({"username": _TEST_USER}).encode(),
                       {"Content-Type": "application/json"})
    assert code == 400
    assert "video_id" in body["error"]


def test_analyze_rejects_invalid_view(server):
    """
    view 必须校验。它直接决定哪些指标能算 ——
    传一个非法值进去会让额状面/侧面指标的计算逻辑拿到预料之外的输入。
    """
    _register(server)
    # 先正常传一个视频
    _, up = _post(f"{server}/api/videos", b"\x00" * 4096,
                  {"X-Filename": "v.mp4"})
    code, body = _post(
        f"{server}/api/analyze",
        json.dumps({"username": _TEST_USER,
                    "video_id": up["video_id"], "view": "top"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 400
    assert "view" in body["error"]


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

def test_register_rejects_short_password(server):
    """密码太短要拒绝 —— 校验必须在服务端，客户端校验可以被绕过。"""
    code, body = _post(
        f"{server}/api/auth/register",
        json.dumps({"username": "abc", "password": "123"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 400
    assert "6" in body["error"]


def test_register_rejects_duplicate(server):
    _register(server, "dup", "password123")
    code, body = _post(
        f"{server}/api/auth/register",
        json.dumps({"username": "dup", "password": "password123"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 409


def test_login_does_not_leak_whether_user_exists(server):
    """
    ⚠️ 安全测试：用户不存在与密码错误必须返回**同一条消息**。

    分开说会变成账号枚举漏洞 —— 攻击者能试出哪些用户名已注册，
    然后针对性爆破。这类漏洞在很多系统里真实存在。
    """
    _register(server, "realuser", "password123")

    _, wrong_pw = _post(
        f"{server}/api/auth/login",
        json.dumps({"username": "realuser", "password": "wrongpass"}).encode(),
        {"Content-Type": "application/json"},
    )
    _, no_user = _post(
        f"{server}/api/auth/login",
        json.dumps({"username": "nobody", "password": "whatever"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert wrong_pw["error"] == no_user["error"], (
        f"两种失败的原因不同 —— 会被用来枚举账号："
        f"{wrong_pw['error']!r} vs {no_user['error']!r}"
    )


def test_account_public_never_contains_password(server):
    """
    ⚠️ 安全测试：给客户端的账号信息**绝不能**含密码或密码哈希。

    这条测试的价值：以后有人给 Account.public() 加字段时，
    如果顺手把 password_hash 也加进去了，这里会立刻失败。
    """
    account = _register(server)
    blob = json.dumps(account, ensure_ascii=False)
    assert "password" not in blob.lower(), f"账号信息里出现了密码字段：{blob}"
    assert "$" not in blob, "账号信息里出现了疑似哈希的内容"


def test_login_returns_fresh_account(server):
    _register(server, "logintest", "password123")
    code, body = _post(
        f"{server}/api/auth/login",
        json.dumps({"username": "logintest",
                    "password": "password123"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 200
    assert body["account"]["username"] == "logintest"
    assert body["account"]["tier"] == "free"


def test_profile_update_changes_display_name_and_role(server):
    _register(server)
    code, body = _post(
        f"{server}/api/profile",
        json.dumps({"username": _TEST_USER,
                    "display_name": "笨笨鱼",
                    "role": "教练员"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 200
    assert body["account"]["display_name"] == "笨笨鱼"
    assert body["account"]["role"] == "教练员"


def test_profile_rejects_invalid_role(server):
    """
    身份取值必须是认识的那几个。

    为什么要校验：这个字符串会**直接显示在界面上**。
    不校验的话，客户端可以塞任意文本进去。
    """
    _register(server)
    code, body = _post(
        f"{server}/api/profile",
        json.dumps({"username": _TEST_USER, "role": "超级管理员"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 400
    assert "身份" in body["error"]


def test_profile_cannot_change_tier(server):
    """
    ⚠️ 安全测试：改资料接口**不能**用来提升会员等级。

    如果这里允许改 tier，任何客户端都能把自己改成高级会员 ——
    会员体系的全部意义就没了。
    """
    _register(server)
    code, body = _post(
        f"{server}/api/profile",
        json.dumps({"username": _TEST_USER, "tier": "premium"}).encode(),
        {"Content-Type": "application/json"},
    )
    # 接口不认这个字段（静默忽略），但等级绝不能变
    assert code == 200
    assert body["account"]["tier"] == "free", (
        f"tier 被客户端改成了 {body['account']['tier']}"
    )


def test_redeem_upgrades_tier(server):
    """兑换码能把免费用户升成会员。"""
    _register(server)
    codes = server_app.ACCOUNTS.add_codes("premium", 1)

    code, body = _post(
        f"{server}/api/redeem",
        json.dumps({"username": _TEST_USER, "code": codes[0]}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 200
    assert body["account"]["tier"] == "premium"
    assert body["account"]["quota"] == 500


def test_training_plan_is_free_for_every_tier(server):
    """
    ⚠️ 训练计划**对所有用户免费**，不是会员权益。

    这条测试守着一个产品决定：曾经把训练计划列在高级会员的权益里，
    那会让免费用户以为自己用不了。功能上它是本地日历，
    和服务端额度完全无关 —— 所以它有**独立的入口**，
    不在会员页面里。

    如果哪天有人把某个等级的 has_plan 改成 True，
    这里会失败，提醒他先想清楚是不是要把免费功能变成收费的。
    """
    from backend.server.accounts import TIERS, tier_has_plan

    for tier in TIERS:
        assert tier_has_plan(tier) is False, (
            f"等级 {tier} 的 has_plan 是 True —— "
            f"但训练计划本来就不需要任何等级解锁。"
            f"它的入口在「我的 → 训练」，标着「免费」。"
        )


def test_training_plan_has_no_server_gate(server):
    """
    训练计划不经过服务端 —— 没有任何接口会因为它而被拒。

    做法：一个**免费且额度已用完**的用户，仍然能正常读写本地训练计划。
    这里只验证服务端不会拦（本地存储由 App 侧测试覆盖）。
    """
    account = _register(server)
    assert account["tier"] == "free"

    # 把额度用尽
    acc = server_app.ACCOUNTS.get(_TEST_USER)
    acc.used_this_month = acc.quota()
    server_app.ACCOUNTS.upsert(acc)

    # 额度用尽后，分析被拒（402）……
    code, _ = _post(
        f"{server}/api/analyze",
        json.dumps({"username": _TEST_USER,
                    "video_id": "a" * 16}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 402

    # ……但账号本身仍然完全可用，训练计划不受影响。
    # 关键是：没有任何 /api/plan* 之类的接口存在，也就无从拦截。
    code, body = _post(
        f"{server}/api/auth/login",
        json.dumps({"username": _TEST_USER,
                    "password": _TEST_PASS}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 200
    assert body["account"]["remaining"] == 0


def test_redeem_rejects_reuse(server):
    """同一张兑换码不能用两次 —— 否则一张码可以无限扩散。"""
    _register(server, "user_a", "password123")
    _register(server, "user_b", "password123")
    codes = server_app.ACCOUNTS.add_codes("basic", 1)

    code, _ = _post(
        f"{server}/api/redeem",
        json.dumps({"username": "user_a", "code": codes[0]}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 200

    code2, body2 = _post(
        f"{server}/api/redeem",
        json.dumps({"username": "user_b", "code": codes[0]}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code2 == 400
    assert "使用过" in body2["error"]


def test_redeem_rejects_unknown_code(server):
    _register(server)
    code, body = _post(
        f"{server}/api/redeem",
        json.dumps({"username": _TEST_USER,
                    "code": "YU-XXXX-XXXX"}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 400
    assert "不存在" in body["error"]


def test_free_quota_is_exhausted(server):
    """
    免费用户 10 次用完就拒绝。

    这条测试同时验证了「额度检查发生在扣减之前」——
    每次提交都因 video_id 不存在而失败，**不该消耗额度**。
    最后一次性提交足够多的有效请求，才应该耗尽。
    """
    account = _register(server)
    assert account["quota"] == 10

    # 先制造 20 次失败提交（video_id 合法但文件不存在）
    for _ in range(20):
        code, _body = _post(
            f"{server}/api/analyze",
            json.dumps({"username": _TEST_USER,
                        "video_id": "a" * 16}).encode(),
            {"Content-Type": "application/json"},
        )
        assert code == 404

    # 失败不该扣额度
    _, body = _post(f"{server}/api/auth/login",
                    json.dumps({"username": _TEST_USER,
                                "password": _TEST_PASS}).encode(),
                    {"Content-Type": "application/json"})
    assert body["account"]["remaining"] == 10, (
        f"失败的分析消耗了额度：剩余 {body['account']['remaining']}"
    )

    # 直接把额度用满，再提交一次应该被拒
    acc = server_app.ACCOUNTS.get(_TEST_USER)
    acc.used_this_month = 10
    server_app.ACCOUNTS.upsert(acc)

    code, body = _post(
        f"{server}/api/analyze",
        json.dumps({"username": _TEST_USER,
                    "video_id": "a" * 16}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 402, f"额度用尽应返回 402，实得 {code}"
    assert "额度" in body["error"]


def test_admin_codes_requires_admin(server):
    """⚠️ 生成兑换码只能由管理员做。普通用户调用必须被拒。"""
    _register(server)
    code, body = _post(
        f"{server}/api/admin/codes",
        json.dumps({"username": _TEST_USER, "tier": "premium",
                    "count": 5}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 403


def test_admin_can_generate_codes(server):
    """管理员生成的兑换码是真实可用的。"""
    _register(server)
    acc = server_app.ACCOUNTS.get(_TEST_USER)
    acc.is_admin = True
    acc.tier = "admin"
    server_app.ACCOUNTS.upsert(acc)

    code, body = _post(
        f"{server}/api/admin/codes",
        json.dumps({"username": _TEST_USER, "tier": "premium",
                    "count": 3}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 201
    assert len(body["codes"]) == 3

    # 生成的码应当真的能兑换
    _register(server, "buyer", "password123")
    c2, b2 = _post(
        f"{server}/api/redeem",
        json.dumps({"username": "buyer",
                    "code": body["codes"][0]}).encode(),
        {"Content-Type": "application/json"},
    )
    assert c2 == 200
    assert b2["account"]["tier"] == "premium"


def test_admin_codes_rejects_free_tier(server):
    """不能给「免费用户」生成兑换码 —— 那没有意义。"""
    _register(server)
    acc = server_app.ACCOUNTS.get(_TEST_USER)
    acc.is_admin = True
    server_app.ACCOUNTS.upsert(acc)

    code, body = _post(
        f"{server}/api/admin/codes",
        json.dumps({"username": _TEST_USER, "tier": "free",
                    "count": 1}).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 400


# ---------------------------------------------------------------------------
# 关键帧图片服务
# ---------------------------------------------------------------------------

def test_keyframe_route_rejects_path_traversal(server):
    """
    ⚠️ 安全测试：/keyframes/ 直接映射文件系统，必须防穿越。

    如果不做校验，任何人都能用
        /keyframes/<任意>/../../../../Windows/System32/...
    读到机器上的文件。本服务监听 0.0.0.0，局域网内都能利用。
    """
    for evil in (
        "../../../Windows/System32/drivers/etc/hosts",
        "abc/../../../etc/passwd",
        "a" * 16 + "/../../secret.jpg",
        "a" * 16 + "/f000001_touchdown.jpg/../../x.jpg",
    ):
        try:
            code, body = _get(f"{server}/keyframes/{evil}")
        except Exception:
            continue        # 客户端可能因为路径不合法直接抛异常，也算被拒
        assert code in (400, 404), f"{evil!r} 得到 {code}，穿越未被拦住"


def test_keyframe_route_rejects_bad_filename(server):
    """文件名格式受限 —— 同样是白名单，不是过滤危险字符。"""
    job_id = "a" * 16
    for bad in ("evil.php", "x.jpg", "f001_touchdown.jpg",
                "f000001_TOUCHDOWN.jpg", "f000001_touchdown.png"):
        code, _ = _get(f"{server}/keyframes/{job_id}/{bad}")
        assert code in (400, 404), f"文件名 {bad!r} 未被拒绝"


def test_keyframe_route_returns_404_for_missing(server):
    """格式合法但文件不存在 → 404，而不是 500。"""
    code, _ = _get(f"{server}/keyframes/{'a' * 16}/f000014_touchdown.jpg")
    assert code == 404


def test_analyze_rejects_malformed_json(server):
    code, body = _post(f"{server}/api/analyze", b"{not json",
                       {"Content-Type": "application/json"})
    assert code == 400
    assert "error" in body


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------

def test_cleanup_removes_stale_uploads(server, monkeypatch):
    """
    过期上传必须被清理。

    教练上传后可能不提交分析（改了主意、App 崩了），
    素材就留在磁盘上。一段慢动作素材几百 MB，攒几次就把盘占满。
    """
    import os

    # 造三个文件：两个"很旧"，一个"很新"
    old1 = server_app.UPLOAD_DIR / "old1.mp4"
    old2 = server_app.UPLOAD_DIR / "old2.mp4"
    fresh = server_app.UPLOAD_DIR / "fresh.mp4"
    for f in (old1, old2, fresh):
        f.write_bytes(b"\x00" * 100)

    long_ago = time.time() - server_app.STALE_UPLOAD_SECONDS - 3600
    os.utime(old1, (long_ago, long_ago))
    os.utime(old2, (long_ago, long_ago))

    removed = server_app.cleanup_stale_uploads()

    assert removed == 2
    assert not old1.exists()
    assert not old2.exists()
    assert fresh.exists(), "新文件不该被清理"


def test_cleanup_tolerates_missing_directory(tmp_path, monkeypatch):
    """上传目录不存在时不该抛异常 —— 服务刚启动就是这个状态。"""
    monkeypatch.setattr(server_app, "UPLOAD_DIR", tmp_path / "nope")
    assert server_app.cleanup_stale_uploads() == 0


# ---------------------------------------------------------------------------
# 端到端（走真实模型，慢）
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_full_upload_analyze_cycle(server, tmp_path):
    """
    完整的「上传 → 分析 → 取报告」流程。

    标记为 slow：要走真实模型，约 10 秒。
    默认不跑（见 pytest.ini 的 markers 配置），
    用 `pytest -m slow` 单独跑。
    """
    import cv2
    import numpy as np

    # 造一段合成视频
    vid = tmp_path / "smoke.mp4"
    w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"),
                        60.0, (640, 480))
    for i in range(40):
        frame = np.full((480, 640, 3), 200, dtype=np.uint8)
        cv2.rectangle(frame, (0, 260), (640, 480), (120, 150, 180), -1)
        cx = int(160 + i * 3)
        cv2.circle(frame, (cx, 212), 11, (40, 40, 60), -1)
        cv2.line(frame, (cx, 224), (cx, 260), (40, 40, 60), 9)
        w.write(frame)
    w.release()

    code, up = _post(f"{server}/api/videos", vid.read_bytes(),
                     {"X-Filename": "smoke.mp4"})
    assert code == 201, up

    # 分析需要登录（额度按账号记）
    _register(server)

    code, job = _post(
        f"{server}/api/analyze",
        json.dumps({
            "username": _TEST_USER,
            "video_id": up["video_id"],
            "athlete_id": "at00001",
            "athlete_name": "测试",
            "height_cm": 178,
            "view": "side",
        }).encode(),
        {"Content-Type": "application/json"},
    )
    assert code == 202, job
    job_id = job["job_id"]

    # 轮询直到完成
    deadline = time.time() + 180
    final = None
    while time.time() < deadline:
        _, st = _get(f"{server}/api/jobs/{job_id}")
        if st["status"] in ("done", "failed"):
            final = st
            break
        time.sleep(1)

    assert final is not None, "分析超时"
    assert final["status"] == "done", (
        f"分析失败：{final.get('error')}\n{final.get('error_detail', '')[:1500]}"
    )

    report = final["report"]
    assert report["schema_version"]
    assert report["metrics"], "报告必须含指标（哪怕是数据不足）"
    assert report["summary"]["headline"]

    # 报告也要能通过单独的报告接口取到
    code, only = _get(f"{server}/api/reports/{job_id}")
    assert code == 200
    assert only["analysis_id"] == report["analysis_id"]
