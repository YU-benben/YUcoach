"""
导出 yolov8n-pose 到 ONNX，并做三件事：

  1. **对拍**：ONNX 的输出必须和 PyTorch 一致。
     不一致的话，手机上和电脑上会算出两套不同的骨架 —— 这是最坏的情况。

  2. **测速**：CPU 推理速度。这是**手机速度的下限参考** ——
     手机有 NPU/GPU，通常比桌面 CPU 单线程快，但我们先用 CPU 拿个保守数字。

  3. **记录模型清单**：模型是可替换的，需要一个清单说明它是哪个版本、
     什么输入尺寸、有什么已知问题。否则换了模型没人知道差别在哪。

## 为什么导出两个输入尺寸

  960 —— 电脑上现在用的。和 .pt 对拍时必须用同一个尺寸，否则比不出真差异。
  640 —— 手机上打算用的。要单独测它掉多少精度。
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODELS = ROOT / ".cache" / "models"
OUT = ROOT / ".cache" / "models" / "exported"
OUT.mkdir(parents=True, exist_ok=True)

# 让 ultralytics 的配置目录落在项目内
import os
os.environ["YOLO_CONFIG_DIR"] = str(ROOT / ".cache" / "ultralytics")

PT = MODELS / "yolov8n-pose.pt"


def export_onnx(imgsz: int) -> Path | None:
    """导出指定输入尺寸的 ONNX。已存在则跳过。"""
    dst = OUT / f"yolov8n-pose-{imgsz}.onnx"
    if dst.exists():
        print(f"  [跳过] {dst.name} 已存在")
        return dst

    print(f"  导出 imgsz={imgsz} ...")
    from ultralytics import YOLO
    model = YOLO(str(PT))
    path = model.export(
        format="onnx",
        imgsz=imgsz,
        opset=12,          # 12 兼容性最好；更高版本部分手机运行时支持不全
        simplify=True,
        dynamic=False,     # 固定尺寸，手机端更快
    )
    produced = Path(path)
    if produced.exists() and produced != dst:
        produced.replace(dst)
    if dst.exists():
        print(f"  [OK] {dst.name}  {dst.stat().st_size / 1024 / 1024:.2f} MB")
        return dst
    print(f"  [FAIL] 导出后找不到文件：{path}")
    return None


def make_input(imgsz: int) -> np.ndarray:
    """造一个假输入。用固定随机种子，保证两边喂的是同一份数据。"""
    rng = np.random.default_rng(42)
    return rng.random((1, 3, imgsz, imgsz), dtype=np.float32)


def run_torch(imgsz: int, x: np.ndarray) -> tuple[np.ndarray, float]:
    """PyTorch 推理，返回 (输出, 单帧毫秒)。"""
    import torch
    from ultralytics import YOLO

    model = YOLO(str(PT))
    net = model.model
    net.eval()

    t = torch.from_numpy(x)
    with torch.no_grad():
        # 先跑几次热身，避免把首次的初始化算进去
        for _ in range(3):
            out = net(t)
        n = 10
        t0 = time.perf_counter()
        for _ in range(n):
            out = net(t)
        ms = (time.perf_counter() - t0) / n * 1000

    arr = out[0] if isinstance(out, (list, tuple)) else out
    return np.asarray(arr.detach().cpu().numpy()), ms


def run_onnx(path: Path, x: np.ndarray, providers: list[str]):
    """ONNX Runtime 推理，返回 (输出, 单帧毫秒, 实际用的 provider)。"""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(path), so, providers=providers)
    iname = sess.get_inputs()[0].name

    for _ in range(3):
        out = sess.run(None, {iname: x})
    n = 10
    t0 = time.perf_counter()
    for _ in range(n):
        out = sess.run(None, {iname: x})
    ms = (time.perf_counter() - t0) / n * 1000

    used = sess.get_providers()
    return np.asarray(out[0]), ms, used


def main() -> int:
    print("=" * 74)
    print("第一步：导出 ONNX")
    print("=" * 74)
    if not PT.exists():
        print(f"  [FAIL] 找不到 {PT}")
        return 1

    exported: dict[int, Path] = {}
    for sz in (960, 640):
        p = export_onnx(sz)
        if p:
            exported[sz] = p

    if not exported:
        print("  [FAIL] 一个都没导出成功")
        return 1

    print()
    print("=" * 74)
    print("第二步：对拍（ONNX 输出 vs PyTorch 输出）")
    print("=" * 74)
    print()
    print("  为什么这一步最重要：")
    print("    如果两者输出不一致，手机和电脑会算出两套不同的骨架。")
    print("    而教练会拿两个版本的报告对比 —— 那时才发现就太晚了。")
    print()

    report: dict = {"exports": {}, "benchmark": {}, "parity": {}}

    for sz in sorted(exported, reverse=True):
        x = make_input(sz)
        print(f"  --- imgsz={sz} ---")

        try:
            t_out, t_ms = run_torch(sz, x)
            print(f"    PyTorch      {t_ms:7.1f} ms/帧")
        except Exception as e:
            print(f"    PyTorch 失败：{type(e).__name__}: {e}")
            t_out, t_ms = None, None

        path = exported[sz]
        try:
            o_out, o_ms, provs = run_onnx(
                path, x, ["CPUExecutionProvider"])
            print(f"    ONNX CPU     {o_ms:7.1f} ms/帧   {provs}")
        except Exception as e:
            print(f"    ONNX CPU 失败：{type(e).__name__}: {e}")
            o_out, o_ms = None, None

        if t_out is not None and o_out is not None:
            if t_out.shape == o_out.shape:
                diff = np.abs(t_out - o_out)
                mx = float(diff.max())
                mean = float(diff.mean())
                ok = mx < 1e-3
                print(f"    形状一致 {t_out.shape}"
                      f"  最大差 {mx:.2e}  平均差 {mean:.2e}"
                      f"  {'[一致]' if ok else '[不一致!]'}")
                report["parity"][str(sz)] = {
                    "shape": list(t_out.shape),
                    "max_abs_diff": mx,
                    "mean_abs_diff": mean,
                    "consistent": ok,
                }
            else:
                print(f"    [形状不同!] torch {t_out.shape} vs onnx {o_out.shape}")
                report["parity"][str(sz)] = {
                    "torch_shape": list(t_out.shape),
                    "onnx_shape": list(o_out.shape),
                    "consistent": False,
                }

        report["benchmark"][str(sz)] = {
            "torch_ms": round(t_ms, 1) if t_ms else None,
            "onnx_cpu_ms": round(o_ms, 1) if o_ms else None,
        }
        report["exports"][str(sz)] = {
            "file": path.name,
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
        }
        print()

    print("=" * 74)
    print("第三步：从 CPU 速度推算手机速度")
    print("=" * 74)
    print()

    for sz in sorted(report["benchmark"], key=int, reverse=True):
        ms = report["benchmark"][sz].get("onnx_cpu_ms")
        if not ms:
            continue
        frames = 1200      # 10 秒 @ 120fps
        sec = ms * frames / 1000
        print(f"  imgsz={sz}")
        print(f"    CPU {ms:.0f} ms/帧  →  1200 帧要 {sec:.0f} 秒（{sec/60:.1f} 分钟）")
        print()

    print("  ⚠️ 这只是**参考**，不是手机的真实数字。")
    print("     手机有 NPU/GPU，通常比桌面 CPU 快 1~3 倍；")
    print("     但手机也可能因为发热降频而更慢。")
    print("     真实数字必须真机实测。")

    (OUT / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"  结果已写入 {OUT / 'benchmark.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
