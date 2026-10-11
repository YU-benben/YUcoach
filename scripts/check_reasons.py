"""
核对实现里用到的 InsufficientReason 是否都在契约枚举内。

为什么需要这个：
    reason 决定客户端给什么补齐建议。用了契约外的值，
    校验会失败；而如果为了通过校验去"将就"用语义不符的值，
    教练会收到错误的下一步指引。

    两种错法都很隐蔽，所以用一个自动检查兜住。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "backend" / "contracts" / "common.schema.json"

# 需要检查的源文件
SOURCES = [
    ROOT / "backend" / "analysis" / "metrics.py",
    ROOT / "backend" / "analysis" / "rules.py",
    ROOT / "backend" / "analysis" / "report.py",
]


def load_allowed() -> set[str]:
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return set(c["$defs"]["InsufficientReason"]["enum"])


def main() -> int:
    allowed = load_allowed()
    print(f"契约允许的 reason（{len(allowed)} 个）：")
    for v in sorted(allowed):
        print(f"  {v}")
    print()

    all_used: dict[str, list[str]] = {}
    for p in SOURCES:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        # 匹配 reason="xxx" 与 reason='xxx'
        found = set(re.findall(r'reason\s*=\s*["\']([a-z_]+)["\']', text))
        for v in found:
            all_used.setdefault(v, []).append(p.name)

    if not all_used:
        print("[WARN] 没找到任何 reason= 用法，检查是否改过写法")
        return 0

    print(f"实现里用到的 reason（{len(all_used)} 个）：")
    for v in sorted(all_used):
        mark = "OK " if v in allowed else "BAD"
        print(f"  [{mark}] {v:28s} {', '.join(all_used[v])}")
    print()

    bad = {k: v for k, v in all_used.items() if k not in allowed}
    if bad:
        for k, files in bad.items():
            print(f"[FAIL] reason=\"{k}\" 不在契约枚举内（{', '.join(files)}）")
        print()
        print("两种修法，按情况选：")
        print("  · 语义确实不同 -> 在 common.schema.json 的 InsufficientReason")
        print("    里新增该值，并升 Minor 版本")
        print("  · 语义可用已有的表达 -> 改用契约内最贴近的值")
        return 1

    print("[OK] 所有 reason 都在契约枚举内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
