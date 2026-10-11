#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查契约的一致性：非空类型字段必须出现在 required 里。

为什么这是一条硬规则
--------------------
Dart 里非空字段必须有值。若契约声明 `"type": "integer"`（非空）却又不写进
`required`，生成出来的构造函数就不会要求传该字段，Dart 直接报
missing_default_value_for_parameter。

这不是生成器的问题，是契约本身自相矛盾：一个字段要么「必须提供」，
要么「可以缺省」——后者就必须允许 null。

用法
----
    python scripts/check_schema_consistency.py
    python scripts/check_schema_consistency.py --fix    # 自动补进 required
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "backend" / "contracts"

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")


def declared_nullable(sch: dict) -> bool:
    """schema 是否允许 null。"""
    t = sch.get("type")
    if isinstance(t, list) and "null" in t:
        return True
    for sub in sch.get("allOf", []) + sch.get("oneOf", []):
        if sub.get("type") == "null":
            return True
        if isinstance(sub.get("type"), list) and "null" in sub["type"]:
            return True
    return False


def scan(node: dict, path: str, out: list[tuple[str, str]]) -> None:
    """收集「非空但不在 required」的字段。"""
    if not isinstance(node, dict):
        return

    props = node.get("properties")
    if isinstance(props, dict):
        required = set(node.get("required", []))
        for name, sub in props.items():
            if name in required:
                continue
            if not isinstance(sub, dict):
                continue
            # 允许 null 的字段不在此列：它是「可缺省且可为空」，合法
            if declared_nullable(sub):
                continue
            # 只有真正有类型的信息才算；纯 $ref 的情况由被引用方保证
            t = sub.get("type")
            if t is None and "$ref" not in sub and "enum" not in sub:
                continue
            out.append((path, name))

    for key, val in node.items():
        if key in ("properties", "$defs", "definitions"):
            if key == "properties" and isinstance(val, dict):
                for name, sub in val.items():
                    scan(sub, f"{path}.{name}", out)
            elif key == "$defs" and isinstance(val, dict):
                for name, sub in val.items():
                    scan(sub, f"$defs.{name}", out)
            continue
        if isinstance(val, dict):
            scan(val, f"{path}.{key}", out)
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    scan(item, f"{path}.{key}[{i}]", out)


def fix(node: dict) -> int:
    """把「非空但不在 required」的字段补进 required。返回改动数。"""
    changed = 0

    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            required = node.setdefault("required", [])
            for name, sub in props.items():
                if not isinstance(sub, dict) or name in required:
                    continue
                if declared_nullable(sub):
                    continue
                t = sub.get("type")
                if t is None and "$ref" not in sub and "enum" not in sub:
                    continue
                required.append(name)
                changed += 1
            if not required:
                node.pop("required", None)

        for key, val in node.items():
            if key in ("properties", "$defs"):
                continue
            changed += fix(val)
        for key in ("properties", "$defs"):
            val = node.get(key)
            if isinstance(val, dict):
                for sub in val.values():
                    changed += fix(sub)

    elif isinstance(node, list):
        for item in node:
            changed += fix(item)

    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description="契约一致性检查")
    ap.add_argument("--fix", action="store_true",
                    help="把非空字段自动补进 required，而不是只报告")
    args = ap.parse_args()

    print("=" * 68)
    print("契约一致性：非空类型字段必须在 required 里")
    print("=" * 68)
    print()

    total = 0
    fixed = 0

    for p in sorted(CONTRACT_DIR.glob("*.schema.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))

        if args.fix:
            n = fix(doc)
            if n:
                p.write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"  {p.name}: 补进 required {n} 处")
                fixed += n
            continue

        problems: list[tuple[str, str]] = []
        scan(doc, "$", problems)
        if problems:
            total += len(problems)
            print(f"  [FAIL] {p.name}")
            for path, name in problems[:20]:
                print(f"          {path}.{name}")
            if len(problems) > 20:
                print(f"          ... 另有 {len(problems) - 20} 处")

    print()
    if args.fix:
        print(f"共补进 {fixed} 处。请重新生成模型并跑一次 flutter analyze。")
        return

    if total:
        print(f"[FAIL] 共 {total} 处不一致。")
        print()
        print("修法二选一：")
        print("  · 字段确实必有  -> 加进该对象的 required")
        print("  · 字段可以缺省  -> 类型写成 [\"<type>\", \"null\"]")
        print()
        print("自动修复（会加进 required）：")
        print("  python scripts/check_schema_consistency.py --fix")
        sys.exit(1)

    print("[OK] 契约一致")


if __name__ == "__main__":
    main()
