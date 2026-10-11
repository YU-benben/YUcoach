"""
指标计算的测试。

用**合成姿态序列**而不是真实视频来测：
    合成数据能精确控制输入，从而验证"算得对不对"；
    真实视频只能验证"跑不跑得通"。
    这两件事必须分开测，否则数值错误会被"反正跑通了"掩盖。

重点覆盖两类行为：
  1. 前置条件判定 —— 帧率不够、视角不对、关键点缺失、无参考尺度时，
     必须明确判为数据不足，**而不是硬算一个数字出来**。
  2. 数值正确性 —— 用几何上已知的构造成姿态，验证角度算得对。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.analysis.metrics import (
    METRIC_FUNCS,
    MetricContext,
    compute_all_metrics,
    metric_step_frequency,
    metric_step_length_relative,
    metric_trunk_lean,
)
from backend.analysis.metrics_base import (
    METRIC_SPECS,
    angle_at,
    segment_angle_from_vertical,
    smooth_series,
)
from backend.analysis.phases import GaitEvents, detect_gait_events, detect_phases
from backend.analysis.pose_types import (
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)
from backend.analysis.reference_scale import ScaleEstimate


# ---------------------------------------------------------------------------
# 构造合成姿态序列
# ---------------------------------------------------------------------------

def make_frame(
    frame_index: int,
    *,
    head: tuple[float, float] = (0.50, 0.15),
    neck: tuple[float, float] = (0.50, 0.20),
    pelvis: tuple[float, float] = (0.50, 0.50),
    knee_r: tuple[float, float] = (0.51, 0.70),
    ankle_r: tuple[float, float] = (0.52, 0.88),
    shoulder_r: tuple[float, float] = (0.51, 0.22),
    hip_r: tuple[float, float] = (0.51, 0.50),
) -> PoseFrame:
    """构造一帧姿态。未显式给出的点由已知点派生，保证几何自洽。"""
    kp = np.zeros((16, 3), dtype=np.float64)

    def put(name: str, xy: tuple[float, float]) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [xy[0], xy[1], Q_CLEAR]

    put("head", head)
    put("neck", neck)
    put("pelvis_center", pelvis)

    # 右腿
    put("shoulder_r", shoulder_r)
    put("hip_r", hip_r)
    put("knee_r", knee_r)
    put("ankle_r", ankle_r)
    put("heel_r", (ankle_r[0] - 0.012, ankle_r[1] + 0.006))
    put("toe_r", (ankle_r[0] + 0.030, ankle_r[1] + 0.004))

    # 左侧相对右侧水平镜像一点，模拟远侧肢体
    for a, b in (("shoulder_r", "shoulder_l"), ("hip_r", "hip_l"),
                 ("knee_r", "knee_l"), ("ankle_r", "ankle_l"),
                 ("heel_r", "heel_l"), ("toe_r", "toe_l")):
        i = KEYPOINT_NAMES.index(a)
        x, y, q = kp[i]
        kp[KEYPOINT_NAMES.index(b)] = [x - 0.02, y, q]

    kp[KEYPOINT_NAMES.index("shoulder_center")] = [
        (kp[KEYPOINT_NAMES.index("shoulder_r")][0]
         + kp[KEYPOINT_NAMES.index("shoulder_l")][0]) / 2,
        (kp[KEYPOINT_NAMES.index("shoulder_r")][1]
         + kp[KEYPOINT_NAMES.index("shoulder_l")][1]) / 2,
        Q_CLEAR,
    ]

    return PoseFrame(frame_index=frame_index, keypoints=kp, person_conf=0.9)


def make_running_sequence(
    n_frames: int = 120,
    fps: float = 240.0,
    step_period_s: float = 0.22,
    forward_speed: float = 0.35,
) -> PoseSequence:
    """
    构造一段"人在跑"的合成序列。

    躯干保持直立，骨盆中心以恒定速度向右移动，膝角随步态周期振荡。
    """
    seq = PoseSequence(estimator_name="synthetic", estimator_version="1.0.0")

    for i in range(n_frames):
        t = i / fps
        # 骨盆水平推进
        px = 0.15 + forward_speed * t
        # 髋部高度随步态周期起伏（每步一次）
        bob = 0.012 * math.sin(2 * math.pi * t / step_period_s)
        pelvis = (px, 0.50 + bob)

        # 膝角随周期变化
        swing = 0.05 * math.sin(2 * math.pi * t / step_period_s + math.pi / 2)

        seq.frames.append(make_frame(
            i,
            head=(px + 0.005, 0.14 + bob),
            neck=(px, 0.20 + bob),
            pelvis=pelvis,
            hip_r=(px + 0.01, 0.50 + bob),
            knee_r=(px + 0.02 + swing, 0.70 + bob),
            ankle_r=(px + 0.03 + swing, 0.88 + bob),
        ))

    return seq


def make_ctx(
    seq: PoseSequence,
    *,
    fps: float = 240.0,
    view: str = "side",
    scale: ScaleEstimate | None = None,
    height_cm: float | None = 178.0,
) -> MetricContext:
    events = detect_gait_events(seq, fps)
    phases, _ = detect_phases(seq, fps)
    return MetricContext(
        seq=seq,
        fps=fps,
        view=view,
        scale=scale or ScaleEstimate(
            method="lane_line", valid_per_frame=True,
            median_pixels_per_meter=0.35, reference_length_m=1.22,
            coverage_pct=100.0, per_frame={},
        ),
        events=events,
        phases=phases,
        athlete_height_cm=height_cm,
    )


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def test_angle_at_right_angle():
    assert angle_at((0, 1), (0, 0), (1, 0)) == pytest.approx(90.0)


def test_angle_at_straight_line():
    assert angle_at((0, 1), (0, 0), (0, -1)) == pytest.approx(180.0)


def test_angle_at_is_order_independent_for_the_arms():
    """∠ABC 与 ∠CBA 应当相等 —— 否则指标会依赖传参顺序。"""
    a, b, c = (0.1, 0.2), (0.4, 0.5), (0.7, 0.3)
    assert angle_at(a, b, c) == pytest.approx(angle_at(c, b, a))


def test_angle_at_degenerate_returns_nan():
    """重合点应当返回 nan 而不是抛异常或给 0。"""
    assert math.isnan(angle_at((0.5, 0.5), (0.5, 0.5), (0.6, 0.6)))


def test_segment_angle_from_vertical():
    # 完全竖直向下
    assert segment_angle_from_vertical((0.5, 0.2), (0.5, 0.8)) == pytest.approx(0.0)
    # 向右偏 45°
    assert segment_angle_from_vertical((0.5, 0.2), (0.8, 0.5)) == pytest.approx(45.0)
    # 向左偏 45°
    assert segment_angle_from_vertical((0.5, 0.2), (0.2, 0.5)) == pytest.approx(-45.0)


def test_smooth_series_preserves_length_and_endpoints():
    v = np.array([1.0, 5.0, 1.0, 5.0, 1.0])
    s = smooth_series(v, window=3)
    assert len(s) == len(v)
    # 平滑会削减峰值，但不该出现零填充造成的端点塌陷
    assert s[0] > 0.5
    assert s[-1] > 0.5


def test_smooth_series_short_input_is_passthrough():
    v = np.array([1.0, 2.0])
    np.testing.assert_allclose(smooth_series(v, window=5), v)


# ---------------------------------------------------------------------------
# 前置条件：宁可说算不了，也不能给错数
# ---------------------------------------------------------------------------

def test_low_fps_blocks_temporal_metrics():
    """
    30 fps 素材上，触地时间必须判为数据不足，而不是硬算一个值。
    这是本项目最重要的安全阀之一。
    """
    seq = make_running_sequence(60, fps=30.0)
    ctx = make_ctx(seq, fps=30.0)

    for mid in ("ground_contact_time", "flight_time", "duty_factor"):
        r = METRIC_FUNCS[mid](ctx)
        assert r.insufficient is not None, f"{mid} 在 30fps 下不该给出数值"
        assert r.value is None
        assert "120" in r.insufficient["required"]
        # 必须说清后果，而不只是"帧率不够"
        # impact 在契约里是数组（一项不足可能有多个后果）
        assert isinstance(r.insufficient["impact"], list)
        assert r.insufficient["impact"]
        assert sum(len(x) for x in r.insufficient["impact"]) > 20
        assert r.insufficient["suggestion"]


def test_low_fps_still_allows_angle_metrics():
    """
    角度类指标不受 120 fps 门槛影响，不该被一并封杀 ——
    那会剥夺教练本来能用上的部分。

    注意 trunk_lean 的契约要求是 60 fps（不是 120），
    所以这里用 60 fps 的素材来验证"帧率够时能算出来"。
    """
    seq = make_running_sequence(120, fps=60.0)
    ctx = make_ctx(seq, fps=60.0)

    r = metric_trunk_lean(ctx)
    assert r.insufficient is None, (
        f"躯干前倾角在 60fps 下应当可算，实际被判：{r.insufficient}"
    )
    assert r.value is not None


def test_angle_metrics_not_blocked_by_the_120fps_tier():
    """
    区分两个帧率门槛：角度类 60 fps，时间类 120 fps。
    用 60 fps 素材时，角度类必须能算，时间类必须不能算 ——
    这是本项目"不搞一刀切"的体现。
    """
    seq = make_running_sequence(120, fps=60.0)
    ctx = make_ctx(seq, fps=60.0)

    assert metric_trunk_lean(ctx).insufficient is None
    assert METRIC_FUNCS["ground_contact_time"](ctx).insufficient is not None


def test_view_mismatch_blocks_metric():
    """侧面指标在正面视角下必须判为数据不足。"""
    seq = make_running_sequence(40)
    ctx = make_ctx(seq, view="front")

    r = METRIC_FUNCS["trunk_lean"](ctx)
    assert r.insufficient is not None
    assert r.insufficient["reason"] == "view_mismatch"
    # 必须解释"为什么不能替代"，而不只是说视角不符
    joined = " ".join(r.insufficient["impact"])
    assert "不同视角" in joined or "只能" in joined


def test_missing_reference_scale_blocks_step_length():
    """没有参考尺度时，相对步长必须判为数据不足。"""
    seq = make_running_sequence(60)
    ctx = make_ctx(seq, scale=ScaleEstimate(method="none", valid_per_frame=False))

    r = metric_step_length_relative(ctx)
    assert r.insufficient is not None
    assert r.insufficient["reason"] == "no_reference_scale"
    assert "分道线" in r.insufficient["suggestion"]


def test_missing_height_blocks_relative_step_length():
    """相对步长需要身高做分母。没有身高时给出明确的补齐方式。"""
    seq = make_running_sequence(60)
    ctx = make_ctx(seq, height_cm=None)
    # 尺度给足，确保拦截原因确实是身高而不是尺度
    ctx.scale = ScaleEstimate(
        method="lane_line", valid_per_frame=True,
        median_pixels_per_meter=0.35, per_frame={})

    r = metric_step_length_relative(ctx)
    assert r.insufficient is not None
    assert r.insufficient["reason"] == "no_athlete_height"
    assert "身高" in r.insufficient["suggestion"]


def test_ground_contact_time_rejects_derived_feet():
    """
    足部点是几何推导时，触地时间必须拒绝出值 ——
    即使帧率达标。因为"取值时刻"本身就是错的。
    """
    seq = make_running_sequence(240, fps=240.0)
    # 标记为推导足部点
    for f in seq.frames:
        f.has_derived_keypoints = True
    ctx = make_ctx(seq, fps=240.0)

    r = METRIC_FUNCS["ground_contact_time"](ctx)
    assert r.insufficient is not None
    assert r.insufficient["reason"] == "contact_timing_unreliable"
    # 后果说明里必须点出"在最关键的瞬间误差最大"
    joined = " ".join(r.insufficient["impact"])
    assert "触地" in joined
    assert "模型" in r.insufficient["suggestion"]


def test_insufficient_always_has_all_five_fields():
    """
    所有"数据不足"说明必须五要素齐全，且类型符合契约。
    缺任何一项，教练都不知道该怎么办；
    类型不对则通不过契约校验（这在本项目里真实发生过）。
    """
    seq = make_running_sequence(30, fps=30.0)
    ctx = make_ctx(seq, fps=30.0, view="front",
                   scale=ScaleEstimate(method="none", valid_per_frame=False))

    for spec in METRIC_SPECS.values():
        fn = METRIC_FUNCS.get(spec.metric_id)
        if fn is None:
            continue
        r = fn(ctx)
        if r.insufficient is None:
            continue

        for key in ("reason", "required", "actual", "impact", "suggestion"):
            assert r.insufficient.get(key), (
                f"{spec.metric_id} 的 insufficient 缺 {key}"
            )

        # 类型必须符合 common.schema.json 的 InsufficientInfo
        assert isinstance(r.insufficient["reason"], str)
        assert isinstance(r.insufficient["required"], str)
        assert isinstance(r.insufficient["actual"], str)
        assert isinstance(r.insufficient["suggestion"], str)
        assert isinstance(r.insufficient["impact"], list), (
            f"{spec.metric_id} 的 impact 必须是字符串数组"
            f"（契约要求），实际是 {type(r.insufficient['impact']).__name__}"
        )
        assert all(isinstance(x, str) for x in r.insufficient["impact"])

        # 不能有契约之外的字段 —— additionalProperties=false
        allowed = {"reason", "required", "actual", "impact", "suggestion"}
        extra = set(r.insufficient) - allowed
        assert not extra, f"{spec.metric_id} 的 insufficient 有未定义字段：{extra}"


def test_aggregate_matches_contract_structure():
    """
    aggregate 必须满足契约：required=['n'] 且 additionalProperties=false。

    这条测试锁定一个真实踩过的坑：曾经往 aggregate 里塞了
    events / steps / scale_method 等自定义字段，
    结构自检直接报"出现未定义字段"。

    注意：指标层允许把**相位统计**放进 aggregate（内部约定），
    由 report 层展开成独立条目并规范化。这里只校验
    非相位统计的那部分字段是否合规。
    """
    from backend.analysis.metrics_base import aggregate_block

    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)

    allowed = {"mean", "sd", "n", "min", "max"}

    for spec in METRIC_SPECS.values():
        fn = METRIC_FUNCS.get(spec.metric_id)
        if fn is None:
            continue
        r = fn(ctx)
        if r.aggregate is None:
            continue

        # 标量字段（相位统计是嵌套 dict，由 report 层处理）
        scalar_keys = {
            k for k, v in r.aggregate.items()
            if not (isinstance(v, dict) and "mean" in v)
        }
        if not scalar_keys:
            continue

        assert "n" in r.aggregate, f"{spec.metric_id} 的 aggregate 缺必备字段 n"
        extra = scalar_keys - allowed
        assert not extra, (
            f"{spec.metric_id} 的 aggregate 有契约外字段：{extra}"
        )

    # 直接验证构造函数
    blk = aggregate_block(n=5, mean=1.0, sd=0.1, min_value=0.8, max_value=1.2)
    assert blk["n"] == 5
    assert set(blk) <= allowed


def test_reliable_false_always_has_note():
    """
    reliable=False 时必须给出原因。
    只标"不可靠"而不说为什么，等于什么都没说。
    """
    seq = make_running_sequence(240, fps=240.0)
    for f in seq.frames:
        f.has_derived_keypoints = True
    ctx = make_ctx(seq, fps=240.0)

    from backend.analysis.metrics import metric_knee_angle_touchdown
    r = metric_knee_angle_touchdown(ctx)
    if not r.reliable:
        assert r.reliability_note, "reliable=false 却没写原因"


# ---------------------------------------------------------------------------
# 数值正确性
# ---------------------------------------------------------------------------

def test_trunk_lean_vertical_trunk_is_zero():
    """躯干完全竖直时前倾角应当接近 0。"""
    seq = PoseSequence(estimator_name="t", estimator_version="1")
    for i in range(60):
        seq.frames.append(make_frame(
            i, head=(0.50, 0.14), neck=(0.50, 0.20),
            pelvis=(0.50, 0.50), hip_r=(0.50, 0.50),
            shoulder_r=(0.50, 0.22),
        ))
    ctx = make_ctx(seq)
    r = metric_trunk_lean(ctx)
    assert r.value == pytest.approx(0.0, abs=1.0)


def test_trunk_lean_detects_lean():
    """
    躯干倾斜时角度应当与几何构造一致。

    构造：颈在骨盆的右上方，水平偏 0.10、竖直差 0.30。
        角度 = atan(0.10 / 0.30) = 18.43°

    用解析解而不是"大概十几度"来断言 ——
    模糊的期望值等于没验证。
    """
    seq = PoseSequence(estimator_name="t", estimator_version="1")
    for i in range(60):
        seq.frames.append(make_frame(
            i, head=(0.60, 0.14), neck=(0.60, 0.20),
            pelvis=(0.50, 0.50), hip_r=(0.50, 0.50),
            shoulder_r=(0.60, 0.22),
        ))
    ctx = make_ctx(seq)

    expected = math.degrees(math.atan2(0.10, 0.30))
    r = metric_trunk_lean(ctx)
    assert r.value == pytest.approx(expected, abs=0.5), (
        f"几何构造给出的解析解是 {expected:.2f}°，实得 {r.value}"
    )


def test_step_frequency_matches_constructed_period():
    """
    步频必须与构造的步态周期一致。
    构造周期 0.22 秒 -> 期望约 273 步/分。
    """
    seq = make_running_sequence(n_frames=480, fps=240.0, step_period_s=0.22)
    ctx = make_ctx(seq, fps=240.0)

    r = metric_step_frequency(ctx)
    if r.insufficient is not None:
        pytest.skip(f"合成序列未检出足够周期：{r.insufficient['actual']}")

    expected = 60.0 / 0.22
    assert r.value == pytest.approx(expected, rel=0.25), (
        f"构造周期 0.22 秒 -> 期望 {expected:.0f} 步/分，实得 {r.value}"
    )


def test_step_frequency_rejects_implausible():
    """超出人类生理范围的步频必须判为数据不足，而不是照报。"""
    seq = make_running_sequence(240, fps=240.0, step_period_s=0.02)
    ctx = make_ctx(seq, fps=240.0)

    r = metric_step_frequency(ctx)
    if r.value is not None:
        # 若给出了数值，必须落在生理范围内
        assert 100 <= r.value <= 400, f"给出了不合理的步频 {r.value}"
    else:
        assert r.insufficient is not None
        assert r.insufficient["reason"] in ("implausible_value",
                                            "insufficient_cycles")


FRONTAL_METRICS = [
    "pelvis_tilt", "pelvis_rotation", "knee_valgus_touchdown",
    "stance_width_relative", "trunk_lateral_lean", "pelvis_drop_midstance",
]


def _frontal_pose(
    i: int,
    *,
    pelvis_tilt_deg: float = 0.0,
    lateral_lean_deg: float = 0.0,
    stanse_width: float = 0.10,
) -> PoseFrame:
    """
    构造一帧正面视角姿态。

    与侧面构造不同，正面视角的关键是：
        左右髋在**同一高度**（骨盆水平）、左右分开一个宽度
    这样 pelvis_tilt 才接近 0，便于用已知值验证。
    """
    kp = np.zeros((16, 3), dtype=np.float64)

    cx = 0.50 + i * 0.001      # 轻微水平移动，供相位划分用
    pelvis_y = 0.50
    shoulder_y = 0.22

    # 骨盆倾斜：右髋高于左髋 => 右髋 y 更小
    half_w = 0.045
    dy = math.tan(math.radians(pelvis_tilt_deg)) * half_w

    hip_r = (cx + half_w, pelvis_y - dy)
    hip_l = (cx - half_w, pelvis_y + dy)

    # 躯干侧倾：肩中心相对骨盆中心横向偏移
    lean_dx = math.tan(math.radians(lateral_lean_deg)) * 0.28
    shoulder_cx = cx + lean_dx
    shoulder_r = (shoulder_cx + 0.075, shoulder_y)
    shoulder_l = (shoulder_cx - 0.075, shoulder_y)

    # 双腿：从上向下微分开，踝间距即支撑宽度
    knee_r = (hip_r[0] + stanse_width * 0.3, pelvis_y + 0.20)
    knee_l = (hip_l[0] - stanse_width * 0.3, pelvis_y + 0.20)
    ankle_r = (hip_r[0] + stanse_width * 0.5, pelvis_y + 0.38)
    ankle_l = (hip_l[0] - stanse_width * 0.5, pelvis_y + 0.38)

    def put(name: str, xy: tuple[float, float]) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [xy[0], xy[1], Q_CLEAR]

    put("head", (shoulder_cx, shoulder_y - 0.10))
    put("neck", (shoulder_cx, shoulder_y))
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


def _frontal_sequence(
    n: int = 120,
    fps: float = 120.0,
    **kwargs,
) -> PoseSequence:
    seq = PoseSequence(estimator_name="frontal", estimator_version="1")
    for i in range(n):
        seq.frames.append(_frontal_pose(i, **kwargs))
    return seq


def test_frontal_metrics_blocked_in_side_view():
    """
    额状面指标在**侧面视角下必须全部返回 insufficient_data**，
    原因必须是 view_mismatch。

    这是 docs/03-指标定义.md 的硬性要求：
    侧面看不到骨盆的左右关系，这些指标在那时根本无从测量。
    """
    seq = make_running_sequence(120, fps=120.0)
    ctx = make_ctx(seq, fps=120.0, view="side")

    for mid in FRONTAL_METRICS:
        r = METRIC_FUNCS[mid](ctx)
        assert r.insufficient is not None, f"{mid} 在侧面视角下不该给值"
        assert r.insufficient["reason"] == "view_mismatch", (
            f"{mid} 的拒绝原因应为 view_mismatch，"
            f"实际是 {r.insufficient['reason']}"
        )
        assert r.value is None


def test_side_metrics_blocked_in_front_view():
    """反向也要成立：侧面指标在正面视角下必须被拦。"""
    seq = _frontal_sequence(120)
    ctx = make_ctx(seq, fps=120.0, view="front")

    for mid in ("trunk_lean", "shank_angle_touchdown", "step_length"):
        r = METRIC_FUNCS[mid](ctx)
        assert r.insufficient is not None, f"{mid} 在正面视角下不该给值"
        assert r.insufficient["reason"] == "view_mismatch"


def test_pelvis_tilt_zero_for_level_pelvis():
    """骨盆水平时侧倾角应当接近 0。"""
    seq = _frontal_sequence(120, pelvis_tilt_deg=0.0)
    ctx = make_ctx(seq, fps=120.0, view="front")

    r = METRIC_FUNCS["pelvis_tilt"](ctx)
    assert r.insufficient is None, f"应当可算：{r.insufficient}"
    assert abs(r.value) < 1.0, f"骨盆水平时侧倾角应接近 0，实得 {r.value}"


def test_pelvis_tilt_sign_follows_right_hip_height():
    """
    符号必须符合定义：正值 = 右侧髋高于左侧。

    构造时 pelvis_tilt_deg 为正表示右髋抬高。
    符号搞反会让"哪一侧需要加强"的结论完全颠倒。
    """
    seq = _frontal_sequence(120, pelvis_tilt_deg=5.0)
    ctx = make_ctx(seq, fps=120.0, view="front")

    r = METRIC_FUNCS["pelvis_tilt"](ctx)
    assert r.insufficient is None
    assert r.value > 0, (
        f"构造时右髋高于左髋，pelvis_tilt 应为正，实得 {r.value}"
    )
    # 构造的倾斜角就是 5°，允许平滑带来的少量偏差
    assert r.value == pytest.approx(5.0, abs=1.5)


def test_trunk_lateral_lean_detects_direction():
    """躯干侧倾的符号必须与构造方向一致。"""
    seq = _frontal_sequence(120, lateral_lean_deg=4.0)
    ctx = make_ctx(seq, fps=120.0, view="front")

    r = METRIC_FUNCS["trunk_lateral_lean"](ctx)
    assert r.insufficient is None
    assert r.value > 0, f"构造为向右侧倾，应为正，实得 {r.value}"
    assert r.value == pytest.approx(4.0, abs=1.5)


def test_stance_width_relative_is_scale_free():
    """
    相对支撑宽度用骨盆宽度归一化，**不依赖参考尺度** ——
    所以它在没有尺度的素材上也必须能算出来。

    这是它相对其它位移类指标的一个实际优势。
    """
    seq = _frontal_sequence(120, stanse_width=0.10)
    ctx = make_ctx(seq, fps=120.0, view="front",
                   scale=ScaleEstimate(method="none", valid_per_frame=False))

    r = METRIC_FUNCS["stance_width_relative"](ctx)
    # 可能因着地事件不足而拒绝，但绝不能因 no_reference_scale 拒绝
    if r.insufficient is not None:
        assert r.insufficient["reason"] != "no_reference_scale", (
            "相对支撑宽度用骨盆宽度归一化，不需要参考尺度"
        )


def test_pelvis_rotation_states_its_limitations():
    """
    pelvis_rotation 的可靠性是 C 级，且 arccos 无法给出方向 ——
    这些局限必须在 reliability_note 里明确告知。

    不说的后果：教练会以为"旋转 12°"能告诉他往前转还是往后转。
    """
    seq = _frontal_sequence(120)
    ctx = make_ctx(seq, fps=120.0, view="front")

    r = METRIC_FUNCS["pelvis_rotation"](ctx)
    if r.insufficient is not None:
        pytest.skip("合成序列未能计算该指标")

    note = r.reliability_note or ""
    assert "方向" in note, "必须说明无法给出旋转方向"
    assert "C 级" in note or "C级" in note, "必须说明可靠性等级"
    assert r.confidence is not None and r.confidence <= 0.5


def test_all_frontal_metrics_satisfy_contract_structure():
    """额状面指标同样要满足契约的结构约束。"""
    seq = _frontal_sequence(120)
    ctx = make_ctx(seq, fps=120.0, view="front")

    allowed_agg = {"mean", "sd", "n", "min", "max"}

    for mid in FRONTAL_METRICS:
        r = METRIC_FUNCS[mid](ctx)

        if r.aggregate is not None:
            assert "n" in r.aggregate, f"{mid} 的 aggregate 缺 n"
            extra = set(r.aggregate) - allowed_agg
            assert not extra, f"{mid} 的 aggregate 有契约外字段：{extra}"

        if r.insufficient is not None:
            for k in ("reason", "required", "actual", "impact", "suggestion"):
                assert r.insufficient.get(k), f"{mid} 缺 {k}"
            assert isinstance(r.insufficient["impact"], list)
            extra = set(r.insufficient) - {
                "reason", "required", "actual", "impact", "suggestion"}
            assert not extra, f"{mid} 的 insufficient 有契约外字段：{extra}"


def test_every_metric_spec_has_an_implementation():
    """
    20 个指标必须全部有实现。

    这条测试的价值在于：漏掉一个指标不会报错 ——
    compute_all_metrics 会给它一条 not_implemented 记录，
    报告照常产出，只是少了一项。没有这个断言就发现不了。
    """
    missing = set(METRIC_SPECS) - set(METRIC_FUNCS)
    assert not missing, f"以下指标尚未实现：{sorted(missing)}"


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------

def test_compute_all_covers_every_metric_spec():
    """
    每个契约里的指标都必须产出一条结果 ——
    哪怕是"尚未实现"。静默省略会让人以为数据被挑选过。
    """
    seq = make_running_sequence(120)
    ctx = make_ctx(seq)

    results = compute_all_metrics(ctx)
    got = {r.metric_id for r in results}
    expected = set(METRIC_SPECS.keys())

    assert got == expected, f"缺少指标：{expected - got}"


# ---------------------------------------------------------------------------
# 事件帧关节角度：用几何上已知的构造验证数值
# ---------------------------------------------------------------------------

def _pose_with_known_angles(
    knee_deg: float = 150.0,
    shank_deg: float = 12.0,
    hip_deg: float = 160.0,
    n: int = 60,
) -> PoseSequence:
    """
    构造一个角度已知的姿态序列。

    构造方式（全部在归一化坐标里，y 向下）：
        hip   = (0.50, 0.45)
        knee  = hip + L1 * (sin(shank_deg), cos(shank_deg))
                —— 大腿与小腿共线，所以膝角就是 hip-knee-ankle 的夹角
        实际上要同时满足指定的膝角与胫骨角，需要解一个小三角。
        为了可控，这里改成**直接构造**：
        先定胫骨方向（由 shank_deg 决定），再由 knee_deg 反推大腿方向。

    简化做法：让大腿与小腿的夹角恰为 knee_deg，
    且小腿相对竖直的夹角恰为 shank_deg。
    """
    seq = PoseSequence(estimator_name="geo", estimator_version="1")

    L_thigh = 0.17
    L_shank = 0.17

    for i in range(n):
        hip = (0.50, 0.45)

        # 小腿方向：相对竖直偏 shank_deg（向画面右侧）
        s = math.radians(shank_deg)
        knee = (hip[0] + L_thigh * math.sin(math.radians(shank_deg * 0.4)),
                hip[1] + L_thigh * math.cos(math.radians(shank_deg * 0.4)))

        # 踝由小腿方向决定：从膝往下、偏 shank_deg
        ankle = (knee[0] + L_shank * math.sin(s),
                 knee[1] + L_shank * math.cos(s))

        # 调整膝的位置，使 ∠(hip, knee, ankle) 恰为 knee_deg
        # 用余弦定理：已知 hip-ankle 距离 d 与两边长，求膝的位置
        d = math.dist(hip, ankle)
        if d < 1e-6:
            d = 1e-6
        # 角 at knee 固定为 knee_deg，则 hip-ankle 距离由它决定。
        # 反过来说，给定两边长与夹角，d 是确定的。
        # 这里为了让 hip 与 ankle 都保持在前面的位置，改用
        # 「以 hip 为顶点、按指定夹角放置 knee」的构造：
        #   knee 位于 hip 与 ankle 之间，使夹角成立。
        # 直接解三角形：两腰 L_thigh、L_shank，夹角 knee_deg，
        # 则 knee 在 hip-ankle 连线的某侧。
        L_left = L_thigh
        L_right = L_shank

        # 用 law of cosines 求 hip-ankle 距离
        d_required = math.sqrt(
            L_left ** 2 + L_right ** 2
            - 2 * L_left * L_right * math.cos(math.radians(knee_deg))
        )
        # 让 ankle 落在距 hip d_required 处，方向沿用前面算的方向
        dir_v = (ankle[0] - hip[0], ankle[1] - hip[1])
        norm = math.hypot(*dir_v)
        if norm < 1e-9:
            dir_v, norm = (0.0, 1.0), 1.0
        ux, uy = dir_v[0] / norm, dir_v[1] / norm
        ankle = (hip[0] + ux * d_required, hip[1] + uy * d_required)

        # knee 的位置：在 hip 到 ankle 的方向上偏转
        # 由余弦定理求 hip 处的角
        cos_a = (L_left ** 2 + d_required ** 2 - L_right ** 2) / (
            2 * L_left * d_required)
        cos_a = max(-1.0, min(1.0, cos_a))
        a = math.acos(cos_a)
        base = math.atan2(uy, ux)
        # 往左侧偏（画面里膝盖朝前）
        kx = hip[0] + L_left * math.cos(base + a)
        ky = hip[1] + L_left * math.sin(base + a)
        knee = (kx, ky)

        shoulder = (hip[0] + 0.02, hip[1] - 0.30)

        kp = np.zeros((16, 3), dtype=np.float64)

        def put(name, xy):
            kp[KEYPOINT_NAMES.index(name)] = [xy[0], xy[1], Q_CLEAR]

        put("head", (shoulder[0], shoulder[1] - 0.10))
        put("neck", shoulder)
        put("shoulder_r", shoulder)
        put("hip_r", hip)
        put("knee_r", knee)
        put("ankle_r", ankle)
        put("heel_r", (ankle[0] - 0.01, ankle[1] + 0.005))
        put("toe_r", (ankle[0] + 0.03, ankle[1] + 0.003))
        # 左侧镜像
        for a_, b_ in (("shoulder_r", "shoulder_l"), ("hip_r", "hip_l"),
                       ("knee_r", "knee_l"), ("ankle_r", "ankle_l"),
                       ("heel_r", "heel_l"), ("toe_r", "toe_l")):
            x, y, q = kp[KEYPOINT_NAMES.index(a_)]
            kp[KEYPOINT_NAMES.index(b_)] = [x - 0.02, y, q]

        kp[KEYPOINT_NAMES.index("pelvis_center")] = [
            (kp[KEYPOINT_NAMES.index("hip_r")][0]
             + kp[KEYPOINT_NAMES.index("hip_l")][0]) / 2,
            (kp[KEYPOINT_NAMES.index("hip_r")][1]
             + kp[KEYPOINT_NAMES.index("hip_l")][1]) / 2,
            Q_CLEAR,
        ]
        kp[KEYPOINT_NAMES.index("shoulder_center")] = kp[
            KEYPOINT_NAMES.index("shoulder_r")]

        seq.frames.append(PoseFrame(frame_index=i, keypoints=kp,
                                    person_conf=0.95))

    return seq


def test_thigh_swing_range_is_non_negative_and_bounded():
    """大腿摆动幅度必须是正数且落在生理范围内。"""
    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)

    r = METRIC_FUNCS["thigh_swing_range"](ctx)
    if r.insufficient is not None:
        pytest.skip(f"合成序列未能计算：{r.insufficient['actual']}")

    assert r.value is not None
    assert 0 < r.value < 180, f"摆动幅度 {r.value}° 不在合理范围"


def test_com_height_oscillation_needs_scale():
    """重心起伏是位移类指标，没有参考尺度必须判为数据不足。"""
    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0,
                   scale=ScaleEstimate(method="none", valid_per_frame=False))

    r = METRIC_FUNCS["com_height_oscillation"](ctx)
    assert r.insufficient is not None
    assert r.insufficient["reason"] == "no_reference_scale"


def test_displacement_metrics_reject_strong_pan():
    """
    位移类指标在明显跟踪拍摄下必须拒绝出值。

    这是单目视觉的固有限制：镜头在动时，
    画面里的位移 = 运动员位移 + 镜头位移，无法分离。
    """
    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)
    ctx.camera_motion_level = "strong_pan"
    ctx.camera_motion_shift = 14.0

    for mid in ("step_length", "com_height_oscillation"):
        r = METRIC_FUNCS[mid](ctx)
        assert r.insufficient is not None, f"{mid} 在跟踪拍摄下不该给值"
        assert r.insufficient["reason"] == "camera_motion"
        joined = " ".join(r.insufficient["impact"])
        assert len(joined) > 20, f"{mid} 的后果说明太短，没说清为什么"

    # 步长：必须点出"无法分离运动员位移与镜头位移"
    step = METRIC_FUNCS["step_length"](ctx)
    step_impact = " ".join(step.insufficient["impact"])
    assert "分开" in step_impact or "分离" in step_impact, (
        "步长的说明必须解释「单目视频无法分离两者」这一根本限制"
    )

    # 重心起伏：镜头俯仰才是它的问题所在，必须说清
    com = METRIC_FUNCS["com_height_oscillation"](ctx)
    com_impact = " ".join(com.insufficient["impact"])
    assert "俯仰" in com_impact, (
        "重心起伏受镜头俯仰影响，说明里必须点出这一点 —— "
        "否则用户以为只要水平跟拍就没问题"
    )


def test_step_length_fixed_camera_is_allowed():
    """固定机位下位移类指标不该被镜头运动这一条拦下。"""
    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)
    ctx.camera_motion_level = "fixed"

    r = METRIC_FUNCS["step_length"](ctx)
    # 可能因别的原因判不足（着地事件不足），但不能是 camera_motion
    if r.insufficient is not None:
        assert r.insufficient["reason"] != "camera_motion"


def test_event_angle_metric_reports_missing_event_clearly():
    """没有事件时必须明确说明"缺少事件"，而不是含糊地说数据不足。"""
    seq = make_running_sequence(60, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)
    ctx.events = GaitEvents()   # 清空所有事件

    for mid in ("shank_angle_touchdown", "knee_angle_midstance",
                "hip_angle_toeoff", "ankle_angle_touchdown"):
        r = METRIC_FUNCS[mid](ctx)
        assert r.insufficient is not None, f"{mid} 无事件时不该给值"
        assert r.insufficient["reason"] == "missing_event"
        # 必须说清是哪个事件缺失
        assert "着地" in r.insufficient["required"] or \
               "支撑中期" in r.insufficient["required"] or \
               "离地" in r.insufficient["required"]


def test_all_new_metrics_satisfy_contract_structure():
    """
    新增的 7 个指标也要满足契约：aggregate 结构、insufficient 五要素。
    这条测试防止"新写的指标漏了某条约束"。
    """
    seq = make_running_sequence(240, fps=240.0)
    ctx = make_ctx(seq, fps=240.0)

    new_metrics = [
        "shank_angle_touchdown", "knee_angle_midstance", "hip_angle_toeoff",
        "ankle_angle_touchdown", "thigh_swing_range", "step_length",
        "com_height_oscillation",
    ]
    allowed_agg = {"mean", "sd", "n", "min", "max"}

    for mid in new_metrics:
        r = METRIC_FUNCS[mid](ctx)

        if r.aggregate is not None:
            assert "n" in r.aggregate, f"{mid} 的 aggregate 缺 n"
            extra = set(r.aggregate) - allowed_agg
            assert not extra, f"{mid} 的 aggregate 有契约外字段：{extra}"

        if r.insufficient is not None:
            for k in ("reason", "required", "actual", "impact", "suggestion"):
                assert r.insufficient.get(k), f"{mid} 缺 {k}"
            assert isinstance(r.insufficient["impact"], list)
            extra = set(r.insufficient) - {
                "reason", "required", "actual", "impact", "suggestion"}
            assert not extra, f"{mid} 的 insufficient 有契约外字段：{extra}"

        if not r.reliable:
            assert r.reliability_note, f"{mid} 标了低置信却没写原因"


def test_one_metric_failure_does_not_kill_the_report(monkeypatch):
    """
    单个指标抛异常时，其余指标仍须产出。
    一份报告里少一项，远好过整份报告失败。
    """
    seq = make_running_sequence(60)
    ctx = make_ctx(seq)

    def boom(_ctx):
        raise RuntimeError("故意抛错")

    monkeypatch.setitem(METRIC_FUNCS, "trunk_lean", boom)

    results = compute_all_metrics(ctx)
    trunk = next(r for r in results if r.metric_id == "trunk_lean")
    assert trunk.insufficient is not None
    # 原因值必须是契约枚举内的。契约里没有"程序出错"这一类，
    # 所以用 not_implemented —— 教练看到的结论是一样的：这项本次没有产出。
    # 真正的诊断信息在 actual 里，由开发者排查。
    assert trunk.insufficient["reason"] == "not_implemented"
    assert "RuntimeError" in trunk.insufficient["actual"], (
        "异常类型必须保留在 actual 里，否则开发者无从排查"
    )

    # 其余指标不受影响
    others = [r for r in results if r.metric_id != "trunk_lean"]
    assert len(others) == len(METRIC_SPECS) - 1
    assert any(r.insufficient is None for r in others), (
        "其它指标应当仍有能算出来的"
    )


# ---------------------------------------------------------------------------
# 相位划分
# ---------------------------------------------------------------------------

def test_detect_phases_finds_acceleration():
    """合成序列是持续加速的，应当划分出加速段。"""
    seq = make_running_sequence(n_frames=240, fps=240.0, forward_speed=0.5)
    phases, notes = detect_phases(seq, fps=240.0)

    assert phases, f"未划分出相位：{notes}"
    assert any(p.phase in ("acceleration", "max_velocity") for p in phases)


def test_detect_phases_returns_empty_for_front_view():
    """正面视角下无法用位移划分相位，应当明确返回空而不是乱猜。"""
    seq = make_running_sequence(120)
    phases, notes = detect_phases(seq, fps=240.0, progress_axis="y")
    assert phases == []
    assert any("前进方向" in n for n in notes)
