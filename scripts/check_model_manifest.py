"""
校验模型清单。

## 为什么需要这个门禁

模型清单里记的是「我们对模型的信任依据」：对拍结果、已知缺陷、
每个产物的用途。这些东西一旦和实际文件脱节，就会产生危险的错觉：

    "清单上说 640 版对拍通过" —— 但文件根本不存在
    "清单上说这个模型没有足部点" —— 但文件其实换了

所以清单必须被机械校验：
  1. 文件真实存在，且大小与记录一致（差太多说明被换过了）
  2. 对拍结论字段齐全
  3. 已知缺陷必须写明（空列表会让"没缺陷"和"没记录"分不清）
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MANIFEST = ROOT / "data" / "models" / "model_manifest.json"

#: 大小允许的偏差比例。文件被重新导出后大小会变，但不会变太多。
SIZE_TOLERANCE = 0.20


def main() -> int:
    print("=" * 70)
    print("校验模型清单")
    print("=" * 70)
    print()

    if not MANIFEST.exists():
        print(f"  [FAIL] 找不到 {MANIFEST}")
        return 1

    try:
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [FAIL] JSON 解析失败：{e}")
        return 1

    problems: list[str] = []

    active = doc.get("active")
    if not isinstance(active, dict):
        print("  [FAIL] 缺少 active 段")
        return 1

    # ---- 1. 身份字段 ----
    print("  模型身份：")
    for key in ("model_version", "base_model", "keypoint_format",
                "keypoint_count", "provides_foot_keypoints"):
        if key not in active:
            problems.append(f"active 缺少字段 {key}")
            continue
        print(f"    {key:26s} {active[key]}")
    print()

    # ---- 2. 产物文件必须真实存在 ----
    print("  产物文件：")
    artifacts = active.get("artifacts") or {}
    if not artifacts:
        problems.append("artifacts 为空 —— 至少要有一个可用的模型文件")

    for name, info in artifacts.items():
        rel = info.get("file")
        if not rel:
            problems.append(f"artifacts.{name} 缺少 file")
            continue
        p = ROOT / rel
        if not p.exists():
            problems.append(f"artifacts.{name} 指向的文件不存在：{rel}")
            print(f"    [缺失] {name:12s} {rel}")
            continue

        actual_mb = p.stat().st_size / 1024 / 1024
        claimed = info.get("size_mb")
        note = ""
        if isinstance(claimed, (int, float)) and claimed > 0:
            ratio = abs(actual_mb - claimed) / claimed
            if ratio > SIZE_TOLERANCE:
                problems.append(
                    f"artifacts.{name} 记录 {claimed} MB，"
                    f"实际 {actual_mb:.2f} MB —— 文件可能被换过，请更新清单"
                )
                note = "  ← 大小与记录不符"
        print(f"    [存在] {name:12s} {actual_mb:6.2f} MB{note}")
    print()

    # ---- 3. 对拍结论 ----
    print("  对拍结果：")
    ver = active.get("verification") or {}
    if not ver:
        problems.append("verification 为空 —— 没有对拍就无法信任 ONNX 产物")
    else:
        for key, val in ver.items():
            if key in ("method", "script", "benchmark_script", "sample"):
                continue
            if not isinstance(val, dict):
                continue
            v = val.get("verdict")
            if not v:
                problems.append(f"verification.{key} 缺少 verdict")
                continue
            mx = val.get("max_pixel_diff")
            print(f"    {key:12s} {v:8s} 最大差 {mx} px")
    print()

    # ---- 4. 已知缺陷必须写明 ----
    #
    # ⚠️ 空列表是危险的：它让"这个模型没有已知问题"和
    #    "我们还没测过"看起来一样。而这个模型确实有已知问题
    #    （蹲踞式起跑识别出错），必须记录。
    print("  已知缺陷：")
    issues = active.get("known_issues")
    if not issues:
        problems.append(
            "known_issues 为空 —— 这个模型确实有已知问题"
            "（蹲踞式起跑识别出错、足部点为推导），必须如实记录"
        )
    else:
        for i, s in enumerate(issues, 1):
            print(f"    {i}. {s[:64]}{'...' if len(s) > 64 else ''}")
    print()

    # ---- 结论 ----
    print("=" * 70)
    if problems:
        print(f"[FAIL] {len(problems)} 个问题：")
        for p in problems:
            print(f"  · {p}")
        return 1
    print("[OK] 模型清单校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
