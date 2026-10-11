"""
生成手机端解析器的对拍样本。

## 为什么需要这个

手机端要自己实现「从 YOLO 输出解出关键点」—— 电脑上这部分是
Ultralytics 做的。两边实现不同，就有**算出不同结果**的风险。

而这是最坏的情况：同一个运动员，手机上和电脑上的报告数字不一样，
却看不出哪里错了。

所以做法是：**电脑上算一遍，把输入和期望输出都存下来，
手机端用同一份输入算，比对结果。**

## 存什么

  · letterbox 参数（原图尺寸、输入尺寸）
  · ONNX 的**原始输出**（那个 (1,56,8400) 的大数组）
  · 电脑端算出的**关键点**（期望值）

手机端测试读这三个，自己解析一遍，比对期望值。
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["YOLO_CONFIG_DIR"] = str(ROOT / ".cache" / "ultralytics")

OUT_DIR = ROOT / "samples" / "pose_fixtures"

# 重新生成前先清掉旧的 .bin/.json。
#
# 为什么必须清：这些文件是**入库的**（Dart 对拍测试依赖它们）。
# 如果换了采样帧而不清理，旧文件会作为"孤儿"留在仓库里 ——
# 没人知道它们还有没有用，而 index.json 里已经没有它们的记录了。
for _old in OUT_DIR.glob("frame_*.bin"):
    _old.unlink()
for _old in OUT_DIR.glob("frame_*.json"):
    _old.unlink()

OUT_DIR.mkdir(parents=True, exist_ok=True)

VIDEO = ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4"
IMGSZ = 640

#: 取几帧做样本。挑不同阶段的，覆盖不同姿态。
FRAME_POSITIONS = [0.15, 0.35, 0.55, 0.75]

COCO_NAMES = [
    "nose", "eye_l", "eye_r", "ear_l", "ear_r",
    "shoulder_l", "shoulder_r", "elbow_l", "elbow_r",
    "wrist_l", "wrist_r", "hip_l", "hip_r",
    "knee_l", "knee_r", "ankle_l", "ankle_r",
]


def letterbox_params(w: int, h: int, size: int) -> dict:
    """必须和 Dart 端 computeLetterbox 一致。"""
    scale = min(size / w, size / h)
    new_w = w * scale
    new_h = h * scale
    return {
        "scale": scale,
        "pad_x": (size - new_w) / 2,
        "pad_y": (size - new_h) / 2,
        "input_size": size,
        "original_width": w,
        "original_height": h,
    }


def main() -> int:
    import onnxruntime as ort

    onnx_path = ROOT / ".cache" / "models" / "exported" / f"yolov8n-pose-{IMGSZ}.onnx"
    if not onnx_path.exists():
        print(f"[FAIL] 找不到 {onnx_path}")
        return 1

    sess = ort.InferenceSession(str(onnx_path),
                                providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name

    cap = cv2.VideoCapture(str(VIDEO))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300

    # 同时用 Ultralytics 跑一遍，取得"期望的关键点"
    from ultralytics import YOLO
    yolo = YOLO(str(onnx_path))

    saved = []
    for pos in FRAME_POSITIONS:
        idx = int(total * pos)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue

        h, w = frame.shape[:2]
        lb = letterbox_params(w, h, IMGSZ)

        # ---- ① 手工做前处理，喂给 ONNX，存下**原始输出** ----
        #
        # 必须和 Dart 端做的一模一样：
        #   1. 按 scale 缩放
        #   2. 居中填充到 640×640，填充色 114
        #   3. BGR → RGB
        #   4. HWC → CHW，归一化到 0~1
        scaled = cv2.resize(frame, (int(round(w * lb["scale"])),
                                    int(round(h * lb["scale"]))),
                            interpolation=cv2.INTER_LINEAR)
        canvas = np.full((IMGSZ, IMGSZ, 3), 114, dtype=np.uint8)
        y0 = int(round(lb["pad_y"]))
        x0 = int(round(lb["pad_x"]))
        canvas[y0:y0 + scaled.shape[0], x0:x0 + scaled.shape[1]] = scaled

        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
        inp = chw[np.newaxis, ...]

        raw = sess.run(None, {iname: inp})[0]      # (1, 56, 8400)

        # ---- ② 用 Ultralytics 取期望的关键点 ----
        r = yolo.predict(frame, imgsz=IMGSZ, verbose=False, device="cpu")[0]
        if r.boxes is None or len(r.boxes) == 0:
            print(f"  帧{idx}: Ultralytics 没检出人，跳过")
            continue

        bc = r.boxes.conf.cpu().numpy()
        bi = int(np.argmax(bc))
        xy = r.keypoints.xy.cpu().numpy()[bi]       # (17, 2) 原图像素
        kc = r.keypoints.conf.cpu().numpy()[bi]     # (17,)

        expected = [
            {
                "name": COCO_NAMES[k],
                # 转成**原图归一化**坐标 —— 这是 Dart 端输出的格式
                "x": float(xy[k][0] / w),
                "y": float(xy[k][1] / h),
                "confidence": float(kc[k]),
            }
            for k in range(17)
        ]

        name = f"frame_{idx:04d}"
        # 原始输出存成二进制（浮点），比 JSON 小得多也更快
        bin_path = OUT_DIR / f"{name}.bin"
        raw.astype(np.float32).tofile(bin_path)

        meta = {
            "frame_index": idx,
            "letterbox": lb,
            "output_shape": list(raw.shape),
            "output_file": bin_path.name,
            "box_confidence": float(bc[bi]),
            # 记录一下这一帧检出了几个人 —— 用来验证"选人"逻辑
            "candidates_over_threshold": int((bc >= 0.25).sum()),
            "expected_keypoints": expected,
        }
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        saved.append((idx, len(expected)))
        print(f"  帧{idx}: 存下原始输出 {raw.size} 个数"
              f"（{bin_path.stat().st_size / 1024:.0f} KB）"
              f"，期望关键点 {len(expected)} 个")

    cap.release()

    # 索引文件
    (OUT_DIR / "index.json").write_text(
        json.dumps({
            "imgsz": IMGSZ,
            "keypoint_count": 17,
            "coco_names": COCO_NAMES,
            "frames": [s[0] for s in saved],
            "note": "由 scripts/gen_pose_fixtures.py 生成。"
                    "Dart 端读这些文件做跨语言对拍。",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"共 {len(saved)} 帧，写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
