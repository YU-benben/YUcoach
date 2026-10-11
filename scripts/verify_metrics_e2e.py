"""
在合成的高帧率素材上跑完整链路，验证指标真的能算出来。

为什么需要这个：
    门禁里的冒烟测试用的是 60 fps 合成素材，且只验证"跑通 + 契约合法"。
    它不会检查指标是否真的产出了数值 —— 因为合成视频里的人形色块
    YOLO 未必能稳定检出。

    而 30 fps 的真实素材上，所有指标都被帧率门槛正确拦下了。
    结果是：**没有任何一次端到端验证能确认指标算得对**。

    这个脚本补上这一环：用几何上已知的姿态序列（不经过 YOLO）
    直接驱动指标计算，全部走 report 层，最后用契约校验产物。
    这样数值正确性由构造保证，链路完整性由契约校验保证。

用法：
    python scripts/verify_metrics_e2e.py
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.analysis.metrics import MetricContext, compute_all_metrics  # noqa: E402
from backend.analysis.metrics_base import METRIC_SPECS  # noqa: E402
from backend.analysis.phases import (  # noqa: E402
    GaitEvents,
    detect_gait_events,
    detect_phases,
)
from backend.analysis.pose_types import (  # noqa: E402
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)
from backend.analysis.reference_scale import ScaleEstimate  # noqa: E402


def make_person(
    t: float,
    fps: float,
    step_period: float = 0.22,
    speed_norm_per_s: float = 0.80,
) -> PoseFrame:
    """
    构造一个"在跑"的人，角度与位移都按已知公式生成。

    坐标是归一化的（0–1），y 向下。骨盆中心匀速右移并上下起伏 ——
    这两点保证步频、步长、重心起伏都有解析解可对照。

    ⚠️ 速度取 0.80 归一化宽度/秒，是为了让**步长落在真人范围**。
       最初取了 0.30，算出来的步长只有 0.13 m ——
       那样步长指标会触发"超出合理范围"的检查而拒绝出值。
       校验脚本的参数必须与真实场景同量级，否则测的是脚本自己。
       推导：人高约 0.40 归一化 → 1.78 m，即 1.0 ≈ 4.45 m。
             每步 0.22 秒 × 0.80 = 0.176 归一化 ≈ 0.78 m 步长，
             短跑加速段 0.8–1.2 m 属正常。
    """
    i = int(round(t * fps))

    cx = 0.05 + speed_norm_per_s * t          # 水平推进
    bob = 0.010 * math.sin(2 * math.pi * t / step_period)   # 垂直起伏

    pelvis = (cx, 0.50 + bob)

    # 大腿与小腿的角度随步态周期变化（幅度已知）
    thigh_swing = math.radians(38) * math.sin(2 * math.pi * t / step_period)
    knee_flex = math.radians(60) + math.radians(40) * math.sin(
        2 * math.pi * t / step_period + math.pi / 2)

    L_thigh = 0.165
    L_shank = 0.165

    # 大腿方向（相对竖直向下，向右侧为正）
    hip = (cx, 0.50 + bob)
    thigh_dir = thigh_swing
    knee = (hip[0] + L_thigh * math.sin(thigh_dir),
            hip[1] + L_thigh * math.cos(thigh_dir))

    # 小腿相对大腿弯 knee_flex 度
    shank_dir = thigh_dir - knee_flex
    ankle = (knee[0] + L_shank * math.sin(shank_dir),
             knee[1] + L_shank * math.cos(shank_dir))

    # 足部：由小腿方向垂直推出（与 keypoint_map 的假设一致）
    foot_dir = shank_dir + math.pi / 2
    L_foot = 0.055
    heel = (ankle[0] - L_foot * 0.25 * math.sin(foot_dir),
            ankle[1] - L_foot * 0.25 * math.cos(foot_dir))
    toe = (ankle[0] + L_foot * 0.75 * math.sin(foot_dir),
           ankle[1] + L_foot * 0.75 * math.cos(foot_dir))

    neck = (cx + 0.005, 0.20 + bob)
    shoulder = neck
    head = (neck[0], neck[1] - 0.10)

    kp = np.zeros((16, 3), dtype=np.float64)

    def put(name: str, xy: tuple[float, float]) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [xy[0], xy[1], Q_CLEAR]

    put("head", head)
    put("neck", neck)
    put("shoulder_r", shoulder)
    put("hip_r", hip)
    put("knee_r", knee)
    put("ankle_r", ankle)
    put("heel_r", heel)
    put("toe_r", toe)

    # 左侧：同一套几何，相位差半个周期（左右腿交替）
    t2 = t + step_period
    ts = math.radians(38) * math.sin(2 * math.pi * t2 / step_period)
    kf = math.radians(60) + math.radians(40) * math.sin(
        2 * math.pi * t2 / step_period + math.pi / 2)
    knee2 = (hip[0] + L_thigh * math.sin(ts),
             hip[1] + L_thigh * math.cos(ts))
    shank2 = ts - kf
    ankle2 = (knee2[0] + L_shank * math.sin(shank2),
              knee2[1] + L_shank * math.cos(shank2))
    foot2 = shank2 + math.pi / 2
    heel2 = (ankle2[0] - L_foot * 0.25 * math.sin(foot2),
             ankle2[1] - L_foot * 0.25 * math.cos(foot2))
    toe2 = (ankle2[0] + L_foot * 0.75 * math.sin(foot2),
            ankle2[1] + L_foot * 0.75 * math.cos(foot2))

    put("shoulder_l", (shoulder[0] - 0.02, shoulder[1]))
    put("hip_l", (hip[0] - 0.02, hip[1]))
    put("knee_l", knee2)
    put("ankle_l", ankle2)
    put("heel_l", heel2)
    put("toe_l", toe2)

    put("pelvis_center", ((hip[0] + hip[0] - 0.02) / 2, hip[1]))
    put("shoulder_center", ((shoulder[0] + shoulder[0] - 0.02) / 2,
                            shoulder[1]))

    # 裁剪到画面内，避免越界值污染角度
    kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
    kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)

    return PoseFrame(frame_index=i, keypoints=kp, person_conf=0.95,
                     has_derived_keypoints=False)


def build_sequence(fps: float = 240.0, duration: float = 2.0) -> PoseSequence:
    seq = PoseSequence(estimator_name="synthetic-geo",
                       estimator_version="1.0.0")
    n = int(fps * duration)
    for i in range(n):
        seq.frames.append(make_person(i / fps, fps))
    return seq


def main() -> int:
    print("=" * 68)
    print("指标端到端验证（合成高帧率素材）")
    print("=" * 68)
    print()

    fps = 240.0
    seq = build_sequence(fps=fps, duration=2.0)
    print(f"合成序列：{len(seq)} 帧 @ {fps:.0f} fps "
          f"（{len(seq) / fps:.1f} 秒）")

    # 尺度：由人高反推。
    # 人的头顶在 0.10、脚踝在约 0.90，即身高约 0.40 归一化宽度；
    # 取身高 1.78 m，得 1.0 归一化宽度 ≈ 4.45 m，
    # 即 pixels_per_meter（归一化单位下）= 1 / 4.45 ≈ 0.225。
    person_height_norm = 0.40
    person_height_m = 1.78
    ppm = person_height_norm / person_height_m   # ≈ 0.225

    scale = ScaleEstimate(
        method="calibration_rod",
        valid_per_frame=True,
        median_pixels_per_meter=ppm,
        reference_length_m=person_height_m,
        coverage_pct=100.0,
    )

    events = detect_gait_events(seq, fps)
    phases, _ = detect_phases(seq, fps)

    ctx = MetricContext(
        seq=seq, fps=fps, view="side", scale=scale,
        events=events, phases=phases,
        athlete_height_cm=178.0,
        camera_motion_level="fixed",
    )

    print(f"检出支撑中期 {len(events.midstances)} 次、"
          f"触地 {len(events.touchdowns)} 次")
    print(f"划分相位 {len(phases)} 段")
    print()

    results = compute_all_metrics(ctx)

    ok, skip = [], []
    for r in results:
        spec = METRIC_SPECS[r.metric_id]
        if r.insufficient is not None:
            skip.append((spec.name_zh, r.insufficient["actual"][:40]))
        else:
            ok.append((spec.name_zh, r.value, spec.unit))

    print(f"算出数值的指标（{len(ok)} 项）：")
    for name, val, unit in ok:
        print(f"  [OK] {name:16s} {val} {unit}")
    print()

    print(f"未算出数值的指标（{len(skip)} 项）：")
    for name, why in skip:
        print(f"  [--] {name:16s} {why}")
    print()

    # ---- 关键断言：这 7 个指标必须在这个素材上算出数值 ----
    # 它们是侧面 + 60fps 门槛的指标，合成素材已满足全部前提。
    must_compute = [
        "trunk_lean", "step_frequency", "thigh_swing_range",
        "shank_angle_touchdown", "knee_angle_midstance", "hip_angle_toeoff",
        "step_length", "com_height_oscillation",
    ]
    by_id = {r.metric_id: r for r in results}
    failed = []
    for mid in must_compute:
        r = by_id.get(mid)
        if r is None or r.insufficient is not None:
            why = r.insufficient["actual"] if r and r.insufficient else "缺失"
            failed.append(f"{mid}: {why}")

    if failed:
        print("[FAIL] 以下指标在满足全部前提的合成素材上仍未算出数值：")
        for f in failed:
            print(f"       {f}")
        return 1

    print(f"[OK] {len(must_compute)} 个侧面指标全部算出数值")
    print()

    # ---- 数值合理性 ----
    problems = []
    sf = by_id["step_frequency"].value
    expected_sf = 60.0 / 0.22      # 构造的步态周期 0.22 秒
    if abs(sf - expected_sf) / expected_sf > 0.20:
        problems.append(
            f"步频 {sf:.0f} 与构造值 {expected_sf:.0f} 相差超过 20%"
        )

    tlr = by_id["trunk_lean"].value
    # 构造时躯干完全竖直（neck 与 pelvis 的 x 只差 0.005-0.01）
    if tlr > 10:
        problems.append(f"躯干前倾角 {tlr}° —— 构造时躯干近乎竖直，不该这么大")

    sl = by_id["step_length"].value
    if not (0.5 <= sl <= 3.5):
        problems.append(f"步长 {sl} m 超出合理范围")

    if problems:
        print("[FAIL] 数值合理性检查未通过：")
        for p in problems:
            print(f"       {p}")
        return 1

    print(f"[OK] 数值合理性检查通过"
          f"（步频 {sf:.0f} vs 构造 {expected_sf:.0f} 步/分；"
          f"躯干前倾 {tlr:.1f}°）")
    print()

    # ---- 正面视角：额状面指标 ----
    return verify_frontal(fps)


def make_frontal_person(i: int, *, tilt_deg: float = 0.0,
                        lean_deg: float = 0.0,
                        stance_w: float = 0.10) -> PoseFrame:
    """
    构造正面视角的人，骨盆倾斜与躯干侧倾都按已知值生成。

    正面与侧面的构造差异：左右髋在**同一高度**（骨盆水平），
    且左右明显分开 —— 这样 pelvis_tilt 接近 0，便于用已知值验证。
    """
    kp = np.zeros((16, 3), dtype=np.float64)
    cx = 0.50 + i * 0.0008
    pelvis_y = 0.50
    shoulder_y = 0.22
    half_w = 0.045
    dy = math.tan(math.radians(tilt_deg)) * half_w

    hip_r = (cx + half_w, pelvis_y - dy)
    hip_l = (cx - half_w, pelvis_y + dy)

    lean_dx = math.tan(math.radians(lean_deg)) * 0.28
    scx = cx + lean_dx
    shoulder_r = (scx + 0.075, shoulder_y)
    shoulder_l = (scx - 0.075, shoulder_y)

    knee_r = (hip_r[0] + stance_w * 0.3, pelvis_y + 0.20)
    knee_l = (hip_l[0] - stance_w * 0.3, pelvis_y + 0.20)
    ankle_r = (hip_r[0] + stance_w * 0.5, pelvis_y + 0.38)
    ankle_l = (hip_l[0] - stance_w * 0.5, pelvis_y + 0.38)

    def put(name: str, xy: tuple[float, float]) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [xy[0], xy[1], Q_CLEAR]

    put("head", (scx, shoulder_y - 0.10))
    put("neck", (scx, shoulder_y))
    put("shoulder_r", shoulder_r)
    put("shoulder_l", shoulder_l)
    put("hip_r", hip_r)
    put("hip_l", hip_l)
    put("knee_r", knee_r)
    put("knee_l", knee_l)
    put("ankle_r", ankle_r)
    put("ankle_l", ankle_l)
    put("heel_r", (ankle_r[0] - 0.005, ankle_r[1] + 0.01))
    put("heel_l", (ankle_l[0] + 0.005, ankle_l[1] + 0.01))
    put("toe_r", (ankle_r[0] + 0.02, ankle_r[1] + 0.01))
    put("toe_l", (ankle_l[0] - 0.02, ankle_l[1] + 0.01))
    put("pelvis_center", ((hip_r[0] + hip_l[0]) / 2,
                          (hip_r[1] + hip_l[1]) / 2))
    put("shoulder_center", ((shoulder_r[0] + shoulder_l[0]) / 2,
                            (shoulder_r[1] + shoulder_l[1]) / 2))

    kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
    kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)

    return PoseFrame(frame_index=i, keypoints=kp, person_conf=0.95)


def verify_frontal(fps: float) -> int:
    """验证额状面指标在正面视角下能算出数值，且数值与构造一致。"""
    print("=" * 68)
    print("额状面指标验证（正面视角合成素材）")
    print("=" * 68)
    print()

    n = int(fps * 2.0)
    tilt_deg = 4.0
    lean_deg = 3.0

    seq = PoseSequence(estimator_name="synthetic-frontal",
                       estimator_version="1.0.0")
    for i in range(n):
        # 骨盆倾斜与躯干侧倾交替，模拟左右支撑期的交替
        phase = math.sin(2 * math.pi * i / (fps * 0.22))
        seq.frames.append(make_frontal_person(
            i,
            tilt_deg=tilt_deg * phase,
            lean_deg=lean_deg * phase,
        ))

    print(f"合成序列：{n} 帧 @ {fps:.0f} fps，"
          f"骨盆倾斜 ±{tilt_deg:.0f}°、躯干侧倾 ±{lean_deg:.0f}°")

    events = detect_gait_events(seq, fps)
    phases, _ = detect_phases(seq, fps)

    # 合成数据是"原地交替"的姿态，不是真的在跑 ——
    # 足部事件检测依赖踝关节高度的变化规律，在这里检不出来。
    #
    # 所以**手动构造事件**。这是刻意的：
    #   本脚本要验证的是**指标计算逻辑**（给定事件帧，角度算得对不对），
    #   不是事件检测本身（那由 test_video_io 与 test_metrics 覆盖）。
    #   用合成数据去验证事件检测会变成"用不可靠的东西验证不可靠的东西"。
    step_frames = int(round(fps * 0.22))
    events.touchdowns = list(range(10, n - 10, step_frames))
    events.midstances = [t + step_frames // 2 for t in events.touchdowns
                         if t + step_frames // 2 < n]
    events.toe_offs = [t + step_frames // 3 for t in events.touchdowns
                       if t + step_frames // 3 < n]

    print(f"手动构造事件：着地 {len(events.touchdowns)} 次、"
          f"支撑中期 {len(events.midstances)} 次")

    ctx = MetricContext(
        seq=seq, fps=fps, view="front",
        scale=ScaleEstimate(method="none", valid_per_frame=False),
        events=events, phases=phases,
        athlete_height_cm=178.0,
        camera_motion_level="fixed",
    )

    results = compute_all_metrics(ctx)
    by_id = {r.metric_id: r for r in results}

    frontal = ["pelvis_tilt", "pelvis_rotation", "knee_valgus_touchdown",
               "stance_width_relative", "trunk_lateral_lean",
               "pelvis_drop_midstance"]

    ok, bad = [], []
    for mid in frontal:
        r = by_id[mid]
        if r.insufficient is None:
            ok.append((mid, r.value))
        else:
            bad.append((mid, r.insufficient["reason"],
                        r.insufficient["actual"][:36]))

    print(f"算出数值（{len(ok)} 项）：")
    for mid, v in ok:
        print(f"  [OK] {mid:24s} {v}")
    print()

    if bad:
        print(f"未算出数值（{len(bad)} 项）：")
        for mid, reason, why in bad:
            print(f"  [--] {mid:24s} {reason}: {why}")
        print()

    # ---- 关键断言 ----
    # 这四项不依赖足部事件、也不依赖参考尺度，在任何正面素材上都该能算。
    must = ["pelvis_tilt", "trunk_lateral_lean", "pelvis_rotation",
            "stance_width_relative"]
    failed = [m for m in must
              if by_id[m].insufficient is not None]
    if failed:
        print(f"[FAIL] 以下指标在正面合成素材上仍未算出数值：{failed}")
        for m in failed:
            ins = by_id[m].insufficient
            print(f"       {m}: {ins['reason']} — {ins['actual']}")
        return 1
    print(f"[OK] {len(must)} 个基础额状面指标算出数值")

    # ---- 数值合理性 ----
    #
    # ⚠️ 断言要选对统计量。
    #    构造的是**对称振荡**（±4°），所以均值本来就该接近 0 ——
    #    用均值去判断"振荡是否被保留"是错的，它必然接近 0。
    #    真正能反映振荡幅度的是**标准差**：
    #    正弦振幅 A 的标准差为 A/√2 ≈ 0.707A。
    #    这一点最初写错过：看到均值 0.01 以为振荡丢了，
    #    实际 aggregate 里的 sd=2.78、min/max=±3.94，振荡完整保留。
    problems = []

    agg_pt = by_id["pelvis_tilt"].aggregate or {}
    sd_pt = agg_pt.get("sd")
    expected_sd = tilt_deg / math.sqrt(2)
    if sd_pt is None:
        problems.append("骨盆侧倾缺少 sd，无法判断振荡幅度")
    elif abs(sd_pt - expected_sd) > 0.8:
        problems.append(
            f"骨盆侧倾 sd={sd_pt:.2f}，"
            f"构造振幅 ±{tilt_deg}° 对应 sd≈{expected_sd:.2f}"
        )

    sd_tl = (by_id["trunk_lateral_lean"].aggregate or {}).get("sd")
    expected_sd_tl = lean_deg / math.sqrt(2)
    if sd_tl is None:
        problems.append("躯干侧倾缺少 sd")
    elif abs(sd_tl - expected_sd_tl) > 0.8:
        problems.append(
            f"躯干侧倾 sd={sd_tl:.2f}，"
            f"构造振幅 ±{lean_deg}° 对应 sd≈{expected_sd_tl:.2f}"
        )

    # 均值：对称振荡下应接近 0（这是另一条独立的检查，不是重复）
    pt = by_id["pelvis_tilt"].value
    if abs(pt) > 1.5:
        problems.append(
            f"对称振荡下骨盆侧倾均值应接近 0，实得 {pt:.2f}°"
        )

    if problems:
        print("[FAIL] 数值合理性检查未通过：")
        for p in problems:
            print(f"       {p}")
        return 1

    print(f"[OK] 数值合理性检查通过 —— 骨盆侧倾 sd={sd_pt:.2f}"
          f"（构造振幅 ±{tilt_deg}° 对应理论 sd≈{expected_sd:.2f}），"
          f"躯干侧倾 sd={sd_tl:.2f}（理论 ≈{expected_sd_tl:.2f}）")
    print(f"     均值分别为 {pt:.2f}° / "
          f"{by_id['trunk_lateral_lean'].value:.2f}° —— "
          f"对称振荡下接近 0 属预期")
    print()

    # ---- 侧面视角下额状面必须全部被拦 ----
    side_seq = build_sequence(fps=fps, duration=1.0)
    side_ctx = MetricContext(
        seq=side_seq, fps=fps, view="side",
        scale=ScaleEstimate(method="none", valid_per_frame=False),
        events=detect_gait_events(side_seq, fps),
        phases=[], athlete_height_cm=178.0,
        camera_motion_level="fixed",
    )
    leaked = []
    for mid in frontal:
        r = compute_all_metrics(side_ctx)
        entry = next(x for x in r if x.metric_id == mid)
        if entry.insufficient is None:
            leaked.append(mid)

    if leaked:
        print(f"[FAIL] 以下额状面指标在侧面视角下未被拦下：{leaked}")
        return 1
    print(f"[OK] {len(frontal)} 个额状面指标在侧面视角下全部被正确拦下")
    return 0


if __name__ == "__main__":
    sys.exit(main())
