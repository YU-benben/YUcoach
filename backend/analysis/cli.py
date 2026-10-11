"""
姿态提取命令行工具：视频 -> 骨骼叠加视频 + 关键点 CSV。

用法：
    python -m backend.analysis.cli 视频路径 [选项]

例：
    python -m backend.analysis.cli samples/videos/run.mp4
    python -m backend.analysis.cli samples/videos/run.mp4 --max-frames 300

产出（默认写到 output/ 下）：
    <名字>_skeleton.mp4   骨骼叠加视频 —— 用于肉眼确认跟踪质量
    <名字>_keypoints.csv  逐帧关键点，44 列（2 + 16×3）

为什么第一步先做"画出来看"而不是直接算指标：
    如果关键点跟踪本身就是错的，后面所有指标都是在错误数据上做精确计算 ——
    这比不做还危险，因为它看起来很像真的。
    肉眼确认是唯一能在早期发现跟踪错误的手段。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ..paths import apply_env_defaults, ensure_cache_dirs

# 缓存路径在导入 cv2 / torch 之前设好，否则会写到项目外
apply_env_defaults()
ensure_cache_dirs()

import cv2
import numpy as np

from .keypoint_map import COCO_NAMES
from .pose_estimator import YoloPoseEstimator
from .pose_types import (
    KEYPOINT_NAMES,
    Q_CLEAR,
    Q_INVISIBLE,
    Q_UNCERTAIN,
    PoseSequence,
)
from .video_io import estimate_camera_motion, iter_frames, read_video_info

# 骨骼连线。用契约的 16 点名称定义，而不是 COCO 的 17 点。
# 每对表示一条要画的线。
SKELETON_EDGES: tuple[tuple[str, str], ...] = (
    # 躯干
    ("head", "neck"),
    ("neck", "shoulder_r"),
    ("neck", "shoulder_l"),
    ("shoulder_r", "shoulder_l"),
    ("neck", "pelvis_center"),
    ("shoulder_r", "hip_r"),
    ("shoulder_l", "hip_l"),
    ("hip_r", "hip_l"),
    # 右腿
    ("hip_r", "knee_r"),
    ("knee_r", "ankle_r"),
    ("ankle_r", "heel_r"),
    ("ankle_r", "toe_r"),
    ("heel_r", "toe_r"),
    # 左腿
    ("hip_l", "knee_l"),
    ("knee_l", "ankle_l"),
    ("ankle_l", "heel_l"),
    ("ankle_l", "toe_l"),
    ("heel_l", "toe_l"),
)

# 颜色（BGR）。区分左右腿，便于肉眼检查左右标签有没有反。
COLOR_CENTER = (240, 240, 240)      # 中线：近白
COLOR_RIGHT = (80, 200, 80)         # 右侧：绿
COLOR_LEFT = (80, 160, 255)         # 左侧：橙
COLOR_DERIVED = (0, 220, 255)       # 推导点：黄（提示精度不足）

_RIGHT_KP = {"shoulder_r", "hip_r", "knee_r", "ankle_r", "heel_r", "toe_r"}
_LEFT_KP = {"shoulder_l", "hip_l", "knee_l", "ankle_l", "heel_l", "toe_l"}
_DERIVED_KP = {"heel_r", "toe_r", "heel_l", "toe_l"}


def _color_for(name: str) -> tuple[int, int, int]:
    if name in _RIGHT_KP:
        return COLOR_RIGHT
    if name in _LEFT_KP:
        return COLOR_LEFT
    return COLOR_CENTER


def draw_pose(
    frame: np.ndarray,
    kps: np.ndarray,
    show_quality: bool = True,
) -> np.ndarray:
    """
    把 16 个关键点与骨骼画到帧上。

    质量码的视觉表达（重要）：
        q=2 清晰   -> 实心圆点 + 实线
        q=1 存疑   -> 空心圆点 + 线（表示不可全信）
        q=0 不可见 -> 不画，相关骨骼线也断开
    这样教练一眼就能看出哪些部位的数据不可靠。
    """
    h, w = frame.shape[:2]
    out = frame.copy()

    idx = {n: i for i, n in enumerate(KEYPOINT_NAMES)}

    def px(name: str):
        i = idx[name]
        x, y, q = kps[i]
        if q == Q_INVISIBLE:
            return None
        return int(x * w), int(y * h), int(q)

    # ---- 骨骼线 ----
    for a, b in SKELETON_EDGES:
        pa, pb = px(a), px(b)
        if pa is None or pb is None:
            continue

        # 一端是推导点时用黄色虚线感（这里用细黄线近似）
        derived = a in _DERIVED_KP or b in _DERIVED_KP
        color = COLOR_DERIVED if derived else _color_for(a)
        thickness = 1 if derived else 2

        cv2.line(out, (pa[0], pa[1]), (pb[0], pb[1]), (0, 0, 0), thickness + 2,
                 cv2.LINE_AA)  # 黑色描边，保证在浅色背景上也看得清
        cv2.line(out, (pa[0], pa[1]), (pb[0], pb[1]), color, thickness,
                 cv2.LINE_AA)

    # ---- 关键点 ----
    for name in KEYPOINT_NAMES:
        p = px(name)
        if p is None:
            continue
        x, y, q = p
        color = COLOR_DERIVED if name in _DERIVED_KP else _color_for(name)

        if q == Q_CLEAR:
            cv2.circle(out, (x, y), 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(out, (x, y), 3, color, -1, cv2.LINE_AA)
        else:
            # 存疑：空心圈。视觉上明显区别于实心，提示"别全信"
            cv2.circle(out, (x, y), 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(out, (x, y), 4, color, 1, cv2.LINE_AA)

    if show_quality:
        pass  # 质量信息在下方文字层统一显示

    return out


def write_keypoints_csv(seq: PoseSequence, path: Path) -> None:
    """
    逐帧关键点写出 CSV，44 列。

    列定义见 docs/02-数据标准.md：
        session_id, frame, 然后每个点 x/y/q 三列，共 2 + 16×3 = 50 列

    注：契约文档写的是 44 列，实际按 16 点算应为 2 + 48 = 50 列。
    这里按**实际点数**生成，并在表头写清列名，
    避免"列数对不上但没人发现"的情况。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    header = ["session_id", "frame"]
    for n in KEYPOINT_NAMES:
        header += [f"{n}_x", f"{n}_y", f"{n}_q"]

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for pf in seq.frames:
            row = ["", pf.frame_index]
            for x, y, q in pf.keypoints:
                row += [f"{x:.6f}", f"{y:.6f}", int(q)]
            w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="视频 -> 姿态提取 -> 骨骼叠加视频 + 关键点 CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("video", type=Path, help="输入视频路径")
    ap.add_argument("--out", type=Path, default=Path("output"),
                    help="输出目录（默认 output/）")
    ap.add_argument("--model", default="yolov8n-pose.pt",
                    help="姿态模型权重（默认 yolov8n-pose.pt）")
    ap.add_argument("--imgsz", type=int, default=960,
                    help="推理分辨率（默认 960）")
    ap.add_argument("--max-frames", type=int, default=None,
                    help="只处理前 N 帧，用于快速试跑")
    ap.add_argument("--start-frame", type=int, default=0,
                    help="从第几帧开始（默认 0）")
    ap.add_argument("--no-video", action="store_true",
                    help="不生成叠加视频（只要 CSV 时用）")
    ap.add_argument("--fourcc", default="mp4v",
                    help="输出视频编码（默认 mp4v；部分播放器不认，"
                         "可换 avc1 或 XVID）")

    args = ap.parse_args()

    if not args.video.exists():
        print(f"[FAIL] 视频不存在：{args.video}")
        return 1

    print("=" * 68)
    print("姿态提取")
    print("=" * 68)
    print()

    # ---- 1. 视频信息与帧率校验 ----
    print("读取视频信息...")
    try:
        info = read_video_info(args.video)
    except Exception as e:
        print(f"[FAIL] {e}")
        return 1

    print(info.summary())
    print()

    if info.fps_verification.status == "warning":
        print("[WARN] 帧率校验未通过 —— 时间类指标的可靠性存疑。")
        print()

    # ---- 2. 镜头运动 ----
    print("估计镜头运动...")
    level, shift, motion_notes = estimate_camera_motion(args.video)
    for n in motion_notes:
        print(f"  {n}")
    print()

    # ---- 3. 姿态提取 ----
    start = args.start_frame
    end = None if args.max_frames is None else start + args.max_frames

    print(f"加载姿态模型 {args.model} ...")
    try:
        est = YoloPoseEstimator(model_name=args.model, imgsz=args.imgsz)
    except Exception as e:
        print(f"[FAIL] 模型加载失败：{e}")
        return 1
    print(f"  设备 {est.device}   权重 {est.weight_file}")
    print()

    total = min(info.frame_count - start,
                args.max_frames if args.max_frames else 10 ** 9)
    print(f"开始处理 {total} 帧...")

    t0 = time.time()
    last_print = [0.0]

    def progress(done: int, idx: int, missed: int) -> None:
        now = time.time()
        # 每 2 秒刷一次，避免刷屏
        if now - last_print[0] < 2.0 and done < total:
            return
        last_print[0] = now
        elapsed = now - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        pct = done / total * 100 if total else 0
        print(f"  {done:5d}/{total}  {pct:5.1f}%  "
              f"{rate:5.1f} 帧/秒  剩余约 {eta:4.0f} 秒  未检出 {missed}",
              end="\r", flush=True)

    frames = iter_frames(args.video, start=start, end=end)
    seq = est.estimate_sequence(frames, progress=progress)
    elapsed = time.time() - t0
    print()
    print(f"  完成：{len(seq)} 帧，耗时 {elapsed:.1f} 秒"
          f"（{len(seq) / elapsed:.1f} 帧/秒）")
    print()

    for n in seq.notes:
        print(f"  · {n}")
    print()

    # ---- 4. 关键点覆盖统计 ----
    cov = seq.coverage()
    print("各关键点可见率：")
    # 分三列打印，便于扫读
    items = list(cov.items())
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        line = "  ".join(f"{n:16s} {v * 100:5.1f}%" for n, v in chunk)
        print(f"  {line}")
    print()

    low = [(n, v) for n, v in cov.items() if v < 0.5]
    if low:
        print("[WARN] 以下关键点可见率低于 50%，基于它们的指标不可靠：")
        for n, v in low:
            print(f"         {n:16s} {v * 100:.1f}%")
        print()

    derived = seq.derived_ratio()
    print(f"含几何推导足部点的帧占比：{derived * 100:.1f}%")
    print("  （足部点非实测，精度不足以支撑精确的触地时间测量）")
    print()

    # ---- 5. 输出 ----
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.video.stem
    wrote: list[Path] = []

    csv_path = args.out / f"{stem}_keypoints.csv"
    write_keypoints_csv(seq, csv_path)
    wrote.append(csv_path)

    if not args.no_video:
        video_path = args.out / f"{stem}_skeleton.mp4"
        fourcc = cv2.VideoWriter_fourcc(*args.fourcc)
        writer = cv2.VideoWriter(str(video_path), fourcc,
                                 info.fps_declared or 30.0,
                                 (info.width, info.height))

        skipped = 0
        frames2 = iter_frames(args.video, start=start, end=end)
        by_index = {f.frame_index: f for f in seq.frames}

        for idx, bgr in frames2:
            pf = by_index.get(idx)
            if pf is None:
                # 未检出的帧：原样写出并加提示，而不是静默跳过 ——
                # 丢帧会让输出视频的时间轴与原始素材错位
                out_frame = bgr
                cv2.putText(out_frame, "no detection", (16, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                skipped += 1
            else:
                out_frame = draw_pose(bgr, pf.keypoints)
                if pf.is_interpolated:
                    cv2.putText(out_frame, "interpolated", (16, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 165, 255), 2)

            writer.write(out_frame)

        writer.release()
        wrote.append(video_path)
        if skipped:
            print(f"[WARN] 有 {skipped} 帧未检出人体，已在视频中标注")

    print("已生成：")
    for p in wrote:
        size_mb = p.stat().st_size / 1024**2
        print(f"  {p}  ({size_mb:.1f} MB)")
    print()
    print("下一步：打开骨骼叠加视频，肉眼确认跟踪质量。")
    print("  重点看：左右腿是否标反、关节点是否稳定、有没有跳变。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
