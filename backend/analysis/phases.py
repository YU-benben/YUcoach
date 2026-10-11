"""
相位划分与事件检测。

为什么这是整个分析里最难的一环：
    "触地时间"、"着地时膝角" 这类指标的定义都锚定在**具体时刻**上。
    触地时刻判错一帧，60fps 下就是 16.7 ms 的误差 ——
    而真实触地时间只有 80–120 ms。

本模块只做**不依赖足部关键点**的那部分检测：
    · 相位划分（加速段 / 途中跑 / 减速）—— 用水平位置与速度
    · 步态周期切分 —— 用髋关节的周期性运动
    · 重心最低/最高点 —— 用髋中点的高度

依赖足部点的检测（触地/离地时刻）单独标注为低可靠，
因为本项目当前的足部点是几何推导的，精度不足。

见 docs/03-指标定义.md 与 docs/06-实现流程.md 的阶段划分部分。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .metrics_base import smooth_series
from .pose_types import PoseFrame, PoseSequence


@dataclass
class GaitEvents:
    """步态事件。帧号均为视频绝对帧号。"""

    #: 每一次触地（脚尖/脚跟接触地面）的帧号。
    #: 依赖足部点，当前的推导精度下只有参考价值。
    touchdowns: list[int] = field(default_factory=list)

    #: 每一次离地的帧号
    toe_offs: list[int] = field(default_factory=list)

    #: 支撑中期（重心最低点）帧号。用髋中点高度判定，不依赖足部点。
    midstances: list[int] = field(default_factory=list)

    #: 腾空期最高点帧号
    flight_peaks: list[int] = field(default_factory=list)

    #: 检测方法说明，写入报告
    method: str = ""
    reliability: str = "B"
    notes: list[str] = field(default_factory=list)

    def step_count(self) -> int:
        """步数。触地次数即步数。"""
        return len(self.touchdowns)


@dataclass
class PhaseSegment:
    """一个相位区间。"""

    phase: str            # set / start / acceleration / transition /
    #                       max_velocity / deceleration
    from_frame: int
    to_frame: int
    confidence: float = 1.0

    @property
    def frame_count(self) -> int:
        return self.to_frame - self.from_frame + 1


# ---------------------------------------------------------------------------
# 相位划分
# ---------------------------------------------------------------------------

def detect_phases(
    seq: PoseSequence,
    fps: float,
    progress_axis: str = "x",
) -> tuple[list[PhaseSegment], list[str]]:
    """
    划分跑步相位。

    判据是**水平推进速度**的变化，而不是时间：
        加速段    速度持续上升
        过渡段    速度增速放缓
        途中跑    速度进入平台期（±5% 内波动）
        减速段    速度持续下降

    为什么不用时间划分：
        不同水平、不同项目的加速持续时间差别很大
        （100 m 精英约 5 秒达到最高速，青少年可能要 7 秒以上）。
        按时间切会把不同阶段混在一起。

    参数
    ----
    progress_axis : 'x' 表示画面横向即前进方向。
                    侧面拍摄时成立；正面/背面拍摄时该轴无意义，
                    此函数会返回空结果。

    返回
    ----
    (相位列表, 说明信息)
    """
    notes: list[str] = []
    if len(seq.frames) < 10:
        notes.append("帧数太少，无法划分相位。")
        return [], notes

    if progress_axis != "x":
        notes.append(
            "正面/背面视角下画面横向不代表前进方向，"
            "无法用位移划分相位。此类视角按整段处理。"
        )
        return [], notes

    # ---- 1. 逐帧的水平位置（用骨盆中心，比单个髋关节稳定）----
    idxs: list[int] = []
    xs: list[float] = []
    for pf in seq.frames:
        p = pf.point("pelvis_center") or pf.point("hip_r")
        if p is None:
            continue
        idxs.append(pf.frame_index)
        xs.append(p[0])

    if len(xs) < 10:
        notes.append(
            "骨盆中心在多数帧上不可见，无法计算位移曲线。"
        )
        return [], notes

    x = smooth_series(np.asarray(xs, dtype=np.float64), window=7)

    # ---- 2. 数值微分求速度 ----
    # 用中心差分。帧率已知，所以速度单位是"归一化宽度/秒"。
    dt = 1.0 / fps
    v = np.gradient(x, dt)

    # 再平滑一次：差分会放大噪声
    v = smooth_series(v, window=9)
    v_abs = np.abs(v)

    peak_v = float(np.max(v_abs))
    if peak_v < 1e-6:
        notes.append("画面中未检测到水平位移，无法划分相位。")
        return [], notes

    # ---- 3. 找速度曲线上的关键点 ----
    peak_i = int(np.argmax(v_abs))

    # 起跑点：速度首次超过峰值 10% 的位置
    onset_i = 0
    for i in range(len(v_abs)):
        if v_abs[i] > peak_v * 0.10:
            onset_i = i
            break

    # 加速段结束：速度首次达到峰值 90%
    accel_end_i = peak_i
    for i in range(onset_i, peak_i + 1):
        if v_abs[i] >= peak_v * 0.90:
            accel_end_i = i
            break

    # 途中跑结束：峰值之后速度首次跌破峰值 90%
    maxvel_end_i = peak_i
    for i in range(peak_i, len(v_abs)):
        if v_abs[i] < peak_v * 0.90:
            maxvel_end_i = i
            break

    # ---- 4. 组装相位 ----
    phases: list[PhaseSegment] = []

    def seg(phase: str, a: int, b: int, conf: float = 1.0) -> None:
        if b > a:
            phases.append(PhaseSegment(phase, idxs[a], idxs[b], conf))

    seg("acceleration", onset_i, accel_end_i)
    seg("max_velocity", accel_end_i, maxvel_end_i, 0.85)

    # 减速段：途中跑之后剩余的部分
    if maxvel_end_i < len(idxs) - 2:
        seg("deceleration", maxvel_end_i, len(idxs) - 1, 0.8)

    notes.append(
        f"按水平速度曲线划分相位："
        f"峰值速度 {peak_v:.3f} 归一化宽度/秒，出现在第 {idxs[peak_i]} 帧。"
    )
    notes.append(
        "相位边界由速度阈值（10% / 90% / 90%）确定，"
        "不同拍摄距离下归一化速度数值不同，但阈值比例不受影响。"
    )

    if len(phases) < 2:
        notes.append(
            "只划分出一个相位。素材可能过短，或未包含完整的加速过程。"
        )

    return phases, notes


# ---------------------------------------------------------------------------
# 步态事件
# ---------------------------------------------------------------------------

def detect_gait_events(
    seq: PoseSequence,
    fps: float,
) -> GaitEvents:
    """
    检测步态事件。

    分两类，可靠性不同，必须分开报告：

    A. 不依赖足部点（较可靠）
       支撑中期：髋中点高度曲线的**局部最低点**。
                 支撑期身体被压缩，重心最低。
       腾空最高点：髋中点高度的局部最高点。

    B. 依赖足部点（当前不可靠）
       触地/离地：由踝关节高度与水平速度判定。
       本项目的足部点是几何推导的，精度不足 ——
       所以这些事件的帧号只作参考，不能支撑精确的时间指标。

    这也是为什么在本项目当前的模型条件下，
    ground_contact_time / flight_time / duty_factor 会被判为
    数据不足而不是给一个不准的数。
    """
    events = GaitEvents()
    notes: list[str] = []

    if len(seq.frames) < 8:
        notes.append("帧数太少，无法检测步态事件。")
        events.notes = notes
        return events

    idxs: list[int] = []
    hip_y: list[float] = []
    ankle_y_r: list[float | None] = []
    ankle_y_l: list[float | None] = []

    for pf in seq.frames:
        pelvis = pf.point("pelvis_center")
        if pelvis is None:
            hr, hl = pf.point("hip_r"), pf.point("hip_l")
            if hr and hl:
                pelvis = ((hr[0] + hl[0]) / 2, (hr[1] + hl[1]) / 2, 2)
        if pelvis is None:
            continue

        idxs.append(pf.frame_index)
        hip_y.append(pelvis[1])

        ar, al = pf.point("ankle_r"), pf.point("ankle_l")
        ankle_y_r.append(ar[1] if ar else None)
        ankle_y_l.append(al[1] if al else None)

    if len(idxs) < 8:
        notes.append("骨盆/髋关节在多数帧上不可见，无法检测步态事件。")
        events.notes = notes
        return events

    y = smooth_series(np.asarray(hip_y, dtype=np.float64), window=5)

    # ---- 支撑中期：髋中点局部最低点 ----
    # 最小间隔按 100 ms 折算成帧数。短跑步频上限约 5 步/秒，
    # 即单步最短 200 ms，所以两个事件至少隔 100 ms。
    min_gap = max(2, int(round(fps * 0.10)))

    free_midstances = _local_extrema(idxs, y, min_gap, mode="min")
    events.flight_peaks = _local_extrema(idxs, y, min_gap, mode="max")

    notes.append(
        f"支撑中期由髋中点高度的局部最低点判定，"
        f"检出 {len(free_midstances)} 次。"
        f"该方法不依赖足部关键点，可靠性等级 B。"
    )

    # ---- 触地/离地：依赖足部点，标注为低可靠 ----
    # 判据：踝关节接近其在整个序列中的最低位置，且水平速度开始下降。
    # 这个判据本身是合理的，但输入数据（足部点）精度不足。
    ankle_y = _combine_ankles(ankle_y_r, ankle_y_l)
    if ankle_y is not None:
        a = smooth_series(np.asarray(ankle_y, dtype=np.float64), window=5)
        span = float(np.max(a) - np.min(a))
        if span > 1e-4:
            # 踝关节处于最低 15% 区间内视为支撑期
            thresh = float(np.min(a)) + span * 0.15
            in_contact = a <= thresh
            events.touchdowns = _rising_edges(idxs, in_contact)
            events.toe_offs = _falling_edges(idxs, in_contact)

            notes.append(
                f"触地/离地由踝关节高度判定，检出 {len(events.touchdowns)} 次触地、"
                f"{len(events.toe_offs)} 次离地。"
            )
            events.reliability = "C"
            notes.append(
                "⚠️ 触地/离地时刻依赖足部关键点，而本项目的足部点由"
                "踝关节与小腿朝向**几何推导**，非实测。"
                "由此得到的时间指标只有参考价值，不足以支撑训练决策。"
                "要精确测量触地时间，必须使用带足部关键点的模型，"
                "或提供 120 fps 以上的素材以降低单帧量化误差。"
            )
    else:
        notes.append(
            "踝关节在多数帧上不可见，无法判定触地/离地时刻。"
            "触地时间、腾空时间、占空比将判为数据不足。"
        )

    events.method = "hip_height_extrema + ankle_height_threshold"

    # ---- 支撑中期：用支撑期区间约束 ----
    #
    # ⚠️ 这一步是**健壮性的关键**，顺序不能颠倒。
    #
    # 髋高的垂直起伏（跑步时约 5–10 cm）远小于腿部摆动等其他运动的幅度，
    # 所以髋高曲线在最低点附近很**平**。在平坦的极小值上定位，
    # 噪声稍微一推，检出点就会滑到相邻的步态周期去。
    #
    # 实测：仅 1 像素的关键点噪声就让支撑中期帧号的中位偏移达到 67 帧，
    #       而真值事件的间隔只有 53 帧 —— 也就是整整错了一个周期。
    #
    # 修法不是"把极值找得更准"，而是**加上物理约束**：
    #   支撑中期按定义就在支撑期之内，即触地与离地之间。
    # 触地/离地由踝高判定，在同样噪声下稳定得多（偏移 < 1 帧）。
    #
    # 于是：在 [触地, 离地] 区间内找髋高最低点。
    # 区间把搜索范围限制在半个周期内，滑到邻周期的可能性消失。
    #
    # 若触地/离地不可得（足部点不可见），退回无约束的全局极值，
    # 并在 notes 里说明可靠性更低 —— 而不是假装没有这个差别。
    if events.touchdowns and events.toe_offs:
        constrained = _midstances_within_stance(idxs, y, events)
        if constrained:
            events.midstances = constrained
            notes.append(
                f"支撑中期由「触地—离地区间内的髋高最低点」判定，"
                f"检出 {len(constrained)} 次（带物理约束，抗噪）。"
            )
        else:
            events.midstances = free_midstances
            notes.append(
                "支撑中期未能与支撑期区间配对，退回无约束的髋高极值判定。"
                "该结果对关键点噪声敏感，可靠性降低。"
            )
    else:
        events.midstances = free_midstances
        notes.append(
            "⚠️ 触地/离地不可得，支撑中期只能由髋高全局极值判定。"
            "髋高曲线在最低点附近较平，该判定对关键点噪声**敏感** —— "
            "在低帧率或关键点抖动大的素材上，检出的事件帧可能偏移一个周期。"
        )

    events.notes = notes
    return events


def _midstances_within_stance(
    idxs: list[int],
    y: np.ndarray,
    events: GaitEvents,
) -> list[int]:
    """
    在每一段支撑期（触地 -> 离地）内找髋高最低点。

    为什么这样更稳：
        髋高曲线在最低点附近平坦，全局找极值时噪声会把它推到相邻周期。
        但支撑中期按定义就落在支撑期之内 ——
        用触地/离地这对稳定事件把搜索范围限制住，
        就等于用可靠的测量去约束不可靠的测量。
    """
    # 帧号 -> 数组下标
    pos = {f: i for i, f in enumerate(idxs)}
    out: list[int] = []

    for td in events.touchdowns:
        # 找该次触地之后的第一次离地
        later = [t for t in events.toe_offs if t > td]
        if not later:
            continue
        to = later[0]

        i0, i1 = pos.get(td), pos.get(to)
        if i0 is None or i1 is None:
            continue

        # 区间太短时跳过：至少要有 3 帧才能谈"最低点"
        if i1 - i0 < 3:
            continue

        seg = y[i0:i1 + 1]
        if len(seg) == 0:
            continue
        out.append(idxs[i0 + int(np.argmin(seg))])

    return sorted(set(out))


def _combine_ankles(
    r: list[float | None],
    l: list[float | None],
) -> list[float] | None:
    """
    合并左右踝高度，取**较低**的那只。

    理由：支撑期一定是最低的那只脚在地面上。
    取平均会让支撑脚与摆动脚混在一起，把事件时刻抹平。
    """
    out: list[float] = []
    for a, b in zip(r, l):
        vals = [v for v in (a, b) if v is not None]
        if not vals:
            return None
        out.append(max(vals))   # y 向下，取最大者为较低
    return out


def _local_extrema(
    idxs: list[int],
    y: np.ndarray,
    min_gap: int,
    mode: str,
) -> list[int]:
    """
    找局部极值，并保证相邻极值间隔不小于 min_gap 帧。

    ⚠️ 这个函数踩过两个坑，都直接导致事件帧大幅漂移：

    坑 1：平台被拆成多个候选
        判据 `z[i] >= z[i-1] and z[i] >= z[i+1]` 对一段**等高的平台**
        会把平台上每一个点都列成候选。而 _prominence 在平台上
        给出的分数几乎相同，于是"选哪个"取决于排序的稳定性 ——
        加一点噪声，选中的点就从平台左端跳到右端。

        修法：识别平台，用平台**中心**作为唯一候选。
        这同时让结果是确定性的（不依赖排序实现）。

    坑 2：显著性的邻域窗口写死成 5 帧
        5 帧在 240 fps 下只占步态周期的 2%，在 60 fps 下占 8%。
        同一个算法在不同帧率下行为不同 —— 而帧率是使用方给的，
        算法不该假设它。

        修法：窗口按 min_gap 缩放（min_gap 本身由帧率算出）。

    实测背景：仅 1 像素的关键点噪声就让支撑中期的检出数
    从 20 掉到 14、帧号偏移 92.8 帧（约两个步态周期）。
    根因就是上面两条。
    """
    if len(y) < 3:
        return []

    sign = 1.0 if mode == "min" else -1.0
    z = y * sign     # 统一转换成"找最大值"

    # ---- 1. 找候选，并把平台折叠成一个中心点 ----
    candidates: list[int] = []
    i = 1
    n = len(z)
    while i < n - 1:
        # 判断是否处在"不小于左右邻"的位置
        if z[i] >= z[i - 1] and z[i] >= z[i + 1]:
            # 向右扩展等高平台
            j = i
            while j + 1 < n and abs(z[j + 1] - z[i]) <= 1e-12:
                j += 1
            # 平台中心。用 (i + j) // 2 而不是 i ——
            # 这正是"选左端还是右端"那个不稳定性的修法。
            candidates.append((i + j) // 2)
            i = j + 1
        else:
            i += 1

    if not candidates:
        return []

    # ---- 2. 显著性窗口按 min_gap 缩放 ----
    # min_gap 由帧率折算而来（约 100 ms），所以窗口与帧率无关。
    # 至少 2 帧，避免 min_gap 很小时窗口退化成单点。
    half_win = max(2, min_gap // 2)

    scored = sorted(
        candidates,
        key=lambda i: -_prominence(z, i, half_win),
    )

    chosen: list[int] = []
    for i in scored:
        if all(abs(idxs[i] - idxs[j]) >= min_gap for j in chosen):
            chosen.append(i)

    return sorted(idxs[i] for i in chosen)


def _prominence(z: np.ndarray, i: int, half_win: int) -> float:
    """
    极值的显著程度：该点与左右邻域均值的差。

    邻域宽度由调用方按帧率折算传入 —— 不写死帧数，
    否则同一段素材在不同帧率下会给出不同的极值。
    """
    lo = max(0, i - half_win)
    hi = min(len(z), i + half_win + 1)
    neighbors = np.concatenate([z[lo:i], z[i + 1:hi]])
    if len(neighbors) == 0:
        return 0.0
    return float(z[i] - np.mean(neighbors))


def _rising_edges(idxs: list[int], mask: np.ndarray) -> list[int]:
    return [idxs[i] for i in range(1, len(mask)) if mask[i] and not mask[i - 1]]


def _falling_edges(idxs: list[int], mask: np.ndarray) -> list[int]:
    return [idxs[i] for i in range(1, len(mask)) if not mask[i] and mask[i - 1]]
