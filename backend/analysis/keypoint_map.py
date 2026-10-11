"""
关键点映射：COCO-17 -> 契约的 16 点（yu16）。

为什么需要这一层：
    契约要求 16 点，其中**必须包含脚跟(heel)与脚尖(toe)** ——
    着地判定、离地判定、步频切分全靠足部点。
    而业界最常用的 YOLOv8-pose 输出 COCO-17，**没有足部点**。

    所以足部点只能由踝关节与小腿朝向几何推导。这会降低精度，
    必须如实标注，而不是假装它是实测值。

两个最容易出错的地方，都在这里显式处理：

  1. **左右定义**（docs/01-术语与命名规范.md §4.2）
     `_r` / `_l` 指运动员自身的右/左，不是画面左右。
     标反不会报错，但会让所有分侧统计完全颠倒。

  2. **足部朝向**
     脚跟与脚尖相对踝关节的位置取决于足部姿态，而这个姿态
     在着地期与蹬离期截然不同（蹬离时踝关节大幅跖屈）。
     用固定几何假设必然有误差，误差集中在最关键的触地时刻。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .pose_types import (
    KEYPOINT_NAMES,
    Q_CLEAR,
    Q_INVISIBLE,
    Q_UNCERTAIN,
    PoseFrame,
)

# COCO-17 关键点顺序（YOLOv8-pose 的输出顺序）
COCO_NAMES: tuple[str, ...] = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)

# COCO -> yu16 的直接映射。None 表示该点在契约里不需要或需推导。
#
# 注意左右：COCO 的 left_* 指"画面中被检测为左侧"，
# 但其训练数据标注的是**人体自身的左右**（这是 COCO 的约定）。
# 所以这里可以直接对应，不需要镜像。
# 但调用方必须确认：正面与背面视角下，画面左右与人体左右是相反的，
# 而侧面视角下取决于运动员朝向 —— 见 resolve_side_convention()。
_COCO_TO_YU: dict[str, int | None] = {
    "head": None,             # 由 nose 推导（COCO 的 nose 偏面部，不是头部中心）
    "neck": None,             # 由双肩中点推导
    "shoulder_r": 6,          # right_shoulder
    "hip_r": 12,              # right_hip
    "knee_r": 14,             # right_knee
    "ankle_r": 16,            # right_ankle
    "heel_r": None,           # 几何推导
    "toe_r": None,            # 几何推导
    "shoulder_l": 5,          # left_shoulder
    "hip_l": 11,
    "knee_l": 13,
    "ankle_l": 15,
    "heel_l": None,
    "toe_l": None,
    "pelvis_center": None,    # 双髋中点
    "shoulder_center": None,  # 双肩中点
}

# 人体测量学比例（相对于人体身高）。
# 来源：标准人体测量学数据。用于在没有尺度参照时给出足部长度。
FOOT_LENGTH_RATIO = 0.152      # 足长约占身高 15.2%
HEEL_BEHIND_ANKLE_RATIO = 0.25  # 足跟在踝后约足长的 25%
TOE_AHEAD_ANKLE_RATIO = 0.75    # 脚尖在踝前约足长的 75%
HEEL_BELOW_ANKLE_RATIO = 0.20   # 足跟在踝下约足长的 20%

# 置信度阈值。低于此值的点标为存疑；低于 INVISIBLE 的标为不可见。
CONF_UNCERTAIN = 0.5
CONF_INVISIBLE = 0.25


@dataclass
class MappingStats:
    """映射过程的统计，用于如实报告精度损失。"""

    derived_foot_frames: int = 0
    total_frames: int = 0

    @property
    def derived_ratio(self) -> float:
        return (self.derived_foot_frames / self.total_frames
                if self.total_frames else 0.0)


def coco17_to_yu16(
    coco_kps: np.ndarray,
    frame_index: int,
    person_conf: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    derive_feet: bool = True,
) -> PoseFrame:
    """
    把 COCO-17 关键点转成契约的 16 点。

    参数
    ----
    coco_kps : 形状 (17, 3) 的数组，每行 [x, y, conf]，坐标为归一化值
    bbox : 归一化的 (x1, y1, x2, y2)，用于推算足部长度尺度

    返回
    ----
    PoseFrame。足部点为推导值时，has_derived_keypoints=True，
    且这些点的质量码最高只给 Q_UNCERTAIN —— 它们不是实测值，
    不该与实测值同级。
    """
    out = np.zeros((len(KEYPOINT_NAMES), 3), dtype=np.float64)

    # ---- 1. 直接映射的点 ----
    for name, coco_idx in _COCO_TO_YU.items():
        if coco_idx is None:
            continue
        yu_idx = KEYPOINT_NAMES.index(name)
        x, y, conf = coco_kps[coco_idx]
        if conf >= CONF_INVISIBLE and not (x == 0 and y == 0):
            out[yu_idx] = [x, y, _quality(conf)]

    # ---- 2. 推导 neck / head ----
    # neck：双肩中点。比 COCO 的 nose 更稳定，且是躯干线的实际端点。
    ls, rs = coco_kps[5], coco_kps[6]
    if ls[2] >= CONF_INVISIBLE and rs[2] >= CONF_INVISIBLE:
        out[KEYPOINT_NAMES.index("neck")] = [
            (ls[0] + rs[0]) / 2,
            (ls[1] + rs[1]) / 2,
            _quality(min(ls[2], rs[2])),
        ]

    # head：从 neck 沿"颈部指向鼻子"的方向外推。
    # 直接用 nose 不行 —— nose 是面部特征，不是头部中心，
    # 在侧视与低头姿态下偏差很大。
    neck = out[KEYPOINT_NAMES.index("neck")]
    nose = coco_kps[0]
    if neck[2] > 0 and nose[2] >= CONF_INVISIBLE:
        dx, dy = nose[0] - neck[0], nose[1] - neck[1]
        norm = math.hypot(dx, dy)
        if norm > 1e-6:
            # 外推约 1.4 倍颈-鼻距离，落在头顶附近
            k = 1.4
            out[KEYPOINT_NAMES.index("head")] = [
                neck[0] + dx * k,
                neck[1] + dy * k,
                _quality(min(neck[2], nose[2])),
            ]

    # ---- 3. 推导 pelvis_center / shoulder_center ----
    lh, rh = coco_kps[11], coco_kps[12]
    if lh[2] >= CONF_INVISIBLE and rh[2] >= CONF_INVISIBLE:
        out[KEYPOINT_NAMES.index("pelvis_center")] = [
            (lh[0] + rh[0]) / 2,
            (lh[1] + rh[1]) / 2,
            _quality(min(lh[2], rh[2])),
        ]
    if ls[2] >= CONF_INVISIBLE and rs[2] >= CONF_INVISIBLE:
        out[KEYPOINT_NAMES.index("shoulder_center")] = [
            (ls[0] + rs[0]) / 2,
            (ls[1] + rs[1]) / 2,
            _quality(min(ls[2], rs[2])),
        ]

    # ---- 4. 推导足部点 ----
    derived = False
    if derive_feet:
        scale = _foot_scale(bbox, out)
        for side, knee_i, ankle_i, heel_n, toe_n in (
            ("r", 14, 16, "heel_r", "toe_r"),
            ("l", 13, 15, "heel_l", "toe_l"),
        ):
            knee = coco_kps[knee_i]
            ankle = coco_kps[ankle_i]
            if ankle[2] < CONF_INVISIBLE:
                continue

            heel, toe = derive_foot_points(
                ankle_xy=(ankle[0], ankle[1]),
                knee_xy=(knee[0], knee[1]) if knee[2] >= CONF_INVISIBLE else None,
                foot_scale=scale,
            )
            # 推导点的质量码上限为"存疑" —— 它不是实测值
            q = Q_UNCERTAIN if ankle[2] >= CONF_UNCERTAIN else Q_UNCERTAIN
            out[KEYPOINT_NAMES.index(heel_n)] = [heel[0], heel[1], q]
            out[KEYPOINT_NAMES.index(toe_n)] = [toe[0], toe[1], q]
            derived = True

    # 裁剪到画面内。越界值会让角度计算出现荒谬结果。
    out[:, 0] = np.clip(out[:, 0], 0.0, 1.0)
    out[:, 1] = np.clip(out[:, 1], 0.0, 1.0)
    # 不可见的点坐标归零，契约要求 q=0 时 x/y 为 0
    invisible = out[:, 2] == 0
    out[invisible, 0] = 0.0
    out[invisible, 1] = 0.0

    return PoseFrame(
        frame_index=frame_index,
        keypoints=out,
        person_conf=person_conf,
        bbox=bbox,
        has_derived_keypoints=derived,
    )


def _quality(conf: float) -> int:
    if conf >= CONF_UNCERTAIN:
        return Q_CLEAR
    if conf >= CONF_INVISIBLE:
        return Q_UNCERTAIN
    return Q_INVISIBLE


def _foot_scale(
    bbox: tuple[float, float, float, float] | None,
    kps: np.ndarray,
) -> float:
    """
    估计足部长度（归一化图像坐标下的长度）。

    优先用人体包围框高度推算：足长约占身高 15.2%。
    拿不到 bbox 时退回用"头到踝"的距离近似身高 ——
    精度差一些，但总比给一个拍脑袋的常数好。
    """
    if bbox is not None:
        height = abs(bbox[3] - bbox[1])
        if height > 0.05:
            return height * FOOT_LENGTH_RATIO

    # 退回：头顶到较低那只踝的距离
    head = kps[KEYPOINT_NAMES.index("head")]
    ankles = [kps[KEYPOINT_NAMES.index("ankle_r")],
              kps[KEYPOINT_NAMES.index("ankle_l")]]
    visible = [a for a in ankles if a[2] > 0]
    if head[2] > 0 and visible:
        lowest = max(visible, key=lambda a: a[1])  # y 向下，取较大者
        h = abs(lowest[1] - head[1])
        if h > 0.05:
            return h * FOOT_LENGTH_RATIO

    # 彻底没有尺度信息。给一个中等身材的典型值，上层会把
    # 结果整体标注为低置信。
    return 0.20 * FOOT_LENGTH_RATIO


def derive_foot_points(
    ankle_xy: tuple[float, float],
    knee_xy: tuple[float, float] | None,
    foot_scale: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    由踝关节几何推导脚跟与脚尖位置。

    ⚠️ 精度说明（必须如实告知使用者）：
       真实足部姿态在步态周期内变化很大 ——
       着地期约 90°，蹬离期踝关节跖屈可达 120° 以上。
       本函数**假定足部与小腿约呈 90°**，因此在蹬离期误差最大。
       而这个误差恰好落在最关键的触地/离地时刻附近。

       结论：由本函数推导的足部点，其**位置**不可用于精细分析，
       由其得到的触地时刻只有**参考价值**。
       要精确测量触地时间，必须使用带足部关键点的模型。

    做法：
       1. 取小腿方向（膝->踝）。膝不可见时假定小腿竖直向下。
       2. 足部方向 = 小腿方向的垂线（即足部与小腿成 90°）。
       3. 在这条线上按人体测量学比例放脚尖与脚跟。
    """
    ax, ay = ankle_xy

    if knee_xy is not None:
        kx, ky = knee_xy
        sx, sy = ax - kx, ay - ky
        norm = math.hypot(sx, sy)
        if norm > 1e-6:
            sx, sy = sx / norm, sy / norm
        else:
            sx, sy = 0.0, 1.0
    else:
        # 膝不可见：假定小腿竖直向下
        sx, sy = 0.0, 1.0

    # 垂线方向（两个候选）
    px, py = -sy, sx

    # 选朝向"身体前方"的那一条。
    # 判据：足部整体应当偏向身体前方。用一个粗略但可靠的办法 ——
    # 若垂线的 y 分量为负（指向上方），说明取反了。
    # 理由：真实的足部（踝+脚尖）在画面中总是低于或等于踝的高度，
    # 脚尖不可能明显高于踝。
    if py < 0:
        px, py = -px, -py

    foot_len = foot_scale
    toe = (ax + px * foot_len * TOE_AHEAD_ANKLE_RATIO,
           ay + py * foot_len * TOE_AHEAD_ANKLE_RATIO)

    # 脚跟在小腿后方，略偏下
    heel = (ax - px * foot_len * HEEL_BEHIND_ANKLE_RATIO,
            ay - py * foot_len * HEEL_BEHIND_ANKLE_RATIO
            + foot_len * HEEL_BELOW_ANKLE_RATIO)

    return heel, toe


def resolve_side_convention(view: str, runner_moves_right: bool) -> bool:
    """
    判断是否需要交换左右标签。

    契约规定 `_r`/`_l` 是**运动员自身**的左右。但姿态模型在部分视角下
    会按画面左右输出（或按可见性选择），因此需要显式校正。

    这是最常见的标注错误之一 —— 标反不会报错，
    但会让所有分侧统计完全颠倒。所以宁可写成一个显式函数，
    而不是散落在各处的隐式假设。

    参数
    ----
    view : 'side' | 'front' | 'back'
    runner_moves_right : 侧面视角下运动员是否朝画面右侧跑动

    返回
    ----
    True 表示需要交换 _r 与 _l

    约定依据（docs/01 §4.2）：
        侧面：运动员面朝跑动方向。若朝右跑，则画面近侧是运动员右侧，
              此时 COCO 的 right_* 恰好对应，不需交换。
              若朝左跑，画面近侧变成运动员左侧，需要交换。
        正面：镜头在运动员前方，画面左侧是运动员的右侧 -> 需交换
        背面：镜头在运动员后方，画面左侧是运动员的左侧 -> 不交换
    """
    if view == "front":
        return True
    if view == "back":
        return False
    # 侧面
    return not runner_moves_right


def swap_left_right(kps: np.ndarray) -> np.ndarray:
    """交换 16 点中的左右侧。用于校正视角带来的左右歧义。"""
    out = kps.copy()
    pairs = [
        ("shoulder_r", "shoulder_l"),
        ("hip_r", "hip_l"),
        ("knee_r", "knee_l"),
        ("ankle_r", "ankle_l"),
        ("heel_r", "heel_l"),
        ("toe_r", "toe_l"),
    ]
    for a, b in pairs:
        ia, ib = KEYPOINT_NAMES.index(a), KEYPOINT_NAMES.index(b)
        out[ia], out[ib] = kps[ib].copy(), kps[ia].copy()
    return out
