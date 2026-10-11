"""
GPU 推理自检：确认姿态模型能加载并跑通。

用法：
    python scripts/check_gpu_pose.py

做三件事：
  1. 确认 CUDA 可用（否则逐帧推理会慢到无法接受）
  2. 下载/加载 YOLOv8-pose 模型（缓存在 D 盘，不占 C 盘）
  3. 用一张合成图跑一次推理，测出每帧耗时

为什么要有这个脚本：
    环境问题（CUDA 版本不匹配、模型下载失败、显存不足）
    往往在跑完整分析时才暴露，而那时已经等了很久。
    这里花十几秒就能确认，避免浪费时间。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.paths import MODELS_DIR, apply_env_defaults, ensure_cache_dirs

# 缓存与模型都在项目内。必须在导入 torch / ultralytics 之前设好。
apply_env_defaults()
ensure_cache_dirs()

MODEL_DIR = MODELS_DIR


def main() -> int:
    print("=" * 68)
    print("GPU 姿态推理自检")
    print("=" * 68)
    print()

    failures: list[str] = []

    # ---- 1. torch / CUDA ----
    try:
        import torch
    except ImportError:
        print("[FAIL] 未安装 torch。跑：")
        print("       python -m pip install torch torchvision "
              "--index-url https://download.pytorch.org/whl/cu124")
        return 1

    print(f"torch        {torch.__version__}")
    if torch.cuda.is_available():
        print(f"CUDA         {torch.version.cuda}")
        print(f"GPU          {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info()
        print(f"显存         可用 {free / 1024**3:.1f} / {total / 1024**3:.1f} GB")
        if free / 1024**3 < 1.0:
            failures.append("显存可用不足 1 GB，推理可能失败")
    else:
        failures.append(
            "CUDA 不可用，只能走 CPU。逐帧推理会慢到无法接受"
            "（几百帧可能要几分钟到几十分钟）。"
            "请确认装了 CUDA 版 torch 且有可用的 NVIDIA 显卡。"
        )
        print("CUDA         不可用（将退回 CPU）")

    print()

    # ---- 2. ultralytics ----
    try:
        from ultralytics import YOLO
        import ultralytics
        print(f"ultralytics  {ultralytics.__version__}")
    except ImportError:
        print("[FAIL] 未安装 ultralytics。跑：")
        print("       python -m pip install ultralytics")
        return 1

    from ultralytics.utils import USER_CONFIG_DIR
    print(f"配置目录     {USER_CONFIG_DIR}")
    # 判据是"在项目内"，不是"不在 C 盘" ——
    # 因为项目要求所有生成物都落在 YUcoach 里，
    # 而 D 盘只是恰好装了 YUcoach。
    if ROOT.resolve() not in Path(USER_CONFIG_DIR).resolve().parents:
        failures.append(
            f"Ultralytics 配置目录不在项目内（{USER_CONFIG_DIR}）。"
            f"它应当位于 {MODELS_DIR.parent / 'ultralytics'}。"
            f"检查是否漏了 apply_env_defaults() 调用。"
        )
    print()

    # ---- 3. 模型 ----
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_name = "yolov8n-pose.pt"   # nano 版：先验证链路，精度够再换 s/m
    model_path = MODEL_DIR / model_name

    print(f"模型         {model_name}")
    print(f"存放位置     {model_path}")
    if model_path.exists():
        size_mb = model_path.stat().st_size / 1024**2
        print(f"             已存在（{size_mb:.1f} MB）")
    else:
        print("             首次运行，正在下载（约 6 MB）...")

    # 在 D 盘目录下工作，让 ultralytics 把权重下到这里
    cwd = os.getcwd()
    try:
        os.chdir(MODEL_DIR)
        t0 = time.time()
        model = YOLO(model_name)
        load_s = time.time() - t0
        print(f"             加载完成（{load_s:.1f} 秒）")

        # 权重可能被下到别处，归位
        downloaded = MODEL_DIR / model_name
        if not downloaded.exists():
            print(f"             [WARN] 权重未落在 {MODEL_DIR}")
    except Exception as e:
        print(f"[FAIL] 模型加载失败：{e}")
        print()
        print("可能原因：网络无法访问 GitHub（ultralytics 的默认下载源）。")
        print("可手动下载 yolov8n-pose.pt 放到：")
        print(f"  {MODEL_DIR}")
        return 1
    finally:
        os.chdir(cwd)

    print()

    # ---- 4. 跑一次真实推理 ----
    import numpy as np
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # 合成一张图。纯色图检不出人，但足以验证推理链路与设备可用性。
    dummy = np.full((720, 1280, 3), 200, dtype=np.uint8)

    print(f"推理设备     {device}")
    print("跑一次推理...")

    try:
        t0 = time.time()
        results = model.predict(dummy, device=device, verbose=False)
        first_s = time.time() - t0
        print(f"  首次推理   {first_s * 1000:.0f} ms（含预热）")

        # 再跑几次取均值，避开首次的初始化开销
        times = []
        for _ in range(5):
            t0 = time.time()
            model.predict(dummy, device=device, verbose=False)
            times.append(time.time() - t0)

        mean_ms = sum(times) / len(times) * 1000
        print(f"  平均       {mean_ms:.0f} ms/帧")
        print()

        # 推算一段真实素材的耗时
        for fps, dur in ((240, 5), (240, 10), (120, 10)):
            frames = fps * dur
            est = frames * mean_ms / 1000
            print(f"  {fps} fps × {dur} 秒 = {frames:5d} 帧  ->  约 {est:6.1f} 秒")

        print()
        print(f"检出结果      {len(results)} 个（合成图检出 0 个是正常的）")
        _ = results

    except Exception as e:
        print(f"[FAIL] 推理失败：{e}")
        if "out of memory" in str(e).lower():
            print("       显存不足。可改用更小的模型或降低推理分辨率。")
        return 1

    print()
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        return 1

    print("[OK] GPU 姿态推理链路正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
