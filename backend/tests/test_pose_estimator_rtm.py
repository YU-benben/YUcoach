"""
Halpe26 -> yu16 映射的单元测试。

为什么这套测试重要：
    换姿态模型是**最容易出静默错误**的一类改动。项目已经踩过两次 ——
    坐标量纲（以为 0~1、实际 0~640，关键点大了 640 倍）与框参数量纲 ——
    两次都不会报错，只是数字悄悄错掉。

    而 Halpe26 的索引顺序**与 Halpe 论文表格的排列不同**
    （例如 [19] 是髋中心，而不是某些资料以为的足部点起点）。
    所以这里用固定输入锁定映射，防止有人凭"论文顺序"去改映射表。

测试不需要真实模型：halpe26_to_yu16 是纯函数。
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.analysis.keypoint_map import (
    HALPE26_NAMES,
    _HALPE_TO_YU,
    halpe26_to_yu16,
)
from backend.analysis.pose_types import (
    KEYPOINT_NAMES,
    Q_CLEAR,
    Q_INVISIBLE,
    Q_UNCERTAIN,
)

#: rtmlib Halpe26 的索引。**写死在这里当契约**，不从代码里 import ——
#: 否则改了映射表测试也跟着改，等于没测。
HALPE_INDEX = {
    "nose": 0, "left_eye": 1, "right_eye": 2, "left_ear": 3, "right_ear": 4,
    "left_shoulder": 5, "right_shoulder": 6, "left_elbow": 7, "right_elbow": 8,
    "left_wrist": 9, "right_wrist": 10,
    "left_hip": 11, "right_hip": 12,
    "left_knee": 13, "right_knee": 14,
    "left_ankle": 15, "right_ankle": 16,
    "head": 17, "neck": 18, "hip": 19,
    "left_big_toe": 20, "right_big_toe": 21,
    "left_small_toe": 22, "right_small_toe": 23,
    "left_heel": 24, "right_heel": 25,
}


def make_halpe(conf: float = 0.9) -> np.ndarray:
    """
    造一个 26 点姿态。坐标按人体比例手工设定（归一化，y 向下）。

    刻意让**同侧的大趾与足跟有明确的前后关系** —— 这是验证
    "足部点没有被张冠李戴"的关键信号：趾在踝的前方、跟在踝的后方。
    """
    kp = np.zeros((26, 3), dtype=np.float64)
    y = 0.30
    for i in range(26):
        kp[i] = (0.50, y + i * 0.001, conf)

    # 躯干（肩 → 髋）
    kp[HALPE_INDEX["left_shoulder"]] = (0.48, 0.40, conf)
    kp[HALPE_INDEX["right_shoulder"]] = (0.52, 0.40, conf)
    kp[HALPE_INDEX["left_hip"]] = (0.48, 0.50, conf)
    kp[HALPE_INDEX["right_hip"]] = (0.52, 0.50, conf)
    kp[HALPE_INDEX["hip"]] = (0.50, 0.50, conf)
    kp[HALPE_INDEX["neck"]] = (0.50, 0.38, conf)
    kp[HALPE_INDEX["head"]] = (0.50, 0.33, conf)

    # 下肢
    kp[HALPE_INDEX["left_knee"]] = (0.48, 0.62, conf)
    kp[HALPE_INDEX["right_knee"]] = (0.52, 0.62, conf)
    kp[HALPE_INDEX["left_ankle"]] = (0.48, 0.74, conf)
    kp[HALPE_INDEX["right_ankle"]] = (0.52, 0.74, conf)

    # 足部：趾在前（x 更大，因为人朝画面右侧跑）、跟在后
    kp[HALPE_INDEX["left_big_toe"]] = (0.505, 0.760, conf)
    kp[HALPE_INDEX["left_small_toe"]] = (0.500, 0.765, conf)
    kp[HALPE_INDEX["left_heel"]] = (0.455, 0.755, conf)
    kp[HALPE_INDEX["right_big_toe"]] = (0.545, 0.760, conf)
    kp[HALPE_INDEX["right_small_toe"]] = (0.540, 0.765, conf)
    kp[HALPE_INDEX["right_heel"]] = (0.495, 0.755, conf)

    return kp


# ---------------------------------------------------------------------------
# 映射表本身
# ---------------------------------------------------------------------------

def test_name_list_matches_rtmlib_skeleton():
    """26 个名字必须与 rtmlib 的 halpe26 骨架定义逐个一致。"""
    expected = [
        "nose", "left_eye", "right_eye", "left_ear", "right_ear",
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
        "head", "neck", "hip",
        "left_big_toe", "right_big_toe", "left_small_toe", "right_small_toe",
        "left_heel", "right_heel",
    ]
    assert list(HALPE26_NAMES) == expected
    assert len(HALPE26_NAMES) == 26


def test_hip_center_is_index_19_not_a_foot_point():
    """
    [19] 是髋中心，**不是**足部点。

    这条专门防一个真实存在的混淆：有资料按 Halpe 论文表格的排列，
    以为足部点从 19 开始。照那个改，趾尖会指向髋部 ——
    角度全错，但数值仍在"合理范围"内，看不出来。
    """
    assert HALPE26_NAMES[19] == "hip"
    assert _HALPE_TO_YU["pelvis_center"] == 19
    # 足部点在 20–25，不在 19
    for name in ("toe_r", "toe_l", "heel_r", "heel_l"):
        assert _HALPE_TO_YU[name] >= 20


def test_every_yu16_name_has_a_source_or_is_explicitly_derived():
    """每个 yu16 点名要么有 Halpe 来源，要么显式标为需推导（None）。"""
    covered = set(_HALPE_TO_YU)
    missing = set(KEYPOINT_NAMES) - covered
    assert not missing, f"这些 yu16 点没有定义来源：{sorted(missing)}"
    # 唯一允许推导的是肩中心（两个实测量求中点）
    derived = {k for k, v in _HALPE_TO_YU.items() if v is None}
    assert derived == {"shoulder_center"}


def test_all_halpe_indices_within_range():
    """索引必须在 0–25 内，且不重复。"""
    idxs = [v for v in _HALPE_TO_YU.values() if v is not None]
    assert all(0 <= i < 26 for i in idxs), f"越界索引：{idxs}"
    assert len(idxs) == len(set(idxs)), f"索引重复：{idxs}"


# ---------------------------------------------------------------------------
# 转换行为
# ---------------------------------------------------------------------------

def test_left_right_not_swapped():
    """
    左右不能标反。

    标反不会报错，但所有分侧统计（骨盆倾斜的正负、膝内扣的左右）完全颠倒。
    用一个"左侧 x 更小、右侧 x 更大"的姿态来锁定。
    """
    out = halpe26_to_yu16(make_halpe(), frame_index=0)
    i = KEYPOINT_NAMES.index
    # 肩
    assert out.keypoints[i("shoulder_l")][0] < out.keypoints[i("shoulder_r")][0]
    # 髋
    assert out.keypoints[i("hip_l")][0] < out.keypoints[i("hip_r")][0]
    # 膝
    assert out.keypoints[i("knee_l")][0] < out.keypoints[i("knee_r")][0]
    # 踝
    assert out.keypoints[i("ankle_l")][0] < out.keypoints[i("ankle_r")][0]
    # 足跟：左跟应比右跟更靠左
    assert out.keypoints[i("heel_l")][0] < out.keypoints[i("heel_r")][0]


def test_toe_is_ahead_of_heel_on_same_side():
    """
    同侧：趾必须比跟在**跑动方向**更前。

    这是足部点没被张冠李戴的核心判据。趾跟标反会让触地判定
    整体反一个方向 —— 而且不会报错。
    """
    out = halpe26_to_yu16(make_halpe(), frame_index=0)
    i = KEYPOINT_NAMES.index
    assert out.keypoints[i("toe_r")][0] > out.keypoints[i("heel_r")][0]
    assert out.keypoints[i("toe_l")][0] > out.keypoints[i("heel_l")][0]


def test_foot_points_come_from_halpe_not_geometry():
    """
    足部点必须是 Halpe 的实测坐标，而不是几何推导出来的。

    做法：把 Halpe 的足部点设到一个"几何推导绝不可能算出来"的位置，
    再确认输出就是它。
    """
    halpe = make_halpe()
    weird = (0.111, 0.222, 0.95)
    halpe[HALPE_INDEX["left_big_toe"]] = weird
    out = halpe26_to_yu16(halpe, frame_index=0)
    got = out.keypoints[KEYPOINT_NAMES.index("toe_l")]
    assert got[0] == pytest.approx(weird[0])
    assert got[1] == pytest.approx(weird[1])


def test_foot_points_marked_clear_when_confident():
    """
    置信度足够高时，足部点质量码应为 Q_CLEAR（2）——
    这是相对旧路径的实质提升：几何推导点的上限只能是 Q_UNCERTAIN（1）。
    """
    out = halpe26_to_yu16(make_halpe(conf=0.9), frame_index=0)
    i = KEYPOINT_NAMES.index
    for name in ("toe_r", "toe_l", "heel_r", "heel_l"):
        assert out.keypoints[i(name)][2] == Q_CLEAR, f"{name} 应为清晰"


def test_no_derived_keypoints_flag():
    """Halpe 路径不应标记 has_derived_keypoints —— 它没有推导点。"""
    out = halpe26_to_yu16(make_halpe(), frame_index=0)
    assert out.has_derived_keypoints is False


def test_low_confidence_downgrades_quality():
    """低置信点降级，低于阈值则标不可见。"""
    halpe = make_halpe(conf=0.9)
    halpe[HALPE_INDEX["left_big_toe"]] = (0.505, 0.760, 0.35)   # 存疑
    halpe[HALPE_INDEX["left_heel"]] = (0.455, 0.755, 0.10)      # 不可见
    out = halpe26_to_yu16(halpe, frame_index=0)
    i = KEYPOINT_NAMES.index
    assert out.keypoints[i("toe_l")][2] == Q_UNCERTAIN
    assert out.keypoints[i("heel_l")][2] == Q_INVISIBLE
    # 不可见的点坐标必须归零（契约要求 q=0 时 x/y 为 0）
    assert out.keypoints[i("heel_l")][0] == 0.0
    assert out.keypoints[i("heel_l")][1] == 0.0


def test_zero_coordinate_with_high_conf_is_dropped():
    """
    (0,0) 且置信度高的点仍应被丢弃。

    COCO/Halpe 的约定是"缺失点填 0"，而左上角恰好是合法坐标 ——
    不显式排除的话，缺失点会被当成"画面左上角的关节"。
    """
    halpe = make_halpe()
    halpe[HALPE_INDEX["right_big_toe"]] = (0.0, 0.0, 0.99)
    out = halpe26_to_yu16(halpe, frame_index=0)
    assert out.keypoints[KEYPOINT_NAMES.index("toe_r")][2] == Q_INVISIBLE


def test_shoulder_center_is_midpoint():
    """肩中心 = 双肩中点（唯一还需要计算的点）。"""
    out = halpe26_to_yu16(make_halpe(), frame_index=0)
    i = KEYPOINT_NAMES.index
    ls = out.keypoints[i("shoulder_l")]
    rs = out.keypoints[i("shoulder_r")]
    sc = out.keypoints[i("shoulder_center")]
    assert sc[0] == pytest.approx((ls[0] + rs[0]) / 2)
    assert sc[1] == pytest.approx((ls[1] + rs[1]) / 2)


def test_coordinates_clipped_to_unit_range():
    """越界坐标被裁剪 —— 越界值会让角度计算出荒谬结果。"""
    halpe = make_halpe()
    halpe[HALPE_INDEX["left_ankle"]] = (1.4, -0.3, 0.9)
    out = halpe26_to_yu16(halpe, frame_index=0)
    x, y, _ = out.keypoints[KEYPOINT_NAMES.index("ankle_l")]
    assert 0.0 <= x <= 1.0
    assert 0.0 <= y <= 1.0


def test_head_and_neck_come_directly_from_halpe():
    """
    head/neck 直接取 Halpe 值，而不是像 COCO 路径那样外推。

    COCO 的 nose 是面部特征点，侧视/低头时偏离头部中心很远；
    Halpe 直接给 head 与 neck，所以这里不该出现外推的痕迹。
    """
    halpe = make_halpe()
    halpe[HALPE_INDEX["head"]] = (0.444, 0.333, 0.9)
    halpe[HALPE_INDEX["neck"]] = (0.446, 0.344, 0.9)
    out = halpe26_to_yu16(halpe, frame_index=0)
    i = KEYPOINT_NAMES.index
    assert out.keypoints[i("head")][0] == pytest.approx(0.444)
    assert out.keypoints[i("neck")][0] == pytest.approx(0.446)


def test_frame_index_and_person_conf_passed_through():
    """溯源字段要原样带到 PoseFrame。"""
    out = halpe26_to_yu16(make_halpe(), frame_index=137, person_conf=0.66)
    assert out.frame_index == 137
    assert out.person_conf == pytest.approx(0.66)


# ---------------------------------------------------------------------------
# 选人逻辑
# ---------------------------------------------------------------------------
#
# 这一段锁定一个目视核对才发现的真实缺陷（docs/14 §9.7）：
#   最初用"躯干像素高度最大"选人，结果在真实素材上选中了背景里的行人 ——
#   关键点浮在半空中，不在任何人的脚上。
#
#   原因：躯干高度不能代表"离镜头近"。远处站立行走的行人，
#   躯干在画面里可能比近处蹲踞的运动员还长（蹲踞时躯干被透视压缩）。
#
# 改成"核心关节置信度最高"后，目视确认真实素材上选对了人。

def _two_people() -> tuple[np.ndarray, np.ndarray]:
    """
    造两个人：
      · 人0：躯干**更高**（像素），但置信度**低** —— 模拟背景里的模糊行人
      · 人1：躯干**更矮**，但置信度**高** —— 模拟近处的主体

    正确的选择是**人1**。
    """
    kp = np.zeros((2, 26, 3), dtype=np.float64)
    sc = np.zeros((2, 26), dtype=np.float64)

    # 人0：肩 y=0.20，髋 y=0.60 → 躯干 0.40（高），但 conf 0.30
    for i in range(26):
        kp[0, i] = (0.30, 0.20 + i * 0.001, 0.30)
    kp[0, 5] = (0.28, 0.20, 0.30)
    kp[0, 6] = (0.32, 0.20, 0.30)
    kp[0, 11] = (0.28, 0.60, 0.30)
    kp[0, 12] = (0.32, 0.60, 0.30)
    sc[0, :] = 0.30

    # 人1：肩 y=0.45，髋 y=0.55 → 躯干 0.10（矮），但 conf 0.90
    for i in range(26):
        kp[1, i] = (0.60, 0.45 + i * 0.001, 0.90)
    kp[1, 5] = (0.58, 0.45, 0.90)
    kp[1, 6] = (0.62, 0.45, 0.90)
    kp[1, 11] = (0.58, 0.55, 0.90)
    kp[1, 12] = (0.62, 0.55, 0.90)
    sc[1, :] = 0.90

    return kp, sc


def test_pick_person_prefers_confident_over_tall():
    """
    选人应挑"置信度高"的，而不是"躯干高"的。

    这是真实缺陷的回归测试：用躯干高度会选中背景里的行人。
    """
    from backend.analysis.pose_estimator_rtm import RtmPoseEstimator

    kp, sc = _two_people()
    pick = RtmPoseEstimator._pick_person(kp, sc)
    assert pick == 1, "应选中置信度高的人1，而不是躯干高的人0"


def test_pick_person_skips_incomplete_torso():
    """躯干四点不全（低于阈值）的人应被跳过。"""
    from backend.analysis.pose_estimator_rtm import RtmPoseEstimator

    kp, sc = _two_people()
    # 人1 的颈肩点被抹掉 → 应退回人0
    sc[1, 5] = 0.05
    sc[1, 11] = 0.05
    pick = RtmPoseEstimator._pick_person(kp, sc)
    assert pick == 0


def test_pick_person_falls_back_when_all_low_confidence():
    """
    所有人都不过阈值时，退回"置信度总和最高"的那个，
    而不是返回 None —— 否则低质量素材会整段没有姿态数据。
    """
    from backend.analysis.pose_estimator_rtm import RtmPoseEstimator

    kp, sc = _two_people()
    sc[:] = 0.05                     # 全员低于 0.25
    sc[0, :] = 0.10                  # 人0 总和略高
    pick = RtmPoseEstimator._pick_person(kp, sc)
    assert pick == 0


def test_pick_person_handles_empty():
    """没有人时返回 None，不该崩。"""
    from backend.analysis.pose_estimator_rtm import RtmPoseEstimator

    assert RtmPoseEstimator._pick_person(np.zeros((0, 26, 2)), np.zeros((0, 26))) is None
