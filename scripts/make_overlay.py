"""
生成关键点叠加图，供人工目视核对（docs/02 的 QC-4）。

## 为什么不能自动化

自动检查只能发现"点在不在合理范围"，发现不了**整体错位** ——
比如所有点统一偏了 5 像素、或者趾跟互相标反。
这类错误不报错、数值也合理，只有把点画回画面上一眼能看出。

所以你项目文档把这一步列为"唯一不能自动化"的环节。

## 输出什么

  · 整帧叠加图（看整体骨架形态）
  · 足部裁剪放大图（看趾尖/足跟是否落在脚上）—— 这个是关键

## 用法

    python scripts/make_overlay.py [--estimator rtm] [--frames 0,30,60]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from backend.analysis.pose_types import KEYPOINT_NAMES  # noqa: E402
from backend.paths import apply_env_defaults, ensure_cache_dirs  # noqa: E402

_I = {n: i for i, n in enumerate(KEYPOINT_NAMES)}

#: 骨架连线（只画有意义的，避免一团乱）
SKELETON = [
    ("head", "neck"), ("neck", "shoulder_r"), ("neck", "shoulder_l"),
    ("shoulder_r", "hip_r"), ("shoulder_l", "hip_l"),
    ("hip_r", "hip_l"),
    ("hip_r", "knee_r"), ("knee_r", "ankle_r"), ("ankle_r", "heel_r"),
    ("ankle_r", "toe_r"), ("heel_r", "toe_r"),
    ("hip_l", "knee_l"), ("knee_l", "ankle_l"), ("ankle_l", "heel_l"),
    ("ankle_l", "toe_l"), ("heel_l", "toe_l"),
]

#: 足部点用醒目的颜色单独标 —— 这是本次要核对的
FOOT_POINTS = {"heel_r": (0, 0, 255), "toe_r": (0, 165, 255),
               "heel_l": (255, 0, 255), "toe_l": (255, 255, 0)}

OTHER_COLOR = (0, 255, 0)


def draw(frame: np.ndarray, kp: np.ndarray) -> np.ndarray:
    """在帧上画骨架与关键点。kp 是归一化 (16,3)。"""
    h, w = frame.shape[:2]
    img = frame.copy()

    def pt(name: str):
        x, y, q = kp[_I[name]]
        if q == 0:
            return None
        return int(x * w), int(y * h)

    # 骨架线
    for a, b in SKELETON:
        pa, pb = pt(a), pt(b)
        if pa and pb:
            cv2.line(img, pa, pb, OTHER_COLOR, 1, cv2.LINE_AA)

    # 普通关键点
    for name in KEYPOINT_NAMES:
        if name in FOOT_POINTS:
            continue
        p = pt(name)
        if p:
            cv2.circle(img, p, 2, OTHER_COLOR, -1, cv2.LINE_AA)

    # 足部点：大一圈 + 描边，便于在小图上分辨
    for name, color in FOOT_POINTS.items():
        p = pt(name)
        if p:
            cv2.circle(img, p, 4, (0, 0, 0), -1, cv2.LINE_AA)
            cv2.circle(img, p, 2, color, -1, cv2.LINE_AA)

    return img


def foot_zoom(frame: np.ndarray, kp: np.ndarray, pad: int = 40,
              scale: int = 8) -> np.ndarray | None:
    """
    裁剪足部区域并放大。

    为什么需要：运动员在画面里可能只有几十像素高，足部不到 10 像素 ——
    不放大根本看不出点有没有落在脚上。
    """
    h, w = frame.shape[:2]
    xs, ys = [], []
    for name in ("ankle_r", "toe_r", "heel_r", "ankle_l", "toe_l", "heel_l"):
        x, y, q = kp[_I[name]]
        if q:
            xs.append(x * w)
            ys.append(y * h)
    if not xs:
        return None

    x0 = max(0, int(min(xs)) - pad)
    x1 = min(w, int(max(xs)) + pad)
    y0 = max(0, int(min(ys)) - pad)
    y1 = min(h, int(max(ys)) + pad)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None

    crop = frame[y0:y1, x0:x1].copy()
    zoom = cv2.resize(crop, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_NEAREST)

    # 放大后重新画点（坐标要按裁剪框平移再放大）
    def zpt(name: str):
        x, y, q = kp[_I[name]]
        if not q:
            return None
        return (int((x * w - x0) * scale), int((y * h - y0) * scale))

    for a, b in (("ankle_r", "toe_r"), ("ankle_r", "heel_r"),
                 ("toe_r", "heel_r"), ("ankle_l", "toe_l"),
                 ("ankle_l", "heel_l"), ("toe_l", "heel_l")):
        pa, pb = zpt(a), zpt(b)
        if pa and pb:
            cv2.line(zoom, pa, pb, (255, 255, 255), 1, cv2.LINE_AA)

    for name, color in (("ankle_r", (0, 255, 0)), ("ankle_l", (0, 255, 0)),
                        ("heel_r", (0, 0, 255)), ("toe_r", (0, 165, 255)),
                        ("heel_l", (255, 0, 255)), ("toe_l", (255, 255, 0))):
        p = zpt(name)
        if p:
            cv2.circle(zoom, p, 3, color, -1, cv2.LINE_AA)

    return zoom


def main() -> int:
    ap = argparse.ArgumentParser(description="生成关键点叠加图供目视核对")
    ap.add_argument("--estimator", default="rtm", choices=["rtm", "yolo"])
    ap.add_argument("--frames", default="0,40,80,120",
                    help="逗号分隔的帧号")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "overlay")
    ap.add_argument("--video", type=Path,
                    default=ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4")
    args = ap.parse_args()

    apply_env_defaults()
    ensure_cache_dirs()

    print("=" * 72)
    print(f"生成叠加图（提取器 {args.estimator}）")
    print("=" * 72)
    print()

    if args.estimator == "rtm":
        from backend.analysis.pose_estimator_rtm import RtmPoseEstimator
        est = RtmPoseEstimator()
    else:
        from backend.analysis.pose_estimator import YoloPoseEstimator
        est = YoloPoseEstimator()
    print(f"  提取器 {est.name}（设备 {getattr(est, 'device', '?')}）")
    print()

    wanted = {int(s) for s in args.frames.split(",") if s.strip()}
    args.out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(args.video))
    idx = 0
    made = 0
    while wanted:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in wanted:
            wanted.discard(idx)
            pf = est.estimate(frame, idx)
            if pf is None:
                print(f"  帧{idx}: 未检出人体，跳过")
                idx += 1
                continue

            full = draw(frame, pf.keypoints)
            p_full = args.out / f"{args.estimator}_f{idx:04d}_full.jpg"
            cv2.imwrite(str(p_full), full,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 92])

            zoom = foot_zoom(frame, pf.keypoints)
            p_zoom = None
            if zoom is not None:
                p_zoom = args.out / f"{args.estimator}_f{idx:04d}_foot.png"
                cv2.imwrite(str(p_zoom), zoom)

            print(f"  帧{idx}: 整帧 -> {p_full.name}"
                  + (f"   足部放大 -> {p_zoom.name}" if p_zoom else ""))
            made += 1
        idx += 1
    cap.release()

    print()
    print(f"共生成 {made} 帧的图，输出目录：{args.out}")
    print()
    print("=" * 72)
    print("怎么核对（docs/02 QC-4）")
    print("=" * 72)
    print()
    print("  看 *_foot.png（足部放大图）：")
    print("    · 橙点（右趾）与黄点（左趾）应落在**脚的最前端**")
    print("    · 红点（右跟）与紫点（左跟）应落在**脚跟最后端**")
    print("    · 三个点应构成一个**朝前伸出的三角形**，而不是挤在一起")
    print("    · 左右不能反：跑动方向上，趾应在跟的**前方**")
    print()
    print("  看 *_full.jpg（整帧）：")
    print("    · 骨架应贴合人体，无扭曲、无断裂")
    print("    · 头→颈→肩→髋→膝→踝 的上下关系正确")
    print()
    print("  ⚠️ 骨架看起来「差不多对」不代表足部点对 —— 足部必须看放大图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
