"""
查清 ONNX 模型的输入输出规格。

## 为什么必须先查清楚

手机端要自己实现「后处理」—— 从网络输出里解出关键点。
电脑端这部分是 Ultralytics 帮着做的，手机上没有。

要做对，必须精确知道：
  · 输入张量的名字、形状、数据类型、像素值范围
  · 输出有几个、各自形状、每个维度是什么含义

**猜错任何一项，手机上的关键点会和电脑上不一致** —— 而这是最坏的情况：
两边的报告数字对不上，却看不出哪里错了。
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import onnx

for imgsz in (640,):
    path = ROOT / ".cache" / "models" / "exported" / f"yolov8n-pose-{imgsz}.onnx"
    if not path.exists():
        print(f"[跳过] {path.name} 不存在")
        continue

    print("=" * 74)
    print(f"{path.name}   {path.stat().st_size / 1024 / 1024:.2f} MB")
    print("=" * 74)
    print()

    m = onnx.load(str(path))
    g = m.graph

    print("--- 输入 ---")
    for inp in g.input:
        dims = []
        for d in inp.type.tensor_type.shape.dim:
            dims.append(d.dim_value if d.dim_value else d.dim_param or "?")
        print(f"  name  = {inp.name!r}")
        print(f"  shape = {dims}")
        print(f"  dtype = {inp.type.tensor_type.elem_type}")
    print()

    print("--- 输出 ---")
    for out in g.output:
        dims = []
        for d in out.type.tensor_type.shape.dim:
            dims.append(d.dim_value if d.dim_value else d.dim_param or "?")
        print(f"  name  = {out.name!r}")
        print(f"  shape = {dims}")
        print(f"  dtype = {out.type.tensor_type.elem_type}")
    print()

    print("--- 元数据（导出时记录的信息）---")
    for prop in m.metadata_props:
        v = prop.value
        if len(v) > 200:
            v = v[:200] + "..."
        print(f"  {prop.key} = {v}")
    print()

    # ---- 实际跑一次，看输出到底是什么形状 ----
    print("--- 实际推理验证 ---")
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name

    # 用 ultralytics 一样的预处理：letterbox 到正方形 + 归一化到 0~1
    rng = np.random.default_rng(0)
    x = rng.random((1, 3, imgsz, imgsz), dtype=np.float32)
    outs = sess.run(None, {iname: x})
    print(f"  输出个数：{len(outs)}")
    for i, o in enumerate(outs):
        print(f"  [{i}] shape={o.shape}  dtype={o.dtype}")
        if o.ndim == 3:
            print(f"       → 可以理解为 ({o.shape[0]}, {o.shape[1]}, {o.shape[2]})")
            print(f"         第 1 维 = batch")
            print(f"         第 2 维 = {o.shape[1]} = 4(框) + 1(置信度) + "
                  f"{(o.shape[1] - 5) // 3}×3(关键点)")
            print(f"         第 3 维 = {o.shape[2]} = 候选框数量")
    print()

    print("=" * 74)
    print("后处理要做的事（手机端也要做一遍）")
    print("=" * 74)
    print()
    print("  1. 输入：RGB 图 letterbox 到 640×640，像素值 /255.0")
    print("     ⚠️ letterbox 要保持长宽比并填充，不是直接拉伸")
    print("        拉伸会让关键点比例失真")
    print()
    print("  2. 输出是 (1, 56, 8400)：8400 个候选，每个 56 个数")
    print("     0:4   = 框中心 x, y, 宽, 高（归一化到 0~1）")
    print("     4     = 该框的置信度")
    print("     5:56  = 17 个关键点，每个 (x, y, conf)")
    print()
    print("  3. 后处理步骤：")
    print("     a. 按置信度筛掉低于阈值的候选（YOLO 默认 0.25）")
    print("     b. 非极大值抑制（NMS）去重")
    print()
    print("     ⭐ 本项目可以简化：单人场景直接取置信度最高的一个，")
    print("        跳过完整 NMS。但**背景有其他人时要小心** ——")
    print("        实测那帧检出了 2 个人。")
    print()
    print("  4. 坐标要**反映射**回原图尺寸（letterbox 的逆变换）")
