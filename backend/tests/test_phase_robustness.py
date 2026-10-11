"""
步态事件检测的健壮性测试。

这一组测试保护一个**真实踩过的坑**：

    髋高的垂直起伏（跑步时约 5–10 cm）远小于腿部摆动等其他运动的幅度，
    所以髋高曲线在最低点附近很**平**。在平坦的极小值上定位，
    关键点噪声稍微一推，检出点就会滑到相邻的步态周期去。

    实测：仅 1 像素的关键点噪声就让支撑中期帧号的中位偏移达到 67 帧，
          而真值事件的间隔只有 53 帧 —— 整整错了一个周期。

    而所有锚定支撑中期的指标（支撑中期膝角、骨盆下沉）都会因此
    在**错误的时刻**取值，误差被放大到 5–7 度。

修法是加物理约束（支撑中期必然落在触地与离地之间），
这一组测试就是防止那个约束被后来的改动去掉。

为什么要单独一个文件：
    这类缺陷**不会让任何测试失败、不会报错、不会产生非法值** ——
    它只是让指标悄悄变差。只有专门针对"抗噪性"的测试才能发现。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.phases import (  # noqa: E402
    _local_extrema,
    detect_gait_events,
)
from backend.analysis.pose_types import (  # noqa: E402
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)

FPS = 240.0
STEP_CYCLE_S = 0.22      # 步频约 273 步/分


# ---------------------------------------------------------------------------
# 合成跑者
# ---------------------------------------------------------------------------

def make_runner(i: int, noise_sigma: float = 0.0,
                rng: np.random.Generator | None = None) -> PoseFrame:
    """
    构造一帧侧视跑步姿态。

    ⚠️ 骨盆垂直起伏的频率必须等于**步频**（cos(phase)），
       不能是它的两倍（cos(2*phase)）。

       最初写成 2*f 时，髋高曲线以两倍步频振荡，
       极值检测在错误的频率上找支撑中期，
       步频指标于是测到谐波、算出 390 步/分（真值 273）。

       这类"构造自洽性"错误很难发现：
       每个单独的数字看着都正常，只有拿理论值一对才露馅。
    """
    kp = np.zeros((16, 3), dtype=np.float64)

    t = i / FPS
    phase = 2 * math.pi * t / STEP_CYCLE_S

    # 骨盆：每步起伏一次（支撑期最低）
    bob = 0.018 * math.cos(phase)
    cx = 0.35 + i * 0.0012
    pelvis = np.array([cx, 0.55 + bob])

    trunk_lean = math.radians(8.0 + 3.0 * math.sin(phase))
    trunk_len = 0.24
    neck = pelvis + np.array([trunk_len * math.sin(trunk_lean),
                              -trunk_len * math.cos(trunk_lean)])
    head = neck + np.array([0.02 * math.sin(trunk_lean), -0.095])

    def leg(ph: float):
        thigh = math.radians(35.0 * math.sin(ph))
        shank = math.radians(45.0 * math.sin(ph + 1.1) - 20.0)
        knee = pelvis + np.array([0.24 * math.sin(thigh),
                                  0.24 * math.cos(thigh)])
        ankle = knee + np.array([0.24 * math.sin(thigh + shank),
                                 0.24 * math.cos(thigh + shank)])
        return knee, ankle

    knee_r, ankle_r = leg(phase)
    knee_l, ankle_l = leg(phase + math.pi)

    def put(name: str, xy) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [float(xy[0]), float(xy[1]), Q_CLEAR]

    put("pelvis_center", pelvis)
    put("hip_r", pelvis + [0.02, 0])
    put("hip_l", pelvis - [0.02, 0])
    put("neck", neck)
    put("shoulder_center", neck)
    put("shoulder_r", neck + [0.04, 0])
    put("shoulder_l", neck - [0.04, 0])
    put("head", head)
    put("knee_r", knee_r)
    put("knee_l", knee_l)
    put("ankle_r", ankle_r)
    put("ankle_l", ankle_l)
    for side, ankle, sign in (("r", ankle_r, 1), ("l", ankle_l, -1)):
        put(f"heel_{side}", ankle + [-0.01 * sign, 0.012])
        put(f"toe_{side}", ankle + [0.030 * sign, 0.010])

    kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
    kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)

    if noise_sigma > 0 and rng is not None:
        vis = kp[:, 2] > 0
        kp[vis, :2] += rng.normal(0, noise_sigma, size=(int(vis.sum()), 2))
        kp[:, 0] = np.clip(kp[:, 0], 0.0, 1.0)
        kp[:, 1] = np.clip(kp[:, 1], 0.0, 1.0)

    return PoseFrame(frame_index=i, keypoints=kp, person_conf=0.95)


def build_sequence(n: int = 480, noise_sigma: float = 0.0,
                   seed: int = 0) -> PoseSequence:
    rng = np.random.default_rng(seed)
    seq = PoseSequence(estimator_name="test", estimator_version="1")
    for i in range(n):
        seq.frames.append(make_runner(i, noise_sigma, rng))
    return seq


# ---------------------------------------------------------------------------
# _local_extrema 的基本行为
# ---------------------------------------------------------------------------

def test_local_extrema_finds_expected_count():
    """
    正弦信号的极值个数必须等于理论值。

    480 帧、步周期 52.8 帧 -> 9.09 个周期 -> 9 个最低点。
    （端点不完整，允许 ±1）
    """
    n = 480
    t = np.arange(n, dtype=np.float64)
    y = np.cos(2 * math.pi * t / 52.8)

    idxs = list(range(n))
    min_gap = int(round(FPS * 0.10))     # 24 帧

    ext = _local_extrema(idxs, y, min_gap, mode="min")
    assert abs(len(ext) - 9) <= 1, (
        f"应检出约 9 个最低点，实得 {len(ext)}"
    )


def test_local_extrema_is_deterministic_on_flat_peaks():
    """
    ⚠️ 平台上的极值必须**确定**，且落在平台中心。

    旧实现的判据 `z[i] >= z[i-1] and z[i] >= z[i+1]` 会把一段等高平台
    上的每个点都列成候选，而显著性分数在平台上几乎相同 ——
    于是"选哪个"取决于排序的稳定性。加一点噪声，选中的点
    就从平台左端跳到右端。

    这里构造**单个**平底凹陷（V 形谷底被削平），验证：
      · 结果稳定（多次调用一致）
      · 选中的是平台中心，而不是左端或右端

    注意不要用方波式的"浅槽"造测试数据 ——
    那种形状在槽的两个上角也会形成极小值，
    会让测试同时考"平台折叠"和"肩部极值"两件事。
    """
    n = 60
    idxs = list(range(n))
    # V 形谷：中心在 30，两侧线性上升
    y = 0.5 + np.abs(np.arange(n, dtype=np.float64) - 30.0) * 0.02
    # 把谷底 27..33 削平，形成一段平台
    y[27:34] = y[27]

    min_gap = 10
    runs = [_local_extrema(idxs, y, min_gap, mode="min") for _ in range(5)]

    assert all(r == runs[0] for r in runs), "平台上的极值检出不稳定"
    assert len(runs[0]) == 1, (
        f"V 形谷只应检出 1 个最低点，实得 {runs[0]}"
    )

    picked = runs[0][0]
    assert 29 <= picked <= 31, (
        f"平台 27–33 的中心应在 30 附近，实得 {picked} —— "
        f"取到端点说明平台未被折叠到中心"
    )


def test_local_extrema_respects_min_gap():
    """相邻极值的间隔必须不小于 min_gap。"""
    idxs = list(range(200))
    t = np.arange(200, dtype=np.float64)
    # 周期 10 帧，但 min_gap 要求 25 帧
    y = np.cos(2 * math.pi * t / 10.0)

    ext = _local_extrema(idxs, y, min_gap=25, mode="min")
    gaps = [ext[i + 1] - ext[i] for i in range(len(ext) - 1)]
    for g in gaps:
        assert g >= 25, f"间隔 {g} 小于 min_gap=25"


def test_local_extrema_handles_short_input():
    """输入过短时应返回空列表而不是崩溃。"""
    assert _local_extrema([0, 1], np.array([1.0, 2.0]), 3, "min") == []
    assert _local_extrema([], np.array([]), 3, "min") == []


def test_prominence_window_scales_with_fps():
    """
    ⚠️ 显著性的邻域窗口必须随帧率缩放。

    旧实现把窗口写死成 5 帧 —— 在 240 fps 下只占步周期的 2%，
    在 60 fps 下占 8%。同一个算法在不同帧率下行为不同，
    而帧率是使用方给的，算法不该假设它。

    这里用同一段**物理信号**在两个帧率下采样，
    验证检出的极值个数一致。
    """
    def extrema_at(fps: float) -> int:
        # 步周期固定 0.22 秒，用不同帧率采样
        dur = 2.2
        n = int(dur * fps)
        t = np.arange(n, dtype=np.float64) / fps
        y = np.cos(2 * math.pi * t / STEP_CYCLE_S)
        min_gap = max(2, int(round(fps * 0.10)))
        return len(_local_extrema(list(range(n)), y, min_gap, "min"))

    n240 = extrema_at(240.0)
    n120 = extrema_at(120.0)
    n60 = extrema_at(60.0)

    assert abs(n240 - n120) <= 1, (
        f"240fps 检出 {n240} 个、120fps 检出 {n120} 个 —— 帧率影响了结果"
    )
    assert abs(n240 - n60) <= 1, (
        f"240fps 检出 {n240} 个、60fps 检出 {n60} 个 —— 帧率影响了结果"
    )


# ---------------------------------------------------------------------------
# 抗噪性：这一组是核心
# ---------------------------------------------------------------------------

def test_midstance_is_stable_under_noise():
    """
    ⚠️ 核心回归测试。

    支撑中期的检出帧号在关键点噪声下必须保持稳定。

    背景：髋高曲线在最低点附近很平（垂直起伏只有 5–10 cm），
    全局找极值时噪声会把它推到相邻周期。
    实测旧实现：1 像素噪声 -> 帧号中位偏移 **67 帧**，
                而事件间隔只有 53 帧 —— 错了一个完整周期。

    修法是加物理约束：支撑中期必然落在触地与离地之间。

    这条测试用 1 像素噪声（YOLOv8-pose 的典型水平），
    要求帧号偏移不超过 3 帧。
    """
    clean = detect_gait_events(build_sequence(480, 0.0), FPS)
    assert len(clean.midstances) >= 8, (
        f"无噪声时应检出约 9 次支撑中期，实得 {len(clean.midstances)}"
    )

    # 用最近邻匹配而不是按下标配对 ——
    # 若检出的次数不同，按下标配对会得出无意义的巨大偏移
    for sigma in (0.001, 0.003):
        shifts = []
        for seed in range(5):
            ev = detect_gait_events(
                build_sequence(480, sigma, seed=seed), FPS)
            for m in ev.midstances:
                nearest = min(clean.midstances, key=lambda c: abs(c - m))
                shifts.append(abs(nearest - m))

        if not shifts:
            pytest.fail(f"噪声 {sigma} 下未检出任何支撑中期")

        # 按下标配对时的"错周期"现象会表现为平均偏移远大于半个周期
        mean_shift = float(np.mean(shifts))
        assert mean_shift < 3.0, (
            f"噪声 {sigma * 960:.0f}px 下支撑中期帧号平均偏移 "
            f"{mean_shift:.1f} 帧（应 <3）。"
            f"这通常意味着「支撑中期必须落在支撑期内」这个约束失效了，"
            f"检测器又回到在平坦的髋高曲线上全局找极值。"
        )


def test_midstance_lies_between_touchdown_and_toeoff():
    """
    支撑中期必须落在支撑期内 —— 这是定义，不是近似。

    如果这条不成立，说明约束逻辑没生效。
    """
    seq = build_sequence(480, 0.0)
    ev = detect_gait_events(seq, FPS)

    assert ev.touchdowns and ev.toe_offs and ev.midstances, (
        "该合成素材应能检出全部三类事件"
    )

    inside = 0
    for m in ev.midstances:
        # 存在一对 (触地, 离地) 把这次支撑中期夹在中间
        for td in ev.touchdowns:
            later = [t for t in ev.toe_offs if t > td]
            if later and td <= m <= later[0]:
                inside += 1
                break

    ratio = inside / len(ev.midstances)
    assert ratio >= 0.9, (
        f"只有 {ratio * 100:.0f}% 的支撑中期落在支撑期内（应 ≥90%）"
    )


def test_touchdown_is_stable_under_noise():
    """着地检测本来就稳，这条测试把它的稳定性固定下来。"""
    clean = detect_gait_events(build_sequence(480, 0.0), FPS)

    for sigma in (0.001, 0.003):
        ev = detect_gait_events(build_sequence(480, sigma, seed=7), FPS)
        assert len(ev.touchdowns) == len(clean.touchdowns), (
            f"噪声 {sigma * 960:.0f}px 下着地检出数从 "
            f"{len(clean.touchdowns)} 变成 {len(ev.touchdowns)}"
        )
        shifts = [abs(a - b) for a, b in
                  zip(ev.touchdowns, clean.touchdowns)]
        assert max(shifts) <= 3, (
            f"着地帧号最大偏移 {max(shifts)} 帧，过大"
        )


def test_events_have_explanatory_notes():
    """
    事件检测必须留下说明，特别是**可靠性**。

    低帧率或足部点不可得时，支撑中期的判定会退化 ——
    这个退化必须写在 notes 里，而不是静默发生。
    """
    ev = detect_gait_events(build_sequence(480, 0.0), FPS)
    assert ev.notes, "事件检测必须给出说明"
    assert ev.method, "必须记录用了什么方法"

    joined = " ".join(ev.notes)
    assert "支撑中期" in joined, "notes 里应说明支撑中期是怎么判定的"


def test_short_sequence_does_not_crash():
    """帧数太少时应优雅返回，而不是抛异常。"""
    seq = PoseSequence(estimator_name="t", estimator_version="1")
    for i in range(3):
        seq.frames.append(make_runner(i))

    ev = detect_gait_events(seq, FPS)
    assert ev.midstances == []
    assert ev.notes, "应说明为什么检不出事件"
