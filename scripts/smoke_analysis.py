"""
G5 端到端冒烟测试：跑完整分析管线，并用契约校验产物。

为什么这道门不可替代：
    单元测试各自都过，不代表连起来能跑通。
    本项目的各模块之间靠**数据结构**耦合：
      · video_io 产出的 Info 要能喂给 report
      · pose_types 的坐标约定要与 metrics 的期望一致
      · metrics 的输出结构要能被 report 组装成合法 JSON
    这些接口约定任何一处错位，单测都不会发现。

    而且必须**用真实契约校验产物**，而不是自己写断言 ——
    自己写的断言只会验证"我以为契约是什么样"。

用合成视频而不是真实素材：
    门禁要在任何机器上、任何时候都能跑，不能依赖
    samples/videos/ 里有没有素材。真实素材的验证是另一件事
    （见 docs/12-姿态提取验证报告.md）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# 本文件在 scripts/ 下，所以仓库根是上两级
ROOT = Path(__file__).resolve().parent.parent

# 控制台编码兜底。
#
# ⚠️ Windows 默认是 GBK。子进程的输出经 UTF-8 解码后可能含
#    替换字符（\ufffd），用 GBK 打印时**直接崩溃** ——
#    而且崩溃点在一个纯输出的 print 上，把真正的错误盖掉了。
#    （本项目真实踩过：子进程失败的信息完全看不到，
#      只看到一个 UnicodeEncodeError。）
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


def make_synthetic_video(path: Path, frames: int = 40,
                         fps: float = 60.0) -> Path:
    """生成一段带人形色块的合成视频，够 YOLO 检出即可。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 640, 480
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                         fps, (w, h))

    for i in range(frames):
        frame = np.full((h, w, 3), 200, dtype=np.uint8)
        # 跑道底色
        cv2.rectangle(frame, (0, int(h * 0.55)), (w, h), (120, 150, 180), -1)
        # 分道线（让参考尺度检测有东西可找）
        for k in range(4):
            y = int(h * (0.62 + k * 0.09))
            cv2.line(frame, (0, y), (w, y), (240, 240, 240), 2)

        # 一个人形：头 + 躯干 + 腿，随帧向右移动
        cx = int(w * 0.25 + i * 3)
        cy = int(h * 0.55)
        cv2.circle(frame, (cx, cy - 52), 11, (40, 40, 60), -1)
        cv2.line(frame, (cx, cy - 40), (cx, cy), (40, 40, 60), 9)
        cv2.line(frame, (cx, cy), (cx - 9, cy + 34), (40, 40, 60), 7)
        cv2.line(frame, (cx, cy), (cx + 9, cy + 34), (40, 40, 60), 7)
        vw.write(frame)

    vw.release()
    return path


def main() -> int:
    tmp = ROOT / "output" / "_smoke"
    tmp.mkdir(parents=True, exist_ok=True)

    video = tmp / "smoke.mp4"
    report_path = tmp / "smoke_analysis.json"

    print("=" * 68)
    print("端到端冒烟测试")
    print("=" * 68)
    print()

    # ---- 1. 合成素材 ----
    try:
        make_synthetic_video(video, frames=40, fps=60.0)
    except Exception as e:
        print(f"[FAIL] 无法生成合成视频：{e}")
        print("       （本机 OpenCV 可能不支持 mp4v 编码）")
        return 1
    print(f"  [OK] 合成素材 {video.name}（40 帧 @60fps）")

    # ---- 2. 跑完整管线 ----
    #
    # 直接在子进程里 import 后调用 main()，而不是 `python -m ...`
    # 或直接跑脚本文件：
    #   · `python -m backend.analysis.analyze` 要求 backend 包在
    #     sys.path 里，而 `-m` 的搜索路径不含 cwd（除非 cwd 就是仓库根）
    #   · 直接跑 analyze.py 会因为包内的相对导入（from .metrics import）
    #     而失败 —— 没有父包上下文
    # 在子进程里显式 sys.path 引导 + import，两种问题都绕开。
    driver = (
        "import sys; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        "from backend.analysis.analyze import main; "
        "sys.exit(main())"
    )
    cmd = [
        sys.executable, "-c", driver,
        str(video),
        "--out", str(tmp),
        "--athlete-id", "at00001",
        "--athlete-name", "冒烟测试",
        "--height", "178",
        "--view", "side",
        "--quiet",
    ]
    # 子进程需要能找到 backend 包。
    # 显式设 PYTHONPATH 而不是依赖 cwd —— python -m 的模块搜索路径
    # 里不包含 cwd（除非是脚本所在目录），这是常见困惑点。
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    if proc.returncode != 0:
        print(f"[FAIL] 分析管线退出码 {proc.returncode}")
        print(proc.stdout[-2000:] if proc.stdout else "")
        print(proc.stderr[-2000:] if proc.stderr else "")
        return 1
    print("  [OK] 分析管线跑通")

    if not report_path.exists():
        print(f"[FAIL] 未生成报告：{report_path}")
        return 1

    # ---- 3. JSON 可解析 ----
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[FAIL] 报告不是合法 JSON：{e}")
        return 1
    print("  [OK] 报告是合法 JSON")

    # ---- 4. 关键结构存在 ----
    required = ["schema_version", "analysis_id", "session", "versions",
                "quality_score", "metrics", "findings", "summary",
                "phases_detected", "keyframes"]
    missing = [k for k in required if k not in report]
    if missing:
        print(f"[FAIL] 报告缺少必填字段：{missing}")
        return 1
    print(f"  [OK] 根字段齐全（{len(required)} 项）")

    if not report["metrics"]:
        print("[FAIL] metrics 为空 —— 契约要求所有指标都要出现，"
              "哪怕是数据不足")
        return 1
    print(f"  [OK] metrics 有 {len(report['metrics'])} 条")

    # ---- 5. 用真实契约校验 ----
    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_contracts.py"),
         "--fixture", str(report_path), "--schema", "analysis"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check.returncode != 0:
        print("[FAIL] 报告不符合 analysis 契约：")
        for line in (check.stdout or "").splitlines()[-15:]:
            print(f"       {line}")
        return 1
    print("  [OK] 报告通过 analysis 契约校验")

    print()
    print("[OK] 端到端冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
