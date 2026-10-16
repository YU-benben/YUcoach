"""
姿态提取。

设计要点：**可插拔**。
    姿态模型是这个项目里最可能被替换的一环 —— 现在用现成模型，
    将来用你自己训练的。所以定义 PoseEstimator 接口，
    上层（指标计算、报告生成）只依赖接口，不依赖具体模型。
    换模型时只需新增一个实现类，其余代码一行不动。

关键约束：契约要求 16 个关键点，**包含脚跟与脚尖**，
    而业界最常用的 YOLOv8-pose 输出 COCO-17，没有足部点。
    因此这里有一个 coco17 -> yu16 的映射层，足部点由几何推导。
    这一步会降低触地时间等指标的精度，必须如实标注（见 keypoint_map.py）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

# 契约规定：16 点，顺序不可变。见 docs/01-术语与命名规范.md §4
KEYPOINT_NAMES: tuple[str, ...] = (
    "head", "neck", "shoulder_r", "hip_r", "knee_r", "ankle_r", "heel_r", "toe_r",
    "shoulder_l", "hip_l", "knee_l", "ankle_l", "heel_l", "toe_l",
    "pelvis_center", "shoulder_center",
)

# 质量码。见 common.schema.json 的 QualityCode
Q_INVISIBLE = 0   # 不可见，客户端不应绘制
Q_UNCERTAIN = 1   # 存疑
Q_CLEAR = 2       # 清晰


@dataclass
class PoseFrame:
    """单帧姿态。坐标已归一化到 [0,1]，原点左上，y 轴向下。"""

    frame_index: int

    # 形状 (16, 3)：每行 [x, y, q]
    keypoints: np.ndarray

    person_conf: float | None = None
    bbox: tuple[float, float, float, float] | None = None

    # 该帧是否有关键点靠几何推导得出（足部点）。上层据此降低指标置信度。
    has_derived_keypoints: bool = False

    # 该帧是否经过插值补出（遮挡期间）。契约要求客户端画成虚线。
    is_interpolated: bool = False

    def visible_mask(self) -> np.ndarray:
        """质量码 > 0 的点，即可以用于计算的点。"""
        return self.keypoints[:, 2] > 0

    def point(self, name: str) -> tuple[float, float, int] | None:
        try:
            i = KEYPOINT_NAMES.index(name)
        except ValueError:
            return None
        x, y, q = self.keypoints[i]
        if q == 0:
            return None
        return float(x), float(y), int(q)

    def as_contract_dict(self) -> dict:
        """转成契约要求的格式。"""
        return {
            "frame_index": int(self.frame_index),
            "keypoints": [
                {
                    "x": round(float(x), 6),
                    "y": round(float(y), 6),
                    "q": int(q),
                }
                for x, y, q in self.keypoints
            ],
            "is_occluded": bool(not self.has_derived_keypoints
                                and self.keypoints[:, 2].mean() < 1.0),
            "is_interpolated": bool(self.is_interpolated),
            **({"person_conf": round(float(self.person_conf), 4)}
               if self.person_conf is not None else {}),
            **({"bbox": [round(float(v), 6) for v in self.bbox]}
               if self.bbox is not None else {}),
        }


@dataclass
class PoseSequence:
    """一段视频的姿态序列。"""

    frames: list[PoseFrame] = field(default_factory=list)
    estimator_name: str = ""
    estimator_version: str = ""
    notes: list[str] = field(default_factory=list)
    model_config: str = ""

    def __len__(self) -> int:
        return len(self.frames)

    @property
    def keypoint_names(self) -> tuple[str, ...]:
        return KEYPOINT_NAMES

    def coverage(self) -> dict[str, float]:
        """
        各关键点的可见率。

        用途：判断这个视角下哪些指标根本算不了。
        例如侧面视角下远侧（_l）肢体常被遮挡，可见率会很低 ——
        此时不应输出基于它的分侧对比。
        """
        if not self.frames:
            return {}
        kp = np.stack([f.keypoints for f in self.frames])  # (N, 16, 3)
        vis = (kp[:, :, 2] > 0).mean(axis=0)
        return {n: float(v) for n, v in zip(KEYPOINT_NAMES, vis)}

    def derived_ratio(self) -> float:
        """有几何推导关键点的帧占比。数值高说明足部精度不足。"""
        if not self.frames:
            return 0.0
        return sum(1 for f in self.frames if f.has_derived_keypoints) / len(
            self.frames
        )


class PoseEstimator(ABC):
    """
    姿态提取器接口。

    换模型时实现这个接口即可，上层代码无需改动。
    """

    #: 实现名称，写入报告用于溯源
    name: str = "unnamed"
    model_config: str = ""
    #: 版本号。模型换了必须改，否则无法回答"为什么这次结果和上次不同"
    version: str = "0.0.0"
    #: 该实现是否提供真实的足部关键点（而非几何推导）
    provides_foot_keypoints: bool = False

    @abstractmethod
    def estimate(self, frame_bgr: np.ndarray, frame_index: int) -> PoseFrame | None:
        """处理单帧。未检出人体时返回 None。"""

    def estimate_sequence(self, frames) -> PoseSequence:
        """
        处理一段视频。frames 是 (frame_index, bgr) 的可迭代对象。

        默认实现逐帧调用 estimate。子类可以覆盖以做批处理 ——
        批处理在 GPU 上能显著提速。
        """
        seq = PoseSequence(
            estimator_name=self.name,
            estimator_version=self.version,
            model_config=self.model_config,
        )

        if not self.provides_foot_keypoints:
            seq.notes.append(
                f"姿态模型 {self.name} 不提供足部关键点，"
                f"heel/toe 由踝关节与小腿朝向几何推导。"
                f"触地时刻的判定精度因此下降，"
                f"触地时间与步频的置信度会被标注为存疑。"
            )

        for idx, bgr in frames:
            pf = self.estimate(bgr, idx)
            if pf is not None:
                seq.frames.append(pf)

        # 遮挡帧的缺口填充
        seq = interpolate_gaps(seq)
        return seq


def interpolate_gaps(seq: PoseSequence, max_gap: int = 5) -> PoseSequence:
    """
    线性插值补出短暂丢失的帧。

    为什么要做：姿态模型偶尔会在单帧上丢失目标（运动模糊、短暂遮挡），
    而指标计算需要连续序列来求导（速度、加速度）。
    几个断点就会让数值微分炸出巨大的假峰值。

    约束：
      · 只补**很短的**缺口（默认 ≤5 帧）。长缺口说明目标真的不见了，
        补出来是编数据。
      · 补出的帧标记 is_interpolated=True。
        契约要求客户端画成虚线 —— 让教练知道这段不是实测的。
    """
    if len(seq.frames) < 3:
        return seq

    by_index = {f.frame_index: f for f in seq.frames}
    indices = sorted(by_index)
    out: list[PoseFrame] = []
    filled = 0

    for a, b in zip(indices, indices[1:]):
        out.append(by_index[a])
        gap = b - a - 1
        if gap <= 0 or gap > max_gap:
            continue

        fa, fb = by_index[a], by_index[b]
        for k in range(1, gap + 1):
            t = k / (gap + 1)
            kp = fa.keypoints * (1 - t) + fb.keypoints * t

            # 质量码取两侧的较小值，再降一级 ——
            # 插值出来的点不如实测可靠，不该与实测同级。
            q = np.minimum(fa.keypoints[:, 2], fb.keypoints[:, 2])
            kp[:, 2] = np.maximum(q - 1, 0)

            out.append(PoseFrame(
                frame_index=a + k,
                keypoints=kp,
                person_conf=None,
                bbox=None,
                has_derived_keypoints=(fa.has_derived_keypoints
                                       or fb.has_derived_keypoints),
                is_interpolated=True,
            ))
            filled += 1

    out.append(by_index[indices[-1]])

    if filled:
        seq.notes.append(
            f"插值补出 {filled} 帧（占比 {filled / len(out) * 100:.1f}%）。"
            f"这些帧在报告中会以虚线标记，不与实测混淆。"
        )

    seq.frames = out
    return seq
