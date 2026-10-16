"""
基于 Ultralytics YOLO 的姿态提取器。

这是 PoseEstimator 接口的一个具体实现。将来换成自己训练的模型时，
新增一个实现类即可，上层代码（指标计算、报告生成）一行不动。

⚠️ 关于足部关键点：
   YOLOv8-pose 输出 COCO-17，**没有脚跟与脚尖**。
   而契约要求 16 点包含足部，且触地时间、步频都依赖它。
   所以足部点由 keypoint_map 几何推导 —— 这会降低精度，
   具体影响见 keypoint_map.derive_foot_points 的说明。
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ..paths import configure_ultralytics_settings
from .keypoint_map import coco17_to_yu16
from .pose_types import PoseEstimator, PoseFrame, PoseSequence

# 模型权重放在项目内的 .cache/ 下，不散落到项目外。
#
# ⚠️ 路径以本文件位置为锚点推导，不用相对路径也不用绝对路径：
#     · 相对路径依赖"当前工作目录"，而服务端/CLI/测试的 cwd 各不相同
#     · 硬编码绝对路径换机器就废
#     parents[2] = backend/analysis/pose_estimator.py -> backend -> 仓库根
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _PROJECT_ROOT / ".cache"

DEFAULT_MODEL_DIR = _CACHE_DIR / "models"

#: ultralytics 的配置目录（它默认写 C:\Users\<用户>\AppData\Roaming\Ultralytics）
YOLO_CONFIG_PATH = _CACHE_DIR / "ultralytics"


class YoloPoseEstimator(PoseEstimator):
    """
    YOLOv8-pose 姿态提取。

    参数
    ----
    model_name : 权重文件名或路径。默认 yolov8n-pose.pt（nano，最快）。
                 验证链路用 nano，追求精度可换 s/m 版 —— 代价是速度。
    device : 'cuda' | 'cpu' | None（自动）
    imgsz : 推理分辨率。提高能改善小目标（远处的人）的检测，
            但耗时线性增长。
    conf : 人体检测置信度阈值。
    """

    name = "yolov8-pose"
    version = "8.4.173"
    provides_foot_keypoints = False   # COCO-17 没有足部点

    def __init__(
        self,
        model_name: str = "yolov8n-pose.pt",
        device: str | None = None,
        imgsz: int = 960,
        conf: float = 0.35,
        verbose: bool = False,
    ):
        # 强制 ultralytics 的配置走项目内的 .cache/。
        #
        # ⚠️ 用直接赋值而不是 setdefault：开发机上可能残留旧的
        #    用户级环境变量（历史上指向 D:\model_cache），
        #    setdefault 会让那个旧值优先，配置就写到项目外去了。
        YOLO_CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        os.environ["YOLO_CONFIG_DIR"] = str(YOLO_CONFIG_PATH)

        from ultralytics import YOLO
        import ultralytics

        self.version = ultralytics.__version__

        # ultralytics 的 datasets_dir / weights_dir / runs_dir 不受
        # 环境变量控制，默认会在当前工作目录建文件夹。必须显式改掉。
        configure_ultralytics_settings()

        self.model_name = model_name
        self.imgsz = imgsz
        self.conf = conf
        self.verbose = verbose

        if device is None:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        # 权重文件优先在 D 盘找。找不到才让 ultralytics 去下载，
        # 并把它引导到 D 盘目录，避免落到 C 盘。
        DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        local = DEFAULT_MODEL_DIR / model_name
        if local.exists():
            self._model = YOLO(str(local))
        else:
            cwd = os.getcwd()
            try:
                os.chdir(DEFAULT_MODEL_DIR)
                self._model = YOLO(model_name)
            finally:
                os.chdir(cwd)

        # 记录实际使用的权重路径，写入报告用于溯源
        try:
            self.weights_path = str(Path(self._model.ckpt_path))
        except Exception:
            self.weights_path = model_name
        self.model_config = f"weights={Path(self.weights_path).name}; imgsz={self.imgsz}"

    # ------------------------------------------------------------------

    def estimate(self, frame_bgr: np.ndarray, frame_index: int) -> PoseFrame | None:
        """处理单帧。未检出人体时返回 None。"""
        results = self._model.predict(
            frame_bgr,
            device=self.device,
            imgsz=self.imgsz,
            conf=self.conf,
            verbose=self.verbose,
        )
        if not results:
            if getattr(self, "target_lock", None) is not None:
                self.target_lock.select(frame_bgr, frame_index, np.empty((0, 4)))
            return None

        r = results[0]
        if r.keypoints is None or len(r.keypoints) == 0:
            if getattr(self, "target_lock", None) is not None:
                self.target_lock.select(frame_bgr, frame_index, np.empty((0, 4)))
            return None

        h, w = frame_bgr.shape[:2]

        # Explicit selection uses persistent association. The legacy area
        # fallback is only retained for callers that supplied no target.
        kp_xy = r.keypoints.xy.cpu().numpy()        # (N, 17, 2) 像素坐标
        kp_conf = r.keypoints.conf
        if kp_conf is None:
            kp_conf = np.ones(kp_xy.shape[:2], dtype=np.float32)
        else:
            kp_conf = kp_conf.cpu().numpy()

        boxes = r.boxes
        if boxes is not None and len(boxes) >= 1:
            xyxy = boxes.xyxy.cpu().numpy()
            areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1])
            lock = getattr(self, "target_lock", None)
            if lock is not None:
                candidates = xyxy.astype(float, copy=True)
                # Do not associate a box whose torso pose is effectively absent.
                candidates[np.min(kp_conf[:, [5, 6, 11, 12]], axis=1) < .3] = np.nan
                pick = lock.select(frame_bgr, frame_index, candidates)
            else:
                pick = int(np.argmax(areas))
            person_conf = float(boxes.conf[pick].cpu().numpy())
            b = xyxy[pick]
            bbox = (b[0] / w, b[1] / h, b[2] / w, b[3] / h)
        else:
            if getattr(self, "target_lock", None) is not None:
                self.target_lock.select(frame_bgr, frame_index, np.empty((0, 4)))
            pick = 0
            person_conf = None
            bbox = None

        # 归一化到 [0,1]，与契约的坐标系一致（原点左上，y 向下）
        coco = np.zeros((17, 3), dtype=np.float64)
        coco[:, 0] = np.clip(kp_xy[pick, :, 0] / w, 0.0, 1.0)
        coco[:, 1] = np.clip(kp_xy[pick, :, 1] / h, 0.0, 1.0)
        coco[:, 2] = kp_conf[pick]

        return coco17_to_yu16(
            coco,
            frame_index=frame_index,
            person_conf=person_conf,
            bbox=bbox,
            derive_feet=True,
        )

    # ------------------------------------------------------------------

    def estimate_sequence(self, frames, progress=None) -> PoseSequence:
        """
        处理整段视频。

        覆盖基类的逐帧实现，加上进度回调 —— 处理 2400 帧要花一分多钟，
        没有进度提示会让人以为卡死了。
        """
        seq = PoseSequence(
            estimator_name=self.name,
            estimator_version=self.version,
            model_config=self.model_config,
        )
        seq.notes.append(
            f"姿态模型 {self.name}（{Path(self.weight_file).name}）"
            f"不提供足部关键点，heel/toe 由踝关节与小腿朝向几何推导。"
            f"触地时刻的判定精度因此下降，"
            f"相关指标的置信度会被标注为存疑。"
        )
        seq.notes.append(f"推理设备 {self.device}，输入分辨率 {self.imgsz}")

        count = 0
        missed = 0
        for idx, bgr in frames:
            pf = self.estimate(bgr, idx)
            if pf is None:
                missed += 1
            else:
                seq.frames.append(pf)
            count += 1
            if progress is not None:
                progress(count, idx, missed)

        if missed:
            seq.notes.append(
                f"有 {missed} 帧未检出人体（占 {missed / max(count, 1) * 100:.1f}%），"
                f"这些帧不参与计算。"
            )

        from .pose_types import interpolate_gaps
        return interpolate_gaps(seq)

    @property
    def weight_file(self) -> str:
        return str(getattr(self, "weights_path", self.model_name))
