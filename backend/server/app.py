"""
分析服务端：接收 App 上传的视频，跑分析引擎，返回报告。

用法：
    python -m backend.server.app --host 0.0.0.0 --port 8770

为什么用标准库而不是 FastAPI/Flask：
    服务端只是一个"接收文件 + 调用引擎 + 返回 JSON"的壳，
    真正的逻辑全在 backend/analysis 里。
    装 FastAPI 会引入 pydantic / starlette / uvicorn 等一串依赖，
    而它们默认都往系统盘写缓存 —— 本项目的开发机上系统盘很紧张。

    标准库的 http.server 足够支撑这个场景，且零依赖。

部署边界：
    已有账号、额度与视频ID路径校验，但请求身份/授权仍是局域网原型。
    默认监听0.0.0.0；目前仅用于可信局域网，不是公网生产服务。
    API和人工计时/选人协议见docs/07-数据契约.md。

接口：
    GET  /api/health
        服务与引擎状态，用于 App 探测。

    POST /api/videos
        Body: 原始视频字节
        Header: X-Filename（可选，仅用于日志）
        返回 {video_id, size_bytes}

    POST /api/analyze
        Body: JSON，含 video_id 与运动员/采集信息
        返回 {job_id, status}

    GET  /api/jobs/<job_id>
        任务状态与进度。完成后含 report。

    GET  /api/reports/<job_id>
        只取报告 JSON。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# 控制台编码处理。
#
# ⚠️ Windows 的默认控制台编码是 GBK，遇到 emoji、特殊符号（如 ⚠️）
#    或部分中文标点时会直接抛 UnicodeEncodeError 让程序崩溃 ——
#    而且崩溃点在 print 上，看起来像是"程序自己挂了"。
#
#    处理方式与 scripts/ 下的其他脚本一致：
#      · 输出被重定向（管道/文件）时强制 UTF-8 并允许替换字符
#      · 终端直接输出时保持系统编码，但把无法编码的字符替换掉而不是崩溃
def _init_console() -> None:
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace")
    else:
        # 交互式终端：保留系统编码（中文才显示正常），
        # 只是不允许因个别字符编码失败而中断。
        try:
            sys.stdout.reconfigure(errors="replace")
            sys.stderr.reconfigure(errors="replace")
        except Exception:
            pass


_init_console()

# 让脚本从任意目录都能跑
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ..paths import (  # noqa: E402
    ACCOUNTS_FILE,
    CACHE_DIR,
    UPLOADS_DIR,
    MANUAL_DATASET_DIR,
    apply_env_defaults,
    ensure_cache_dirs,
)
from ..analysis.pose_options import PoseOptionsError, pose_options_from_params
from .accounts import (  # noqa: E402
    TIERS,
    Account,
    AccountStore,
    hash_password,
    seed_demo_codes,
    tier_label,
    verify_password,
)

apply_env_defaults()
ensure_cache_dirs()

# 上传文件的落地目录。默认在项目内的 .cache/uploads，
# 不往项目外写；可用环境变量 YUCOACH_UPLOAD_DIR 覆盖。
UPLOAD_DIR = UPLOADS_DIR

# ---------------------------------------------------------------------------
# 管理员账号
#
# ⚠️ 密码以**哈希**形式存进账号文件，源码里只留初始明文用于首次创建。
#    首次启动时创建账号，之后改密码走接口 —— 源码里那份就不再生效。
#
# ⚠️ 安全边界（必须说清楚）：
#    这是单机、无数据库的简化实现。密码哈希挡的是"密码被直接读到"，
#    **挡不住**能读写 .cache/accounts.json 的人改会员等级。
#    真要上线需要数据库 + 会话令牌 + 权限校验中间件。
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.environ.get("YUCOACH_ADMIN_USER", "MazingLIU")
ADMIN_INITIAL_PASSWORD = os.environ.get("YUCOACH_ADMIN_PASSWORD",
                                        "Lmyiuinu20061212")

ACCOUNTS = AccountStore(ACCOUNTS_FILE)

# 上传大小上限。2 GB 覆盖 10 秒 240fps 的手机慢动作素材（约 300 MB）
# 还留了很大余量 —— 超限时明确报错，而不是让它把磁盘写满。
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# 上传后多久没被分析就清理（秒）。避免磁盘被遗忘的素材堆满。
STALE_UPLOAD_SECONDS = 24 * 3600

#: 关键帧图片的存放根目录。每个任务一个子目录。
#:
#: 为什么按任务分目录：清理某次分析时直接删目录即可，
#: 不会因为文件名规则复杂而误删别的任务的图。
KEYFRAMES_ROOT = CACHE_DIR / "keyframes"
DATASET_ROOT = MANUAL_DATASET_DIR

SERVER_VERSION = "0.2.0"
API_VERSION = "1"


def ensure_admin() -> list[str]:
    """
    确保管理员账号存在。返回要打印的提示行。

    只创建一次 —— 已存在就不动它，否则每次重启都会把密码重置回源码里那份，
    用户改了密码也白改。
    """
    notes: list[str] = []
    existing = ACCOUNTS.get(ADMIN_USERNAME)
    if existing is not None:
        if not existing.is_admin:
            existing.is_admin = True
            existing.tier = "admin"
            ACCOUNTS.upsert(existing)
            notes.append(f"已把账号 {ADMIN_USERNAME} 标记为管理员")
        return notes

    ACCOUNTS.upsert(Account(
        username=ADMIN_USERNAME,
        password_hash=hash_password(ADMIN_INITIAL_PASSWORD),
        tier="admin",
        display_name="管理员",
        role="教练员",
        is_admin=True,
    ))
    notes.append(f"已创建管理员账号：{ADMIN_USERNAME}")
    notes.append("⚠️ 初始密码来自源码默认值，建议首次登录后修改。")
    return notes


def current_period() -> str:
    """当前额度周期，格式 YYYY-MM。"""
    return time.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """一次分析任务。"""

    job_id: str
    video_id: str
    video_path: str
    status: str = "queued"      # queued / running / done / failed
    progress: float = 0.0
    stage: str = "排队中"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    report: dict | None = None
    error: str | None = None
    error_detail: str | None = None
    log: list[str] = field(default_factory=list)

    def public(self, include_report: bool = True) -> dict:
        out: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "stage": self.stage,
            "created_at": self.created_at,
            "elapsed_s": round(
                (self.finished_at or time.time()) - self.created_at, 1),
            "log": self.log[-12:],
        }
        if self.started_at:
            out["started_at"] = self.started_at
        if self.finished_at:
            out["finished_at"] = self.finished_at
        if self.error:
            out["error"] = self.error
        if self.error_detail:
            out["error_detail"] = self.error_detail
        if include_report and self.report is not None:
            out["report"] = self.report
        return out


class JobStore:
    """
    内存里的任务表。

    为什么不持久化：分析任务的生命周期是"提交 → 几十秒 → 取结果"，
    重启服务时丢掉几个进行中的任务没有实际影响。
    而持久化会引入清理、并发写、磁盘占用等一堆问题 ——
    对一个训练场临时开启的服务不值得。

    ⚠️ 服务重启后，App 手里未取回的 job_id 会失效。
       App 侧据此提示用户"服务已重启，请重新提交"。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values()
                       if j.status in ("queued", "running"))


JOBS = JobStore()

# 视频上传登记表：video_id -> 落盘的文件名。
#
# 为什么需要它，而不是直接用 video_id 去 glob：
#   glob 的模式里如果混入用户输入，会有两个问题 ——
#     ① video_id="/etc/passwd" 这类绝对路径会让 glob 直接抛异常
#     ② 更危险的：构造出的模式可能匹配到上传目录之外的文件
#   改成"只接受登记过的 id"，用户输入就完全无法影响文件路径。
UPLOADED: dict[str, str] = {}
_UPLOAD_LOCK = threading.Lock()

# video_id 的合法格式：本服务自己生成的 16 位十六进制。
# 严格校验比"过滤危险字符"可靠 —— 后者总会漏掉某种编码方式。
_VIDEO_ID_RE = __import__("re").compile(r"^[0-9a-f]{16}$")

# 关键帧文件名格式：f<6位帧号>_<事件名>.jpg，由 keyframes.py 生成。
# 同样是白名单 —— 不接受任何别的形式。
_KEYFRAME_NAME_RE = __import__("re").compile(
    r"^f\d{6}_[a-z_]{3,20}\.jpg$")


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------

def run_analysis(job: Job, params: dict) -> None:
    """
    在后台线程里跑分析。

    所有异常都必须在这里被接住 —— 漏出去会让线程静默死掉，
    任务永远停在 running 状态，App 会一直转圈。
    """
    try:
        job.status = "running"
        job.started_at = time.time()

        # 延迟导入：服务启动时不加载 torch（要几秒），
        # 只在真的提交任务时才付出这个代价。
        from backend.analysis.analyze import run_pipeline

        pose_options = pose_options_from_params(params)

        def on_progress(pct: float, stage: str) -> None:
            job.progress = pct
            job.stage = stage

        report = run_pipeline(
            video_path=Path(job.video_path),
            athlete_id=params.get("athlete_id", "at_local"),
            athlete_name=params.get("athlete_name", "未署名"),
            gender=params.get("gender", "male"),
            event=params.get("event", "100m"),
            level=params.get("level", "college"),
            height_cm=params.get("height_cm"),
            athlete_age=params.get("athlete_age"),
            running_condition=params.get("running_condition"),
            load_protocol=params.get("load_protocol"),
            complete_run=params.get("complete_run", False),
            population_confirmed=(params.get("gender") in ("male", "female")
                                  and params.get("level") in ("elite", "sub_elite", "college", "high_school", "amateur")
                                  and params.get("event") in ("100m", "200m", "400m")),
            view=params.get("view", "side"),
            test_type=params.get("test_type", "acceleration"),
            camera_distance_m=params.get("camera_distance_m"),
            camera_height_m=params.get("camera_height_m"),
            has_lane_line=params.get("has_lane_line"),
            camera_followed=params.get("camera_followed"),
            manual_review=params.get("manual_review"),
            target_selection=params.get("target_selection"),
            session_id=params.get("session_id"),
            team_id=params.get("team_id", "t_local"),
            **pose_options,
            # 关键帧图片按任务分开存 —— 一个任务一个目录，
            # 这样清理某次分析时直接删目录，不会误删别的任务。
            keyframe_dir=KEYFRAMES_ROOT / job.job_id,
            keyframe_url_prefix=f"keyframes/{job.job_id}",
            progress=on_progress,
            log=job.log.append,
        )

        if params.get("manual_review") is not None or params.get("target_selection") is not None:
            # Reviewed clips are retained independently of expiring uploads.
            import shutil
            archive = DATASET_ROOT / job.job_id
            archive.mkdir(parents=True, exist_ok=True)
            source = Path(job.video_path)
            shutil.copy2(source, archive / ("video" + source.suffix))
            (archive / "review.json").write_text(json.dumps({
                "video_id": job.video_id, "job_id": job.job_id,
                "athlete_id": params.get("athlete_id"),
                "athlete_name": params.get("athlete_name"),
                "review": params.get("manual_review"),
                "target_selection": params.get("target_selection"),
                "provenance": "human_annotations_not_validated_ground_truth",
                "created_at": time.time(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            (archive / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            tracking = KEYFRAMES_ROOT / job.job_id / "target_tracking.json"
            if tracking.is_file():
                shutil.copy2(tracking, archive / "target_tracking.json")
        job.report = report
        job.progress = 1.0
        job.stage = "完成"
        job.status = "done"
        job.finished_at = time.time()

    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.stage = "失败"
        job.error = f"{type(e).__name__}: {e}"
        # 完整堆栈只写日志，不回传给 App ——
        # App 那边展示堆栈对教练没有意义，反而会淹没真正的提示。
        job.error_detail = traceback.format_exc()
        job.finished_at = time.time()
        print(f"[job {job.job_id}] 分析失败：{job.error}")
        print(job.error_detail)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = f"YUcoach/{SERVER_VERSION}"
    protocol_version = "HTTP/1.1"

    # ---- 工具 ----

    def _send_json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 允许 Web 版 App 直接调用（移动端不受 CORS 限制，但 Web 端需要）
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Filename")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("缺少 Content-Length")
        if length > limit:
            raise ValueError(
                f"请求体 {length / 1024**2:.0f} MB 超过上限 "
                f"{limit / 1024**2:.0f} MB"
            )
        # 分块读，避免一次性分配大缓冲
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def log_message(self, fmt: str, *args: Any) -> None:
        """默认实现会把每个请求打到 stderr，太吵。只保留错误。"""
        if args and str(args[1]).startswith(("4", "5")):
            sys.stderr.write(f"[http] {self.address_string()} {fmt % args}\n")

    def handle_one_request(self) -> None:
        """
        容忍客户端中途断开。

        ⚠️ 不处理的话，手机在请求完成前切走 App（或锁屏、切网络）时，
           socketserver 会把完整的 ConnectionResetError 堆栈打到控制台。
           用户看到一大段红色 traceback，会以为服务坏了 ——
           实际上服务完全正常，只是对方走了。

           这类噪声还有一个更坏的后果：它会把真正的问题埋掉。
           之前排查手机连不上时，控制台被这些堆栈刷满，
           反而看不出关键信息。

        只吞掉"连接被对方重置/中止"这一类；其它异常照常抛出，
        因为它们可能真的是 bug，不该被静默。
        """
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError,
                BrokenPipeError, TimeoutError):
            self.close_connection = True

    # ---- 路由 ----

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path.startswith("/api/videos/"):
            self._serve_video_review(path)
            return

        if path in ("/api/health", "/api"):
            self._send_health()
            return

        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            self._send_job(job_id, include_report=True)
            return

        if path.startswith("/api/reports/"):
            job_id = path[len("/api/reports/"):]
            job = JOBS.get(job_id)
            if job is None:
                self._send_json({"error": "任务不存在，服务可能已重启"},
                                404)
                return
            if job.report is None:
                self._send_json({
                    "error": "报告尚未生成",
                    "status": job.status,
                    "progress": round(job.progress, 3),
                    "stage": job.stage,
                }, 409)
                return
            self._send_json(job.report)
            return

        # ---- 关键帧图片 ----
        #
        # 报告里的 image_url 是相对路径（如 keyframes/<job>/f000014_touchdown.jpg），
        # App 用同一个 baseUrl 拼成完整地址来取图。
        #
        # ⚠️ 这条路径直接映射到文件系统，必须做穿越防护 ——
        #    见 _resolve_keyframe() 的白名单式校验。
        if path.startswith("/keyframes/"):
            self._serve_keyframe(path[len("/keyframes/"):])
            return

        self._send_json({"error": f"未知路径 {self.path}"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path == "/api/videos":
            self._handle_upload()
            return

        if path == "/api/analyze":
            self._handle_analyze()
            return

        if path == "/api/auth/register":
            self._handle_register()
            return

        if path == "/api/auth/login":
            self._handle_login()
            return

        if path == "/api/profile":
            self._handle_profile_update()
            return

        if path == "/api/redeem":
            self._handle_redeem()
            return

        if path == "/api/admin/codes":
            self._handle_admin_codes()
            return

        self._send_json({"error": f"未知路径 {self.path}"}, 404)

    # ---- 各接口 ----

    def _send_health(self) -> None:
        try:
            import torch
            cuda = torch.cuda.is_available()
            gpu = torch.cuda.get_device_name(0) if cuda else None
            torch_version = torch.__version__
        except ImportError:
            cuda, gpu, torch_version = False, None, None

        self._send_json({
            "ok": True,
            "service": "yucoach-analysis",
            "version": SERVER_VERSION,
            "api_version": API_VERSION,
            "engine": {
                "torch": torch_version,
                "cuda_available": cuda,
                "gpu": gpu,
            },
            "jobs_running": JOBS.running_count(),
            "upload_dir": str(UPLOAD_DIR),
        })

    # ---- 账号 ----

    def _read_json(self, limit: int = 64 * 1024) -> dict | None:
        """读请求体并解析 JSON。失败时回错误并返回 None。"""
        try:
            raw = self._read_body(limit)
            return json.loads(raw.decode("utf-8"))
        except ValueError as e:
            self._send_json({"error": f"请求体不合法：{e}"}, 400)
        except json.JSONDecodeError as e:
            self._send_json({"error": f"JSON 解析失败：{e}"}, 400)
        return None

    def _handle_register(self) -> None:
        params = self._read_json()
        if params is None:
            return

        username = (params.get("username") or "").strip()
        password = params.get("password") or ""

        # 校验规则写在这里而不是 App 里 —— App 的校验只是提醒，
        # 服务端才是真正把关的地方（客户端校验永远可以被绕过）。
        if len(username) < 2 or len(username) > 24:
            self._send_json({"error": "用户名需要 2–24 个字符"}, 400)
            return
        if len(password) < 6:
            self._send_json({"error": "密码至少 6 位"}, 400)
            return
        if ACCOUNTS.get(username) is not None:
            self._send_json({"error": f"用户名「{username}」已被注册"}, 409)
            return

        acc = Account(
            username=username,
            password_hash=hash_password(password),
            tier="free",
            display_name=username,
            role=params.get("role") or "",
            period=current_period(),
        )
        ACCOUNTS.upsert(acc)
        self._send_json({"ok": True, "account": acc.public()}, 201)

    def _handle_login(self) -> None:
        params = self._read_json()
        if params is None:
            return

        username = (params.get("username") or "").strip()
        password = params.get("password") or ""
        acc = ACCOUNTS.get(username)

        # ⚠️ 用户不存在与密码错误**返回同一条消息**。
        #    分开说会变成账号枚举漏洞：攻击者能试出哪些用户名已注册。
        if acc is None or not verify_password(password, acc.password_hash):
            self._send_json({"error": "用户名或密码不正确"}, 401)
            return

        if acc.ensure_period(current_period()):
            ACCOUNTS.upsert(acc)

        self._send_json({"ok": True, "account": acc.public()})

    def _handle_profile_update(self) -> None:
        """
        修改昵称 / 身份 / 头像。

        ⚠️ 这里**不允许改 tier**。会员等级只能由兑换码或管理员变更 ——
           否则任何客户端都能把自己改成高级会员。
        """
        params = self._read_json()
        if params is None:
            return

        username = (params.get("username") or "").strip()
        acc = ACCOUNTS.get(username)
        if acc is None:
            self._send_json({"error": "账号不存在"}, 404)
            return

        if "display_name" in params:
            name = (params.get("display_name") or "").strip()
            if len(name) > 24:
                self._send_json({"error": "昵称太长（最多 24 字）"}, 400)
                return
            acc.display_name = name
        if "role" in params:
            role = (params.get("role") or "").strip()
            # 身份取值必须是我们认识的 —— 存进去的字符串会直接显示在界面上
            if role and role not in ("家长", "教练员", "运动员"):
                self._send_json({"error": f"身份取值非法：{role}"}, 400)
                return
            acc.role = role
        if "avatar" in params:
            acc.avatar = (params.get("avatar") or "")[:64]

        ACCOUNTS.upsert(acc)
        self._send_json({"ok": True, "account": acc.public()})

    def _handle_redeem(self) -> None:
        params = self._read_json()
        if params is None:
            return

        username = (params.get("username") or "").strip()
        code = params.get("code") or ""
        ok, msg = ACCOUNTS.redeem(code, username)
        if not ok:
            self._send_json({"error": msg}, 400)
            return

        acc = ACCOUNTS.get(username)
        self._send_json({
            "ok": True,
            "message": msg,
            "account": acc.public() if acc else None,
        })

    def _handle_admin_codes(self) -> None:
        """
        生成兑换码。**仅管理员可用。**

        ⚠️ 鉴权靠 is_admin 标志，而它存在账号文件里。
           这是单机实现的边界 —— 能改那个文件的人就能提权。
           见 accounts.py 开头的说明。
        """
        params = self._read_json()
        if params is None:
            return

        username = (params.get("username") or "").strip()
        acc = ACCOUNTS.get(username)
        if acc is None or not acc.is_admin:
            # 不告诉调用方"你不是管理员" —— 那等于确认了这个接口的存在。
            self._send_json({"error": "无权限"}, 403)
            return

        tier = params.get("tier") or "basic"
        try:
            count = int(params.get("count") or 1)
        except (TypeError, ValueError):
            self._send_json({"error": "count 必须是整数"}, 400)
            return

        if count < 1 or count > 100:
            self._send_json({"error": "count 需在 1–100 之间"}, 400)
            return

        try:
            codes = ACCOUNTS.add_codes(tier, count)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return

        self._send_json({"ok": True, "codes": codes}, 201)

    def _handle_upload(self) -> None:
        try:
            data = self._read_body(MAX_UPLOAD_BYTES)
        except ValueError as e:
            self._send_json({"error": str(e)}, 413)
            return

        if len(data) < 1024:
            self._send_json({"error": "上传内容过小，可能不是视频文件"}, 400)
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        video_id = uuid.uuid4().hex[:16]

        # 保留原始扩展名：分析引擎按扩展名无法判断编码，
        # 但日志与人工排查时需要知道文件类型。
        raw_name = self.headers.get("X-Filename") or "video.mp4"
        suffix = Path(raw_name).suffix.lower() or ".mp4"
        if suffix not in (".mp4", ".mov", ".m4v", ".avi", ".mkv"):
            suffix = ".mp4"

        dest = UPLOAD_DIR / f"{video_id}{suffix}"
        dest.write_bytes(data)

        with _UPLOAD_LOCK:
            UPLOADED[video_id] = dest.name

        self._send_json({
            "video_id": video_id,
            "size_bytes": len(data),
            "filename": raw_name,
        }, 201)

    def _handle_analyze(self) -> None:
        params = self._read_json()
        if params is None:
            return

        condition = params.get("running_condition")
        load_protocol = params.get("load_protocol")
        age = params.get("athlete_age")
        if (condition is not None and condition not in ("unloaded", "resisted", "assisted")
                or type(params.get("complete_run", False)) is not bool
                or age is not None and (type(age) not in (int, float) or not 0 < age < 120)
                or load_protocol is not None and (not isinstance(load_protocol, str) or not load_protocol.strip())
                or condition in ("resisted", "assisted") and not load_protocol
                or condition == "unloaded" and load_protocol is not None):
            self._send_json({"error": "参考匹配参数无效：请检查年龄、完整全程确认和负荷方案"}, 400)
            return

        # ---- 额度检查 ----
        #
        # ⚠️ 必须在**扣额度之前**把所有会失败的检查做完，
        #    否则用户会因为一次失败的提交白掉一次额度。
        #
        # 顺序：先查账号与额度（便宜），再查文件是否存在（便宜），
        # 最后才扣额度并起任务。
        username = (params.get("username") or "").strip()
        if not username:
            self._send_json({
                "error": "请先登录",
                "hint": "分析需要账号来记录额度。"
                        "App 里注册的账号若是用手机号，就没有用户名，"
                        "请用「用户名」方式重新注册。",
            }, 401)
            return

        acc = ACCOUNTS.get(username)

        # ---- 首次提交时自动建号 ----
        #
        # 为什么要有这一步：App 的账号体系是**纯本地**的
        # （AuthService 存在手机文件里），而额度记在服务端。
        # 两边从来没接通过，于是用户明明登录了、提交分析却一律
        # 收到「请先登录」——而那句话完全指不出问题在哪。
        #
        # 这里做**信任式自动建号**：App 说是谁就是谁，首次见到就
        # 建一个普通账号。这个信任级别与服务本身一致 ——
        # 它本来就是「无认证、仅供局域网内短期使用」（见上面的 WARN），
        # 手机上存密码也不会让它更安全。
        #
        # 额度仍然由服务端裁定并累计，客户端改不了。
        if acc is None:
            acc = Account(
                username=username,
                password_hash="",          # 无需密码登录，故不存
                tier="free",
                display_name=params.get("athlete_name") or username,
                role="",
                period=current_period(),
            )
            ACCOUNTS.upsert(acc)

        if acc.ensure_period(current_period()):
            ACCOUNTS.upsert(acc)
        if not acc.can_analyze():
            self._send_json({
                "error": f"{tier_label(acc.tier)}的额度已用完",
                "hint": f"本月已用 {acc.used_this_month}/{acc.quota()} 次。"
                        f"可在「我的 → 会员中心」用兑换码升级。",
                "account": acc.public(),
            }, 402)
            return

        video_id = params.get("video_id")
        if not video_id:
            self._send_json({"error": "缺少 video_id"}, 400)
            return

        # ⚠️ 安全边界：video_id 必须严格匹配本服务生成的格式。
        #
        # 这一条不能省。若不校验，调用方可以传 "../../Windows/System32/..."
        # 让服务读取机器上任意文件 —— 本服务默认监听 0.0.0.0，
        # 局域网内任何人都能利用。
        #
        # 做法是**白名单式精确匹配**，而不是"过滤危险字符"：
        # 后者总会漏掉某种编码方式（..%2F、....//、Unicode 归一化等）。
        if not isinstance(video_id, str) or not _VIDEO_ID_RE.match(video_id):
            self._send_json({
                "error": "video_id 格式非法。它应当是上传接口返回的"
                         "16 位十六进制字符串。",
            }, 400)
            return

        with _UPLOAD_LOCK:
            stored_name = UPLOADED.get(video_id)

        if stored_name is None:
            self._send_json({
                "error": f"找不到 video_id={video_id} 对应的文件，"
                         f"可能已被清理，或服务已重启，请重新上传",
            }, 404)
            return

        video_path = UPLOAD_DIR / stored_name
        # 双重保险：解析后必须仍在上传目录内。
        # 文件名由服务自己生成，理论上不会越界；
        # 但符号链接等文件系统特性仍可能造成越界，所以再确认一次。
        try:
            if video_path.resolve().parent != UPLOAD_DIR.resolve():
                self._send_json({"error": "文件路径越界"}, 400)
                return
        except OSError:
            self._send_json({"error": "文件路径无法解析"}, 400)
            return

        if not video_path.is_file():
            self._send_json({
                "error": "文件已不存在，可能已被清理，请重新上传",
            }, 404)
            return

        mode = params.get("analysis_mode", "automatic")
        if mode not in ("automatic", "manual_side_v1"):
            self._send_json({"error": "未知分析模式"}, 400)
            return
        if "target_selection" in params:
            try:
                from backend.analysis.target_lock import validate_target
                from backend.analysis.manual_timing import inspect_video
                metadata = inspect_video(video_path)
                target = validate_target(params["target_selection"], metadata["frame_count"])
                if params.get("view") != "side" or params.get("camera_followed") is not False:
                    raise ValueError("人物锁定首版仅支持固定侧面高帧率原片")
                review = params.get("manual_review")
                if isinstance(review, dict) and isinstance(review.get("events"), list):
                    for e in review["events"]:
                        if not isinstance(e, dict) or type(e.get("frame")) is not int or not target["frame"] <= e["frame"] <= target["end_frame"]:
                            raise ValueError("人工事件超出选人区间")
            except (ValueError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
                return
        if mode == "manual_side_v1" or "manual_review" in params:
            try:
                from backend.analysis.manual_timing import inspect_video, validate_review
                if mode != "manual_side_v1":
                    raise ValueError("人工标注必须使用 manual_side_v1 模式")
                metadata = inspect_video(video_path)
                validate_review(params.get("manual_review"), metadata,
                                view=params.get("view"), camera_followed=params.get("camera_followed"))
            except (ValueError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
                return

        view = params.get("view", "side")
        if view not in ("side", "front", "back"):
            self._send_json({"error": f"view 取值非法：{view}"}, 400)
            return

        try:
            pose_options_from_params(params)
        except PoseOptionsError as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        # ---- 扣额度 ----
        # 放在这里而不是更早：上面每一条检查失败都会 return，
        # 提前扣的话用户会因为一次参数写错就白掉一次额度。
        ok, msg = ACCOUNTS.consume_quota(username, current_period())
        if not ok:
            self._send_json({"error": msg}, 402)
            return

        job = Job(
            job_id=uuid.uuid4().hex[:16],
            video_id=video_id,
            video_path=str(video_path),
        )
        JOBS.add(job)

        threading.Thread(
            target=run_analysis, args=(job, params), daemon=True,
        ).start()

        self._send_json({"job_id": job.job_id, "status": job.status}, 202)

    def _serve_video_review(self, path: str) -> None:
        match = re.fullmatch(r"/api/videos/([0-9a-f]{16})/(metadata|frames/([0-9]{1,7}))", path)
        if match is None:
            self._send_json({"error": "视频预览路径无效"}, 400)
            return
        with _UPLOAD_LOCK:
            name = UPLOADED.get(match[1])
        video = UPLOAD_DIR / name if name else None
        if video is None or not video.is_file() or video.resolve().parent != UPLOAD_DIR.resolve():
            self._send_json({"error": "视频已不存在，请重新上传"}, 404)
            return
        try:
            from backend.analysis.manual_timing import inspect_video, read_frame
            if match[2] == "metadata":
                self._send_json(inspect_video(video))
                return
            index = int(match[3])
            # Fast upper bound before sequential decoding.
            import cv2
            cap = cv2.VideoCapture(str(video))
            try:
                count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            finally:
                cap.release()
            if not 0 <= index < count:
                raise ValueError("帧号越界")
            data = read_frame(video, index)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except (ValueError, RuntimeError) as exc:
            self._send_json({"error": str(exc)}, 400)

    def _send_job(self, job_id: str, include_report: bool) -> None:
        job = JOBS.get(job_id)
        if job is None:
            self._send_json({
                "error": "任务不存在。服务可能已重启 —— "
                         "请重新提交分析。",
            }, 404)
            return
        self._send_json(job.public(include_report=include_report))

    def _serve_keyframe(self, rel: str) -> None:
        """
        返回一张关键帧图。

        ⚠️ 这是**直接映射到文件系统**的路径，必须防目录穿越。
           做法与 /api/analyze 的 video_id 校验同源：白名单式。

        具体两道：
          ① 只接受 `<任务ID>/<文件名>` 两段，且各段字符集受限
          ② 解析后的绝对路径必须仍在 KEYFRAMES_ROOT 之内
        """
        parts = rel.split("/")
        if len(parts) != 2:
            self._send_json({"error": "路径格式非法"}, 400)
            return

        job_id, fname = parts
        if not _VIDEO_ID_RE.match(job_id):
            self._send_json({"error": "任务 ID 格式非法"}, 400)
            return
        # 文件名由本服务生成，格式固定为 f000014_touchdown.jpg。
        # 用正则而不是"过滤 .." —— 后者总会漏掉某种编码。
        if not _KEYFRAME_NAME_RE.match(fname):
            self._send_json({"error": "文件名格式非法"}, 400)
            return

        path = KEYFRAMES_ROOT / job_id / fname
        try:
            resolved = path.resolve()
            root = KEYFRAMES_ROOT.resolve()
        except OSError:
            self._send_json({"error": "路径无法解析"}, 400)
            return

        if root not in resolved.parents:
            self._send_json({"error": "路径越界"}, 400)
            return
        if not resolved.is_file():
            self._send_json({"error": "图片不存在"}, 404)
            return

        try:
            data = resolved.read_bytes()
        except OSError as e:
            self._send_json({"error": f"读取失败：{e}"}, 500)
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        # 关键帧图一旦生成就**不会变**（文件名含帧号），
        # 所以可以放心让 App 长期缓存 —— 手机重复打开报告时不用重下。
        self.send_header("Cache-Control", "public, max-age=604800")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------

def cleanup_stale_uploads() -> int:
    """
    删掉超过 STALE_UPLOAD_SECONDS 没被分析的上传文件。

    为什么需要：教练上传后可能不提交分析（改了主意、App 崩了），
    素材就留在磁盘上。一段 240fps 的慢动作素材几百 MB，
    攒几次就把磁盘占满了。
    """
    if not UPLOAD_DIR.exists():
        return 0
    cutoff = time.time() - STALE_UPLOAD_SECONDS
    removed = 0
    for f in UPLOAD_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def check_firewall(port: int) -> str:
    """
    启动时检查防火墙是否放行了本端口。

    为什么要做这个检查：
        手机连不上服务时，用户看到的是"连接超时"，
        而超时既可能是服务没启动、也可能是防火墙拦了、还可能是网段不对。
        从手机那一侧完全无法区分。

        实测踩过：服务正常监听 0.0.0.0、IP 也对、
        规则也确实加了，但手机一直超时 —— 而服务端日志干干净净。

    这里在**服务端**把结论直接给出来，让用户不用自己排查。

    ⚠️ 这个函数**必须准确**。误报比不报更糟：
       它会把用户引向错误的方向 —— 去加一条本来不需要的规则，
       或者忽略真正的原因。

       第一版按**空行**切分 netsh 输出。但字段之间是单换行、
       规则之间才是空行，于是整个输出被当成一块，
       再对端口号做子串匹配 —— 结果是"规则明明存在却报没有"。
       现在按字段逐条解析，并精确比对端口。

    只用标准库（netsh 在所有 Windows 上都有；调用开销远小于 PowerShell，
    这是服务启动路径，不该慢）。

    ⚠️ 返回值是**三态字符串**，不是布尔 —— 因为"不知道"是一种真实状态：

        "allowed"  —— 确认有规则放行
        "blocked"  —— 确认没有规则放行（此时才该提示用户去修）
        "unknown"  —— 查不了（权限不足等），**不下结论**

    为什么第一版会误报（真实踩过的坑）：
        读取规则的 `netsh advfirewall firewall show rule`
        **需要管理员权限**。服务以普通用户启动时，netsh 返回
        returncode=1、stdout="Access is denied."，解析不到任何规则，
        于是报"防火墙没有放行" —— **而规则好好地在那儿**。

        代价很大：用户被引去跑一条 New-NetFirewallRule，
        而真正的原因是手机热点的 AP 隔离。**误报比不报更糟**，
        因为它把排查方向带偏了。

        所以现在：**读不到规则就说"不知道"，绝不猜。**
    """
    try:
        proc = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=all"],
            capture_output=True, text=True, encoding="gbk",
            errors="replace", timeout=60,
        )
        out = proc.stdout

        # 权限不足的两种表现：非零返回码，或正文里明确说拒绝访问。
        # 命中任一即判"不知道"，不做任何猜测。
        if proc.returncode != 0:
            return "unknown"
        if "Access is denied" in out or "拒绝访问" in out:
            return "unknown"

        # 逐条规则解析。
        # 字段名在中文系统上仍是英文（Enabled/Direction/LocalPort/Action），
        # 只有"规则名"是用户填的内容 —— 所以按字段名解析是安全的。
        current: dict[str, str] = {}
        exact = 0
        saw_any_rule = False

        for raw in out.splitlines():
            line = raw.rstrip()
            if not line:
                if current:
                    saw_any_rule = True
                    if _allows_port(current, port):
                        exact += 1
                    current = {}
                continue
            # 分隔线（整行都是横线）跳过
            if line.strip() and set(line.strip()) == {"-"}:
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()

        if current:
            saw_any_rule = True
            if _allows_port(current, port):
                exact += 1

        if exact:
            return "allowed"
        # 解析到规则了，但其中没有放行本端口的 → 这个结论可信
        if saw_any_rule:
            return "blocked"
        # 一条规则都没解析出来 → 多半是输出格式变了或被截断，不下结论
        return "unknown"
    except Exception:
        # 检查失败不影响服务运行 —— 只是少一条提示
        return "unknown"


def firewall_hint(port: int) -> list[str]:
    """
    防火墙确实被拦时，给用户的修复提示；否则返回空列表。

    与 check_firewall 分开，是因为调用方要按三态打印**不同**的话：
    "blocked" 要给修复命令，"unknown" 要说明为什么查不了。
    """
    if check_firewall(port) != "blocked":
        return []
    return [
        f"防火墙没有放行 TCP {port} —— 手机连接会一直超时。",
        "以管理员身份运行一次即可修复：",
        f'  New-NetFirewallRule -DisplayName "YUcoach (TCP {port})" '
        f"-Direction Inbound -Protocol TCP -LocalPort {port} "
        f"-Action Allow -Profile Any",
    ]


def _allows_port(rule: dict[str, str], port: int) -> bool:
    """该条 netsh 规则是否放行了指定端口的入站 TCP。"""
    if rule.get("Enabled") != "Yes":
        return False
    if rule.get("Direction") != "In":
        return False
    if rule.get("Action") != "Allow":
        return False
    if rule.get("Protocol") not in ("TCP", "Any"):
        return False
    return rule.get("LocalPort") == str(port)


def start_cleanup_thread() -> None:
    def loop() -> None:
        while True:
            time.sleep(3600)
            n = cleanup_stale_uploads()
            if n:
                print(f"[cleanup] 清理了 {n} 个过期上传文件")

    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="YUcoach 分析服务端")
    ap.add_argument("--host", default="0.0.0.0",
                    help="监听地址。0.0.0.0 表示局域网可访问")
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    KEYFRAMES_ROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print("YUcoach 分析服务端")
    print("=" * 68)
    print(f"  监听      http://{args.host}:{args.port}")
    print(f"  上传目录  {UPLOAD_DIR}")
    print()

    # 账号初始化
    for line in ensure_admin():
        print(f"  {line}")

    new_codes = seed_demo_codes(ACCOUNTS)
    if new_codes:
        print()
        print("  [演示兑换码] 首次启动已生成，用于测试升级流程：")
        for c in new_codes:
            acc = ACCOUNTS.list_codes()
            tier = next((x.tier for x in acc if x.code == c), "?")
            print(f"    {c}   -> {tier_label(tier)}")
        print("  ⚠️ 这些码写在 .cache/accounts.json 里，可删文件重置。")
    print()

    # 打印局域网地址，方便在手机上填
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        print(f"  手机访问   http://{lan_ip}:{args.port}")
        print()
    except OSError:
        pass

    print("  [WARN] 本服务无认证，仅供局域网内短期使用。")
    print("         不要暴露到公网。")
    print()

    # 防火墙自检。放在"手机访问"地址之后 ——
    # 用户先是看到地址、去手机上填，然后失败；这里要能在同一屏上
    # 直接告诉他原因，而不是让他回去翻文档。
    fw = check_firewall(args.port)
    if fw == "blocked":
        for line in firewall_hint(args.port):
            print(f"  {line}")
        print("  " + "-" * 64)
        print()
    elif fw == "allowed":
        print(f"  [OK] 防火墙已放行 TCP {args.port}")
        print()
    else:
        # "unknown"：读不到规则（通常是权限不足）。
        # ⚠️ 这里**不能**说"没放行" —— 那是猜测，而且实测误报过：
        #    规则明明存在，用户却被引去加规则。
        print("  防火墙状态未能确认（读取规则需要管理员权限）。")
        print("  这不代表被拦截 —— 若手机连不上，优先检查：")
        print("    1. 手机与电脑是否在同一网络")
        print("    2. 地址是否用的上面打印的那个 IP")
        print("    3. 手机热点是否开着 AP 隔离（需关闭）")
        print()

    print("  Ctrl+C 停止")
    print()

    start_cleanup_thread()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
