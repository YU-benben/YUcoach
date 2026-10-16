"""Explicit athlete selection and conservative association, never auto-reacquire.

This is an association heuristic, not biometric identity recognition. Ambiguous
or absent detections terminate the selected interval rather than mix athletes.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

PROTOCOL = "athlete_lock_v1"


def validate_target(value: dict, frame_count: int) -> dict:
    if not isinstance(value, dict) or set(value) != {"protocol", "frame", "end_frame", "bbox", "confirmed"}:
        raise ValueError("请先框选运动员并确认分析区间")
    if value["protocol"] != PROTOCOL or value["confirmed"] is not True:
        raise ValueError("人物选择尚未确认")
    start, end, box = value["frame"], value["end_frame"], value["bbox"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end < frame_count:
        raise ValueError("选人帧和结束帧必须在视频范围内，结束帧须晚于选人帧")
    if (not isinstance(box, list) or len(box) != 4
            or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in box)
            or box[2] - box[0] < .02 or box[3] - box[1] < .05):
        raise ValueError("选人框无效：请框住一个运动员的完整身体")
    return {**value, "bbox": [float(x) for x in box]}


class TargetLostError(RuntimeError):
    pass


def iou(a, b) -> float:
    low = np.maximum(a[:2], b[:2])
    high = np.minimum(a[2:], b[2:])
    intersection = float(np.prod(np.maximum(0, high - low)))
    areas = float(np.prod(a[2:]-a[:2]) + np.prod(b[2:]-b[:2]))
    return intersection / max(areas - intersection, 1e-9)


def keypoint_boxes(kp: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """RTM has no returned boxes: bound only finite, confident body landmarks."""
    boxes = []
    for points, confidence in zip(kp, scores):
        visible = (confidence >= .3) & np.isfinite(points).all(axis=1)
        core = [5, 6, 11, 12]
        if visible.sum() < 6 or not visible[core].all():
            boxes.append([np.nan] * 4)
            continue
        selected = points[visible]
        low, high = selected.min(axis=0), selected.max(axis=0)
        pad = (high - low) * .08
        boxes.append([*(low-pad), *(high+pad)])
    return np.asarray(boxes, dtype=float).reshape(-1, 4)


class AthleteLock:
    def __init__(self, selection: dict):
        self.selection = selection
        self.last_frame = None
        self.last_box = None
        self.velocity = np.zeros(2)
        self.anchor = None
        self.failed = False
        self.records: list[dict] = []

    @staticmethod
    def _appearance(frame, box):
        # Central upper body reduces background and rapidly moving leg influence.
        x1, y1, x2, y2 = box
        w, h = x2-x1, y2-y1
        height, width = frame.shape[:2]
        left, right = max(0, int(x1+.2*w)), min(width, int(x2-.2*w))
        top, bottom = max(0, int(y1+.15*h)), min(height, int(y1+.55*h))
        if right-left < 3 or bottom-top < 3:
            return None
        hsv = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        return cv2.normalize(hist, None, norm_type=cv2.NORM_L1)

    def _fail(self, index, reason):
        self.failed = True
        self.records.append({"frame": index, "status": "lost", "reason": reason})
        raise TargetLostError(f"第 {index} 帧人物锁定中断：{reason}。请缩短区间或更换无遮挡素材后重新框选；本次不生成混合人物报告。")

    def select(self, frame: np.ndarray, index: int, boxes: np.ndarray) -> int:
        if self.failed:
            self._fail(index, "锁定已中断，禁止自动重选")
        boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
        height, width = frame.shape[:2]
        valid = [i for i, b in enumerate(boxes) if np.isfinite(b).all()
                 and b[2]-b[0] >= 4 and b[3]-b[1] >= 8]
        if self.last_frame is None:
            if index != self.selection["frame"]:
                self._fail(index, "起始帧与框选帧不一致")
            chosen = np.asarray(self.selection["bbox"]) * [width, height, width, height]
            candidates = [(iou(chosen, boxes[i]), i) for i in valid if iou(chosen, boxes[i]) >= .35]
            candidates.sort(reverse=True)
            if not candidates:
                self._fail(index, "框内未检出足够匹配的人体")
            if len(candidates) > 1 and candidates[0][0]-candidates[1][0] < .2:
                self._fail(index, "选人框内存在多个相似候选")
            pick = candidates[0][1]
            if any(i != pick and iou(boxes[pick], boxes[i]) > .25 for i in valid):
                self._fail(index, "起始帧人物重叠，请选择可清楚分离的一帧")
            appearance = self._appearance(frame, boxes[pick])
            if appearance is None:
                self._fail(index, "人物太小，无法建立衣着外观参照")
            self.anchor = appearance
        else:
            if index != self.last_frame + 1:
                self._fail(index, "检测帧不连续")
            previous = self.last_box
            size = previous[2:] - previous[:2]
            center = (previous[:2] + previous[2:]) / 2
            predicted = center + self.velocity
            nearby = []
            for i in valid:
                box = boxes[i]
                candidate_center = (box[:2]+box[2:])/2
                distance = float(np.linalg.norm(candidate_center-predicted) / size[1])
                scale = (box[3]-box[1])/size[1]
                if distance > .45 or not .65 <= scale <= 1.5:
                    continue
                appearance = self._appearance(frame, box)
                if appearance is None:
                    continue
                color_distance = cv2.compareHist(self.anchor, appearance, cv2.HISTCMP_BHATTACHARYYA)
                nearby.append((distance + color_distance, i, color_distance))
            nearby.sort()
            if not nearby or nearby[0][2] > .55:
                self._fail(index, "运动位置或衣着外观不匹配，可能被遮挡或已出画")
            pick = nearby[0][1]
            # Overlap/crossing is ambiguous even if shirt colors differ: pose
            # joints can be mixed by the detector inside either box.
            if any(i != pick and iou(boxes[pick], boxes[i]) > .25 for i in valid):
                self._fail(index, "目标与其他人物重叠，无法可靠分离身份")
            if len(nearby) > 1 and nearby[1][0]-nearby[0][0] < .2:
                self._fail(index, "附近人物的关联结果接近，身份不确定")
            new_center = (boxes[pick][:2]+boxes[pick][2:])/2
            self.velocity = .5*self.velocity + .5*(new_center-center)
        self.last_box = boxes[pick].copy()
        self.last_frame = index
        self.records.append({"frame": index, "status": "locked",
                             "bbox": (boxes[pick]/[width, height, width, height]).clip(0, 1).tolist()})
        return pick
