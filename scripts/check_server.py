"""
G5b 分析服务端接口自检。

与 backend/tests/test_server.py 的关系：
    测试文件覆盖的是**逻辑正确性**（路径穿越防护、参数校验、清理逻辑），
    本脚本覆盖的是**服务能被正常启动并响应**这件事本身。

为什么单独需要一道门：
    测试里是用 ThreadingHTTPServer 直接在进程内起服务的，
    绕过了 `python -m backend.server.app` 这条**真实的启动路径**。
    而真实启动路径上有它自己的问题 —— 例如控制台编码
    （Windows 的 GBK 遇到 emoji 会直接崩在 print 上，
     服务根本起不来，但所有测试仍然全绿）。

    这道门就是补这个缺口：真的把服务当子进程起起来，
    真的用 HTTP 打它的接口。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 用一个非常规端口，避免和开发时手动起的服务撞车。
# 撞车的后果是"连上了另一个服务"，测试结果变得不可信。
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"


def _wait_ready(timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    print("=" * 68)
    print("分析服务端接口自检")
    print("=" * 68)
    print()

    # ---- 启动服务（真实的启动路径）----
    # 用子进程而不是进程内起，才能覆盖到"服务能不能被启动"这一环。
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.server.app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        if not _wait_ready():
            # 启动失败时把服务的输出打出来 —— 否则只看到"连不上"，
            # 完全不知道是端口占用、编码崩溃还是别的。
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
            print("[FAIL] 服务未能在 25 秒内就绪")
            print("       服务输出：")
            for line in (out or "").splitlines()[-25:]:
                print(f"         {line}")
            return 1

        print(f"  [OK] 服务启动成功（{BASE}）")

        # ---- 健康检查 ----
        with urllib.request.urlopen(f"{BASE}/api/health", timeout=5) as r:
            h = json.loads(r.read().decode("utf-8"))
        assert h["ok"] is True
        assert h["api_version"]
        print(f"  [OK] /api/health  版本 {h['version']}"
              f"  设备 {(h.get('engine') or {}).get('gpu') or 'CPU'}")

        # ---- 参数校验 ----
        # 这些接口不需要模型，能快速验证路由与校验逻辑是否真的生效
        def post(path: str, body: bytes, ctype: str = "application/json"):
            req = urllib.request.Request(
                BASE + path, data=body, method="POST")
            req.add_header("Content-Type", ctype)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode("utf-8"))

        code, body = post("/api/analyze", b"{}")
        assert code == 401, f"未登录应返回 401，实得 {code}"
        print("  [OK] /api/analyze 未登录被拒（401）")

        # ---- 账号 ----
        # 分析接口要求登录（额度按账号记），所以自检要先建一个账号。
        # 用户名随机 —— 避免和真实账号撞名，也避免污染开发数据。
        import random
        import string as _string
        uname = "selftest_" + "".join(
            random.choices(_string.ascii_lowercase, k=8))

        code, body = post("/api/auth/register",
                          json.dumps({"username": uname,
                                      "password": "selftest123"}).encode())
        assert code == 201, f"注册自检账号失败：{code} {body}"
        print("  [OK] /api/auth/register 自检账号已创建")

        code, body = post("/api/auth/login",
                          json.dumps({"username": uname,
                                      "password": "selftest123"}).encode())
        assert code == 200
        assert body["account"]["tier"] == "free"
        assert body["account"]["quota"] == 10
        print(f"  [OK] /api/auth/login  免费用户额度 "
              f"{body['account']['quota']} 次")

        # ⚠️ 账号信息里绝不能有密码或哈希
        blob = json.dumps(body["account"], ensure_ascii=False)
        assert "password" not in blob.lower(), "账号信息泄漏了密码字段"
        assert "$" not in blob, "账号信息里出现了疑似哈希"
        print("  [OK] 账号信息不含密码或哈希")

        code, _ = post("/api/auth/login",
                       json.dumps({"username": uname,
                                   "password": "wrong"}).encode())
        assert code == 401
        print("  [OK] /api/auth/login  错误密码被拒（401）")

        code, body = post("/api/analyze",
                          json.dumps({"username": uname}).encode())
        assert code == 400, f"缺 video_id 应返回 400，实得 {code}"
        print("  [OK] /api/analyze 缺参数被拒（400）")

        code, body = post(
            "/api/analyze",
            json.dumps({"username": uname,
                        "video_id": "../../../etc/passwd"}).encode())
        assert code in (400, 404), f"路径穿越未被拦，实得 {code}"
        assert "root:" not in json.dumps(body)
        print("  [OK] /api/analyze 路径穿越被拒")

        code, body = post("/api/videos", b"x" * 10,
                          "application/octet-stream")
        assert code == 400, f"过小上传应返回 400，实得 {code}"
        print("  [OK] /api/videos 过小内容被拒（400）")

        # ---- 关键帧路径穿越 ----
        # /keyframes/ 是直接映射文件系统的路径，必须防穿越。
        # 不校验的话，局域网内任何人都能读到机器上的文件。
        try:
            urllib.request.urlopen(
                f"{BASE}/keyframes/{'a' * 16}/../../etc/passwd", timeout=5)
            print("[FAIL] 关键帧路径穿越未被拦住")
            return 1
        except urllib.error.HTTPError as e:
            assert e.code in (400, 404), f"实得 {e.code}"
        except Exception:
            pass
        print("  [OK] /keyframes 路径穿越被拒")

        # ---- 权限 ----
        code, _ = post("/api/admin/codes",
                       json.dumps({"username": uname, "tier": "premium",
                                   "count": 1}).encode())
        assert code == 403, f"非管理员生成兑换码应 403，实得 {code}"
        print("  [OK] /api/admin/codes 非管理员被拒（403）")

        # ---- 404 路由 ----
        try:
            urllib.request.urlopen(f"{BASE}/api/nope", timeout=5)
            print("[FAIL] 未知路径未返回 404")
            return 1
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print("  [OK] 未知路径返回 404")

        print()
        print("[OK] 服务端接口自检通过")
        return 0

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
