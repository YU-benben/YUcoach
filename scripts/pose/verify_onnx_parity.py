"""
端到端对拍：用**真实视频帧**跑完整 YOLO 流程，比较最终关键点。

## 为什么上一版对拍的方式不对

上一版比较的是网络的**原始输出**，形状 (1, 56, 8400)：

    56 = 4（框）+ 1（置信度）+ 51（17 个点 × 3）
    8400 = 候选框数量

那 8400 个候选里，**绝大多数是垃圾**（背景、重复框、低置信度）。
逐个比较它们的原始浮点值毫无意义 —— 差 0.001 完全不影响最终结果。

**真正该比的是"最终选出来的那个人的 17 个关键点"** ——
那才是喂给算法的数据。差 0.001 个像素和差 3 个像素，
后果天差地别。

## 所以这一版做三件事

  1. 从真实视频取帧
  2. 用 Ultralytics 的**完整流程**（含 NMS、后处理）分别跑 .pt 和 .onnx
  3. 比较**最终 17 个关键点的像素坐标**
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["YOLO_CONFIG_DIR"] = str(ROOT / ".cache" / "ultralytics")

MODELS = ROOT / ".cache" / "models"
EXPORTED = MODELS / "exported"
VIDEO = ROOT / "samples" / "videos" / "训练素材刘珉宇.mp4"

import cv2


def grab_frames(n: int = 5) -> list[np.ndarray]:
    """从视频里取若干帧。均匀取样，覆盖不同姿态。"""
    cap = cv2.VideoCapture(str(VIDEO))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        total = 300
    idxs = [int(total * i / (n + 1)) for i in range(1, n + 1)]

    out = []
    for want in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, want)
        ok, frame = cap.read()
        if ok:
            out.append(frame)
    cap.release()
    return out


def keypoints_from(result) -> tuple[np.ndarray, float] | None:
    """
    从 Ultralytics 的结果里取**置信度最高的那个人**的 17 个关键点。

    返回 ((17, 3)：x, y, conf, 该人的框置信度)。没人检出则返回 None。

    ## ⚠️ 这里踩过一个坑，记下来

      `keypoints.conf` 的形状是 **(N, 17)** —— 第 i 个人的第 j 个点的置信度。
      `boxes.conf` 的形状是 **(N,)** —— 第 i 个人的整体检出置信度。

      **选人要用 `boxes.conf`，不是 `keypoints.conf`。**
      用错了会报 "index out of bounds"，或者更糟 ——
      静默选中错误的那个人。

    ## 为什么取置信度最高的一个

      本项目是单人分析场景，画面里的主角就是运动员。
      但实测这帧检出了 **2 个人**（置信度 0.76 和 0.33）——
      背景里有其他人在跑。所以"选一个"不是可选项，是必须做的。

      手机端也要做同样的简化 —— 完整的多人 NMS 在这里没必要。
    """
    if result.keypoints is None or result.boxes is None:
        return None
    if len(result.boxes) == 0:
        return None

    box_conf = result.boxes.conf
    box_conf = (box_conf.cpu().numpy() if hasattr(box_conf, "cpu")
                else np.asarray(box_conf))
    if len(box_conf) == 0:
        return None

    i = int(np.argmax(box_conf))

    xy = result.keypoints.xy
    xy = xy.cpu().numpy() if hasattr(xy, "cpu") else np.asarray(xy)
    if i >= len(xy):
        return None

    pts = xy[i]

    kconf = result.keypoints.conf
    if kconf is not None:
        kconf = (kconf.cpu().numpy() if hasattr(kconf, "cpu")
                 else np.asarray(kconf))
        c = kconf[i]
    else:
        c = np.ones(len(pts), dtype=np.float32)

    return np.concatenate([pts, c.reshape(-1, 1)], axis=1), float(box_conf[i])


def run(model_path: Path, imgsz: int, frames: list[np.ndarray]):
    from ultralytics import YOLO
    m = YOLO(str(model_path))
    out = []
    for f in frames:
        r = m.predict(f, imgsz=imgsz, verbose=False, device="cpu")[0]
        out.append(keypoints_from(r))
    return out


def main() -> int:
    print("=" * 74)
    print("端到端对拍：最终关键点是否一致")
    print("=" * 74)
    print()

    frames = grab_frames(5)
    print(f"  取到 {len(frames)} 帧（形状 {frames[0].shape}）")
    print()

    onnx_960 = EXPORTED / "yolov8n-pose-960.onnx"
    onnx_640 = EXPORTED / "yolov8n-pose-640.onnx"

    for imgsz, onnx_path in ((960, onnx_960), (640, onnx_640)):
        if not onnx_path.exists():
            print(f"  跳过 imgsz={imgsz}：{onnx_path.name} 不存在")
            continue

        print("-" * 74)
        print(f"imgsz = {imgsz}")
        print("-" * 74)

        try:
            pt_kps = run(MODELS / "yolov8n-pose.pt", imgsz, frames)
            ox_kps = run(onnx_path, imgsz, frames)
        except Exception as e:
            print(f"  运行失败：{type(e).__name__}: {e}")
            continue

        max_d = 0.0
        n_compared = 0
        miss = 0
        picks_differ = 0

        for i, (a, b) in enumerate(zip(pt_kps, ox_kps)):
            if a is None or b is None:
                miss += 1
                print(f"    帧{i}: pt={'有' if a is not None else '无'} "
                      f"onnx={'有' if b is not None else '无'}")
                continue

            kp_a, conf_a = a
            kp_b, conf_b = b

            if kp_a.shape != kp_b.shape:
                print(f"    帧{i}: 形状不同 {kp_a.shape} vs {kp_b.shape}")
                continue

            # 两边选的必须是**同一个人**。选到不同的人，
            # 坐标差异会非常大 —— 那不是浮点误差，是选人逻辑不一致。
            if abs(conf_a - conf_b) > 0.05:
                picks_differ += 1
                print(f"    帧{i}: ⚠️ 两边选的人不同！"
                      f"框置信度 {conf_a:.3f} vs {conf_b:.3f}")

            d = np.abs(kp_a[:, :2] - kp_b[:, :2])     # 只比坐标
            md = float(d.max())
            max_d = max(max_d, md)
            n_compared += 1
            print(f"    帧{i}: 17 点坐标最大差 {md:6.2f} 像素  "
                  f"平均差 {float(d.mean()):5.2f}  "
                  f"(框置信度 {conf_a:.2f})")

        print()
        if n_compared:
            if picks_differ:
                print(f"  ⚠️ 有 {picks_differ} 帧两边选到了不同的人 —— "
                      f"这不是浮点误差，要查选人逻辑")
            verdict = ("[一致] 差异在亚像素级，可忽略"
                       if max_d < 1.0 else
                       (f"[可接受] 最大差 {max_d:.2f} 像素，"
                        f"相当于多了一点噪声"
                        if max_d < 3.0 else
                        f"[要查] 最大差 {max_d:.2f} 像素，超出噪声量级"))
            print(f"  结论：{verdict}")
            print(f"        比较了 {n_compared} 帧，{miss} 帧缺失")
        else:
            print("  没有可比对的帧")
        print()

    print("=" * 74)
    print("怎么判断这个差异可接受")
    print("=" * 74)
    print()
    print("  本项目已有的噪声敏感性数据：")
    print("    3 像素噪声  →  躯干角误差 0.03°、髋角 0.20°")
    print()
    print("  所以：")
    print("    < 1 像素   完全可忽略")
    print("    1~3 像素   可接受（相当于多了一点噪声）")
    print("    > 3 像素   要查原因 —— 可能是前处理不一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
