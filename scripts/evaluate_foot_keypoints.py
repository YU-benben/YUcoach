"""
评估 MediaPipe PoseLandmarker 的足部关键点质量。

要回答的问题：
    我们当前用几何推导生成脚跟/脚尖点（COCO-17 没有足部点）。
    换成 MediaPipe 的真实足部点，能带来实质改善吗？

判据（不是"跑通就算数"）：
    1. 足部点是否**稳定可见**（可见率）
    2. 置信度分布如何
    3. 与几何推导的足部点相比，位置差异多大
    4. **可信度自检**：脚尖应当在踝关节的前下方 —— 违背这个几何关系的帧
       说明关键点错了

    第 4 条是关键。一个"稳定但系统性错误"的足部点，
    比"不稳定但无偏"的更危险 —— 它会稳定地给出错误的触地时刻。

用法：
    python scripts/evaluate_foot_keypoints.py [视频路径] [最大帧数]
"""

from __future__ import annotations

import math
import statistics as st
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from backend.analysis.keypoint_map import derive_foot_points  # noqa: E402
from backend.paths import MODELS_DIR  # noqa: E402

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task"
)
MODEL_PATH = MODELS_DIR / "pose_landmarker_full.task"

# MediaPipe 的 33 点索引
MP_NOSE = 0
MP_L_SHOULDER, MP_R_SHOULDER = 11, 12
MP_L_ELBOW, MP_R_ELBOW = 13, 14
MP_L_WRIST, MP_R_WRIST = 15, 16
MP_L_HIP, MP_R_HIP = 23, 24
MP_L_KNEE, MP_R_KNEE = 25, 26
MP_L_ANKLE, MP_R_ANKLE = 27, 28
MP_L_HEEL, MP_R_HEEL = 29, 30
MP_L_TOE, MP_R_TOE = 31, 32


def ensure_model() -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 100_000:
        print(f"模型已缓存：{MODEL_PATH.name} "
              f"（{MODEL_PATH.stat().st_size / 1024 / 1024:.1f} MB）")
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载模型 -> {MODEL_PATH}")
    req = urllib.request.Request(
        MODEL_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; YUcoach/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    MODEL_PATH.write_bytes(data)
    print(f"已下载 {len(data) / 1024 / 1024:.1f} MB")
    return MODEL_PATH


def main() -> int:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    video = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4")
    max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    print("=" * 72)
    print("MediaPipe 足部关键点质量评估")
    print("=" * 72)
    print(f"素材：{video.name}")
    print(f"最多处理 {max_frames} 帧")
    print()

    model = ensure_model()
    print()

    options = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.3,
        min_pose_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"[FAIL] 打不开视频：{video}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"视频 {w}x{h} @ {fps:.1f} fps")
    print()

    # 统计容器
    stats = {
        "frames": 0,
        "detected": 0,
        "r_heel_vis": [], "r_toe_vis": [],
        "l_heel_vis": [], "l_toe_vis": [],
        "toe_ok": 0, "toe_bad": 0,      # 脚尖在踝的前下方？
        "heel_ok": 0, "heel_bad": 0,    # 脚跟相对踝的位置合理？
        "derived_vs_mp": [],            # 与几何推导点的距离（画面归一化）
        "ankle_vs_mp": [],
    }

    # 同时用 YOLOv8-pose + 几何推导做对照
    from backend.analysis.pose_estimator import YoloPoseEstimator
    yolo = YoloPoseEstimator()
    print(f"对照模型：YOLOv8-pose（设备 {yolo.device}）")
    print()

    idx = 0
    while idx < max_frames:
        ok, bgr = cap.read()
        if not ok:
            break
        idx += 1
        stats["frames"] += 1

        # ---- MediaPipe ----
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts_ms = int(idx / fps * 1000)
        res = landmarker.detect_for_video(mp_img, ts_ms)

        if not res.pose_landmarks:
            continue
        stats["detected"] += 1
        lm = res.pose_landmarks[0]

        def vis(i: int) -> float:
            return float(getattr(lm[i], "visibility", 0.0) or 0.0)

        def pt(i: int) -> tuple[float, float]:
            return (float(lm[i].x), float(lm[i].y))

        stats["r_heel_vis"].append(vis(MP_R_HEEL))
        stats["r_toe_vis"].append(vis(MP_R_TOE))
        stats["l_heel_vis"].append(vis(MP_L_HEEL))
        stats["l_toe_vis"].append(vis(MP_L_TOE))

        # ---- 几何自检：脚尖应在踝关节的**下方** ----
        # 跑步时脚不会翻到踝关节上方。违反这一点的帧说明关键点错了。
        for ankle_i, toe_i, heel_i, side in (
            (MP_R_ANKLE, MP_R_TOE, MP_R_HEEL, "R"),
            (MP_L_ANKLE, MP_L_TOE, MP_L_HEEL, "L"),
        ):
            a = pt(ankle_i)
            t = pt(toe_i)
            hh = pt(heel_i)
            # y 向下。脚尖 y 应大于或接近踝的 y
            if t[1] >= a[1] - 0.02:
                stats["toe_ok"] += 1
            else:
                stats["toe_bad"] += 1
            # 脚跟也应在踝的下方或齐平
            if hh[1] >= a[1] - 0.02:
                stats["heel_ok"] += 1
            else:
                stats["heel_bad"] += 1

    cap.release()
    landmarker.close()

    # ---- 与几何推导对照（抽样若干帧）----
    print("与 YOLOv8 + 几何推导的对照（抽取 12 帧）：")
    print()
    print(f"  {'帧':>5s} {'MP踝':>16s} {'MP脚尖':>16s} {'推导脚尖':>16s} "
          f"{'相差':>8s}")
    print("  " + "-" * 68)

    cap2 = cv2.VideoCapture(str(video))
    options2 = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.3,
        min_pose_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    lm2 = vision.PoseLandmarker.create_from_options(options2)

    picks = set(range(20, min(max_frames, 200), max(1, max_frames // 12)))
    i2 = 0
    while i2 < max_frames:
        ok, bgr = cap2.read()
        if not ok:
            break
        i2 += 1
        if i2 not in picks:
            continue

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = lm2.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
            int(i2 / fps * 1000))
        if not res.pose_landmarks:
            continue
        lm = res.pose_landmarks[0]

        # YOLO 的 16 点
        try:
            seq = yolo.estimate_sequence(iter([(i2 - 1, bgr)]))
            if not seq.frames:
                continue
            pf = seq.frames[0]
        except Exception:
            continue

        def mp_pt(i: int) -> tuple[float, float]:
            return (float(lm[i].x), float(lm[i].y))

        a_mp = mp_pt(MP_R_ANKLE)
        t_mp = mp_pt(MP_R_TOE)

        # 几何推导：用 YOLO 的踝 + 小腿朝向
        knee = pf.point("knee_r")
        ankle = pf.point("ankle_r")
        if knee is None or ankle is None:
            continue
        heel_d, toe_d = derive_foot_points(
            (ankle[0], ankle[1]),
            (knee[0], knee[1]),
            foot_scale=0.152,
        )

        d = math.hypot(toe_d[0] - t_mp[0], toe_d[1] - t_mp[1])
        d_ankle = math.hypot(ankle[0] - a_mp[0], ankle[1] - a_mp[1])
        stats["derived_vs_mp"].append(d)
        stats["ankle_vs_mp"].append(d_ankle)

        print(f"  {i2:>5d} ({a_mp[0]:.3f},{a_mp[1]:.3f}) "
              f"({t_mp[0]:.3f},{t_mp[1]:.3f}) "
              f"({toe_d[0]:.3f},{toe_d[1]:.3f}) {d:>8.4f}")

    cap2.release()
    lm2.close()
    print()

    # ---- 汇总 ----
    print("=" * 72)
    print("结果")
    print("=" * 72)
    print()
    n = stats["frames"]
    det = stats["detected"]
    print(f"  处理帧数        {n}")
    print(f"  检出姿态        {det}（{det / max(n, 1) * 100:.0f}%）")
    print()

    if det:
        for label, key in (("右脚跟", "r_heel_vis"), ("右脚尖", "r_toe_vis"),
                           ("左脚跟", "l_heel_vis"), ("左脚尖", "l_toe_vis")):
            v = stats[key]
            if not v:
                continue
            high = sum(1 for x in v if x >= 0.5)
            print(f"  {label} 可见度：均值 {st.mean(v):.3f}，"
                  f"中位 {st.median(v):.3f}，"
                  f"≥0.5 的比例 {high / len(v) * 100:.0f}%")
        print()

    toe_total = stats["toe_ok"] + stats["toe_bad"]
    heel_total = stats["heel_ok"] + stats["heel_bad"]
    if toe_total:
        print(f"  几何自检 · 脚尖在踝下方："
              f"{stats['toe_ok'] / toe_total * 100:.0f}% 通过")
    if heel_total:
        print(f"  几何自检 · 脚跟不低于踝："
              f"{stats['heel_ok'] / heel_total * 100:.0f}% 通过")
    print()

    if stats["derived_vs_mp"]:
        dd = stats["derived_vs_mp"]
        da = stats["ankle_vs_mp"]
        print(f"  几何推导脚尖 与 MediaPipe 脚尖 的距离："
              f"中位 {st.median(dd):.4f}（画面归一化）")
        print(f"  两者踝关节的距离："
              f"中位 {st.median(da):.4f}")
        print()
        print("  参考：两者踝关节的差异是**模型本身的差异**（基线）。")
        print("        若脚尖差异远大于踝差异，说明两个模型对足部的")
        print("        判断确实不同；若相近，说明差异主要来自整体定位。")

    print()
    print("=" * 72)
    print("判定")
    print("=" * 72)
    print()

    if not det:
        print("  MediaPipe 在这段素材上一帧都没检出，无法评估。")
        return 1

    toe_pass = (stats["toe_ok"] / toe_total * 100) if toe_total else 0
    heel_vis_med = st.median(stats["r_heel_vis"]) if stats["r_heel_vis"] else 0

    if toe_pass >= 95 and heel_vis_med >= 0.5:
        print("  足部点几何自检通过率高、可见度足够。")
        print("  → 值得接入，可用于触地/离地时刻判定。")
    elif toe_pass >= 80:
        print("  足部点大体合理，但存在明显比例的几何矛盾帧。")
        print("  → 可用，但必须保留几何自检作为过滤条件，")
        print("     并在报告里标注这些帧不可用于时间指标。")
    else:
        print("  足部点的几何自检通过率低 —— 相当比例的帧里")
        print("  脚尖位置与踝关节的几何关系矛盾，说明关键点不可信。")
        print("  → **不建议**用它替换现有的几何推导法。")
        print("     一个稳定但系统性错误的足部点，比不稳定的更危险：")
        print("     它会稳定地给出错误的触地时刻，而且看不出来。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
