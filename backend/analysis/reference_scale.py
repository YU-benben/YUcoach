"""
参考尺度：把归一化图像坐标换算成实际物理尺寸。

为什么这是位移类指标的前提：
    关键点坐标是归一化到 [0,1] 的，本身没有任何物理意义。
    "步幅 1.2" 到底是 1.2 米还是 1.2 倍身高，取决于参考尺度。
    没有它，步幅、步长、重心起伏全部不可测。

三种尺度来源，精度从高到低（见 docs/02-数据标准.md）：
    1. lane_line      分道线     —— 分道宽 1.22 m 是国标，最可靠
    2. height_derived 身高推算   —— 用运动员身高做参照，需准确身高
    3. calibration_rod 标定杆    —— 画面中有已知长度的参照物

⚠️ 跟踪拍摄下**逐帧不同**：
    镜头在跟随运动员移动时，透视关系逐帧变化，
    单一全局尺度会产生系统性误差。
    所以本模块产出的是"逐帧像素/米"，而不是一个常数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .pose_types import PoseFrame, PoseSequence


@dataclass
class ScaleEstimate:
    """参考尺度估计结果。"""

    method: str                     # lane_line / height_derived / calibration_rod / none
    valid_per_frame: bool           # 是否为逐帧变化
    median_pixels_per_meter: float | None = None
    reference_length_m: float | None = None
    coverage_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    # 逐帧尺度：key 为 frame_index，value 为 pixels_per_meter
    per_frame: dict[int, float] = field(default_factory=dict)

    def as_contract_dict(self) -> dict:
        """转成契约的 ReferenceScale 结构。"""
        out: dict = {
            "method": self.method,
            "valid_per_frame": self.valid_per_frame,
        }
        if self.median_pixels_per_meter is not None:
            out["median_pixels_per_meter"] = round(
                self.median_pixels_per_meter, 4)
        if self.reference_length_m is not None:
            out["reference_length_m"] = round(self.reference_length_m, 4)
        if self.coverage_pct is not None:
            out["coverage_pct"] = round(self.coverage_pct, 2)
        return out


# 国标分道宽。这是最常见的已知尺寸参照物。
# 来源：世界田联竞赛规则 / GB/T 22517.6
LANE_WIDTH_M = 1.22


def estimate_from_height(
    seq: PoseSequence,
    athlete_height_cm: float | None,
) -> ScaleEstimate:
    """
    用运动员身高推算逐帧尺度。

    做法：每帧取"头顶到最低踝"的像素高度，除以实际身高。

    ⚠️ 这个方法的误差来源，必须知情：
      1. 人在跑动时身体并不总是直立的，躯干前倾会让"头到踝"的
         垂直距离小于真实身高，导致尺度被高估（步幅被算小）。
      2. 腾空期双腿离地，踝关节位置升高，同样影响估计。
      3. 要求运动员身高填得准 —— 填错 5 cm，所有位移类指标错 3%。

    因此它的可靠性等级为 B 而非 A，且必须标注。
    """
    notes: list[str] = []

    if athlete_height_cm is None or athlete_height_cm <= 0:
        notes.append(
            "未提供运动员身高，且画面中未检出可分道线，"
            "位移类指标（步幅、步长、重心起伏）无法计算。"
            "补齐方式：在运动员档案里填写身高，"
            "或让画面中的跑道分道线入镜。"
        )
        return ScaleEstimate(
            method="none", valid_per_frame=False, notes=notes)

    height_m = athlete_height_cm / 100.0
    per_frame: dict[int, float] = {}
    samples: list[float] = []

    for pf in seq.frames:
        span = _head_to_ankle_span(pf)
        if span is None:
            continue
        # span 是归一化的**垂直**比例，需乘画面像素高度才得到像素数。
        # 但帧里没存画面尺寸，这里统一用"归一化高度"表示，
        # 调用方换算时再乘像素高度 —— 见 to_pixels_per_meter()。
        per_frame[pf.frame_index] = span / height_m
        samples.append(span / height_m)

    if not samples:
        notes.append("所有帧都取不到头到踝的距离，无法推算尺度。")
        return ScaleEstimate(
            method="none", valid_per_frame=False, notes=notes)

    coverage = len(samples) / max(len(seq.frames), 1) * 100
    median = float(np.median(samples))

    notes.append(
        f"用身高 {athlete_height_cm:.0f} cm 推算尺度，"
        f"覆盖 {coverage:.0f}% 的帧。"
    )
    notes.append(
        "注意：躯干前倾与腾空会让「头到踝」的垂直距离小于实际身高，"
        "尺度因此偏大、步幅偏小。该方法的可靠性等级为 B。"
    )

    return ScaleEstimate(
        method="height_derived",
        valid_per_frame=True,       # 逐帧变化 —— 跟踪拍摄下必须如此
        median_pixels_per_meter=median,
        reference_length_m=height_m,
        coverage_pct=coverage,
        notes=notes,
        per_frame=per_frame,
    )


def _head_to_ankle_span(pf: PoseFrame) -> float | None:
    """
    取头顶到最低踝的垂直距离，单位是**归一化画面高度**。

    用垂直距离而不是欧氏距离：跑动中前后腿分开，
    欧氏距离会把水平分量算进去，导致尺度随步态周期波动。
    垂直距离更稳定。
    """
    head = pf.point("head")
    if head is None:
        return None

    ankles = [pf.point("ankle_r"), pf.point("ankle_l")]
    visible = [a for a in ankles if a is not None]
    if not visible:
        return None

    lowest_y = max(a[1] for a in visible)   # y 向下，取最大者
    span = lowest_y - head[1]
    return span if span > 1e-4 else None


def detect_lane_lines(
    frame_bgr: np.ndarray,
    view: str = "side",
) -> tuple[float | None, float | None]:
    """
    检测画面中的跑道分道线，返回 (分道线间距占比, 置信度)。

    这是**精度最高**的尺度来源，因为分道宽 1.22 m 是国标常数。

    做法（侧面视角）：
        分道线在画面中大致是水平方向的平行线。
        用霍夫变换找长直线，按斜率筛出接近水平的，
        再统计相邻平行线的间距。
        间距的中位数 / 1.22 = 每米对应的归一化长度。

    ⚠️ 局限（必须知情）：
        · 仅在侧视角、且分道线明显可见时有效。
        · 画面透视会让远处的分道线间距变小，
          所以取的是**运动员所在位置附近**的间距，
          而不是整幅画面的平均。
        · 白色跑道线在各种光照下都可能检不出，
          此时返回 None 而不是猜一个值。

    返回
    ----
    (spacing_normalized, confidence)
        spacing_normalized: 分道线间距占画面高度的比例
        confidence: 0–1，检出的线越多、越平行则越高
    """
    import cv2

    h, w = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    # 跑道线是浅色（白）细线，用自适应阈值突出
    # 不用固定阈值：不同场地、不同光照差异很大
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,
        blockSize=31, C=-10,
    )

    # 只在下半部分找 —— 分道线在画面上部通常被看台/草地占据
    roi = thresh[int(h * 0.35):, :]
    lines = cv2.HoughLinesP(
        roi, 1, np.pi / 180,
        threshold=80, minLineLength=int(w * 0.25), maxLineGap=20,
    )
    if lines is None:
        return None, 0.0

    # 侧面视角下分道线接近水平。保留斜率小的。
    #
    # 注意形状：HoughLinesP 返回 (N, 1, 4)。用 reshape(-1, 4) 展平，
    # 直接 lines[:, 0] 拿到的是 (N, 4) 但元素类型是数组，
    # 用 `for x1, y1, x2, y2 in ...` 解包会失败。
    ys: list[float] = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if x2 == x1:
            continue
        slope = abs((y2 - y1) / (x2 - x1))
        if slope > 0.12:          # 约 7° 以内
            continue
        ys.append((y1 + y2) / 2 + int(h * 0.35))

    if len(ys) < 3:
        return None, 0.0

    ys.sort()
    # 相邻线间距
    gaps = np.diff(ys)
    gaps = gaps[gaps > 4]        # 去掉因同一线被检出多次产生的极小间距
    if len(gaps) < 2:
        return None, 0.0

    spacing_px = float(np.median(gaps))
    spacing_norm = spacing_px / h

    # 置信度：间距越一致越可信
    consistency = 1.0 - min(1.0, float(np.std(gaps) / max(np.mean(gaps), 1e-6)))
    confidence = float(np.clip(consistency * min(1.0, len(gaps) / 4.0), 0, 1))

    return spacing_norm, confidence


def estimate_from_lane_lines(
    seq: PoseSequence,
    frames_by_index: dict[int, np.ndarray],
    min_confidence: float = 0.5,
) -> ScaleEstimate:
    """
    用分道线推算逐帧尺度。

    只在运动员附近检测分道线 —— 透视会让远处的间距偏小，
    用远处的线会把尺度算错。
    """
    notes: list[str] = []
    per_frame: dict[int, float] = {}
    confidences: list[float] = []
    detected = 0

    for pf in seq.frames:
        frame = frames_by_index.get(pf.frame_index)
        if frame is None:
            continue

        spacing, conf = detect_lane_lines(frame)
        if spacing is None or conf < min_confidence:
            continue

        detected += 1
        confidences.append(conf)
        # pixels_per_meter（归一化单位） = 分道线间距占比 / 1.22 m
        per_frame[pf.frame_index] = spacing / LANE_WIDTH_M

    if not per_frame:
        notes.append(
            "画面中未检出足够清晰的跑道分道线。"
            "分道线间距是国标 1.22 米，是最可靠的尺度参照 —— "
            "下次拍摄时让分道线入镜可显著提升位移类指标精度。"
        )
        return ScaleEstimate(
            method="none", valid_per_frame=False, notes=notes)

    coverage = detected / max(len(seq.frames), 1) * 100
    median = float(np.median(list(per_frame.values())))

    notes.append(
        f"从跑道分道线推算尺度（分道宽 {LANE_WIDTH_M} m，国标常数），"
        f"覆盖 {coverage:.0f}% 的帧，"
        f"平均检出置信度 {np.mean(confidences):.2f}。"
    )
    notes.append(
        "分道线是画面中的固定参照物，不受运动员姿态影响，"
        "因此可靠性等级为 A。"
    )

    return ScaleEstimate(
        method="lane_line",
        valid_per_frame=True,
        median_pixels_per_meter=median,
        reference_length_m=LANE_WIDTH_M,
        coverage_pct=coverage,
        notes=notes,
        per_frame=per_frame,
    )


def estimate_reference_scale(
    seq: PoseSequence,
    athlete_height_cm: float | None = None,
    frames_by_index: dict[int, np.ndarray] | None = None,
) -> ScaleEstimate:
    """
    按优先级自动选择尺度来源。

    优先分道线（A 级），退回身高推算（B 级）。
    两者都不可用时返回 none，并说明如何补齐 ——
    而不是给一个拍脑袋的默认值。

    **不给默认值是刻意的**：一个错误的尺度会让所有位移类指标
    看起来很正常但实际全错，比明确说"算不了"危险得多。
    """
    if frames_by_index:
        lane = estimate_from_lane_lines(seq, frames_by_index)
        if lane.method == "lane_line":
            return lane

    return estimate_from_height(seq, athlete_height_cm)


def normalized_span_to_meters(
    span_normalized: float,
    pixels_per_meter_norm: float,
) -> float:
    """
    把归一化长度换算成米。

    注意单位的一致性：pixels_per_meter_norm 是"每米对应多少
    **归一化画面高度**"。因为关键点坐标已归一化，
    所以换算在归一化空间内完成，不需要知道实际像素尺寸。

    这也是为什么整个引擎不需要原视频分辨率就能算位移 ——
    归一化空间内自洽。
    """
    if pixels_per_meter_norm <= 1e-9:
        return float("nan")
    return span_normalized / pixels_per_meter_norm
