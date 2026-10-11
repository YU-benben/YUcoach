"""
关键点映射的单元测试。

为什么这套测试重要：
    COCO-17 -> 契约 16 点的映射里有两处**不会报错但会全盘出错**的陷阱：
      1. 左右标签反了 —— 所有分侧统计完全颠倒
      2. 足部点推导方向错了 —— 脚尖跑到脚踝后面，触地判定全错

    这两种错误都不会抛异常，只会让结果安静地错下去。
    所以必须用已知答案的合成姿态来锁定行为。

测试用的合成姿态是**真人比例**的手工构造：
    身高约 0.8（归一化），站立侧面朝向，坐标 y 向下。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.analysis.keypoint_map import (
    COCO_NAMES,
    coco17_to_yu16,
    derive_foot_points,
    resolve_side_convention,
    swap_left_right,
)
from backend.analysis.pose_types import KEYPOINT_NAMES, Q_CLEAR, Q_UNCERTAIN


def make_standing_coco() -> np.ndarray:
    """
    构造一个站立人体的 COCO-17 姿态，面朝画面右侧。

    坐标是手工设定的，符合真人比例：
      · 头顶约 y=0.08，脚踝约 y=0.88
      · 双肩在 y=0.22 附近，双髋在 y=0.50 附近
      · 右腿在画面更右（朝右站立时，近侧腿是右腿）
    """
    kps = np.zeros((17, 3), dtype=np.float64)

    def put(idx: int, x: float, y: float, conf: float = 0.95) -> None:
        kps[idx] = [x, y, conf]

    # 0 nose（面朝右，所以偏右）
    put(0, 0.520, 0.115)
    # 1-4 眼睛耳朵（本测试不关心，给个合理值）
    put(1, 0.515, 0.105)
    put(2, 0.525, 0.105)
    put(3, 0.510, 0.110)
    put(4, 0.530, 0.110)

    # 5 left_shoulder / 6 right_shoulder
    put(5, 0.495, 0.225)   # 远侧
    put(6, 0.515, 0.220)   # 近侧
    # 7-10 肘腕（本测试不关心）
    put(7, 0.500, 0.330)
    put(8, 0.520, 0.325)
    put(9, 0.505, 0.430)
    put(10, 0.525, 0.425)

    # 11 left_hip / 12 right_hip
    put(11, 0.490, 0.500)
    put(12, 0.510, 0.498)

    # 13 left_knee / 14 right_knee
    put(13, 0.495, 0.690)
    put(14, 0.515, 0.688)
    # 15 left_ankle / 16 right_ankle
    put(15, 0.497, 0.870)
    put(16, 0.517, 0.868)

    return kps


# ---------------------------------------------------------------------------
# 基本映射
# ---------------------------------------------------------------------------

def test_coco_names_order_matches_yolov8_convention():
    """COCO 顺序写错会让所有点错位。这是最容易犯的错。"""
    assert COCO_NAMES[0] == "nose"
    assert COCO_NAMES[5] == "left_shoulder"
    assert COCO_NAMES[6] == "right_shoulder"
    assert COCO_NAMES[11] == "left_hip"
    assert COCO_NAMES[12] == "right_hip"
    assert COCO_NAMES[15] == "left_ankle"
    assert COCO_NAMES[16] == "right_ankle"


def test_contract_keypoint_order_is_immutable():
    """契约规定 16 点顺序不可变。改动会让所有已存数据的含义错位。"""
    assert KEYPOINT_NAMES == (
        "head", "neck", "shoulder_r", "hip_r", "knee_r", "ankle_r",
        "heel_r", "toe_r",
        "shoulder_l", "hip_l", "knee_l", "ankle_l", "heel_l", "toe_l",
        "pelvis_center", "shoulder_center",
    )
    assert len(KEYPOINT_NAMES) == 16


def test_maps_all_16_points():
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0,
                       person_conf=0.9, bbox=(0.45, 0.05, 0.58, 0.89))

    assert pf.keypoints.shape == (16, 3)
    # 每一个点都应当有值 —— 契约要求不可见点用 q=0 占位，不得缺项
    for i, name in enumerate(KEYPOINT_NAMES):
        x, y, q = pf.keypoints[i]
        assert q in (0, 1, 2), f"{name} 的质量码非法：{q}"
        if q > 0:
            assert 0.0 <= x <= 1.0, f"{name} 的 x 越界：{x}"
            assert 0.0 <= y <= 1.0, f"{name} 的 y 越界：{y}"


def test_shoulders_and_hips_map_to_correct_side():
    """
    左右映射必须正确。这是"不会报错但全盘错"的头号陷阱。
    构造时 right_shoulder 的 x 更大（0.515 > 0.495）。
    """
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)

    r = pf.point("shoulder_r")
    l = pf.point("shoulder_l")
    assert r is not None and l is not None
    assert r[0] > l[0], "right_shoulder 应当映射自 COCO 的 right_shoulder"

    r = pf.point("hip_r")
    l = pf.point("hip_l")
    assert r is not None and l is not None
    assert r[0] > l[0]

    r = pf.point("ankle_r")
    l = pf.point("ankle_l")
    assert r is not None and l is not None
    assert r[0] > l[0]


def test_derived_centers_are_midpoints():
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)

    sr, sl = pf.point("shoulder_r"), pf.point("shoulder_l")
    sc = pf.point("shoulder_center")
    assert sc is not None
    assert sc[0] == pytest.approx((sr[0] + sl[0]) / 2, abs=1e-9)
    assert sc[1] == pytest.approx((sr[1] + sl[1]) / 2, abs=1e-9)

    hr, hl = pf.point("hip_r"), pf.point("hip_l")
    pc = pf.point("pelvis_center")
    assert pc is not None
    assert pc[0] == pytest.approx((hr[0] + hl[0]) / 2, abs=1e-9)
    assert pc[1] == pytest.approx((hr[1] + hl[1]) / 2, abs=1e-9)


def test_neck_is_midpoint_not_nose():
    """
    neck 应当由双肩中点推导，而不是直接用鼻子。
    用鼻子会让颈点在低头姿态下严重偏移。
    """
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)
    neck = pf.point("neck")
    sr, sl = pf.point("shoulder_r"), pf.point("shoulder_l")
    assert neck is not None
    assert neck[0] == pytest.approx((sr[0] + sl[0]) / 2, abs=1e-9)
    # 而且应当明显低于鼻子
    nose_y = make_standing_coco()[0][1]
    assert neck[1] > nose_y


def test_head_is_above_neck():
    """head 必须比 neck 更靠上（y 更小），否则躯干线方向就反了。"""
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)
    head, neck = pf.point("head"), pf.point("neck")
    assert head is not None and neck is not None
    assert head[1] < neck[1], "头部应当在颈上方"


# ---------------------------------------------------------------------------
# 足部推导
# ---------------------------------------------------------------------------

def test_derived_foot_points_are_marked_uncertain():
    """
    推导出的足部点**不得**标为"清晰" —— 它们不是实测值。
    如果标成清晰，下游会按实测精度对待，得出过于自信的结论。
    """
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0,
                       bbox=(0.45, 0.05, 0.58, 0.89))

    assert pf.has_derived_keypoints is True
    for name in ("heel_r", "toe_r", "heel_l", "toe_l"):
        p = pf.point(name)
        assert p is not None, f"{name} 应当有值"
        assert p[2] == Q_UNCERTAIN, f"{name} 是推导值，质量码应为存疑"


def test_toe_is_below_or_level_with_ankle():
    """
    脚尖不可能明显高于脚踝。
    这是足部推导方向的正确性判据 —— 方向取反时脚尖会跑到上面去。
    """
    coco = make_standing_coco()
    pf = coco17_to_yu16(coco, frame_index=0,
                       bbox=(0.45, 0.05, 0.58, 0.89))

    for side in ("r", "l"):
        ankle = pf.point(f"ankle_{side}")
        toe = pf.point(f"toe_{side}")
        assert ankle is not None and toe is not None
        assert toe[1] >= ankle[1] - 0.01, (
            f"{side} 侧脚尖(y={toe[1]:.3f}) 高于脚踝(y={ankle[1]:.3f})，"
            f"足部方向推导反了"
        )


def test_foot_points_straddle_the_ankle():
    """
    脚跟与脚尖应当在踝关节的两侧 —— 一个在前一个在后，不能都在同侧。
    """
    coco = make_standing_coco()
    pf = coco17_to_yu16(coco, frame_index=0,
                       bbox=(0.45, 0.05, 0.58, 0.89))

    for side in ("r", "l"):
        ankle = pf.point(f"ankle_{side}")
        heel = pf.point(f"heel_{side}")
        toe = pf.point(f"toe_{side}")
        assert ankle and heel and toe
        # 沿 x 轴看，脚跟与脚尖必须在踝的两边
        spans = (heel[0] - ankle[0]) * (toe[0] - ankle[0])
        assert spans < 0, (
            f"{side} 侧脚跟与脚尖在踝的同一侧，几何推导有误"
        )


def test_foot_length_scales_with_person_size():
    """
    足部长度必须随人体尺度缩放。
    固定常数会让高个子与矮个子的足部点误差方向相反。
    """
    small = coco17_to_yu16(make_standing_coco(), frame_index=0,
                          bbox=(0.45, 0.05, 0.58, 0.45))
    large = coco17_to_yu16(make_standing_coco(), frame_index=0,
                          bbox=(0.40, 0.02, 0.62, 0.98))

    def foot_span(pf):
        heel, toe = pf.point("heel_r"), pf.point("toe_r")
        return math.dist(heel[:2], toe[:2])

    assert foot_span(large) > foot_span(small), (
        "包围框更高（人更大）时足部长度应当更长"
    )


def test_invisible_ankle_skips_foot_derivation():
    """踝关节不可见时不该硬凑足部点 —— 那等于编数据。"""
    coco = make_standing_coco()
    coco[16] = [0, 0, 0.0]  # 右踝不可见
    coco[14] = [0, 0, 0.0]  # 右膝也不可见

    pf = coco17_to_yu16(coco, frame_index=0,
                       bbox=(0.45, 0.05, 0.58, 0.89))

    assert pf.point("ankle_r") is None
    assert pf.point("toe_r") is None, "踝不可见时不应推导出脚尖"
    assert pf.point("heel_r") is None


def test_low_confidence_ankle_still_derives():
    """踝关节存疑（不是完全不可见）时仍可推导，但要标为存疑。"""
    coco = make_standing_coco()
    coco[16] = [0.517, 0.868, 0.35]  # 右踝置信度偏低

    pf = coco17_to_yu16(coco, frame_index=0,
                       bbox=(0.45, 0.05, 0.58, 0.89))
    ankle = pf.point("ankle_r")
    assert ankle is not None
    assert ankle[2] == Q_UNCERTAIN


def test_derive_foot_points_without_knee_falls_back_to_vertical():
    """膝不可见时假定小腿竖直，仍应产出合理的足部点，而不是崩溃。"""
    heel, toe = derive_foot_points(
        ankle_xy=(0.5, 0.8), knee_xy=None, foot_scale=0.1
    )
    # 小腿竖直 -> 足部水平
    assert toe[1] == pytest.approx(0.8, abs=1e-6), "小腿竖直时脚尖应与踝同高"
    assert toe[0] != pytest.approx(0.5, abs=1e-6), "脚尖应当有水平位移"


# ---------------------------------------------------------------------------
# 左右约定
# ---------------------------------------------------------------------------

def test_side_view_running_right_keeps_labels():
    """侧面朝右跑：画面近侧是运动员右侧，COCO 标签可直接用，不需交换。"""
    assert resolve_side_convention("side", runner_moves_right=True) is False


def test_side_view_running_left_needs_swap():
    """侧面朝左跑：画面近侧变成运动员左侧，需要交换。"""
    assert resolve_side_convention("side", runner_moves_right=False) is True


def test_front_and_back_views_are_mirrored():
    """
    正面与背面视角的镜像关系相反。
    搞反了会让左右腿的分析结论对调 —— 而教练会据此调整训练。
    """
    assert resolve_side_convention("front", runner_moves_right=True) is True
    assert resolve_side_convention("back", runner_moves_right=True) is False


def test_swap_left_right_is_symmetric():
    """交换两次应当回到原状。"""
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)
    once = swap_left_right(pf.keypoints)
    twice = swap_left_right(once)
    np.testing.assert_allclose(twice, pf.keypoints)


def test_swap_left_right_actually_moves_points():
    """交换必须真的换掉左右，而不是空操作。"""
    pf = coco17_to_yu16(make_standing_coco(), frame_index=0)
    swapped = swap_left_right(pf.keypoints)

    i_r = KEYPOINT_NAMES.index("shoulder_r")
    i_l = KEYPOINT_NAMES.index("shoulder_l")
    np.testing.assert_allclose(swapped[i_r], pf.keypoints[i_l])
    np.testing.assert_allclose(swapped[i_l], pf.keypoints[i_r])

    # 中线点不该被交换
    i_pc = KEYPOINT_NAMES.index("pelvis_center")
    np.testing.assert_allclose(swapped[i_pc], pf.keypoints[i_pc])
