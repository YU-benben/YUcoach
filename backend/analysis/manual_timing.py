"""Conservative fixed-side timing protocol. No pose-derived measurements."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from .metrics_base import METRIC_SPECS, MetricResult, aggregate_block, insufficient

PROTOCOL = "manual_side_v1"


def inspect_video(path: Path) -> dict:
    """Decode in presentation order; reject absent or irregular timestamps.

    Container timing cannot prove original camera capture rate. A separate
    human confirmation of an unretimed original is mandatory.
    """
    cap = cv2.VideoCapture(str(path))
    stamps = []
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        while True:
            ok, _ = cap.read()
            if not ok:
                break
            stamps.append(float(cap.get(cv2.CAP_PROP_POS_MSEC)))
    finally:
        cap.release()
    if len(stamps) < 3 or not math.isfinite(fps) or not 120 <= fps <= 1000:
        raise ValueError("需要播放时间基准为 120 fps 及以上的原始视频；低帧率慢放导出文件不能使用")
    intervals = np.diff(stamps)
    expected = 1000 / fps
    if not np.isfinite(stamps).all() or not np.all(np.abs(intervals - expected) <= expected * .02):
        raise ValueError("视频时间戳缺失、变帧率或不连续，无法进行本版逐帧计时")
    return {"fps": fps, "frame_count": len(stamps), "width": width,
            "height": height, "frame_interval_ms": expected,
            "timing_basis": "container_timestamps_cfr_not_capture_rate"}


def validate_review(review: dict, metadata: dict, *, view: str, camera_followed) -> list[dict]:
    if view != "side" or camera_followed is not False:
        raise ValueError("人工计时版仅支持固定侧面，请确认没有移动、跟拍或变焦")
    if not isinstance(review, dict) or review.get("protocol") != PROTOCOL:
        raise ValueError("缺少人工接触帧确认")
    for key in ("original_cfr_confirmed", "fixed_side_confirmed", "same_athlete_confirmed", "all_contacts_confirmed"):
        if review.get(key) is not True:
            raise ValueError("请确认原始高帧率素材、固定侧面、同一运动员及区间内无漏标")
    labels = review.get("events")
    if not isinstance(labels, list) or not 4 <= len(labels) <= 2000:
        raise ValueError("请标注至少两个完整接触（着地和离地），最多 2000 个事件")
    for e in labels:
        if (not isinstance(e, dict) or set(e) != {"frame", "side", "type"}
                or type(e["frame"]) is not int or not 0 <= e["frame"] < metadata["frame_count"]
                or e["side"] not in ("left", "right")
                or e["type"] not in ("touchdown", "toe_off")):
            raise ValueError("事件格式错误或帧号越界（帧号从 0 开始）")
    labels = sorted(labels, key=lambda e: e["frame"])
    if len({e["frame"] for e in labels}) != len(labels) or len(labels) % 2:
        raise ValueError("事件不能在同一帧重复；只保留完整的着地—离地配对")
    for i in range(0, len(labels), 2):
        td, to = labels[i:i+2]
        if td["type"] != "touchdown" or to["type"] != "toe_off" or td["side"] != to["side"]:
            raise ValueError("短跑区间须按同脚着地→同脚离地→另一脚着地排序；不支持双支撑")
        if i and labels[i-2]["side"] == td["side"]:
            raise ValueError("相邻接触必须左右脚交替，请检查漏标和左右脚")
    return labels


def timing_metrics(events: list[dict], fps: float) -> list[MetricResult]:
    contacts = [(a, b) for a, b in zip(events[::2], events[1::2])]
    td = [a for a, _ in contacts]
    contact_ms = [(b["frame"]-a["frame"])*1000/fps for a, b in contacts]
    flights = [(contacts[i+1][0]["frame"]-b["frame"])*1000/fps
               for i, (_, b) in enumerate(contacts[:-1])]
    steps = [(b["frame"]-a["frame"])*1000/fps for a, b in zip(td, td[1:])]
    duty = []
    for i, (a, b) in enumerate(contacts):
        following = next((c for c in td[i+1:] if c["side"] == a["side"]), None)
        if following:
            duty.append((b["frame"]-a["frame"])/(following["frame"]-a["frame"]))
    values = {"ground_contact_time": contact_ms, "flight_time": flights,
              "step_frequency": [60000/t for t in steps], "duty_factor": duty}
    note = (f"固定侧面人工逐帧标注；{fps:g} fps，单帧 {1000/fps:.3f} ms。"
            f"若每个边界误差±1帧，时长最坏误差±{2000/fps:.3f} ms；此为条件误差，非实测精度。"
            "仅代表所选连续区间，不自动判定跑动阶段，不作标准值优劣判断。"
            "占空比=该脚接触时长/该脚相邻两次着地周期。")
    results = []
    for metric_id in METRIC_SPECS:
        samples = values.get(metric_id, [])
        if not samples:
            results.append(MetricResult(metric_id=metric_id, reliable=False,
                insufficient=insufficient("insufficient_cycles" if metric_id in values else "not_implemented",
                    "完整同侧周期" if metric_id in values else "经验证的空间测量",
                    "缺少同侧下一次着地" if metric_id in values else "本版仅计算人工事件时间指标",
                    "本项不输出测量值或技术结论。", "补标连续完整周期。" if metric_id in values else "等待空间标定及姿态验证版本。")))
            continue
        # Pooled cadence = count of observed step intervals / elapsed time.
        mean = 60000 / float(np.mean(steps)) if metric_id == "step_frequency" else float(np.mean(samples))
        results.append(MetricResult(metric_id=metric_id, value=round(mean, 4),
            aggregate=aggregate_block(n=len(samples), mean=mean,
                sd=None if metric_id == "step_frequency" else float(np.std(samples)),
                min_value=min(samples), max_value=max(samples)),
            reliability_note=note, reference_window="event_mean"))
    return results


def read_frame(path: Path, index: int) -> bytes:
    """Sequential decode avoids codec seek returning a nearby keyframe."""
    cap = cv2.VideoCapture(str(path))
    try:
        for _ in range(index):
            if not cap.grab():
                raise ValueError("帧号超出视频范围")
        ok, frame = cap.read()
        if not ok:
            raise ValueError("无法读取该帧")
        # Preserve native resolution so zooming can reveal the shoe boundary.
        ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise ValueError("预览图片生成失败")
        return data.tobytes()
    finally:
        cap.release()
