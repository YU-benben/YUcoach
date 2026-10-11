"""
指标计算的公共定义：规格、注册表、几何工具。

设计要点：**每个指标自带"能不能算"的判据**。
    不是等算出来再判断可信度，而是在入口就检查前提条件：
    帧率够不够、视角对不对、关键点可见率够不够、参考尺度有没有。
    任一不满足就返回 insufficient_data 并说明原因与补齐方式。

为什么这样设计：
    教练看到"步幅 1.15 m"会直接采信。如果这个数字是在
    30 fps、没有参考尺度的素材上硬算出来的，它可能差 30% 以上 ——
    而报告上没有任何迹象。**宁可明确说算不了，也不能给错数据。**

指标清单与最低帧率要求来自 docs/03-指标定义.md 附录 A。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .pose_types import PoseFrame, PoseSequence


# ---------------------------------------------------------------------------
# 指标规格
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricSpec:
    """指标的静态规格。这些信息来自契约与文档，不随数据变化。"""

    metric_id: str
    name_zh: str
    unit: str
    #: 适用的视角集合。数据视角不在此列时判为 insufficient_data
    views: tuple[str, ...]
    #: 最低帧率要求。低于此值判为 insufficient_data
    min_fps: float
    #: 方法学可靠性等级 A/B/C。C 级仅可用于趋势对比
    reliability: str
    #: 是否需要参考尺度（位移类指标）
    needs_scale: bool = False
    #: 是否为"逐帧/逐事件"指标（需要在事件帧上取值）
    is_event_metric: bool = False

    #: 数值的**生理可信范围**（下限, 上限）。
    #:
    #: ⚠️ 这个字段的存在理由是拦截「标准值行列错位」这类错误。
    #:
    #:    实际踩过的坑：从 IAAF 报告提取 trunk_lean 的标准值时，
    #    PDF 表格的列标题在提取中丢失，取到的值换算出
    #    61–68° 的躯干前倾角 —— 而短跑途中跑是 5–15°。
    #    这个值**看起来像数字**、在 0–180° 的通用角度范围内也合法，
    #    只有对照"人体在这个动作里能摆成什么样"才能发现它错了。
    #:
    #:    所以给每个指标声明一个可信范围，加载标准值时对照检查。
    #:    超出范围的标准值被拒绝加载 —— 宁可少一条标准值，
    #:    也不能拿一个错的去下结论。
    plausible_range: tuple[float, float] | None = None

    def plausibility_error(self, value: float) -> str | None:
        """值是否落在生理可信范围内。返回 None 表示没问题。"""
        if self.plausible_range is None:
            return None
        lo, hi = self.plausible_range
        if lo <= value <= hi:
            return None
        return (
            f"{value:g} {self.unit} 超出 {self.name_zh} 的生理可信范围 "
            f"{lo:g}–{hi:g} {self.unit}"
        )


#: 全部指标。顺序与 docs/03-指标定义.md 附录 A 一致。
METRIC_SPECS: dict[str, MetricSpec] = {
    # ---- 全局 ----
    #
    # plausible_range 的依据：人体在短跑中能达到的物理范围。
    # 下限比"正常值"宽松得多 —— 作用只是拦住量纲/行列错位级别的错误，
    # 不是判断"这个值好不好"。判断好坏是标准值库的事。
    "step_frequency": MetricSpec(
        "step_frequency", "步频", "steps/min", ("side", "front", "back"),
        60, "A",
        # 短跑步频：儿童慢跑可能低到 120，精英冲刺可到 320
        plausible_range=(60.0, 400.0)),
    "ground_contact_time": MetricSpec(
        "ground_contact_time", "触地时间", "ms", ("side", "front", "back"),
        120, "A",
        # 短跑触地时间量级：精英途中跑 80–120 ms，起跑前几步可到 200 ms。
        # 2000 ms 以上已不是"跑"，是走或站。
        plausible_range=(40.0, 2000.0)),
    "flight_time": MetricSpec(
        "flight_time", "腾空时间", "ms", ("side", "front", "back"),
        120, "A",
        plausible_range=(20.0, 2000.0)),
    "duty_factor": MetricSpec(
        "duty_factor", "占空比", "ratio", ("side", "front", "back"),
        120, "A",
        # 跑是 <0.5（有腾空），走是 >0.5（有双支撑）
        plausible_range=(0.05, 0.95)),

    # ---- 侧面 ----
    "shank_angle_touchdown": MetricSpec(
        "shank_angle_touchdown", "着地时胫骨角", "deg", ("side",),
        60, "A", is_event_metric=True,
        # 相对竖直的胫骨角：向前倾斜为正、向后为负，实际范围很窄
        plausible_range=(-45.0, 45.0)),
    "knee_angle_touchdown": MetricSpec(
        "knee_angle_touchdown", "着地时膝角", "deg", ("side",),
        60, "A", is_event_metric=True,
        # 膝关节是单轴铰链：完全伸直 180°，深蹲可到 30°
        plausible_range=(20.0, 180.0)),
    "knee_angle_midstance": MetricSpec(
        "knee_angle_midstance", "支撑中期膝角", "deg", ("side",),
        60, "A", is_event_metric=True,
        plausible_range=(20.0, 180.0)),
    "hip_angle_toeoff": MetricSpec(
        "hip_angle_toeoff", "离地时髋角", "deg", ("side",),
        60, "A", is_event_metric=True,
        # 肩-髋-膝夹角
        plausible_range=(20.0, 220.0)),
    "trunk_lean": MetricSpec(
        "trunk_lean", "躯干前倾角", "deg", ("side",), 60, "A",
        # ⚠️ 这个范围拦过一次真实错误。
        #
        # 从 IAAF 报告提取标准值时，PDF 表格的列标题在提取中丢失，
        # 我取到的行换算出 61–68° 的前倾角。短跑途中跑是 5–15°，
        # 起跑前三步最大也就 60° 左右。
        #
        # 61–68° 在"0–180° 的合法角度"里毫无问题，只有对照
        # 「人在跑的时候躯干能摆成什么样」才能发现它错了。
        # 加上这个范围后，这类错误会在加载标准值时就被拒绝。
        plausible_range=(-20.0, 75.0)),
    "thigh_swing_range": MetricSpec(
        "thigh_swing_range", "大腿摆动幅度", "deg", ("side",), 60, "B",
        # 摆动幅度是极差，恒为正
        plausible_range=(5.0, 140.0)),
    "ankle_angle_touchdown": MetricSpec(
        "ankle_angle_touchdown", "着地时踝角", "deg", ("side",),
        120, "B", is_event_metric=True,
        plausible_range=(40.0, 160.0)),
    "step_length_relative": MetricSpec(
        "step_length_relative", "相对步长", "ratio", ("side",),
        60, "A", needs_scale=True,
        # 步长 ÷ 身高。短跑步长可达身高的 1.3 倍，慢跑约 0.6
        plausible_range=(0.3, 1.8)),
    "step_length": MetricSpec(
        "step_length", "步长", "m", ("side",),
        60, "B", needs_scale=True,
        plausible_range=(0.3, 3.5)),
    "com_height_oscillation": MetricSpec(
        "com_height_oscillation", "重心起伏", "m", ("side",),
        120, "C", needs_scale=True,
        # 重心垂直起伏：跑步通常 2–10 cm，超过 30 cm 一定有问题
        plausible_range=(0.005, 0.30)),

    # ---- 额状面 ----
    "pelvis_tilt": MetricSpec(
        "pelvis_tilt", "骨盆侧倾", "deg", ("front", "back"), 60, "B",
        plausible_range=(-35.0, 35.0)),
    "pelvis_rotation": MetricSpec(
        "pelvis_rotation", "骨盆旋转", "deg", ("front", "back"), 120, "C",
        plausible_range=(0.0, 60.0)),
    "knee_valgus_touchdown": MetricSpec(
        "knee_valgus_touchdown", "着地时膝外翻", "deg", ("front", "back"),
        60, "B", is_event_metric=True,
        # 正值内扣、负值外展，临床上有意义的范围很窄
        plausible_range=(-30.0, 30.0)),
    "stance_width_relative": MetricSpec(
        "stance_width_relative", "相对支撑宽度", "ratio", ("front", "back"),
        60, "B",
        # needs_scale=False 是**修正**，不是笔误。
        #
        # docs/03-指标定义.md 的表格把这一项标为"需参考尺度"，
        # 但计算式是：
        #     相对支撑宽度 = |着地侧踝x − 对侧踝x| / 髋宽像素中位数
        # 分子分母都是画面长度，换算成实际距离时**尺度因子会约掉**。
        # 所以它根本不需要参考尺度 —— 标成需要会让它在没有尺度的素材上
        # 被无谓地拦下，而实际上它是额状面里少数几个在跟踪拍摄下
        # 仍能用的指标。
        needs_scale=False,
        is_event_metric=True,
        plausible_range=(0.1, 4.0)),
    "trunk_lateral_lean": MetricSpec(
        "trunk_lateral_lean", "躯干侧倾", "deg", ("front", "back"), 60, "B",
        plausible_range=(-40.0, 40.0)),
    "pelvis_drop_midstance": MetricSpec(
        "pelvis_drop_midstance", "支撑中期骨盆下沉", "deg", ("front", "back"),
        60, "B", is_event_metric=True,
        plausible_range=(-25.0, 25.0)),
}


# ---------------------------------------------------------------------------
# 计算结果的统一表达
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """
    单个指标的计算结果。

    三态之一：
      · 有效      value 有值，insufficient=None
      · 数据不足  value=None，insufficient 说明原因与建议
    不存在"有值但不可靠却不说"的状态 —— reliable=False 时
    reliability_note 必填。
    """

    metric_id: str
    value: float | str | None = None

    #: 逐帧指标的聚合统计
    aggregate: dict | None = None

    #: 事件帧（如着地帧号）
    frame_index: int | None = None
    time_ms: float | None = None

    valid_frame_count: int | None = None
    total_frame_count: int | None = None

    reliable: bool = True
    reliability_note: str | None = None
    confidence: float | None = None

    #: 透视误差估计（度）。>3 时结论必须降级
    perspective_error_estimate: float | None = None

    #: 数据不足时的说明
    insufficient: dict | None = None

    def to_contract_dict(self, spec: MetricSpec, view: str) -> dict:
        out: dict = {
            "metric_id": self.metric_id,
            "name_zh": spec.name_zh,
            "unit": spec.unit,
            "view": view,
            # phase 必须是契约枚举里的六个之一，没有"整段"这个值。
            # 这里的默认值只是占位，调用方（report.build_metrics）
            # 会按 aggregate 里的相位统计逐条覆盖。
            # 取 max_velocity 而非 acceleration：整段汇总更接近途中跑的语义。
            "phase": "max_velocity",
            "value": self.value,
            "reliable": self.reliable,
            "reliability": spec.reliability,
        }
        if self.aggregate is not None:
            out["aggregate"] = self.aggregate
        if self.frame_index is not None:
            out["frame_index"] = self.frame_index
        if self.time_ms is not None:
            out["time_ms"] = self.time_ms
        if self.valid_frame_count is not None:
            out["valid_frame_count"] = self.valid_frame_count
        if self.total_frame_count is not None:
            out["total_frame_count"] = self.total_frame_count
        if self.confidence is not None:
            out["confidence"] = self.confidence
        if self.reliability_note is not None:
            out["reliability_note"] = self.reliability_note
        if self.perspective_error_estimate is not None:
            out["perspective_error_estimate"] = round(
                self.perspective_error_estimate, 2)
        if self.insufficient is not None:
            out["insufficient"] = self.insufficient
        return out


def insufficient(
    reason: str,
    required: str,
    actual: str,
    impact: str | list[str],
    suggestion: str,
) -> dict:
    """
    构造"数据不足"说明。

    五个字段缺一不可：
      required/actual  让用户知道差距有多大
      impact           让用户知道后果 —— 不知道后果就不会去补
      suggestion       给出可执行的下一步

    只写一句"数据不足"是没用的，教练不知道该怎么办。

    ⚠️ impact 在契约里是**字符串数组**（见 common.schema.json 的
       InsufficientInfo），因为一项不足往往有多个后果。
       传字符串时自动包成单元素数组，避免每个调用点都写方括号。
    """
    if isinstance(impact, str):
        impact = [impact]
    return {
        "reason": reason,
        "required": required,
        "actual": actual,
        "impact": impact,
        "suggestion": suggestion,
    }


def aggregate_block(
    n: int,
    mean: float | None = None,
    sd: float | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
) -> dict:
    """
    构造契约的 Aggregate 结构。

    ⚠️ 契约规定 additionalProperties=false 且 required=['n']，
       所以**不能塞自定义字段**。需要附带额外信息（如"步数"、
       "尺度来源"）时，放到 reliability_note 里，不要放进 aggregate。

       踩过这个坑：曾经往 aggregate 里加了 events/steps 字段，
       结构自检直接报"出现未定义字段"。
    """
    out: dict = {"n": int(n)}
    if mean is not None:
        out["mean"] = round(float(mean), 4)
    if sd is not None:
        out["sd"] = round(float(sd), 4)
    if min_value is not None:
        out["min"] = round(float(min_value), 4)
    if max_value is not None:
        out["max"] = round(float(max_value), 4)
    return out


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def angle_at(a: tuple[float, float],
             b: tuple[float, float],
             c: tuple[float, float]) -> float:
    """
    求 ∠ABC，返回角度（0–180）。

    b 是顶点。用 arctan2 而不是 arccos(点积)：
    点积法在角度接近 0° 或 180° 时数值不稳定
    （浮点误差可能让 |cos| 略大于 1 从而抛 domain error）。
    """
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return float("nan")
    # atan2 版本：对退化情形更鲁棒
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return math.degrees(abs(math.atan2(cross, dot)))


def segment_angle_from_vertical(
    p_top: tuple[float, float],
    p_bottom: tuple[float, float],
) -> float:
    """
    线段相对**竖直方向**的夹角，返回 0–180 度。

    图像坐标 y 轴向下，所以"竖直"是 (0, 1)。
    正值表示偏向画面右侧，负值偏向左侧 —— 调用方按需取绝对值。

    为什么很多指标要用"相对竖直"而不是"相对水平"：
    短跑里胫骨角、躯干前倾角的行业惯例都是以竖直为基准。
    """
    dx = p_bottom[0] - p_top[0]
    dy = p_bottom[1] - p_top[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return float("nan")
    # atan2(dx, dy)：dy 向下为正，所以这是相对竖直向下的夹角
    return math.degrees(math.atan2(dx, dy))


def smooth_series(values: np.ndarray, window: int = 5) -> np.ndarray:
    """
    滑动平均平滑。

    为什么必须平滑：关键点坐标有亚像素抖动，
    而角度是由**差分**算出来的（速度、加速度），
    差分会放大噪声 —— 不对原始坐标平滑就直接求导，
    会得到巨大的假峰值。

    边界用 edge padding 而不是零填充：零填充会在序列两端
    制造出虚假的陡降，进而被误判成事件。
    """
    if window <= 1 or len(values) < window:
        return values.copy()

    pad = window // 2
    padded = np.pad(values, pad, mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="valid")[:len(values)]


def wrap_angle_deg(deg: float) -> float:
    """把角度归一化到 (-180, 180]。用于处理跨 ±180 的连续性。"""
    while deg <= -180:
        deg += 360
    while deg > 180:
        deg -= 360
    return deg
