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

import os
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
               yolo（torch CUDA）              7.9 秒
               rtm lightweight（onnxruntime CUDA） 11.9 秒
               rtm lightweight（退回 CPU）      45.6 秒
               rtm balanced（退回 CPU）        214.8 秒

    device : 'cpu' | 'cuda' | None（自动）
             ⚠️ rtmlib 的 device 语义与 torch 不同：
                'cpu' / 'cuda' 是**计算设备**，不是后端。
             ⚠️ 'cuda' 需要 onnxruntime-gpu，且**版本要与 CUDA 匹配**：

                onnxruntime-gpu 1.31  要 CUDA 13  ❌ 本机是 CUDA 12.6
                onnxruntime-gpu 1.22  要 CUDA 12  ✅

                本机没装 CUDA Toolkit，但 **torch 自带 CUDA 运行库** ——
                代码里已把 torch/lib 前置到 DLL 搜索路径（见
                _prepare_cuda_dlls），所以**不需要单独装 CUDA Toolkit**。

                判断 provider 能否用的唯一可信方式是真建一个
                InferenceSession 看 get_providers()；
                get_available_providers() 只检查 DLL 能否加载，会误导。
    backend : 'onnxruntime' | 'openvino' | 'opencv'
             ⚠️ 'opencv' 后端要走 GPU 需自己编译带 CUDA 的 OpenCV
                （现在装的是 CPU 构建，cv2.cuda 设备数为 0）。不值得。
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
        self.model_config = f"mode={mode}"
        self.backend = backend
        self.verbose = verbose

        # ⚠️ 必须在 import onnxruntime 之前把 torch 的 CUDA DLL 加进搜索路径，
        #    否则 provider 创建失败并静默退回 CPU。理由见 _prepare_cuda_dlls。
        self.cuda_dll_dir = None
        if backend == "onnxruntime" and device != "cpu":
            self.cuda_dll_dir = self._prepare_cuda_dlls()

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
    def _prepare_cuda_dlls() -> str | None:
        """
        把 torch 自带的 CUDA 运行库借给 onnxruntime。

        ## 为什么需要这一步

        onnxruntime-gpu 需要 cuBLAS / cuDNN 等 **CUDA 运行库**，
        而本机没装 CUDA Toolkit。但 **torch 自带这些 DLL** ——
        它们在 `.venv/Lib/site-packages/torch/lib/` 下。

        Windows 加载器不会自动去那里找，于是 onnxruntime 找不到
        `cublasLt64_12.dll`，创建 CUDA provider 失败并**静默退回 CPU**：

            Failed to create CUDAExecutionProvider.
            Require cuDNN 9.* and CUDA 12.*

        实测（见 docs/14 §9.4）：只要把 torch/lib 前置到 PATH，
        provider 就能正常创建 —— **不需要单独安装 CUDA Toolkit**。

        ## ⚠️ 判断 provider 能不能用的唯一可信方式

        **不要用 `ort.get_available_providers()`。**
        它只检查 DLL 能否**加载**，不代表 provider 能**创建**。
        实测：它列出了 `CUDAExecutionProvider`，但会话实际建在 CPU 上。
        这个区别会让人以为 GPU 生效了。

        返回
        ----
        实际加进去的目录路径；不需要或失败时返回 None。
        """
        try:
            import torch
            torch_lib = Path(torch.__file__).parent / "lib"
            if not torch_lib.is_dir():
                return None
            # 前置到 PATH（而不是 append）—— 要优先于系统里可能存在的旧版本
            os.environ["PATH"] = (
                str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
            )
            # 再加一次 DLL 目录。两种方式都做，因为它们在不同
            # Windows 版本 / Python 版本上的可靠性不同。
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(torch_lib))
                except Exception:
                    pass
            return str(torch_lib)
        except Exception:
            return None

    @staticmethod
    def _detect_device(backend: str) -> str:
        """
        自动挑计算设备。

        为什么必须探测而不是写死 'cuda'：
            没装 onnxruntime-gpu 时，传 'cuda' 给 rtmlib 不一定报错 ——
            可能静默退回 CPU。而 CPU 慢得多（实测 lightweight 模式
            45 秒 vs GPU 预计数秒），表现为"分析很慢"，
            很难联想到是 provider 缺失。
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
            if getattr(self, "target_lock", None) is not None:
                self.target_lock.select(frame_bgr, frame_index, np.empty((0, 4)))
            return None

        h, w = frame_bgr.shape[:2]

        # 多人时选一个。rtmlib 不给人体框，所以用躯干高度当尺度。
        lock = getattr(self, "target_lock", None)
        if lock is not None:
            from .target_lock import keypoint_boxes
            boxes = keypoint_boxes(kp, sc)
            pick = lock.select(frame_bgr, frame_index, boxes)
        else:
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
            bbox=tuple((boxes[pick] / [w, h, w, h]).clip(0, 1)) if lock is not None else None,
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

        ## 判据：核心关节置信度最高

        核心关节 = 双肩 + 双髋 + 双膝 + 双踝。

        ## ⚠️ 为什么不用"躯干像素高度最大"（曾经的做法，已废弃）

        目视核对（docs/14 §9.7）发现：在真实素材上选错了人 ——
        关键点浮在半空中，不在任何人的脚上。

        原因是**躯干高度不能代表"离镜头近"**：
          · 远处站立行走的行人，躯干在画面里可能比近处蹲踞的
            运动员还长（蹲踞时躯干被透视压缩）
          · 结果是选中了背景里的行人

        也不能用包围盒面积：rtmlib 根本不返回人体框。

        置信度则是"模型自己认为像不像人"的直接信号 ——
        远处的小人、模糊的人、半个人，分数天然更低。
        实测在样例素材上明显更稳。

        ## 退回策略

        核心关节都不可信时，退回"全部 26 点里置信度最高的人"，
        而不是返回 None —— 否则低质量素材会整段没有姿态数据，
        上层看不出是"检出质量差"还是"根本没有素材"。
        """
        if kp.ndim != 3 or kp.shape[0] == 0:
            return None

        #: 核心关节索引。肩/髋/膝/踝各一对，缺一个都算不上一个人。
        core = (5, 6, 11, 12, 13, 14, 15, 16)
        n = kp.shape[0]

        # 每人的核心关节分数：取**最大值**而不是中位数。
        # 中位数会让"六个数都低"和"六个数都高"的人难以区分，
        # 而最大值直接反映"这个人的关节有多可信"。
        core_score = np.array(
            [float(sc[i, list(core)].max()) for i in range(n)]
        )

        order = np.argsort(-core_score)          # 从高到低
        for i in order:
            if core_score[i] < min_conf:
                break
            # 躯干四点齐全才算合格（否则算不出躯干，后面也用不了）
            if min(sc[i, 5], sc[i, 6], sc[i, 11], sc[i, 12]) < min_conf:
                continue
            return int(i)

        # 退回：全部点的置信度总和最高者
        totals = sc.sum(axis=1)
        if totals.size and float(totals.max()) > 0:
            return int(np.argmax(totals))
        return None

    # ------------------------------------------------------------------

    def estimate_sequence(self, frames, progress=None) -> PoseSequence:
        """处理整段视频，带进度回调。"""
        seq = PoseSequence(
            estimator_name=self.name,
            estimator_version=self.version,
            model_config=self.model_config,
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
