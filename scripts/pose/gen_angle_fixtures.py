"""
生成角度计算的对拍样本。

## 为什么要对拍角度

手机端为了画角度弧，必须自己算角度。而项目原则是
「指标算法只有一份」（在电脑端）。这两件事看似矛盾，
所以要用**对拍**把它们钉在一起：

    同一份关键点 → 手机算一遍 → 电脑算一遍 → 必须相等

只要这个对拍通过，就可以放心地说"手机上画的角度
和报告里的数值是同一个数"。

## 存什么

  · 关键点（归一化坐标）
  · 电脑端按各角度定义算出的值

手机端读同一份关键点，用 Dart 实现算一遍，比对。

## 只比"能算的角度"

有几个指标依赖 `heel` / `toe`（足部点），而那两个点是
**几何推导**出来的。电脑端的推导参数在 `keypoint_map.py`，
手机端在 `foot_derivation.dart` —— 两边都要一致才行。

所以这一版同时验证：
  ① 三点点角与线段角的公式
  ② 足部点推导
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.analysis.keypoint_map import derive_foot_points  # noqa: E402
from backend.analysis.metrics_base import (  # noqa: E402
    angle_at,
    segment_angle_from_vertical,
)

OUT = ROOT / "samples" / "angle_fixtures"
OUT.mkdir(parents=True, exist_ok=True)

#: 与 mobile/lib/pose/angle_catalog.dart 的 angleCatalog 对应。
#:
#: ⚠️ 两边必须一致。这里多一条或少一条，对拍就只覆盖一部分 ——
#:    而"没覆盖到的那条"恰恰是最可能出错的。
#:
#: (metric_id, kind, points, vertex_index)
ANGLES = [
    # ---- 侧面 ----
    ("trunk_lean", "segment", ["shoulder_mid", "hip_mid"], 0),
    ("knee_angle_touchdown", "three", ["hip_r", "knee_r", "ankle_r"], 1),
    ("knee_angle_midstance", "three", ["hip_r", "knee_r", "ankle_r"], 1),
    ("hip_angle_toeoff", "three", ["shoulder_r", "hip_r", "knee_r"], 1),
    ("shank_angle_touchdown", "segment", ["knee_r", "ankle_r"], 0),
    ("ankle_angle_touchdown", "three", ["knee_r", "ankle_r", "toe_r"], 1),
    # ---- 正面 / 背面 ----
    ("pelvis_tilt", "segment", ["hip_l", "hip_r"], 0),
    ("knee_valgus_touchdown", "three", ["hip_r", "knee_r", "ankle_r"], 1),
    ("trunk_lateral_lean", "segment", ["shoulder_mid", "hip_mid"], 0),
]


def resolve(name: str, kps: dict, derived: dict):
    """解析点名到坐标。支持中点与推导点。"""
    if name == "shoulder_mid":
        a, b = kps.get("shoulder_l"), kps.get("shoulder_r")
        if not a or not b or a[2] <= 0 or b[2] <= 0:
            return None
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if name == "hip_mid":
        a, b = kps.get("hip_l"), kps.get("hip_r")
        if not a or not b or a[2] <= 0 or b[2] <= 0:
            return None
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    if name in derived:
        d = derived[name]
        return (d[0], d[1]) if d else None
    p = kps.get(name)
    if not p or p[2] <= 0:
        return None
    return (p[0], p[1])


def main() -> int:
    # 从真人姿态里取几帧。用对拍样本里的期望关键点 ——
    # 那是真实模型输出的坐标，比人造数据更有代表性。
    pose_dir = ROOT / "samples" / "pose_fixtures"
    idx_file = pose_dir / "index.json"
    if not idx_file.exists():
        print("[FAIL] 缺少姿态样本，请先跑 scripts/pose/gen_pose_fixtures.py")
        return 1

    idx = json.loads(idx_file.read_text(encoding="utf-8"))
    names = idx["coco_names"]

    samples = []
    for fi in idx["frames"]:
        mf = pose_dir / f"frame_{fi:04d}.json"
        if not mf.exists():
            continue
        meta = json.loads(mf.read_text(encoding="utf-8"))

        kps = {}
        for k in meta["expected_keypoints"]:
            # (x, y, conf)
            kps[k["name"]] = (k["x"], k["y"], k["confidence"])

        # ---- 推导足部点（电脑端算法）----
        derived = {}
        for side in ("l", "r"):
            ankle = kps.get(f"ankle_{side}")
            knee = kps.get(f"knee_{side}")
            if not ankle or ankle[2] <= 0:
                derived[f"heel_{side}"] = None
                derived[f"toe_{side}"] = None
                continue
            kn = (knee[0], knee[1]) if knee and knee[2] > 0 else None

            # 足长：用鼻尖到最低踝的距离 × 0.152（与 Dart 端一致）
            nose = kps.get("nose")
            lowest = None
            for s2 in ("l", "r"):
                a2 = kps.get(f"ankle_{s2}")
                if a2 and a2[2] > 0:
                    lowest = a2[1] if lowest is None else max(lowest, a2[1])
            if nose and nose[2] > 0 and lowest is not None:
                h = abs(lowest - nose[1])
                scale = h * 0.152 if h > 0.05 else 0.20 * 0.152
            else:
                scale = 0.20 * 0.152

            heel, toe = derive_foot_points(
                (ankle[0], ankle[1]), kn, scale)
            derived[f"heel_{side}"] = heel
            derived[f"toe_{side}"] = toe

        # ---- 算各角度 ----
        values = {}
        for mid, kind, pts, vi in ANGLES:
            coords = []
            ok = True
            for p in pts:
                c = resolve(p, kps, derived)
                if c is None:
                    ok = False
                    break
                coords.append(c)
            if not ok or len(coords) < (3 if kind == "three" else 2):
                values[mid] = None
                continue

            if kind == "three":
                v = angle_at(coords[0], coords[1], coords[2])
                values[mid] = None if math.isnan(v) else v
            else:
                v = segment_angle_from_vertical(coords[0], coords[1])
                values[mid] = None if math.isnan(v) else abs(v)

        samples.append({
            "frame_index": fi,
            "keypoints": {k: list(v) for k, v in kps.items()},
            "derived": {
                k: (list(v) if v else None) for k, v in derived.items()
            },
            "angles": values,
        })
        print(f"  帧{fi}: 算了 {sum(1 for v in values.values() if v is not None)}"
              f" 个角度")

    doc = {
        "coco_names": names,
        "angles": [
            {"metric_id": m, "kind": k, "points": p, "vertex_index": v}
            for m, k, p, v in ANGLES
        ],
        "samples": samples,
        "note": "由 scripts/gen_angle_fixtures.py 生成。"
                "Dart 端读这些做角度计算对拍。",
    }
    (OUT / "angles.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"共 {len(samples)} 帧，写入 {OUT / 'angles.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
