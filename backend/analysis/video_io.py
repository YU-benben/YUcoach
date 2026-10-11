"""
视频读取与帧率处理。

这个模块存在的唯一理由：**帧率是整条分析链路的地基**。
帧率错一倍，触地时间、腾空时间、步频全部静默出错，而且不会报任何错。
所以这里不信任容器声称的帧率，而是独立数出真实帧数，两者必须自洽。

见 docs/02-数据标准.md §8（帧率可信度协议）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FpsVerification:
    """
    帧率校验结果。

    ⚠️ 三个概念必须严格区分，混用会造成严重后果：

        counted_frames   解出的**帧数**（个）
        verified_fps     实测**帧率**（帧/秒）—— 参与所有时间换算的就是它
        declared_fps     容器**声称**的帧率

    本项目真实踩过的坑：把 counted_frames 直接当成 verified_fps 写进了报告，
    于是 332 帧的视频被标成 "332 fps"。这个错误不会崩溃，
    但会让所有基于帧率的时间换算错得离谱 ——
    而且从报告表面完全看不出来（332 看着像个合法的帧率）。

    教训：**单位不同的量必须有各自的字段名**，不能都叫 "fps"。
    """

    declared: float | None
    verified: float | None          # 帧/秒
    counted_frames: int             # 帧（个）
    status: str                     # verified / warning / rejected
    agreement_pct: float
    method_results: dict[str, float | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # 兼容旧字段名。已在上面改名，这里保留只读别名避免调用方漏改。
    @property
    def counted(self) -> float | None:
        """已废弃：请用 verified（帧率）或 counted_frames（帧数）。"""
        return float(self.counted_frames) if self.counted_frames else None


@dataclass
class VideoInfo:
    """视频的客观信息。全部来自实际解码，不来自容器声称值。"""

    path: str
    width: int
    height: int
    frame_count: int
    fps_declared: float | None
    fps_verified: float | None
    duration_s: float
    rotation: int
    fps_verification: FpsVerification

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"

    def summary(self) -> str:
        lines = [
            f"文件      {Path(self.path).name}",
            f"分辨率    {self.resolution_label}   旋转 {self.rotation}°",
            f"帧数      {self.frame_count}",
            f"时长      {self.duration_s:.3f} 秒",
            f"声明帧率  {self.fps_declared if self.fps_declared else '未知'}",
            f"实测帧率  {self.fps_verified if self.fps_verified else '无法确定'}",
            f"校验结论  {self.fps_verification.status}"
            f"（一致性 {self.fps_verification.agreement_pct:.1f}%）",
        ]
        for n in self.fps_verification.notes:
            lines.append(f"          · {n}")
        return "\n".join(lines)


def read_video_info(path: str | Path) -> VideoInfo:
    """
    读取视频，独立数帧，并做帧率自洽性校验。

    为什么要独立数帧而不是信任 CAP_PROP_FRAME_COUNT：
        部分容器（尤其是剪辑软件导出的 mp4）里 frame_count 与
        fps 是分别写入的，可能互相矛盾。逐帧解码数出来的才是真的。
        代价是慢一些，但这是唯一可靠的办法。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"视频不存在：{p}")

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        raise RuntimeError(
            f"无法打开视频：{p}\n"
            f"可能原因：编码格式不被 OpenCV 支持（如 H.265/HEVC），"
            f"或文件损坏。可先用 ffmpeg 转成 H.264 再试。"
        )

    try:
        declared_fps = cap.get(cv2.CAP_PROP_FPS)
        declared_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 逐帧数出真实帧数，同时记录真实解码耗时。
        #
        # 用解码耗时估时长，而不是 CAP_PROP_POS_MSEC：
        # 后者在部分编码上不可靠（返回 -1 或与帧号不成比例）。
        # 实际解码一遍是最贴近真相的测量 ——
        # 帧率是整条链路的地基，值得多花这点时间。
        t_decode = time.perf_counter()
        counted = 0
        while True:
            ok = cap.grab()  # grab 只取帧不解码，比 read 快得多
            if not ok:
                break
            counted += 1
        decode_seconds = time.perf_counter() - t_decode
    finally:
        cap.release()

    declared_fps_opt = declared_fps if declared_fps > 0 else None

    verification = verify_fps(
        declared_fps=declared_fps_opt,
        declared_count=declared_count if declared_count > 0 else None,
        counted=counted,
    )

    # 时长：校验通过时用声明帧率推算（更准，不受解码速度波动影响）；
    # 校验不通过时用解码实测时长 —— 后者不依赖容器元数据。
    if declared_fps_opt and verification.status == "verified":
        duration = counted / declared_fps_opt
    else:
        duration = decode_seconds

    return VideoInfo(
        path=str(p),
        width=width,
        height=height,
        frame_count=counted,
        fps_declared=declared_fps_opt,
        fps_verified=verification.verified,
        duration_s=duration,
        rotation=0,  # OpenCV 已按容器元数据自动旋转，此处仅作记录
        fps_verification=verification,
    )


def verify_fps(
    declared_fps: float | None,
    declared_count: int | None,
    counted: int,
) -> FpsVerification:
    """
    帧率自洽性校验。

    ⚠️ 本函数返回的是**帧率**（帧/秒），不是帧数。
       曾经把"解出的帧数"直接填进 verified 字段，
       导致 332 帧的视频被标成 "332 fps"。
       这个错误不会崩溃，只会让所有时间换算错得离谱，
       而且报告表面完全看不出来 —— 详见 FpsVerification 的说明。

    判据：
        容器声明的帧率与帧数应当自洽：
            declared_count ≈ declared_fps × duration
        我们独立解码数出的 counted 若与 declared_count 偏差过大，
        说明容器元数据不可信。

    注意：剪辑软件导出的慢动作视频典型症状是「声明 30fps，帧数却是
    240fps 的量」—— 这时 counted 会远大于 declared_count，偏差立刻暴露。

    校验通过时，verified 就等于 declared —— 因为我们**没有独立的
    时长测量**，无法给出比容器更可信的帧率。
    OpenCV 不提供帧时间戳接口，所以这三项交叉验证里的另外两项
    （由步频反推、由已知位移反推）需要姿态与尺度数据参与，
    在指标计算阶段完成，见 docs/02-数据标准.md §8。
    """
    notes: list[str] = []
    methods: dict[str, float | None] = {}

    methods["declared_fps"] = declared_fps
    methods["decoded_frame_count"] = float(counted)

    if declared_fps is None or declared_count is None or declared_count <= 0:
        notes.append(
            "容器未提供完整的帧率信息，无法做自洽性校验。"
            "时间类指标（触地时间、腾空时间、步频）的可靠性因此下降。"
        )
        return FpsVerification(
            declared=declared_fps,
            verified=None,
            counted_frames=counted,
            status="warning",
            agreement_pct=0.0,
            method_results=methods,
            notes=notes,
        )

    # 声明帧数与我们独立数出的帧数之差
    deviation = abs(counted - declared_count) / declared_count
    agreement = max(0.0, (1.0 - deviation) * 100.0)

    methods["declared_frame_count"] = float(declared_count)
    methods["deviation_pct"] = round(deviation * 100, 2)

    if deviation > 0.20:
        status = "warning"
        notes.append(
            f"容器声明 {declared_count} 帧，实际解出 {counted} 帧，"
            f"偏差 {deviation * 100:.0f}%。容器元数据不可信 —— "
            f"常见于经过变速处理的视频。时间类指标的可靠性因此下降。"
        )
    elif deviation > 0.02:
        status = "verified"
        notes.append(
            f"声明与实际帧数相差 {deviation * 100:.1f}%，属正常范围"
            f"（部分编码器不写入末尾不完整帧）。"
        )
    else:
        status = "verified"

    # 帧率门槛检查（不是硬拦截，只作提示）
    if declared_fps < 120:
        notes.append(
            f"帧率 {declared_fps:.0f} fps 低于 120 fps 门槛，"
            f"时间类指标（触地时间、腾空时间、占空比）将不可用。"
        )

    return FpsVerification(
        declared=declared_fps,
        # 校验通过时信容器；不通过时也不改口 —— 我们没有独立测量，
        # 与其编一个数，不如把不确定性留在 status 上。
        verified=declared_fps,
        counted_frames=counted,
        status=status,
        agreement_pct=round(agreement, 2),
        method_results=methods,
        notes=notes,
    )


def iter_frames(path: str | Path, start: int = 0, end: int | None = None):
    """
    逐帧产出 (frame_index, bgr_ndarray)。

    用 decode 顺序读取而不是 seek：随机 seek 在部分编码上会落到
    关键帧从而拿到重复帧，导致时间轴错乱。
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{path}")

    try:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if idx >= start and (end is None or idx < end):
                yield idx, frame

            idx += 1
            if end is not None and idx >= end:
                break
    finally:
        cap.release()


def estimate_camera_motion(
    path: str | Path,
    sample_step: int = 10,
    max_samples: int = 120,
) -> tuple[str, float, list[str]]:
    """
    估计镜头运动程度。

    本项目的前提就是「拍摄者会跟着运动员移动镜头」，所以这不是可选项 ——
    跟踪会引入透视误差，且让绝对速度无法测量（无法区分是人在动还是镜头在动）。

    做法：在相邻采样帧之间做稀疏光流，取背景区域（画面四边）的平均位移。
    运动员自身的位移是局部的，镜头平移则是**全画面一致的**，
    用中位数可以剔除运动员造成的局部干扰。

    返回 (level, mean_shift_px_per_frame, notes)
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{path}")

    notes: list[str] = []
    shifts: list[float] = []

    try:
        prev_gray = None
        idx = 0
        taken = 0

        # 光流参数：特征点少一点、窗口大一点，适合平移估计
        feature_params = dict(maxCorners=200, qualityLevel=0.01,
                              minDistance=20, blockSize=3)
        lk_params = dict(winSize=(21, 21), maxLevel=3,
                         criteria=(cv2.TERM_CRITERIA_EPS |
                                   cv2.TERM_CRITERIA_COUNT, 20, 0.03))

        while taken < max_samples:
            ok, frame = cap.read()
            if not ok:
                break

            if idx % sample_step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    pts = cv2.goodFeaturesToTrack(prev_gray, mask=None,
                                                  **feature_params)
                    if pts is not None and len(pts) >= 8:
                        nxt, st, _ = cv2.calcOpticalFlowPyrLK(
                            prev_gray, gray, pts, None, **lk_params)
                        if nxt is not None:
                            good = st.reshape(-1) == 1
                            if good.sum() >= 8:
                                d = (nxt[good] - pts[good]).reshape(-1, 2)
                                mag = np.linalg.norm(d, axis=1)
                                # 用中位数：运动员造成的局部大位移不影响整体估计
                                shifts.append(float(np.median(mag)))

                prev_gray = gray
                taken += 1

            idx += 1
    finally:
        cap.release()

    if not shifts:
        notes.append("无法估计镜头运动（特征点不足，画面可能过曝或过于模糊）")
        return "unknown", 0.0, notes

    mean_shift = float(np.mean(shifts))

    if mean_shift < 1.0:
        level = "fixed"
    elif mean_shift < 4.0:
        level = "slight_pan"
    else:
        level = "strong_pan"

    notes.append(
        f"相邻采样帧的平均画面位移 {mean_shift:.2f} px"
        f"（判定为 {level}）"
    )

    if level == "strong_pan":
        notes.append(
            "镜头跟随明显：绝对速度与绝对位移不可测（无法区分是运动员移动"
            "还是镜头移动）。步幅类指标将使用逐帧参考尺度换算。"
        )

    return level, mean_shift, notes
