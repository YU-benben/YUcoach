"""
基于 rtmlib（RTMPose / Halpe26）的姿态提取器。

## 为什么需要它

现有 `YoloPoseEstimator` 用 YOLOv8-pose，输出 COCO-17 —— **没有足部点**。
而契约要求的 16 点里必须含 `heel` / `toe`：触地、离地、步频切分全靠它们。
之前只能靠 `keypoint_map.derive_foot_points()` 几何推导，而那个函数自己
写明了后果：

    假定"足部与小腿呈 90°"，而蹬离期踝关节跖屈可达 120° 以上 ——
    误差恰好落在最关键的触地/离地时刻。

Halpe26 骨干**直接输出趾尖与足跟**，从根本上解决这个问题。
切换后 16 点里有 13 个是实测量（原先只有 9 个，另 7 个靠推导）。

## 与 YoloPoseEstimator 的关系

两者都实现 `PoseEstimator` 接口，**上层（指标计算、报告生成）一行不用改**。
默认仍走 YOLO —— 换模型要显式指定，避免历史报告的数字被静默改变。

## ⚠️ 两个实测得到的注意点（2026-10-11）

1. **rtmlib 不返回人体框**。所以契约里的 `bbox` 字段留空；
   选人只能靠关键点自身算出的尺度，不能用包围盒面积。

2. **一帧可能检出多个人**（样例素材上实测检出 7 个）。
   rtmlib 没有内置选人，必须自己实现 —— 这里的策略是
   **取"躯干最高"的那个**（肩中点到髋中点的像素距离）。
   比包围盒面积稳：远侧的人框可能更宽但更矮。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..paths import apply_env_defaults, ensure_cache_dirs
from .keypoint_map import HALPE26_NAMES, halpe26_to_yu16
from .pose_types import PoseEstimator, PoseFrame, PoseSequence

#: rtmlib 的输出关键点数。改了这里说明模型换了，映射表也要跟着改。
HALPE_KEYPOINT_COUNT = 26


class RtmPoseEstimator(PoseEstimator):
    """
    rtmlib 的 RTMPose + Halpe26 姿态提取（含足部点）。

    参数
    ----
    mode : 'lightweight' | 'balanced' | 'performance'
           对应 rtmlib 的三档权重。默认 lightweight，理由是实测速度差：

               lightweight   30 帧 2.64s（332 帧约 29s）
               balanced      30 帧 17.2s（332 帧约 190s）

           **差 6.5 倍**，而两者都能给出足部点 —— 换模型的首要目的是
           "拿到实测趾尖/足跟"，不是把关键点做到极致。
           要精度时再显式传 'balanced'。

           端到端实测（332 帧素材）：
               yolo（GPU）            7.9 秒
               rtm lightweight       45.6 秒
               rtm balanced         214.8 秒

    device : 'cpu' | 'cuda' | None（自动）
             ⚠️ rtmlib 的 device 语义与 torch 不同：
                'cpu' / 'cuda' 是**计算设备**，不是后端。
             ⚠️ 'cuda' 需要 onnxruntime-gpu，且它对 CUDA 版本有要求。
                本机实测：onnxruntime-gpu 1.31 要 **CUDA 13 + cuDNN 9**，
                而 torch 装的是 CUDA 12.6 前缀 —— 所以即使
                `get_available_providers()` 里列出了 CUDA，
                实际创建 provider 时也会失败并**静默退回 CPU**：

                    Failed to create CUDAExecutionProvider.
                    Require cuDNN 9.* and CUDA 13.*

                这一点很坑：provider 列表里有 CUDA ≠ 能用。
                所以判断不能只看列表，要真跑一次看日志。
                目前结论：**rtm 提取器实际跑在 CPU 上**。
                对有 GPU 版 torch 的 YOLO 路径没有影响（两者互不相干）。
    backend : 'onnxruntime' | 'openvino' | 'opencv'
    """

    name = "rtmpose-halpe26"
    version = "0.0.16"
    provides_foot_keypoints = True   # ✅ 这是换它的全部理由

    def __init__(
        self,
        mode: str = "lightweight",
        device: str | None = None,
        backend: str = "onnxruntime",
        verbose: bool = False,
    ):
        # 缓存目录必须先就位：rtmlib 下载权重时会落到 TORCH_HOME，
        # 而那个变量由 apply_env_defaults() 接管到项目内。
        # 不先调用的话，权重会落到当前工作目录（踩过这个坑）。
        apply_env_defaults()
        ensure_cache_dirs()

        from rtmlib import BodyWithFeet

        self.mode = mode
        self.backend = backend
        self.verbose = verbose

        if device is None:
            device = self._detect_device(backend)
        self.device = device

        self._model = BodyWithFeet(
            mode=mode,
            to_openpose=False,     # 保持 COCO/Halpe 原生顺序，便于对映射表
            backend=backend,
            device=device,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _detect_device(backend: str) -> str:
        """
        自动挑计算设备。

        为什么必须探测而不是写死 'cuda'：
            没装 onnxruntime-gpu 时，传 'cuda' 给 rtmlib 不一定报错 ——
            可能静默退回 CPU。而 CPU 比 GPU 慢约 80 倍，
            表现为"分析卡住"，很难联想到是 provider 缺失。
            所以这里先查 provider 列表，再决定传什么。
        """
        if backend != "onnxruntime":
            # openvino / opencv 后端各有自己的设备名，不在这里猜
            return "cpu"
        try:
            import onnxruntime as ort
            if "CUDAExecutionProvider" in ort.get_available_providers():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    # ------------------------------------------------------------------

    def estimate(self, frame_bgr: np.ndarray, frame_index: int) -> PoseFrame | None:
        """处理单帧。未检出人体时返回 None。"""
        keypoints, scores = self._model(frame_bgr)

        kp = np.asarray(keypoints, dtype=np.float64)
        sc = np.asarray(scores, dtype=np.float64)
        if kp.size == 0 or kp.shape[-2] != HALPE_KEYPOINT_COUNT:
            return None

        h, w = frame_bgr.shape[:2]

        # 多人时选一个。rtmlib 不给人体框，所以用躯干高度当尺度。
        pick = self._pick_person(kp, sc)
        if pick is None:
            return None

        # 归一化到 [0,1]，与契约坐标系一致（原点左上，y 向下）
        halpe = np.zeros((HALPE_KEYPOINT_COUNT, 3), dtype=np.float64)
        halpe[:, 0] = np.clip(kp[pick, :, 0] / w, 0.0, 1.0)
        halpe[:, 1] = np.clip(kp[pick, :, 1] / h, 0.0, 1.0)
        halpe[:, 2] = sc[pick]

        # person_conf：契约字段，rtmlib 不提供整体置信度。
        # 用工整性最好的折中 —— 取核心关节置信度的中位数，
        # 而不是 0 或 None，否则报告里这一项会长期是空的。
        core = [5, 6, 11, 12, 13, 14, 15, 16]      # 双肩/双髋/双膝/双踝
        person_conf = float(np.median(halpe[core, 2]))

        return halpe26_to_yu16(
            halpe,
            frame_index=frame_index,
            person_conf=person_conf,
            bbox=None,          # rtmlib 不返回人体框
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _pick_person(
        kp: np.ndarray,
        sc: np.ndarray,
        min_conf: float = 0.25,
    ) -> int | None:
        """
        从多人里选一个，返回其索引；都不合格时返回 None。

        依据：**躯干像素高度最大** —— 即「肩中点 → 髋中点」的垂直距离。

        为什么不用关键点包围盒：
            · 远侧的人可能有更宽的框（手臂张开），但离镜头更远、更矮
            · 包围盒还受检出的四肢外扩影响，抖动大
            躯干高度直接反映"离镜头多近"，且对姿态变化不敏感。

        为什么不直接用检测框面积（像 YoloPoseEstimator 那样）：
            rtmlib 不返回框，没有这个信息可用。
        """
        if kp.ndim != 3 or kp.shape[0] == 0:
            return None

        best_idx: int | None = None
        best_height = 0.0

        for i in range(kp.shape[0]):
            ls, rs = kp[i, 5], kp[i, 6]
            lh, rh = kp[i, 11], kp[i, 12]
            # 四个点都要够可信才算得出躯干
            if min(sc[i, 5], sc[i, 6], sc[i, 11], sc[i, 12]) < min_conf:
                continue
            shoulder_y = (ls[1] + rs[1]) / 2.0
            hip_y = (lh[1] + rh[1]) / 2.0
            torso = abs(hip_y - shoulder_y)
            if torso > best_height:
                best_height = torso
                best_idx = i

        # 一个人都没过阈值时，退回"置信度总和最高"的那个，
        # 而不是返回 None —— 否则低质量素材会整段没有姿态数据，
        # 上层反而看不出是"检出质量差"还是"没有素材"。
        if best_idx is None:
            totals = sc.sum(axis=1)
            if totals.size and float(totals.max()) > 0:
                return int(np.argmax(totals))
            return None

        return best_idx

    # ------------------------------------------------------------------

    def estimate_sequence(self, frames, progress=None) -> PoseSequence:
        """处理整段视频，带进度回调。"""
        seq = PoseSequence(
            estimator_name=self.name,
            estimator_version=self.version,
        )
        seq.notes.append(
            f"姿态模型 {self.name}（rtmlib {self.version}，{self.mode} 权重）"
            f"**提供实测足部关键点**（Halpe26 的第 20/21 大趾、22/23 小趾、"
            f"24/25 足跟）。heel/toe 不再是几何推导值，"
            f"触地/离地时刻的判定精度因此提升。"
        )
        seq.notes.append(f"推理设备 {self.device}，后端 {self.backend}")

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
        """权重标识。rtmlib 内部管理下载，这里只给出可溯源的描述。"""
        return f"rtmlib/{self.name}/{self.mode}"
