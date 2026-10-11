"""
指标计算。

核心设计：**入口先检查前提条件，不满足就明确说"算不了"。**

    教练看到"步幅 1.15 m"会直接采信。如果这个数字是在 30 fps、
    没有参考尺度的素材上硬算出来的，它可能差 30% 以上，
    而报告上没有任何迹象。

    所以每个指标在计算前都过一遍前置检查：
      视角是否匹配 · 帧率是否达标 · 关键点可见率是否够 · 参考尺度是否有
    任一不满足 -> insufficient_data，并给出原因、差距、后果、补齐方式。

指标定义与最低帧率要求来自 docs/03-指标定义.md 附录 A。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .metrics_base import (
    METRIC_SPECS,
    MetricResult,
    MetricSpec,
    aggregate_block,
    angle_at,
    insufficient,
    segment_angle_from_vertical,
    smooth_series,
)
from .phases import GaitEvents, PhaseSegment
from .pose_types import PoseFrame, PoseSequence
from .reference_scale import ScaleEstimate

# 关键点可见率低于此值时，基于它的指标判为不可靠
MIN_KP_COVERAGE = 0.60


@dataclass
class MetricContext:
    """计算所有指标所需的上下文。一次构建，多次使用。"""

    seq: PoseSequence
    fps: float
    view: str
    scale: ScaleEstimate
    events: GaitEvents
    phases: list[PhaseSegment]
    athlete_height_cm: float | None = None

    # 镜头运动。位移类指标必须知道这个 ——
    # 跟踪拍摄下画面位移 = 运动员位移 + 镜头位移，单目无法分离。
    camera_motion_level: str = "fixed"
    camera_motion_shift: float = 0.0

    # 关键点可见率缓存
    _coverage: dict[str, float] | None = None

    def coverage(self, name: str) -> float:
        if self._coverage is None:
            self._coverage = self.seq.coverage()
        return self._coverage.get(name, 0.0)

    def min_coverage(self, *names: str) -> float:
        return min((self.coverage(n) for n in names), default=0.0)

    def frames_by_index(self) -> dict[int, PoseFrame]:
        return {f.frame_index: f for f in self.seq.frames}

    def phase_of(self, frame_index: int) -> str:
        for p in self.phases:
            if p.from_frame <= frame_index <= p.to_frame:
                return p.phase
        return "whole_run"


# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------

def _check_preconditions(
    spec: MetricSpec,
    ctx: MetricContext,
    required_keypoints: tuple[str, ...],
) -> dict | None:
    """
    检查指标能否计算。返回 None 表示可以算，否则返回 insufficient 说明。

    顺序是有意的：先查最根本的（视角、帧率），
    这样给出的原因最贴近真实障碍。
    """
    # ---- 视角 ----
    if ctx.view not in spec.views:
        need = "、".join(_view_zh(v) for v in spec.views)
        return insufficient(
            reason="view_mismatch",
            required=f"{need}视角拍摄",
            actual=f"当前是{_view_zh(ctx.view)}视角",
            impact=(
                f"{spec.name_zh}只能从{need}视角测量。"
                f"从其它角度看，这个量要么看不到，要么量出来不是同一个东西——"
                f"不同视角测的是不同的物理量，不能互相替代。"
            ),
            suggestion=(
                f"补拍一段{need}视角的素材。拍摄时让镜头光轴垂直于"
                f"跑动方向（侧面）或正对运动员（正面/背面）。"
            ),
        )

    # ---- 帧率 ----
    if ctx.fps < spec.min_fps:
        impact = _fps_impact(spec)
        return insufficient(
            reason="frame_rate_unverified",
            required=f"≥ {spec.min_fps:.0f} fps",
            actual=f"{ctx.fps:.0f} fps",
            impact=impact,
            suggestion=(
                "用手机「慢动作」模式录制（120 或 240 fps），"
                "并把原视频直接上传，不要经过剪辑软件导出——"
                "导出会改变时序，让帧率信息不可信。"
            ),
        )

    # ---- 关键点可见率 ----
    covered = [(n, ctx.coverage(n)) for n in required_keypoints]
    poor = [(n, c) for n, c in covered if c < MIN_KP_COVERAGE]
    if poor:
        detail = "、".join(f"{_kp_zh(n)}{c * 100:.0f}%" for n, c in poor)
        return insufficient(
            reason="occlusion",
            required=f"关键点可见率 ≥ {MIN_KP_COVERAGE * 100:.0f}%",
            actual=detail,
            impact=(
                f"{spec.name_zh}依赖这些点，而它们在大部分帧上没被检测到。"
                f"用少数几帧算出来的结果不能代表这次跑动。"
            ),
            suggestion=(
                "检查拍摄时是否有遮挡（其他队员、器材、看台立柱）。"
                "运镜时尽量让运动员保持在画面中央，"
                "靠边时透视变形大，关键点也更难定位。"
            ),
        )

    # ---- 参考尺度 ----
    if spec.needs_scale and ctx.scale.method == "none":
        return insufficient(
            reason="no_reference_scale",
            required="画面中有已知尺寸的参照物，或提供准确身高",
            actual="两者都没有",
            impact=(
                f"{spec.name_zh}是把画面长度换算成实际距离得到的。"
                f"没有参照物就无法换算——"
                f"同一个画面里，近处的人和远处的人「同样长」"
                f"代表完全不同的实际距离。"
            ),
            suggestion=(
                "两个办法任选：① 拍摄时让跑道分道线入镜"
                "（分道宽 1.22 米是国标，最可靠）；"
                "② 在运动员档案里填写准确身高。"
            ),
        )

    return None


def _view_zh(v: str) -> str:
    return {"side": "侧面", "front": "正面", "back": "背面"}.get(v, v)


def _kp_zh(name: str) -> str:
    return {
        "head": "头", "neck": "颈", "shoulder_r": "右肩", "hip_r": "右髋",
        "knee_r": "右膝", "ankle_r": "右踝", "heel_r": "右跟", "toe_r": "右趾",
        "shoulder_l": "左肩", "hip_l": "左髋", "knee_l": "左膝",
        "ankle_l": "左踝", "heel_l": "左跟", "toe_l": "左趾",
        "pelvis_center": "骨盆中心", "shoulder_center": "肩中心",
    }.get(name, name)


def _fps_impact(spec: MetricSpec) -> str:
    """帧率不足对具体指标的影响。每个指标的后果不一样，不能套同一句话。"""
    if spec.metric_id in ("ground_contact_time", "flight_time", "duty_factor"):
        return (
            "短跑单脚触地只有 80–120 毫秒。帧率不够时，"
            "触地期内只有两三帧，时间分辨率不足以测准——"
            "误差会超过 30%。这不是精度问题，是物理上测不出来。"
        )
    if spec.metric_id in ("ankle_angle_touchdown", "com_height_oscillation",
                          "pelvis_rotation"):
        return (
            "这个指标要在极短的时间窗内取极值或变化率，"
            "帧率不足会直接削平曲线的峰谷，让数值系统性偏小。"
        )
    return "帧率不足会导致该指标的时间分辨率不够。"


# ---------------------------------------------------------------------------
# 逐帧序列构建
# ---------------------------------------------------------------------------

def _series(ctx: MetricContext, name: str) -> tuple[list[int], np.ndarray]:
    """取某个关键点的坐标序列。返回 (帧号列表, (N,2) 数组)。"""
    idxs: list[int] = []
    pts: list[tuple[float, float]] = []
    for pf in ctx.seq.frames:
        p = pf.point(name)
        if p is None:
            continue
        idxs.append(pf.frame_index)
        pts.append((p[0], p[1]))
    return idxs, np.asarray(pts, dtype=np.float64)


def _angle_series(
    ctx: MetricContext, a: str, b: str, c: str,
) -> tuple[list[int], np.ndarray]:
    """计算 ∠ABC 随帧变化的序列。三点都可见的帧才纳入。"""
    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        pa, pb, pc = pf.point(a), pf.point(b), pf.point(c)
        if pa is None or pb is None or pc is None:
            continue
        v = angle_at(pa[:2], pb[:2], pc[:2])
        if math.isnan(v):
            continue
        idxs.append(fi)
        vals.append(v)
    return idxs, np.asarray(vals, dtype=np.float64)


def _value_at(idxs: list[int], vals: np.ndarray, frame: int) -> float | None:
    """取指定帧（或最近帧）的值。"""
    if not idxs:
        return None
    j = int(np.argmin([abs(i - frame) for i in idxs]))
    return float(vals[j])


# ---------------------------------------------------------------------------
# 各指标
# ---------------------------------------------------------------------------

def metric_trunk_lean(ctx: MetricContext) -> MetricResult:
    """
    躯干前倾角。躯干线与竖直方向的夹角，正值表示前倾。

    ⚠️ 这个指标是**唯一一个需要按相位给不同标准值**的指标：
       加速段前倾 45–60° 是正确的，
       途中跑前倾 5–15° 才是正确的，超过 20° 就是错误。
       同一个数值在不同相位含义完全相反。
       所以本函数按相位分别输出。
    """
    spec = METRIC_SPECS["trunk_lean"]

    problem = _check_preconditions(
        spec, ctx, ("neck", "pelvis_center", "hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    idxs, _ = _series(ctx, "neck")
    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="躯干线可计算",
                actual="颈或骨盆中心在多数帧上不可见",
                impact="无法测量躯干前倾角。",
                suggestion="调整机位，确保运动员的整个躯干在画面内。",
            ),
        )

    # 逐帧躯干角
    by_index = ctx.frames_by_index()
    fidx: list[int] = []
    angs: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        neck = pf.point("neck")
        pelvis = pf.point("pelvis_center")
        if pelvis is None:
            hr, hl = pf.point("hip_r"), pf.point("hip_l")
            if hr and hl:
                pelvis = ((hr[0] + hl[0]) / 2, (hr[1] + hl[1]) / 2, 2)
        if neck is None or pelvis is None:
            continue
        a = segment_angle_from_vertical(neck[:2], pelvis[:2])
        if math.isnan(a):
            continue
        fidx.append(fi)
        angs.append(abs(a))

    if len(fidx) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="躯干线可计算",
                actual="颈或骨盆中心在多数帧上不可见",
                impact="无法测量躯干前倾角。",
                suggestion="调整机位，确保运动员的整个躯干在画面内。",
            ),
        )

    arr = smooth_series(np.asarray(angs, dtype=np.float64), window=5)

    # 按相位统计
    per_phase: dict[str, list[float]] = {}
    for fi, v in zip(fidx, arr):
        per_phase.setdefault(ctx.phase_of(fi), []).append(float(v))

    agg = {}
    for ph, vals in per_phase.items():
        if len(vals) >= 3:
            agg[ph] = {
                "mean": round(float(np.mean(vals)), 2),
                "sd": round(float(np.std(vals)), 2),
                "min": round(float(np.min(vals)), 2),
                "max": round(float(np.max(vals)), 2),
                "n": len(vals),
            }

    # 主值取整段的均值
    main_value = float(np.mean(arr))

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(main_value, 2),
        aggregate=agg or None,
        valid_frame_count=len(fidx),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.8,
        reliability_note=(
            "各相位的正常范围不同：加速段前倾 45–60° 是正确的，"
            "途中跑 5–15° 才是正确的。同一个角度值在不同相位含义相反，"
            "所以判定偏差时必须按相位分别对照。"
        ),
    )


def metric_step_frequency(ctx: MetricContext) -> MetricResult:
    """
    步频。单位为步/分钟。

    用**两个独立方法交叉验证**，一致才给值：

      方法 A（频域）  对髋中点高度序列做 FFT，取生理范围内的主频。
                      周期信号在频域里表现为尖锐的峰，比时域数峰稳健得多 ——
                      噪声会被摊到整个频谱上，不会聚成一个假的峰。
      方法 B（时域）  数支撑中期（髋高度局部最低点）的间隔，取中位数。

    为什么要两个：
        单一方法在低帧率、小目标、跟踪拍摄的素材上都可能出错，
        而且**错得看不出来** —— 538 步/分这种明显错误能被合理性检查拦下，
        但 320 步/分（真实 280）看起来完全正常。

        两个原理不同的方法若给出一致的答案，结论就可靠得多；
        若相差很大，说明至少有一个错了，此时宁可说"测不准"。

    合理性范围取 100–400 步/分：
        低于 100 接近步行，高于 400 超出人类神经肌肉的摆动能力。
    """
    spec = METRIC_SPECS["step_frequency"]

    problem = _check_preconditions(spec, ctx, ("hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    # ---- 取出髋中点的垂直位置序列 ----
    idxs, ys = _hip_height_series(ctx)
    if len(ys) < 12:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 12 帧可用的髋部高度数据",
                actual=f"只有 {len(ys)} 帧",
                impact="髋部高度是判断步态周期的基础，数据太少无法分析。",
                suggestion="上传更长的连续跑动片段（建议 3 秒以上）。",
            ),
        )

    # ---- 方法 A：频域 ----
    freq_spm, freq_snr = _cadence_from_spectrum(ys, ctx.fps)

    # ---- 方法 B：时域（沿用支撑中期间隔）----
    time_spm = _cadence_from_events(ctx)

    # ---- 交叉验证 ----
    if freq_spm is None and time_spm is None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="可识别的步态周期",
                actual="频域与时域两种方法都未能得到合理结果",
                impact=(
                    "两种独立方法都没能识别出步态周期，"
                    "说明髋部高度的变化里没有稳定的周期成分 —— "
                    "可能是关键点在帧间跳变，或素材里没有连续跑动。"
                ),
                suggestion=_cadence_advice(ctx),
            ),
        )

    if freq_spm is not None and time_spm is not None:
        diff = abs(freq_spm - time_spm) / max(freq_spm, time_spm)
        if diff > 0.15:
            return MetricResult(
                metric_id=spec.metric_id,
                insufficient=insufficient(
                    reason="implausible_value",
                    required="两种独立方法的结果相差 ≤15%",
                    actual=(
                        f"频域法得 {freq_spm:.0f} 步/分，"
                        f"时域法得 {time_spm:.0f} 步/分，"
                        f"相差 {diff * 100:.0f}%"
                    ),
                    impact=(
                        "两种原理不同的方法给出差距很大的答案，"
                        "说明至少有一个是错的，而无法判断是哪一个。"
                        "这种情况下给出具体数值会误导训练决策。"
                    ),
                    suggestion=_cadence_advice(ctx),
                ),
            )
        value = (freq_spm + time_spm) / 2
        agreement = 1.0 - diff
        note = (
            f"频域法 {freq_spm:.0f} 步/分、时域法 {time_spm:.0f} 步/分，"
            f"两者相差 {diff * 100:.0f}%，取均值。"
        )
    elif freq_spm is not None:
        value = freq_spm
        agreement = 0.6
        note = (
            f"仅频域法给出结果（{freq_spm:.0f} 步/分），"
            f"时域法未能检出足够的支撑中期。"
        )
    else:
        value = time_spm  # type: ignore[assignment]
        agreement = 0.6
        note = (
            f"仅时域法给出结果（{time_spm:.0f} 步/分），"
            f"频域法未找到显著的主频。"
        )

    # ---- 最终合理性检查（两个方法都已各自检查过，这里是兜底）----
    if not (100 <= value <= 400):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="步频落在 100–400 步/分（人类生理范围）",
                actual=f"推算得 {value:.0f} 步/分",
                impact="超出人类可能的范围，结果不可用。",
                suggestion=_cadence_advice(ctx),
            ),
        )

    confidence = round(min(0.9, 0.45 + agreement * 0.45 + freq_snr * 0.1), 2)

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(value), 1),
        aggregate=aggregate_block(
            n=len(ctx.events.midstances) if ctx.events.midstances else 1,
            mean=float(value),
        ),
        valid_frame_count=len(ys),
        total_frame_count=len(ctx.seq.frames),
        confidence=confidence,
        reliability_note=note,
    )


def _hip_height_series(ctx: MetricContext) -> tuple[list[int], np.ndarray]:
    """取髋中点的垂直位置序列（y 向下，数值越大越低）。"""
    idxs: list[int] = []
    ys: list[float] = []
    for pf in ctx.seq.frames:
        p = pf.point("pelvis_center")
        if p is None:
            hr, hl = pf.point("hip_r"), pf.point("hip_l")
            if hr and hl:
                p = ((hr[0] + hl[0]) / 2, (hr[1] + hl[1]) / 2, 2)
        if p is None:
            continue
        idxs.append(pf.frame_index)
        ys.append(p[1])
    return idxs, np.asarray(ys, dtype=np.float64)


def _cadence_from_spectrum(
    ys: np.ndarray,
    fps: float,
    lo_spm: float = 100.0,
    hi_spm: float = 400.0,
) -> tuple[float | None, float]:
    """
    频域法求步频。

    做法：去趋势 -> 加窗 -> FFT -> 在生理范围内找主频。

    为什么要去趋势：髋高度里含有整体的上升/下降趋势（起跑时身体逐渐抬起），
    这个低频分量会污染频谱，让主频偏移。

    为什么要加窗：信号两端不连续会在频谱里产生旁瓣，
    可能盖过真实的主频峰。Hann 窗能把旁瓣压下去。

    返回 (步频, 信噪比)。信噪比 = 主频峰值 / 频带内中位幅度，
    用来判断这个峰是否显著。
    """
    n = len(ys)
    if n < 12 or fps <= 0:
        return None, 0.0

    # 去趋势：减去线性拟合
    t = np.arange(n, dtype=np.float64)
    coef = np.polyfit(t, ys, 1)
    detrended = ys - np.polyval(coef, t)

    # 去均值 + 加 Hann 窗
    detrended = detrended - np.mean(detrended)
    window = np.hanning(n)
    windowed = detrended * window

    # 频谱
    spec = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)

    # 生理范围内的频带（Hz）
    lo_hz = lo_spm / 60.0
    hi_hz = hi_spm / 60.0
    band = (freqs >= lo_hz) & (freqs <= hi_hz)

    if not np.any(band):
        return None, 0.0
    if n / fps < 1.5:
        # 时长不足 1.5 秒时，频率分辨率太差（最低可分辨频率约 0.67 Hz），
        # 无法可靠区分步频的候选值
        return None, 0.0

    band_spec = spec[band]
    band_freqs = freqs[band]
    if len(band_spec) < 2:
        return None, 0.0

    peak_i = int(np.argmax(band_spec))
    peak_hz = float(band_freqs[peak_i])
    peak_amp = float(band_spec[peak_i])

    # 信噪比：峰值与频带内中位幅度之比
    median_amp = float(np.median(band_spec))
    snr = peak_amp / median_amp if median_amp > 1e-12 else 0.0

    # 抛物线插值提高频率估计精度。
    # 不加这一步时，主频会被量化到离散的频率格点上，
    # 在短序列上误差可达 ±10 步/分。
    if 0 < peak_i < len(band_spec) - 1:
        y0, y1, y2 = (band_spec[peak_i - 1], band_spec[peak_i],
                      band_spec[peak_i + 1])
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-12:
            delta = 0.5 * (y0 - y2) / denom
            delta = float(np.clip(delta, -0.5, 0.5))
            bin_width = float(band_freqs[1] - band_freqs[0])
            peak_hz += delta * bin_width

    if snr < 1.5:
        # 峰不够显著。宁可说测不到，也不要报一个被噪声主导的频率。
        return None, snr

    return peak_hz * 60.0, snr


def _cadence_from_events(ctx: MetricContext) -> float | None:
    """时域法求步频：由支撑中期的间隔取中位数。"""
    ms = ctx.events.midstances
    if len(ms) < 4:
        return None

    intervals = [(b - a) / ctx.fps * 1000.0 for a, b in zip(ms, ms[1:])]
    intervals = [v for v in intervals if v > 0]
    if len(intervals) < 3:
        return None

    # 用中位数抗离群值；但先剔除明显异常的长间隔（如中途停顿）
    med = float(np.median(intervals))
    kept = [v for v in intervals if 0.4 * med <= v <= 2.5 * med]
    if len(kept) < 3:
        return None

    final_med = float(np.median(kept))
    if final_med <= 1:
        return None

    spm = 60_000.0 / final_med
    return spm if 100 <= spm <= 400 else None


def _cadence_advice(ctx: MetricContext) -> str:
    """
    根据实际条件给出针对性的补齐建议。

    这一点很重要：泛泛地说"检查素材质量"没有用。
    真正的原因是**帧率太低导致髋部高度曲线采样不足**，
    教练需要知道的是"下次用慢动作模式拍"。
    """
    if ctx.fps < 120:
        return (
            f"当前素材 {ctx.fps:.0f} fps。步频由髋部高度曲线的周期推算，"
            f"帧率越低，一个步态周期内的采样点越少，"
            f"曲线的峰谷就越容易被削平、位置漂移，"
            f"导致周期识别失败。"
            f"建议用手机「慢动作」模式（120 或 240 fps）重拍，"
            f"并把原视频直接上传，不要用剪辑软件导出。"
        )
    return (
        "检查素材中运动员是否全程完整、无遮挡地处于画面内，"
        "并确保包含 3 秒以上连续的跑动（不要有停顿或变速）。"
    )


def metric_knee_angle_touchdown(ctx: MetricContext) -> MetricResult:
    """
    着地瞬间的膝角。

    着地时刻由触地事件给出，而**触地事件依赖足部关键点**，
    本项目的足部点是几何推导的。所以这个指标即使算出来，
    也要标注可靠性下降。
    """
    spec = METRIC_SPECS["knee_angle_touchdown"]

    problem = _check_preconditions(
        spec, ctx, ("hip_r", "knee_r", "ankle_r"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    tds = ctx.events.touchdowns
    if not tds:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="至少一次可判定的着地事件",
                actual="未检出着地时刻",
                impact=(
                    "着地时膝角是**在着地那一瞬间**取值，"
                    "没有着地时刻就无法确定取哪一帧的值。"
                ),
                suggestion=(
                    "确保运动员的脚部始终在画面内且未被遮挡。"
                    "侧面拍摄时让分道线入画有助于判断足部与地面的接触。"
                ),
            ),
        )

    idxs, angs = _angle_series(ctx, "hip_r", "knee_r", "ankle_r")
    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="右腿三点可见",
                actual="髋/膝/踝在多数帧上不可见",
                impact="无法计算膝角。",
                suggestion="调整机位，让近侧腿完整入镜。",
            ),
        )

    vals = [
        v for td in tds
        if (v := _value_at(idxs, angs, td)) is not None
    ]
    if not vals:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="着地帧上与膝角序列对齐",
                actual="着地帧落在膝角序列的有效范围之外",
                impact="无法取值。",
                suggestion="延长素材或检查关键点连续性。",
            ),
        )

    # 触地事件依赖推导的足部点，可靠性必须下调
    derived = ctx.seq.derived_ratio() > 0.5
    note = (
        f"由 {len(vals)} 次着地事件取值，均值 {np.mean(vals):.1f}°。"
    )
    if derived:
        note += (
            "⚠️ 着地时刻由几何推导的足部点判定，非实测——"
            "该指标的**取值时刻**本身存在不确定性，"
            "数值仅供趋势参考，不足以支撑精确的技术诊断。"
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(vals)), 1),
        aggregate=aggregate_block(
            n=len(vals),
            mean=float(np.mean(vals)),
            sd=float(np.std(vals)),
            min_value=float(np.min(vals)),
            max_value=float(np.max(vals)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.45 if derived else 0.75,
        reliable=not derived,
        reliability_note=note,
    )


def metric_step_length_relative(ctx: MetricContext) -> MetricResult:
    """
    相对步长：步长 ÷ 身高。

    用身长归一化后可以跨身高比较 —— 这是它相对绝对步长的优势。

    实现方式：由相邻两次支撑中期之间骨盆中心的**水平位移**推算。
    注意这在跟踪拍摄下不成立（镜头在动，位移里混入了镜头运动）——
    所以当检测到 strong_pan 时该指标判为数据不足。
    """
    spec = METRIC_SPECS["step_length_relative"]

    problem = _check_preconditions(
        spec, ctx, ("pelvis_center", "hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    if ctx.athlete_height_cm is None or ctx.athlete_height_cm <= 0:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="no_athlete_height",
                required="运动员身高",
                actual="档案中未填写",
                impact=(
                    "相对步长是步长除以身高得到的比值。"
                    "没有身高就只能给绝对步长，而绝对步长无法跨身高比较。"
                ),
                suggestion="在「运动员」页编辑档案，填上身高。",
            ),
        )

    ms = ctx.events.midstances
    if len(ms) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 个步态周期",
                actual=f"检出 {len(ms)} 个支撑中期",
                impact="步长由相邻两步之间的距离推算，至少需要两步。",
                suggestion="上传更长的连续跑动片段。",
            ),
        )

    # 骨盆中心的水平位置
    by_index = ctx.frames_by_index()
    pos: dict[int, float] = {}
    for fi, pf in by_index.items():
        p = pf.point("pelvis_center")
        if p is not None:
            pos[fi] = p[0]

    if len(pos) < len(ms):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="骨盆中心在全部步态周期内可见",
                actual=f"仅 {len(pos)} 帧可用",
                impact="无法追踪跨步的水平位移。",
                suggestion="调整机位，让运动员全程保持在画面中央。",
            ),
        )

    xs = [(fi, pos[fi]) for fi in sorted(pos)]
    arr = smooth_series(np.asarray([v for _, v in xs]), window=7)

    # 每一步的水平位移（归一化画面宽度）
    steps: list[float] = []
    for a, b in zip(ms, ms[1:]):
        ia = min(range(len(xs)), key=lambda i: abs(xs[i][0] - a))
        ib = min(range(len(xs)), key=lambda i: abs(xs[i][0] - b))
        if ib <= ia:
            continue
        steps.append(abs(float(arr[ib] - arr[ia])))

    if not steps:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="有效的跨步位移",
                actual="步态周期之间没有可用的位移",
                impact="无法计算步长。",
                suggestion="检查素材中运动员是否持续向同一方向移动。",
            ),
        )

    # 换算出实际距离需要参考尺度
    if ctx.scale.per_frame:
        ppm = float(np.median(list(ctx.scale.per_frame.values())))
    elif ctx.scale.median_pixels_per_meter:
        ppm = ctx.scale.median_pixels_per_meter
    else:
        ppm = float("nan")

    if math.isnan(ppm) or ppm <= 1e-9:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="no_reference_scale",
                required="可靠的参考尺度",
                actual="尺度估计为空",
                impact="无法把画面长度换算成实际距离。",
                suggestion="让分道线入镜，或在档案中填写身高。",
            ),
        )

    mean_norm = float(np.median(steps))
    step_m = mean_norm / ppm
    height_m = ctx.athlete_height_cm / 100.0
    ratio = step_m / height_m

    # 合理性检查：相对步长通常在 0.6–1.6 之间。超出说明尺度或事件有误。
    if not (0.3 <= ratio <= 2.5):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="相对步长落在 0.3–2.5（生理范围）",
                actual=f"推算得 {ratio:.2f}",
                impact=(
                    "这个数值超出合理范围，说明参考尺度或步态周期检测有误。"
                ),
                suggestion=(
                    "检查运动员身高是否填对；"
                    "若画面中有分道线，系统会优先用它做尺度，精度更高。"
                ),
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(ratio, 3),
        aggregate=aggregate_block(
            n=len(steps),
            mean=step_m,
            sd=float(np.std(steps)) / ppm,
            min_value=float(np.min(steps)) / ppm,
            max_value=float(np.max(steps)) / ppm,
        ),
        valid_frame_count=len(pos),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.7 if ctx.scale.method == "lane_line" else 0.5,
        reliability_note=(
            f"尺度来源：{ctx.scale.method}（{ctx.scale.method} 的说明见 "
            f"reference_scale 模块）；"
            f"由 {len(steps)} 步的中位水平位移推算，"
            f"步长中位数 {step_m:.3f} m。"
        ),
    )


def metric_ground_contact_time(ctx: MetricContext) -> MetricResult:
    """
    触地时间。

    ⚠️ 这个指标在本项目当前的模型条件下**多数情况会判为数据不足**，
    这是刻意的，不是缺陷。

    原因有两层：
      1. 帧率：需要 ≥120 fps。30 fps 下触地期内只有 2–4 帧。
      2. 足部点：触地时刻依赖脚跟/脚尖，而它们由几何推导，
         精度不足 —— 即使帧率够，时刻判定也不可靠。
    """
    spec = METRIC_SPECS["ground_contact_time"]

    problem = _check_preconditions(
        spec, ctx, ("ankle_r", "heel_r", "toe_r"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    # 第二层检查：足部点是否为推导值
    derived_ratio = ctx.seq.derived_ratio()
    if derived_ratio > 0.5 and not ctx.seq.__dict__.get("_real_feet"):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="contact_timing_unreliable",
                required="实测的脚跟/脚尖关键点",
                actual=f"{derived_ratio * 100:.0f}% 的帧上足部点为几何推导",
                impact=(
                    "触地时间要求把着地时刻定位到毫秒级。"
                    "而当前的足部点是由踝关节与小腿朝向推算出来的——"
                    "真实的足部姿态在着地期与蹬离期差别很大（踝关节跖屈可达 120°），"
                    "用固定几何假设必然在**最关键的触地瞬间**产生最大误差。"
                    "强行给一个数字，它可能差 30% 以上，而报告上看不出来。"
                ),
                suggestion=(
                    "两条路：① 换用带足部关键点的姿态模型"
                    "（本项目正在做的自训练模型会包含脚跟/脚尖）；"
                    "② 先用现有的角度类指标做技术诊断——"
                    "膝角、胫骨角、躯干前倾不依赖足部点，当前精度可用。"
                ),
            ),
        )

    # 真实足部点可用时的计算路径
    tds = ctx.events.touchdowns
    tos = ctx.events.toe_offs
    if len(tds) < 2 or len(tos) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 次完整的触地—离地",
                actual=f"{len(tds)} 次触地、{len(tos)} 次离地",
                impact="样本太少，单次检测误差会被放大。",
                suggestion="上传包含 3 秒以上连续跑动的片段。",
            ),
        )

    durations: list[float] = []
    for td in tds:
        later = [t for t in tos if t > td]
        if later:
            durations.append((later[0] - td) / ctx.fps * 1000.0)

    if len(durations) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 次完整的触地—离地配对",
                actual=f"{len(durations)} 次配对成功",
                impact="无法给出稳定的均值。",
                suggestion="延长素材或检查触地/离地检测的连续性。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(durations)), 1),
        aggregate=aggregate_block(
            n=len(durations),
            mean=float(np.mean(durations)),
            sd=float(np.std(durations)),
            min_value=float(np.min(durations)),
            max_value=float(np.max(durations)),
        ),
        valid_frame_count=len(ctx.seq.frames),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.7,
    )


def metric_flight_time(ctx: MetricContext) -> MetricResult:
    """腾空时间。前提条件与触地时间相同。"""
    spec = METRIC_SPECS["flight_time"]

    problem = _check_preconditions(
        spec, ctx, ("ankle_r", "heel_r", "toe_r"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    gct = metric_ground_contact_time(ctx)
    if gct.insufficient is not None:
        # 触地时间算不了，腾空时间也一定算不了 —— 它们依赖同一套事件
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=gct.insufficient,
        )

    tds = ctx.events.touchdowns
    tos = ctx.events.toe_offs
    durations: list[float] = []
    for to in tos:
        later = [t for t in tds if t > to]
        if later:
            durations.append((later[0] - to) / ctx.fps * 1000.0)

    if len(durations) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 次完整的离地—触地配对",
                actual=f"{len(durations)} 次配对成功",
                impact="无法给出稳定的均值。",
                suggestion="延长素材或检查事件检测的连续性。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(durations)), 1),
        aggregate=aggregate_block(
            n=len(durations),
            mean=float(np.mean(durations)),
            sd=float(np.std(durations)),
            min_value=float(np.min(durations)),
            max_value=float(np.max(durations)),
        ),
        valid_frame_count=len(ctx.seq.frames),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.7,
    )


def metric_duty_factor(ctx: MetricContext) -> MetricResult:
    """占空比 = 触地时间 ÷ 步态周期。"""
    spec = METRIC_SPECS["duty_factor"]

    problem = _check_preconditions(spec, ctx, ("ankle_r",))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    gct = metric_ground_contact_time(ctx)
    if gct.insufficient is not None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason=gct.insufficient["reason"],
                required="触地时间与步态周期都可测",
                actual=gct.insufficient["actual"],
                impact=(
                    "占空比是触地时间除以步态周期。"
                    "分子测不准，比值就没有意义。"
                ),
                suggestion=gct.insufficient["suggestion"],
            ),
        )

    freq = metric_step_frequency(ctx)
    if freq.insufficient is not None or freq.value is None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="可测的步频与触地时间",
                actual="步频无法计算",
                impact="占空比需要步态周期作为分母。",
                suggestion="上传更长的连续跑动片段。",
            ),
        )

    cycle_ms = 60_000.0 / float(freq.value)
    duty = float(gct.value) / cycle_ms

    if not (0.05 <= duty <= 0.9):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="占空比落在 0.05–0.9",
                actual=f"推算得 {duty:.3f}",
                impact="超出合理范围，说明触地时间或步频有误。",
                suggestion="检查素材质量与事件检测的连续性。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(duty, 3),
        aggregate=aggregate_block(n=1, mean=duty),
        confidence=0.6,
    )


# ---------------------------------------------------------------------------
# 侧面 · 事件帧关节角度
#
# 这组指标的共同特点：**取值时刻由事件决定**，而事件本身可能不可靠。
# 所以每个函数都要检查两件事：
#   1. 事件是否检出了
#   2. 事件时刻的判定是否可靠（当前依赖几何推导的足部点）
# 第一件不满足 -> 数据不足；第二件不满足 -> 给值但标低置信。
# ---------------------------------------------------------------------------

def _event_angle_metric(
    ctx: MetricContext,
    metric_id: str,
    required_kps: tuple[str, str, str],
    events: list[int],
    event_label: str,
    event_note: str,
    angle_fn=None,
) -> MetricResult:
    """
    事件帧取角度的通用实现。

    三个指标（胫骨角、支撑中期膝角、离地髋角）的结构完全一样，
    差别只在取哪三个点、在什么事件上取值。
    抽出来统一处理，避免三份几乎相同的代码各自演化出不一致的行为。

    angle_fn 为 None 时用标准的三点夹角；传入自定义函数可算"相对竖直"的角。
    """
    spec = METRIC_SPECS[metric_id]

    problem = _check_preconditions(spec, ctx, required_kps)
    if problem:
        return MetricResult(metric_id=metric_id, insufficient=problem)

    if not events:
        return MetricResult(
            metric_id=metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required=f"至少一次可判定的{event_label}",
                actual=f"未检出{event_label}",
                impact=(
                    f"{spec.name_zh}是在{event_label}那一瞬间取值，"
                    f"没有该事件就无法确定取哪一帧的值。"
                ),
                suggestion=event_note,
            ),
        )

    a, b, c = required_kps
    idxs, vals = (
        _angle_series(ctx, a, b, c) if angle_fn is None
        else _segment_angle_series(ctx, a, b)
    )

    if len(idxs) < 5:
        return MetricResult(
            metric_id=metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required=f"{_kp_zh(a)}、{_kp_zh(b)}、{_kp_zh(c)} 可见",
                actual="这些点在大部帧上不可见",
                impact=f"无法计算{spec.name_zh}。",
                suggestion="调整机位，确保近侧腿完整入镜且不被躯干遮挡。",
            ),
        )

    picked = [v for ev in events if (v := _value_at(idxs, vals, ev)) is not None]
    if not picked:
        return MetricResult(
            metric_id=metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required=f"{event_label}帧与角度序列对齐",
                actual=f"{event_label}帧落在角度序列的有效范围之外",
                impact="无法取值。",
                suggestion="延长素材或检查关键点的连续性。",
            ),
        )

    derived = ctx.seq.derived_ratio() > 0.5
    note = (
        f"由 {len(picked)} 次{event_label}取值，"
        f"均值 {np.mean(picked):.1f}°、标准差 {np.std(picked):.1f}°。"
    )
    if derived and metric_id in ("shank_angle_touchdown",
                                 "knee_angle_midstance",
                                 "hip_angle_toeoff",
                                 "ankle_angle_touchdown"):
        note += (
            f"⚠️ {event_label}时刻由几何推导的足部点判定，非实测 —— "
            f"该指标的**取值时刻**存在不确定性，数值仅供趋势参考。"
        )

    return MetricResult(
        metric_id=metric_id,
        value=round(float(np.mean(picked)), 1),
        aggregate=aggregate_block(
            n=len(picked),
            mean=float(np.mean(picked)),
            sd=float(np.std(picked)),
            min_value=float(np.min(picked)),
            max_value=float(np.max(picked)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.45 if derived else 0.75,
        reliable=not derived,
        reliability_note=note,
    )


def _segment_angle_series(
    ctx: MetricContext,
    p_top: str,
    p_bottom: str,
) -> tuple[list[int], np.ndarray]:
    """取"线段相对竖直方向夹角"的逐帧序列，返回绝对值。"""
    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        pt, pb = pf.point(p_top), pf.point(p_bottom)
        if pt is None or pb is None:
            continue
        v = segment_angle_from_vertical(pt[:2], pb[:2])
        if math.isnan(v):
            continue
        idxs.append(fi)
        vals.append(abs(v))
    return idxs, np.asarray(vals, dtype=np.float64)


def metric_shank_angle_touchdown(ctx: MetricContext) -> MetricResult:
    """
    着地时胫骨角：着地瞬间小腿相对竖直方向的夹角。

    为什么这个指标重要：胫骨角偏大意味着着地点落在重心前方更远处，
    地面反作用力会产生向后的制动分量 —— 跑得越快，这个损失越大。
    """
    return _event_angle_metric(
        ctx, "shank_angle_touchdown",
        # 胫骨角是"线段相对竖直"的角，只需要膝与踝两点。
        # 第三个参数（angle_fn）为 "segment" 时前两个才是真正用到的点，
        # 但为避免调用约定混乱，仍传三个：第三个重复第二个。
        ("knee_r", "ankle_r", "ankle_r"),
        ctx.events.touchdowns, "着地",
        "确保运动员的脚部始终在画面内且未被遮挡。"
        "侧面拍摄时让分道线入画有助于判断足部与地面的接触。",
        angle_fn="segment",
    )


def metric_knee_angle_midstance(ctx: MetricContext) -> MetricResult:
    """
    支撑中期膝角。

    支撑中期是身体被压缩最大的时刻。膝角过小（过度屈曲）说明缓冲过多、
    蹬伸不充分；过大（几乎伸直）说明缺乏缓冲，冲击直接上传。
    """
    return _event_angle_metric(
        ctx, "knee_angle_midstance",
        ("hip_r", "knee_r", "ankle_r"),
        ctx.events.midstances, "支撑中期",
        "支撑中期由髋部高度曲线的局部最低点判定，不依赖足部点。"
        "若未检出，说明髋部高度曲线没有明显的周期成分 —— "
        "通常是帧率过低或运动员在画面中太小。",
    )


def metric_hip_angle_toeoff(ctx: MetricContext) -> MetricResult:
    """
    离地时髋角：离地瞬间躯干与大腿的夹角。

    反映蹬伸结束后髋关节的伸展程度。偏小说明髋伸展不充分，
    推进力没有完全释放。
    """
    return _event_angle_metric(
        ctx, "hip_angle_toeoff",
        ("shoulder_r", "hip_r", "knee_r"),
        ctx.events.toe_offs, "离地",
        "离地时刻由踝关节高度判定，依赖足部关键点。"
        "确保脚部全程在画面内。",
    )


def metric_ankle_angle_touchdown(ctx: MetricContext) -> MetricResult:
    """
    着地时踝角：着地瞬间小腿与足部的夹角。

    ⚠️ 这个指标对足部点的精度要求最高 —— 它本身就是由脚跟/脚尖
    与踝关节的关系定义的。本项目的足部点是几何推导的，
    所以即使给出数值也要标为低置信。
    """
    return _event_angle_metric(
        ctx, "ankle_angle_touchdown",
        ("knee_r", "ankle_r", "toe_r"),
        ctx.events.touchdowns, "着地",
        "该指标直接依赖脚尖关键点。要精确测量必须使用"
        "带足部关键点的姿态模型。",
    )


# ---------------------------------------------------------------------------
# 侧面 · 逐帧统计
# ---------------------------------------------------------------------------

def metric_thigh_swing_range(ctx: MetricContext) -> MetricResult:
    """
    大腿摆动幅度：摆动期内大腿相对竖直方向夹角的最大变化量。

    "摆动期"定义为同侧离地到下次同侧着地。大腿前后摆动的幅度
    反映髋关节的活动范围与摆腿的充分程度。

    若事件检测不可用，退回用整段的最大最小差值 —— 但那会
    把支撑期也算进去，数值系统性偏大，所以必须在说明里讲清楚。
    """
    spec = METRIC_SPECS["thigh_swing_range"]

    problem = _check_preconditions(spec, ctx, ("hip_r", "knee_r"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    idxs, vals = _segment_angle_series(ctx, "hip_r", "knee_r")
    if len(idxs) < 10:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="髋、膝在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="摆动幅度需要连续的序列才能取到真实的极值。",
                suggestion="调整机位，确保近侧腿全程完整入镜。",
            ),
        )

    # 优先按摆动期切分
    tos = ctx.events.toe_offs
    tds = ctx.events.touchdowns
    swings: list[float] = []
    used_events = False

    for to in tos:
        later = [t for t in tds if t > to]
        if not later:
            continue
        td = later[0]
        seg = [v for i, v in zip(idxs, vals) if to <= i <= td]
        if len(seg) >= 3:
            swings.append(max(seg) - min(seg))
            used_events = True

    if swings:
        value = float(np.median(swings))
        note = (
            f"由 {len(swings)} 个摆动期（离地→下次着地）的幅度取中位数。"
            f"摆动期由足部事件切分，依赖几何推导的足部点，"
            f"因此**切分边界**存在不确定性。"
        )
        confidence = 0.5
    else:
        value = float(np.max(vals) - np.min(vals))
        note = (
            "未能按摆动期切分（足部事件不可用），"
            "改用整段的角度极差。"
            "⚠️ 这会**把支撑期也算进去**，数值比真实的摆动幅度偏大，"
            "只能用于纵向趋势对比，不可与文献值直接比较。"
        )
        confidence = 0.35

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(value, 1),
        aggregate=aggregate_block(
            n=len(swings) if swings else len(idxs),
            mean=value,
            sd=float(np.std(swings)) if len(swings) > 1 else None,
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=confidence,
        reliability_note=note,
    )


# ---------------------------------------------------------------------------
# 侧面 · 位移类
#
# 位移类指标有一个共同的前提：**跟踪拍摄会破坏它们**。
# 镜头在动时，画面里的位移等于运动员位移 + 镜头位移，
# 而单目视频无法把两者分开。
# 所以这组函数都要先检查镜头运动。
# ---------------------------------------------------------------------------

def _check_camera_motion_for_displacement(
    ctx: MetricContext,
    metric_id: str,
    metric_name: str,
) -> dict | None:
    """
    位移类指标的镜头运动检查。

    为什么要单独检查：姿态提取本身不受镜头运动影响（逐帧独立），
    但**位移**受影响 —— 镜头跟随会让画面里的"位移"混入镜头自身的移动。
    这是单目视觉的固有限制，不是实现问题。
    """
    if ctx.camera_motion_level == "strong_pan":
        return insufficient(
            reason="camera_motion",
            required="固定机位，或画面中有已知尺寸的静止参照物",
            actual=f"检测到明显的镜头跟随（平均位移 "
                   f"{ctx.camera_motion_shift:.1f} px/帧）",
            impact=(
                f"{metric_name}测的是运动员相对**地面**移动了多远。"
                f"镜头跟随时，画面里的位移等于运动员位移加上镜头位移 —— "
                f"而单目视频无法把这两者分开。"
                f"强行计算会得到一个既不是步长也不是别的什么的数字。"
            ),
            suggestion=(
                "把相机固定在跑道上，让运动员跑过画面（不要跟拍）。"
                "若必须跟拍，画面中需要一个静止的已知尺寸参照物"
                "（如分道线），但即便如此精度也会明显下降。"
            ),
        )
    return None


def metric_step_length(ctx: MetricContext) -> MetricResult:
    """
    步长：相邻两次着地之间，脚落点的水平距离（米）。

    需要参考尺度把画面长度换算成实际距离，所以标为 B 级可靠性。
    """
    spec = METRIC_SPECS["step_length"]

    problem = _check_preconditions(
        spec, ctx, ("pelvis_center", "ankle_r", "ankle_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    motion_problem = _check_camera_motion_for_displacement(
        ctx, spec.metric_id, spec.name_zh)
    if motion_problem:
        return MetricResult(metric_id=spec.metric_id,
                            insufficient=motion_problem)

    ppm = _resolve_pixels_per_meter(ctx)
    if ppm is None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="no_reference_scale",
                required="可靠的参考尺度",
                actual="尺度估计为空",
                impact="无法把画面长度换算成实际距离。",
                suggestion="让跑道分道线入镜（分道宽 1.22 米是国标）。",
            ),
        )

    # 用踝关节的水平位置在着地时刻的差值。
    # _series 返回的是 (N, 2) 的 x/y 数组，所以取水平分量要写 [i, 0]。
    idxs, xs = _series(ctx, "ankle_r")
    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="踝关节在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="无法定位着地点。",
                suggestion="调整机位，确保双脚全程在画面内。",
            ),
        )

    tds = ctx.events.touchdowns
    if len(tds) < 3:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 3 次着地",
                actual=f"检出 {len(tds)} 次",
                impact="步长由相邻着地点的距离推算，样本太少无法给出稳定值。",
                suggestion="上传包含 3 秒以上连续跑动的片段。",
            ),
        )

    steps = []
    for a, b in zip(tds, tds[1:]):
        ia = int(np.argmin([abs(i - a) for i in idxs]))
        ib = int(np.argmin([abs(i - b) for i in idxs]))
        steps.append(abs(float(xs[ib, 0] - xs[ia, 0])))

    if not steps:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="有效的着地点配对",
                actual="着地帧无法与踝关节序列对齐",
                impact="无法计算步长。",
                suggestion="检查关键点连续性，或延长素材。",
            ),
        )

    step_m = float(np.median(steps)) / ppm

    # 合理性检查。
    #
    # 下限取 0.4 m 而不是 0.8：**蹲踞式起跑的最初几步本来就短**
    # （0.4–0.6 m 是正常的）。最初定的 0.8 m 下限会把真实的起跑数据
    # 误判为"超出合理范围"—— 而这类误判比漏判更糟，
    # 因为它会让教练以为系统坏了。
    #
    # 上限 3.5 m：即便顶级短跑的步长也很少超过 2.8 m，
    # 超过 3.5 必然是尺度或事件检测出错。
    if not (0.4 <= step_m <= 3.5):
        hint = ""
        if step_m < 0.4:
            hint = (
                "若这是起跑最初几步，步长本身确实很短 —— "
                "但连 0.4 m 都不到，更可能是参考尺度偏小。"
            )
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="步长落在 0.4–3.5 m",
                actual=f"推算得 {step_m:.2f} m",
                impact=(
                    "超出合理范围，说明参考尺度或着地检测有误。"
                    + hint
                ),
                suggestion=(
                    "确认画面中的分道线是否被正确识别；"
                    "身高推算的尺度在躯干前倾明显时会偏大，"
                    "使步长偏小。"
                ),
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(step_m, 3),
        aggregate=aggregate_block(
            n=len(steps),
            mean=step_m,
            sd=float(np.std(steps)) / ppm,
            min_value=float(np.min(steps)) / ppm,
            max_value=float(np.max(steps)) / ppm,
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.7 if ctx.scale.method == "lane_line" else 0.45,
        reliability_note=(
            f"尺度来源：{ctx.scale.method}，由 {len(steps)} 步的中位距离推算。"
            f"{'分道线是画面中的固定参照物，不受运动员姿态影响。' if ctx.scale.method == 'lane_line' else '身高推算的尺度在躯干前倾明显时偏大，步长会因此偏小。'}"
        ),
    )


def metric_com_height_oscillation(ctx: MetricContext) -> MetricResult:
    """
    重心起伏：跑步过程中身体重心上下波动的幅度（米）。

    用骨盆中心的垂直位移近似重心 —— 这是常用做法，
    但要知道骨盆不等于重心：腿的摆动会改变真实重心位置。
    所以契约把它的可靠性定为 C 级（仅可用于趋势对比）。
    """
    spec = METRIC_SPECS["com_height_oscillation"]

    problem = _check_preconditions(
        spec, ctx, ("pelvis_center", "hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    motion_problem = _check_camera_motion_for_displacement(
        ctx, spec.metric_id, spec.name_zh)
    if motion_problem:
        # 重心起伏测的是**垂直**方向的变化，所以它的失效机制与步长不同：
        # 水平的镜头平移影响不大，真正致命的是镜头**俯仰**（上下转动）——
        # 那会让画面里的垂直位移混入镜头自身的转动量。
        # 这一点必须讲清楚，否则用户以为"只要水平跟拍就没问题"。
        motion_problem = dict(motion_problem)
        motion_problem["impact"] = [
            "镜头跟随时若伴随俯仰（镜头上下转动），画面里的垂直位移"
            "会混入镜头自身的转动量。单目视频无法把两者分开 —— "
            "算出来的「起伏」里有一部分其实来自相机在动。",
            "与步长不同：水平的镜头平移对这个指标影响较小，"
            "俯仰才是主要误差来源。",
        ]
        motion_problem["suggestion"] = (
            "把相机固定在三脚架上。若必须手持跟拍，"
            "尽量保持镜头只做水平移动、不要上下俯仰 —— "
            "但这仍会引入误差，精度不如固定机位。"
        )
        return MetricResult(metric_id=spec.metric_id,
                            insufficient=motion_problem)

    ppm = _resolve_pixels_per_meter(ctx)
    if ppm is None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="no_reference_scale",
                required="可靠的参考尺度",
                actual="尺度估计为空",
                impact="无法把画面里的高度变化换算成实际距离。",
                suggestion="让跑道分道线入镜，或在档案中填写身高。",
            ),
        )

    idxs, ys = _hip_height_series(ctx)
    if len(idxs) < 10:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="骨盆中心在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="重心起伏需要连续的垂直位置序列。",
                suggestion="调整机位，让躯干完整入镜。",
            ),
        )

    # 去趋势后再取极差：起跑阶段身体整体抬升的趋势
    # 会被误算成"起伏"，必须剔除。
    t = np.arange(len(ys), dtype=np.float64)
    coef = np.polyfit(t, ys, 1)
    detrended = ys - np.polyval(coef, t)

    oscillation_m = float(np.max(detrended) - np.min(detrended)) / ppm

    # 合理性检查：短跑重心起伏通常 3–10 cm
    if not (0.01 <= oscillation_m <= 0.25):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="重心起伏落在 1–25 cm",
                actual=f"推算得 {oscillation_m * 100:.1f} cm",
                impact="超出合理范围，说明参考尺度或骨盆关键点有误。",
                suggestion="确认分道线是否被正确识别；检查骨盆关键点是否稳定。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(oscillation_m, 4),
        aggregate=aggregate_block(
            n=len(idxs),
            mean=oscillation_m,
            min_value=float(np.min(detrended)) / ppm,
            max_value=float(np.max(detrended)) / ppm,
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.4,
        reliability_note=(
            f"用骨盆中心的垂直位移近似重心，已剔除整体抬升趋势。"
            f"尺度来源：{ctx.scale.method}。"
            f"⚠️ 骨盆不等于真实重心（腿部摆动会改变重心位置），"
            f"该方法学可靠性为 C 级 —— 只可用于同一个人不同时期的趋势对比，"
            f"不可与文献绝对值直接比较。"
        ),
    )


def _resolve_pixels_per_meter(ctx: MetricContext) -> float | None:
    """
    取一个代表性的像素/米值。

    逐帧尺度取中位数；只有全局尺度时直接用它。
    取不到返回 None —— 由调用方决定怎么报"数据不足"。
    """
    if ctx.scale.per_frame:
        val = float(np.median(list(ctx.scale.per_frame.values())))
        return val if val > 1e-9 else None
    if ctx.scale.median_pixels_per_meter:
        val = float(ctx.scale.median_pixels_per_meter)
        return val if val > 1e-9 else None
    return None


# ---------------------------------------------------------------------------
# 额状面（正面 / 背面视角）
#
# 关键前提：契约里的 `_r` / `_l` 指**运动员自身**的左右，不是画面左右
# （见 docs/01-术语与命名规范.md §4.2）。所以这些指标的计算本身
# **与视角无关** —— 拿到的坐标已经在运动员自身坐标系里了。
#
# 真正需要处理左右歧义的地方在**上游**：姿态模型从画面里检测关键点时，
# 正面与背面视角下画面左右与人体左右的关系是相反的。
# 那一步由 keypoint_map.resolve_side_convention() 负责，
# 这里不再重复处理 —— 重复处理会变成"换了两次等于没换"。
#
# 还有一个必须遵守的约定（docs/03 实现要点）：
#   额状面指标在**侧面视角下全部返回 insufficient_data**，
#   原因 view_mismatch。已由 _check_preconditions 的视角检查保证。
# ---------------------------------------------------------------------------

def _hip_width_series(ctx: MetricContext) -> tuple[list[int], np.ndarray]:
    """
    髋宽（左右髋的水平距离）逐帧序列。

    额状面指标的归一化基准：骨盆宽度反映个体体型，
    用它做分母可以跨身高比较。
    """
    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    widths: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        hr, hl = pf.point("hip_r"), pf.point("hip_l")
        if hr is None or hl is None:
            continue
        idxs.append(fi)
        widths.append(abs(hr[0] - hl[0]))
    return idxs, np.asarray(widths, dtype=np.float64)


def metric_pelvis_tilt(ctx: MetricContext) -> MetricResult:
    """
    骨盆侧倾：左右髋连线相对水平面的夹角。

    正值 = 右侧髋高于左侧。

    为什么重要：跑步是单腿支撑的连续交替动作，支撑期骨盆需要保持
    相对水平，让摆动腿有足够的空间完成动作。侧倾过大会让摆动腿
    "掉"下去，代偿性地增加膝外翻与髂胫束的负担。
    """
    spec = METRIC_SPECS["pelvis_tilt"]

    problem = _check_preconditions(spec, ctx, ("hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        hr, hl = pf.point("hip_r"), pf.point("hip_l")
        if hr is None or hl is None:
            continue
        dx = hl[0] - hr[0]          # 从左指向右的横向分量
        dy = hl[1] - hr[1]
        if abs(dx) < 1e-6:
            continue
        # 右侧髋高于左侧 -> dy 为正（y 向下，左髋更低）
        ang = math.degrees(math.atan2(dy, abs(dx)))
        idxs.append(fi)
        vals.append(ang)

    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="左右髋在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="骨盆侧倾需要连续的骨盆姿态序列才能看出规律。",
                suggestion="正面或背面拍摄，确保整个骨盆区域不被手臂遮挡。",
            ),
        )

    arr = smooth_series(np.asarray(vals, dtype=np.float64), window=5)

    # 左右两侧分别统计：单腿支撑期骨盆本来就会倾向摆动腿一侧，
    # 只看整体均值会把两个方向的侧倾互相抵消。
    right_support = float(np.mean(arr[arr > 0])) if np.any(arr > 0) else 0.0
    left_support = float(np.mean(arr[arr < 0])) if np.any(arr < 0) else 0.0

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(arr)), 2),
        aggregate=aggregate_block(
            n=len(idxs),
            mean=float(np.mean(arr)),
            sd=float(np.std(arr)),
            min_value=float(np.min(arr)),
            max_value=float(np.max(arr)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.6,
        reliability_note=(
            f"正值表示右侧髋高于左侧。"
            f"右支撑期均值 {right_support:.1f}°、左支撑期均值 {left_support:.1f}°。"
            f"整体均值会把两个方向的侧倾互相抵消，"
            f"判断时请看分侧数值而不是总值。"
        ),
    )


def metric_pelvis_rotation(ctx: MetricContext) -> MetricResult:
    """
    骨盆旋转：骨盆绕纵轴转动的角度。

    原理：骨盆宽度在正面画面上的**投影**随旋转而缩短。
        投影宽 / 中位投影宽 = cos(旋转角)
    所以旋转角 = arccos(投影宽 / 中位投影宽)。

    ⚠️ 契约把它的可靠性定为 **C 级**（仅可用于趋势对比），原因：
        · 中位投影宽本身就是从这段素材里估的，不是真实骨盆宽 ——
          如果整段都在旋转，基准就是偏的
        · 跟踪拍摄带来的透视变化会被误读成旋转
        · 关键点抖动直接变成宽度抖动

    使用 arccos 还有一个固有问题：**它无法区分旋转的正负方向**
    （向前转和向后转给出同样的宽度）。所以本指标只能给出幅度，
    不给出方向。这一点必须在报告里讲清楚。
    """
    spec = METRIC_SPECS["pelvis_rotation"]

    problem = _check_preconditions(spec, ctx, ("hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    idxs, widths = _hip_width_series(ctx)
    if len(widths) < 10:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="左右髋在多数帧上可见",
                actual=f"仅 {len(widths)} 帧可用",
                impact="骨盆旋转由髋宽投影的变化推算，需要连续序列。",
                suggestion="正面或背面拍摄，确保骨盆区域全程清晰可见。",
            ),
        )

    median_w = float(np.median(widths))
    if median_w < 1e-6:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="可测的骨盆投影宽度",
                actual="髋宽中位数为 0",
                impact="左右髋关键点重合，说明检测有误。",
                suggestion="检查素材中骨盆区域是否被遮挡或裁剪。",
            ),
        )

    # 投影宽不能超过中位宽 —— 超过了说明基准估计偏小（如整段都在旋转）
    ratios = np.clip(widths / median_w, 0.0, 1.0)
    angles = np.degrees(np.arccos(ratios))

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(angles)), 2),
        aggregate=aggregate_block(
            n=len(idxs),
            mean=float(np.mean(angles)),
            sd=float(np.std(angles)),
            min_value=float(np.min(angles)),
            max_value=float(np.max(angles)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.3,
        reliability_note=(
            "骨盆旋转由髋宽投影的变化推算（arccos 关系）。"
            "⚠️ 两点局限："
            "① arccos 无法区分旋转方向 —— 本指标只给出幅度，不给出前后方向；"
            "② 中位投影宽是从本段素材估的基准，若整段都在旋转则基准偏小。"
            "该方法学可靠性为 C 级，仅可用于同一个人不同时期的趋势对比，"
            "不可与文献绝对值比较。"
        ),
    )


def metric_knee_valgus_touchdown(ctx: MetricContext) -> MetricResult:
    """
    着地时膝外翻（膝内扣）：膝关节在额状面上偏向身体中线的程度。

    正值 = 膝偏向身体中线**内侧**（内扣，knock-knee 方向）。

    为什么重要：膝内扣是跑者膝（髌股疼痛）与前交叉韧带损伤的
    主要风险因素之一。着地瞬间的冲击最大，此时的膝外翻角度
    比其它时刻更值得关注。

    符号判定：把髋→踝连线作为参考，看膝落在连线的哪一侧。
    用 cross product 定符号，比比较 x 坐标稳健 ——
    后者在腿侧向时会把左右搞混。
    """
    spec = METRIC_SPECS["knee_valgus_touchdown"]

    problem = _check_preconditions(
        spec, ctx, ("hip_r", "knee_r", "ankle_r"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    tds = ctx.events.touchdowns
    if not tds:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="至少一次可判定的着地事件",
                actual="未检出着地时刻",
                impact=(
                    "膝外翻是在着地瞬间取值 —— 那是冲击最大、"
                    "也是这个指标最有意义的时刻。"
                ),
                suggestion="正面或背面拍摄，确保双腿全程不被遮挡。",
            ),
        )

    idxs, vals = _knee_valgus_series(ctx)
    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="髋、膝、踝在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="无法计算膝外翻角。",
                suggestion="正面或背面拍摄，确保下肢完整入镜。",
            ),
        )

    picked = [v for td in tds if (v := _value_at(idxs, vals, td)) is not None]
    if not picked:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="着地帧与膝外翻序列对齐",
                actual="着地帧落在有效范围之外",
                impact="无法取值。",
                suggestion="延长素材或检查关键点连续性。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(picked)), 2),
        aggregate=aggregate_block(
            n=len(picked),
            mean=float(np.mean(picked)),
            sd=float(np.std(picked)),
            min_value=float(np.min(picked)),
            max_value=float(np.max(picked)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.5,
        reliability_note=(
            f"由 {len(picked)} 次着地取值，正值表示膝偏向身体中线内侧（内扣）。"
            f"着地时刻由几何推导的足部点判定，取值时刻存在不确定性。"
        ),
    )


def _knee_valgus_series(ctx: MetricContext) -> tuple[list[int], np.ndarray]:
    """
    膝外翻的逐帧序列。

    做法：算出髋→踝的参考线，取膝到该线的垂足，
    用膝相对参考线的偏移量与髋-踝距离算角度，用叉积定符号。

    右侧与左侧的"内侧"方向相反：
        右腿的内侧在画面的 -x 方向（身体中线在右边腿的左侧），
        左腿的内侧在 +x 方向。
    所以两侧要分别取符号，否则会把内扣和外展搞反 ——
    而这两者的训练处方完全相反。
    """
    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []

    for fi in sorted(by_index):
        pf = by_index[fi]
        hr, kr, ar = pf.point("hip_r"), pf.point("knee_r"), pf.point("ankle_r")
        hl, kl, al = pf.point("hip_l"), pf.point("knee_l"), pf.point("ankle_l")

        # 优先用右腿；右腿不可见时用左腿
        if hr and kr and ar:
            v = _valgus_angle(hr[:2], kr[:2], ar[:2], side="R")
        elif hl and kl and al:
            v = _valgus_angle(hl[:2], kl[:2], al[:2], side="L")
        else:
            continue

        if v is None or math.isnan(v):
            continue
        idxs.append(fi)
        vals.append(v)

    return idxs, np.asarray(vals, dtype=np.float64)


def _valgus_angle(
    hip: tuple[float, float],
    knee: tuple[float, float],
    ankle: tuple[float, float],
    side: str,
) -> float | None:
    """
    单侧的膝外翻角。

    几何：以髋→踝连线为参考轴，膝相对该轴的偏离。
    用叉积定符号，再按左右侧归一化到"正值 = 内扣"。

    叉积的符号只告诉你"在哪一侧"，不告诉你"是内侧还是外侧" ——
    那取决于这是左腿还是右腿。所以最后一步要按 side 翻转。
    """
    ax = ankle[0] - hip[0]
    ay = ankle[1] - hip[1]
    base = math.hypot(ax, ay)
    if base < 1e-9:
        return None

    # 膝到髋→踝直线的垂距
    kx = knee[0] - hip[0]
    ky = knee[1] - hip[1]
    cross = ax * ky - ay * kx
    perp = abs(cross) / base

    # 膝到垂足的距离（用于算角度）
    thigh = math.hypot(kx, ky)
    if thigh < 1e-9:
        return None

    # 偏移角：sin(θ) = 垂距 / 大腿长
    ratio = max(-1.0, min(1.0, perp / thigh))
    ang = math.degrees(math.asin(ratio))

    # 符号：右腿的内侧是 -x 方向（画面），左腿的内侧是 +x 方向。
    # 用叉积判断膝落在参考线的哪一侧，再按 side 归一化。
    inward = (cross < 0) if side == "R" else (cross > 0)
    return ang if inward else -ang


def metric_stance_width_relative(ctx: MetricContext) -> MetricResult:
    """
    相对支撑宽度：着地瞬间双脚的水平距离 ÷ 骨盆宽度中位数。

    用骨盆宽度做分母而不是身高：支撑宽度直接受骨盆宽度影响，
    用骨盆宽归一化能更干净地反映"步伐是宽还是窄"。

    支撑过窄（接近或小于骨盆宽）会让重心左右晃动加剧；
    过宽则增加髋关节的外展负担。
    """
    spec = METRIC_SPECS["stance_width_relative"]

    problem = _check_preconditions(
        spec, ctx, ("hip_r", "hip_l", "ankle_r", "ankle_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    tds = ctx.events.touchdowns
    if not tds:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="至少一次可判定的着地事件",
                actual="未检出着地时刻",
                impact="支撑宽度在着地瞬间测量，没有该时刻无法取值。",
                suggestion="正面或背面拍摄，确保双脚全程在画面内。",
            ),
        )

    idxs, widths = _hip_width_series(ctx)
    if len(widths) < 10:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="左右髋在多数帧上可见",
                actual=f"仅 {len(widths)} 帧可用",
                impact="骨盆宽度是归一化基准，取不到就无法跨人比较。",
                suggestion="正面或背面拍摄，确保骨盆区域可见。",
            ),
        )

    median_hip_w = float(np.median(widths))
    if median_hip_w < 1e-6:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="可测的骨盆宽度",
                actual="髋宽中位数为 0",
                impact="左右髋关键点重合。",
                suggestion="检查素材中骨盆区域是否被遮挡。",
            ),
        )

    by_index = ctx.frames_by_index()
    ratios: list[float] = []
    for td in tds:
        pf = by_index.get(td)
        if pf is None:
            # 着地帧可能因插值而不在序列里，找最近的
            near = min(by_index, key=lambda i: abs(i - td)) if by_index else None
            pf = by_index.get(near) if near is not None else None
        if pf is None:
            continue
        ar, al = pf.point("ankle_r"), pf.point("ankle_l")
        if ar is None or al is None:
            continue
        ratios.append(abs(ar[0] - al[0]) / median_hip_w)

    if len(ratios) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 次可测的着地",
                actual=f"仅 {len(ratios)} 次",
                impact="样本太少，无法给出稳定值。",
                suggestion="上传包含 3 秒以上连续跑动的片段。",
            ),
        )

    val = float(np.median(ratios))

    if not (0.1 <= val <= 3.0):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="相对支撑宽度落在 0.1–3.0",
                actual=f"推算得 {val:.2f}",
                impact="超出合理范围，说明骨盆宽度或踝关节位置检测有误。",
                suggestion="检查素材中双脚与骨盆是否全程可见。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(val, 3),
        aggregate=aggregate_block(
            n=len(ratios),
            mean=val,
            sd=float(np.std(ratios)),
            min_value=float(np.min(ratios)),
            max_value=float(np.max(ratios)),
        ),
        valid_frame_count=len(ratios),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.5,
        reliability_note=(
            f"由 {len(ratios)} 次着地的踝间距 ÷ 骨盆宽度中位数推算。"
            f"用骨盆宽度归一化的好处：不依赖参考尺度，"
            f"因此该指标在跟踪拍摄下仍可用。"
        ),
    )


def metric_trunk_lateral_lean(ctx: MetricContext) -> MetricResult:
    """
    躯干侧倾：肩中心相对骨盆中心的横向偏移角。

    正值 = 向右侧倾。

    为什么重要：躯干侧倾是骨盆控制不足的常见代偿 ——
    支撑期骨盆下沉时，上半身会向支撑侧倾斜以维持平衡。
    长期如此会让脊柱两侧受力不均。
    """
    spec = METRIC_SPECS["trunk_lateral_lean"]

    problem = _check_preconditions(
        spec, ctx, ("shoulder_center", "pelvis_center"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []

    for fi in sorted(by_index):
        pf = by_index[fi]
        sc = pf.point("shoulder_center")
        pc = pf.point("pelvis_center")
        # 退路：用左右肩/髋的中点，兼容契约里中线点缺省的情况
        if sc is None:
            sr, sl = pf.point("shoulder_r"), pf.point("shoulder_l")
            if sr and sl:
                sc = ((sr[0] + sl[0]) / 2, (sr[1] + sl[1]) / 2, 2)
        if pc is None:
            hr, hl = pf.point("hip_r"), pf.point("hip_l")
            if hr and hl:
                pc = ((hr[0] + hl[0]) / 2, (hr[1] + hl[1]) / 2, 2)
        if sc is None or pc is None:
            continue

        dx = sc[0] - pc[0]
        dy = pc[1] - sc[1]          # 肩到骨盆的垂直距离（向下为正）
        if abs(dy) < 1e-6:
            continue
        # 正值 = 肩相对骨盆偏向画面右侧
        ang = math.degrees(math.atan2(dx, abs(dy)))
        idxs.append(fi)
        vals.append(ang)

    if len(idxs) < 10:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="肩中心与骨盆中心在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="躯干侧倾需要连续的躯干姿态序列。",
                suggestion="正面或背面拍摄，确保整个躯干不被遮挡。",
            ),
        )

    arr = smooth_series(np.asarray(vals, dtype=np.float64), window=5)

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(float(np.mean(arr)), 2),
        aggregate=aggregate_block(
            n=len(idxs),
            mean=float(np.mean(arr)),
            sd=float(np.std(arr)),
            min_value=float(np.min(arr)),
            max_value=float(np.max(arr)),
        ),
        valid_frame_count=len(idxs),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.55,
        reliability_note=(
            "正值表示躯干向画面右侧倾斜。"
            "注意：正面与背面视角下「画面右」对应的身体侧是相反的 —— "
            "解读方向时需要结合拍摄视角（正面：画面右 = 运动员左侧）。"
        ),
    )


def metric_pelvis_drop_midstance(ctx: MetricContext) -> MetricResult:
    """
    支撑中期骨盆下沉（Trendelenburg 征象）：

        pelvis_drop_midstance = pelvis_tilt @ 支撑中期 − pelvis_tilt @ 着地

    正值 = 支撑侧髋关节下沉。

    机制：支撑腿单腿承重时，髋外展肌群（主要是臀中肌）负责把骨盆
    维持在水平位。若臀中肌力量不足，对侧骨盆会掉下去 ——
    这就是 Trendelenburg 征象，也是跑者髂胫束综合征的常见成因。

    这个指标是**差值**，不是绝对值：着地瞬间骨盆本来就有一定倾斜，
    减去它才能分离出"支撑期额外下沉"的那部分。
    """
    spec = METRIC_SPECS["pelvis_drop_midstance"]

    problem = _check_preconditions(spec, ctx, ("hip_r", "hip_l"))
    if problem:
        return MetricResult(metric_id=spec.metric_id, insufficient=problem)

    tds = ctx.events.touchdowns
    ms = ctx.events.midstances
    if not tds or not ms:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="missing_event",
                required="着地与支撑中期两类事件都可判定",
                actual=f"着地 {len(tds)} 次、支撑中期 {len(ms)} 次",
                impact=(
                    "骨盆下沉是「支撑中期相对着地的差值」，"
                    "缺少任一类事件都无法算出这个差值。"
                ),
                suggestion=(
                    "支撑中期由髋部高度曲线的极值判定，不依赖足部点 —— "
                    "若它未检出，通常是帧率过低或运动员在画面中太小。"
                ),
            ),
        )

    tilt = metric_pelvis_tilt(ctx)
    if tilt.insufficient is not None or tilt.value is None:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason=tilt.insufficient["reason"] if tilt.insufficient
                else "occlusion",
                required="可测的骨盆侧倾序列",
                actual="骨盆侧倾无法计算",
                impact="骨盆下沉是骨盆侧倾的差值，基础量测不出来就无法计算。",
                suggestion="正面或背面拍摄，确保骨盆区域全程可见。",
            ),
        )

    # 重建逐帧骨盆侧倾，才能在特定事件帧上取值
    by_index = ctx.frames_by_index()
    idxs: list[int] = []
    vals: list[float] = []
    for fi in sorted(by_index):
        pf = by_index[fi]
        hr, hl = pf.point("hip_r"), pf.point("hip_l")
        if hr is None or hl is None:
            continue
        dx = hl[0] - hr[0]
        dy = hl[1] - hr[1]
        if abs(dx) < 1e-6:
            continue
        idxs.append(fi)
        vals.append(math.degrees(math.atan2(dy, abs(dx))))

    if len(idxs) < 5:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="occlusion",
                required="左右髋在多数帧上可见",
                actual=f"仅 {len(idxs)} 帧可用",
                impact="无法在事件帧上取骨盆侧倾值。",
                suggestion="正面或背面拍摄，确保骨盆区域全程可见。",
            ),
        )

    arr = np.asarray(vals, dtype=np.float64)
    drops: list[float] = []
    for td in tds:
        # 找该次着地之后最近的一次支撑中期
        later = [m for m in ms if m > td]
        if not later:
            continue
        m = later[0]
        at_td = _value_at(idxs, arr, td)
        at_ms = _value_at(idxs, arr, m)
        if at_td is None or at_ms is None:
            continue
        drops.append(at_ms - at_td)

    if len(drops) < 2:
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="insufficient_cycles",
                required="至少 2 组「着地→支撑中期」配对",
                actual=f"{len(drops)} 组配对成功",
                impact="样本太少，无法给出稳定值。",
                suggestion="上传包含 3 秒以上连续跑动的片段。",
            ),
        )

    val = float(np.median(drops))

    if not (-25 <= val <= 25):
        return MetricResult(
            metric_id=spec.metric_id,
            insufficient=insufficient(
                reason="implausible_value",
                required="骨盆下沉量落在 ±25° 内",
                actual=f"推算得 {val:.1f}°",
                impact="超出合理范围，说明骨盆侧倾或事件检测有误。",
                suggestion="检查素材中骨盆区域是否全程清晰。",
            ),
        )

    return MetricResult(
        metric_id=spec.metric_id,
        value=round(val, 2),
        aggregate=aggregate_block(
            n=len(drops),
            mean=val,
            sd=float(np.std(drops)),
            min_value=float(np.min(drops)),
            max_value=float(np.max(drops)),
        ),
        valid_frame_count=len(drops),
        total_frame_count=len(ctx.seq.frames),
        confidence=0.5,
        reliability_note=(
            f"由 {len(drops)} 组「着地→支撑中期」的骨盆侧倾差值取中位数。"
            f"正值表示支撑期骨盆向支撑侧下沉（Trendelenburg 征象），"
            f"提示髋外展肌群可能力量不足。"
        ),
    )


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------

#: 指标 ID -> 计算函数。未在此表中的指标暂未实现。
METRIC_FUNCS: dict[str, callable] = {
    "trunk_lean": metric_trunk_lean,
    "step_frequency": metric_step_frequency,
    "knee_angle_touchdown": metric_knee_angle_touchdown,
    "step_length_relative": metric_step_length_relative,
    "ground_contact_time": metric_ground_contact_time,
    "flight_time": metric_flight_time,
    "duty_factor": metric_duty_factor,
    # ---- 侧面 · 关节角度（事件帧取值）----
    "shank_angle_touchdown": metric_shank_angle_touchdown,
    "knee_angle_midstance": metric_knee_angle_midstance,
    "hip_angle_toeoff": metric_hip_angle_toeoff,
    "ankle_angle_touchdown": metric_ankle_angle_touchdown,
    # ---- 侧面 · 逐帧统计 ----
    "thigh_swing_range": metric_thigh_swing_range,
    # ---- 侧面 · 位移类 ----
    "step_length": metric_step_length,
    "com_height_oscillation": metric_com_height_oscillation,
    # ---- 额状面（正面 / 背面视角）----
    "pelvis_tilt": metric_pelvis_tilt,
    "pelvis_rotation": metric_pelvis_rotation,
    "knee_valgus_touchdown": metric_knee_valgus_touchdown,
    "stance_width_relative": metric_stance_width_relative,
    "trunk_lateral_lean": metric_trunk_lateral_lean,
    "pelvis_drop_midstance": metric_pelvis_drop_midstance,
}


def compute_all_metrics(ctx: MetricContext) -> list[MetricResult]:
    """
    计算全部已实现的指标。

    未实现的指标也会产出一条 insufficient 记录，
    原因写明"尚未实现" —— 这比静默省略好：
    教练会注意到少了一项，但不知道是"没测出来"还是"没做"。
    """
    results: list[MetricResult] = []

    for metric_id, spec in METRIC_SPECS.items():
        fn = METRIC_FUNCS.get(metric_id)
        if fn is None:
            results.append(MetricResult(
                metric_id=metric_id,
                insufficient=insufficient(
                    reason="not_implemented",
                    required=spec.name_zh,
                    actual="分析引擎尚未实现该指标",
                    impact="本次报告不含该项。",
                    suggestion="该指标正在开发中，不影响其余指标的使用。",
                ),
            ))
            continue

        try:
            results.append(fn(ctx))
        except Exception as e:  # noqa: BLE001
            # 单个指标出错不应让整份报告失败 ——
            # 其余指标仍然有价值。
            #
            # 原因值取 not_implemented 而不是自造一个 computation_error：
            # 契约的枚举里没有"程序出错"这一类，而教练看到的结论是一样的
            # —— 这项本次没有产出。真正的诊断信息放在 actual 里，
            # 由开发者排查，不指望教练看懂异常类型。
            results.append(MetricResult(
                metric_id=metric_id,
                insufficient=insufficient(
                    reason="not_implemented",
                    required=spec.name_zh,
                    actual=f"计算过程出错：{type(e).__name__}: {e}",
                    impact="本次报告不含该项。",
                    suggestion="这是程序缺陷，请把该素材反馈给开发者。",
                ),
            ))

    return results
