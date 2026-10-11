"""
足部点质量评估：用解剖学尺度判据检查"点是否挤成一团"。

## 要防的错误

姿态模型在足部看不清时，会把"趾尖""脚跟"都预测到**踝关节附近** ——
三点挤成一团。

这种错误很阴险：
  · **方向是对的**（趾确实在踝下方、跟也确实在踝后方）
    → 现有脚本的方向性自检 100% 通过
  · **置信度可能也不低** → 可见度检查也通过
  · 但足部几何已经失真

而触地/离地判定**恰恰依赖足部的伸展形态** —— 点挤成一团后
触地时刻就判不准了，而且不会报错。

## 判据（解剖学常数）

    足长     ≈ 0.15 × 身高
    躯干长   ≈ 0.30 × 身高        （肩中点到髋中点）
    ─────────────────────────
    ⇒ (踝→趾) / 躯干长 ≈ 0.5

落在 [0.35, 0.75] 之外的帧标记为可疑。

## 为什么用比值而不是像素

比值**与画面尺度无关** —— 同一段素材里运动员远近变化时，
像素长度会变但比值不变。所以它能跨帧、跨素材、跨分辨率使用。

见 docs/14 §3。
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np  # noqa: E402

from backend.analysis.pose_types import KEYPOINT_NAMES  # noqa: E402

#: 解剖学比值区间。见模块文档。
RATIO_MIN = 0.35
RATIO_MAX = 0.75

_I = {n: i for i, n in enumerate(KEYPOINT_NAMES)}


def torso_length(kp: np.ndarray) -> float | None:
    """
    躯干像素长度 = 肩中点 → 髋中点。

    两个中点都由左右两点求平均。任一侧缺失（q=0）则返回 None。
    """
    need = ("shoulder_l", "shoulder_r", "hip_l", "hip_r")
    if any(kp[_I[n]][2] == 0 for n in need):
        return None
    sy = (kp[_I["shoulder_l"]][1] + kp[_I["shoulder_r"]][1]) / 2
    hy = (kp[_I["hip_l"]][1] + kp[_I["hip_r"]][1]) / 2
    d = abs(hy - sy)
    return d if d > 1e-6 else None


def foot_ratios(kp: np.ndarray) -> dict[str, float]:
    """
    算出每侧的"踝→趾 / 躯干"比值。缺点的侧不出现。

    返回形如 {'r': 0.52, 'l': 0.48}
    """
    t = torso_length(kp)
    if t is None:
        return {}
    out: dict[str, float] = {}
    for side in ("r", "l"):
        ankle, toe, heel = (kp[_I[f"ankle_{side}"]], kp[_I[f"toe_{side}"]],
                            kp[_I[f"heel_{side}"]])
        if ankle[2] == 0 or toe[2] == 0:
            continue
        d_toe = float(np.hypot(toe[0] - ankle[0], toe[1] - ankle[1]))
        out[side] = d_toe / t
        # 脚跟也顺带算一个，供人工参考（跟本来就更短，不参与判定）
        if heel[2] != 0:
            out[f"{side}_heel"] = float(
                np.hypot(heel[0] - ankle[0], heel[1] - ankle[1])
            ) / t
    return out


def summarize(name: str, per_frame: list[float]) -> dict:
    """汇总一段序列的比值分布与判定。"""
    if not per_frame:
        return {"name": name, "n": 0, "verdict": "无数据"}

    arr = np.array(per_frame, dtype=float)
    inside = ((arr >= RATIO_MIN) & (arr <= RATIO_MAX)).mean() * 100

    if inside >= 95:
        verdict = "✅ 通过"
    elif inside >= 80:
        verdict = "⚠️ 大体合理，但有可疑帧"
    else:
        verdict = "❌ 足部点可能挤成一团"

    return {
        "name": name,
        "n": len(arr),
        "median": float(np.median(arr)),
        "p10": float(np.percentile(arr, 10)),
        "p90": float(np.percentile(arr, 90)),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "inside_pct": inside,
        "verdict": verdict,
    }


def print_summary(s: dict) -> None:
    if s["n"] == 0:
        print(f"  {s['name']:<28} 无数据")
        return
    print(f"  {s['name']}")
    print(f"      样本 {s['n']:>5}   中位 {s['median']:.3f}   "
          f"p10 {s['p10']:.3f}   p90 {s['p90']:.3f}")
    print(f"      范围 {s['min']:.3f} – {s['max']:.3f}   "
          f"落在 [{RATIO_MIN}, {RATIO_MAX}] 内 {s['inside_pct']:5.1f}%")
    print(f"      {s['verdict']}")


def evaluate(estimator: str, video: Path, max_frames: int | None) -> dict:
    """用指定提取器跑一遍，统计足部比值。"""
    import cv2

    from backend.analysis.video_io import iter_frames
    from backend.paths import apply_env_defaults, ensure_cache_dirs

    apply_env_defaults()
    ensure_cache_dirs()

    print(f"  加载提取器 {estimator} …")
    if estimator == "rtm":
        from backend.analysis.pose_estimator_rtm import RtmPoseEstimator
        est = RtmPoseEstimator()
    else:
        from backend.analysis.pose_estimator import YoloPoseEstimator
        est = YoloPoseEstimator()

    print(f"  提取姿态（设备 {getattr(est, 'device', '?')}）…")
    frames = []
    for i, (idx, bgr) in enumerate(iter_frames(video, end=max_frames)):
        pf = est.estimate(bgr, idx)
        if pf is not None:
            frames.append(pf)
    print(f"  得到 {len(frames)} 帧姿态")
    print()

    right, left, r_heel, l_heel = [], [], [], []
    for pf in frames:
        r = foot_ratios(pf.keypoints)
        if "r" in r:
            right.append(r["r"])
        if "l" in r:
            left.append(r["l"])
        if "r_heel" in r:
            r_heel.append(r["r_heel"])
        if "l_heel" in r:
            l_heel.append(r["l_heel"])

    return {
        "estimator": estimator,
        "estimator_name": est.name,
        "provides_feet": est.provides_feet if hasattr(est, "provides_feet")
                         else est.provides_foot_keypoints,
        "frames": len(frames),
        "right": summarize("右侧 (踝→趾) / 躯干", right),
        "left": summarize("左侧 (踝→趾) / 躯干", left),
        "right_heel": summarize("右侧 (踝→跟) / 躯干", r_heel),
        "left_heel": summarize("左侧 (踝→跟) / 躯干", l_heel),
        "raw_right": right,
        "raw_left": left,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="足部点解剖学尺度自检")
    ap.add_argument("video", nargs="?", type=Path,
                    default=ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4")
    ap.add_argument("--max-frames", type=int, default=200)
    ap.add_argument("--estimators", default="rtm,yolo",
                    help="逗号分隔：rtm / yolo")
    args = ap.parse_args()

    print("=" * 72)
    print("足部点解剖学尺度自检")
    print("=" * 72)
    print(f"素材：{args.video.name}")
    print(f"判据：(踝→趾) / 躯干 应落在 [{RATIO_MIN}, {RATIO_MAX}]")
    print("      依据：足长≈0.15×身高，躯干≈0.30×身高 ⇒ 比值≈0.5")
    print()

    results = []
    for name in [s.strip() for s in args.estimators.split(",") if s.strip()]:
        try:
            results.append(evaluate(name, args.video, args.max_frames))
        except Exception as e:                        # noqa: BLE001
            print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
            print()
        print()

    print("=" * 72)
    print("结果")
    print("=" * 72)
    print()
    for r in results:
        tag = "实测足部点" if r["provides_feet"] else "几何推导足部点"
        print(f"--- {r['estimator']}（{r['estimator_name']}，{tag}）"
              f"  共 {r['frames']} 帧 ---")
        for key in ("right", "left", "right_heel", "left_heel"):
            print_summary(r[key])
        print()

    print("=" * 72)
    print("说明")
    print("=" * 72)
    print()
    print("  · 踝→趾 用比值判定，所以与画面尺度无关，可跨素材比较。")
    print("  · 踝→跟 本来就更短（跟离踝比趾离踝近），只作参考，不参与判定。")
    print("  · 现有素材运动员仅占画面高度约 13%，绝对像素很小，")
    print("    比值的方差会偏大 —— 合规素材上应更集中。")
    print("  · **比值只是筛查，不能替代目视**：它抓「挤成一团」，")
    print("    抓不到「整体错位」（比如所有点统一偏了 5 像素）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
