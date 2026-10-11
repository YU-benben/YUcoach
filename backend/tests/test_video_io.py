"""
视频读取与帧率校验的测试。

为什么这套测试重要：
    帧率是整条分析链路的地基。帧率错一倍，触地时间、腾空时间、步频
    会**静默出错** —— 不报错、不崩溃，只是结果全错。
    而"容器声称的帧率不可信"恰恰是最常见的情况
    （剪辑软件导出的慢动作视频典型症状就是声明 30fps、实际 240fps）。

    所以这里用合成视频构造出几种典型场景，锁定判据行为。
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.analysis.video_io import (
    estimate_camera_motion,
    iter_frames,
    read_video_info,
    verify_fps,
)


def make_video(
    path: Path,
    frame_count: int,
    fps: float,
    size: tuple[int, int] = (320, 240),
    moving: bool = False,
) -> Path:
    """生成一段合成视频。moving=True 时画面整体平移，用于测镜头运动估计。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w = cv2.VideoWriter(str(path), fourcc, fps, size)
    if not w.isOpened():
        pytest.skip("本机 OpenCV 无法写 mp4v 视频，跳过")

    for i in range(frame_count):
        frame = np.full((size[1], size[0], 3), 230, dtype=np.uint8)
        offset = int(i * 2) % size[0] if moving else 0

        # 画一些纹理，让光流有特征点可跟
        for k in range(6):
            x = (k * 53 + offset) % size[0]
            cv2.rectangle(frame, (x, 40 + k * 25),
                          (x + 26, 60 + k * 25), (60, 60, 60), -1)
        # 一个"人"形状的块
        cx = size[0] // 2
        cv2.circle(frame, (cx, 90), 16, (30, 30, 30), -1)
        cv2.rectangle(frame, (cx - 8, 105), (cx + 8, 175), (30, 30, 30), -1)

        w.write(frame)

    w.release()
    return path


# ---------------------------------------------------------------------------
# 帧率自洽性校验（纯逻辑，不需要视频文件）
# ---------------------------------------------------------------------------

def test_matching_counts_are_verified():
    """声明帧数与实际帧数一致 -> 通过。"""
    v = verify_fps(declared_fps=240.0, declared_count=2400, counted=2400)
    assert v.status == "verified"
    assert v.agreement_pct == 100.0


def test_verified_is_fps_not_frame_count():
    """
    ⚠️ 回归测试：verified 必须是**帧率**（帧/秒），不是帧数。

    真实踩过的坑：把"解出的帧数"直接填进了 verified 字段，
    于是 332 帧的视频被标成 "332 fps"。

    这个错误极难发现，因为：
      · 不会崩溃
      · 332 看起来像个合法的帧率
      · 报告里也写着 332，肉眼无法判断对错
    但所有基于帧率的时间换算都会错得离谱
    （332/30 ≈ 11 倍）。

    教训：单位不同的量必须有各自的字段名。
    """
    v = verify_fps(declared_fps=30.0, declared_count=332, counted=332)

    assert v.verified == 30.0, (
        f"verified 应为帧率 30.0，实际得到 {v.verified} —— "
        f"若等于帧数 {v.counted_frames}，说明又混淆了帧率与帧数"
    )
    assert v.counted_frames == 332
    assert v.verified != float(v.counted_frames), (
        "帧率恰好等于帧数说明字段填反了"
    )


def test_verified_fps_is_independent_of_video_length():
    """
    帧率不该随视频变长而变大 —— 这是混淆帧率与帧数最直接的判据。
    同一个帧率的两个时长不同的视频，verified 必须相同。
    """
    short = verify_fps(declared_fps=240.0, declared_count=240, counted=240)
    long = verify_fps(declared_fps=240.0, declared_count=2400, counted=2400)

    assert short.verified == long.verified == 240.0
    assert short.counted_frames == 240
    assert long.counted_frames == 2400


def test_small_deviation_is_still_verified():
    """轻微偏差属正常（部分编码器不写入末尾不完整帧）。"""
    v = verify_fps(declared_fps=240.0, declared_count=2400, counted=2380)
    assert v.status == "verified"
    assert v.agreement_pct > 98


def test_large_deviation_is_flagged():
    """
    变速导出的典型场景：声明 30fps / 300 帧，实际解出 2400 帧。
    这是最危险的坑 —— 若不抓出来，所有时间指标都会错 8 倍。
    """
    v = verify_fps(declared_fps=30.0, declared_count=300, counted=2400)
    assert v.status == "warning"
    assert v.agreement_pct < 25
    assert any("偏差" in n for n in v.notes)


def test_missing_metadata_is_warned_not_crashed():
    """容器没提供帧率信息时给警告，不能抛异常。"""
    v = verify_fps(declared_fps=None, declared_count=None, counted=500)
    assert v.status == "warning"
    assert v.counted == 500.0
    assert any("未提供" in n for n in v.notes)


def test_low_fps_is_noted_but_not_rejected():
    """
    低帧率不拦截，但要说明后果 ——
    角度类指标仍然可用，不该剥夺教练用得上的部分。
    """
    v = verify_fps(declared_fps=60.0, declared_count=600, counted=600)
    assert v.status == "verified"
    assert any("120" in n for n in v.notes)


def test_zero_declared_count_falls_back_to_warning():
    """声明帧数为 0 属于元数据缺失，按缺失处理。"""
    v = verify_fps(declared_fps=240.0, declared_count=0, counted=100)
    assert v.status == "warning"


# ---------------------------------------------------------------------------
# 真实视频读取
# ---------------------------------------------------------------------------

def test_reads_synthetic_video_correctly(tmp_path: Path):
    """读出的帧数、分辨率必须与实际相符。"""
    p = make_video(tmp_path / "t.mp4", frame_count=60, fps=30.0,
                   size=(320, 240))
    info = read_video_info(p)

    assert info.width == 320
    assert info.height == 240
    # 逐帧解码数出来的帧数。编码器可能合并完全相同的帧，
    # 所以允许小幅偏差，但不能差出量级。
    assert abs(info.frame_count - 60) <= 6, f"帧数偏差过大：{info.frame_count}"
    assert info.fps_declared == pytest.approx(30.0, abs=0.5)
    assert info.duration_s > 1.0


def test_reports_missing_file_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_video_info(tmp_path / "nope.mp4")


def test_iter_frames_honours_range(tmp_path: Path):
    """区间读取的帧数必须准确 —— 与真实帧数不符，不能只验证不抛异常。"""
    p = make_video(tmp_path / "t.mp4", frame_count=60, fps=30.0)

    all_frames = list(iter_frames(p))
    assert len(all_frames) == 60

    subset = list(iter_frames(p, start=10, end=20))
    assert len(subset) == 10
    # 帧号必须连续且正确
    assert [i for i, _ in subset] == list(range(10, 20))


def test_iter_frames_raises_on_unreadable(tmp_path: Path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(RuntimeError):
        list(iter_frames(bad))


# ---------------------------------------------------------------------------
# 镜头运动估计
# ---------------------------------------------------------------------------

def test_static_camera_is_detected_as_fixed(tmp_path: Path):
    """固定机位应当判为 fixed，而不是误报为跟踪拍摄。"""
    p = make_video(tmp_path / "static.mp4", frame_count=40, fps=30.0,
                   moving=False)
    level, shift, notes = estimate_camera_motion(p, sample_step=2)

    assert level in ("fixed", "slight_pan"), (
        f"固定机位被误判为 {level}（位移 {shift:.2f} px）"
    )
    assert notes


def test_moving_camera_is_detected_as_panning(tmp_path: Path):
    """
    画面整体平移时必须判出跟踪拍摄。
    这个判定的意义：跟踪拍摄下绝对速度不可测（无法区分是人动还是镜头动），
    漏判会让报告给出错误的位移数据。
    """
    p = make_video(tmp_path / "pan.mp4", frame_count=40, fps=30.0,
                   moving=True)
    level, shift, _ = estimate_camera_motion(p, sample_step=2)

    assert level in ("slight_pan", "strong_pan"), (
        f"明显的镜头平移被误判为 {level}（位移 {shift:.2f} px）"
    )


def test_camera_motion_notes_explain_consequence():
    """判出跟踪拍摄时，说明必须包含对指标可用性的影响，而不只是标签。"""
    v = verify_fps(240.0, 2400, 2400)
    assert v.status == "verified"
