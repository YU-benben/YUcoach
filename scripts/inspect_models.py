#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成结果自检 + 契约变更影响速查
================================

用法
----
    python scripts/inspect_models.py                 # 自检生成的 Dart 文件
    python scripts/inspect_models.py --list          # 列出全部模型与枚举
    python scripts/inspect_models.py --model Metric  # 看某个模型的字段类型

为什么需要
----------
Flutter 未安装时无法编译验证生成的 Dart 代码，而生成器的 bug 往往表现为
「Dart 编译报错」——排查链路很长（改契约 -> 生成 -> 打开 Flutter -> 看报错）。

本脚本做结构性自检，能在几秒内定位绝大多数生成缺陷：
    - 括号/花括号是否配对
    - 类名是否重复
    - 是否有空类（字段全丢）
    - 字段类型里是否引用了未定义的类（拓扑排序错误）
    - 非空字段是否误用了可空读取表达式
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if not sys.stdout.isatty():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")

import gen_models as g  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "mobile" / "lib" / "models" / "models.dart"
ENUMS = ROOT / "mobile" / "lib" / "models" / "enums.dart"

DART_BUILTINS = {
    "String", "int", "double", "bool", "Object", "dynamic", "num",
    "List", "Map", "DateTime",
}


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def check_balanced(text: str, path: Path) -> list[str]:
    """括号配对检查。注意字符串字面量与注释里的括号要跳过。"""
    errors: list[str] = []
    depth = {"{": 0, "(": 0, "[": 0}
    pairs = {"}": "{", ")": "(", "]": "["}
    i, n = 0, len(text)
    line = 1

    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        # 行注释
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        # 字符串
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                if text[i] == "\n":
                    line += 1
                i += 1
            continue
        if ch in depth:
            depth[ch] += 1
        elif ch in pairs:
            depth[pairs[ch]] -= 1
            if depth[pairs[ch]] < 0:
                errors.append(f"{path.name}:{line} 多余的 '{ch}'")
                depth[pairs[ch]] = 0
        i += 1

    for k, v in depth.items():
        if v:
            errors.append(f"{path.name}: '{k}' 未闭合，还差 {v} 个")
    return errors


def check_structure(text: str, path: Path) -> list[str]:
    """类/枚举结构检查。"""
    errors: list[str] = []

    classes = re.findall(r"^class (\w+) \{", text, re.M)
    enums = re.findall(r"^enum (\w+) \{", text, re.M)
    names = classes + enums

    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        errors.append(f"{path.name}: 重复定义 {sorted(dupes)}")

    # 每个 class 必须有三段：构造函数、fromJson、toJson
    for cls in classes:
        block = _extract_block(text, f"class {cls} {{")
        if block is None:
            errors.append(f"{path.name}: 类 {cls} 没有匹配的闭合花括号")
            continue
        for member in (f"const {cls}(", f"static {cls} fromJson(",
                       "Map<String, dynamic> toJson()"):
            if member not in block:
                errors.append(f"{path.name}: 类 {cls} 缺少 {member!r}")

        fields = re.findall(r"^\s{2}final [\w<>?, ]+ (\w+);", block, re.M)
        if not fields:
            errors.append(f"{path.name}: 类 {cls} 没有字段（疑似空壳）")

        ctor = re.search(rf"const {cls}\(\{{(.*?)\}}\);", block, re.S)
        if ctor and fields:
            ctor_names = set(re.findall(r"this\.(\w+)", ctor.group(1)))
            missing = [f for f in fields if f not in ctor_names]
            if missing:
                errors.append(
                    f"{path.name}: 类 {cls} 的构造函数缺少字段 {missing}"
                )

    # 字段类型引用的类必须已定义，或来自 enums.dart
    enum_text = ENUMS.read_text(encoding="utf-8") if ENUMS.exists() else ""
    enum_names = set(re.findall(r"^enum (\w+) \{", enum_text, re.M))
    defined = set(names) | enum_names | DART_BUILTINS

    for m in re.finditer(r"^\s{2}final ([\w<>?, ]+?) (\w+);", text, re.M):
        for type_name in re.findall(r"\b([A-Z]\w+)\b", m.group(1)):
            if type_name not in defined:
                errors.append(
                    f"{path.name}: 字段 {m.group(2)} 引用了未定义的类 {type_name}"
                    f"（拓扑排序错误）"
                )

    # 非空字段不得使用可空的读取表达式（会导致 Dart 编译错误）
    for cls in classes:
        block = _extract_block(text, f"class {cls} {{")
        if block is None:
            continue
        for fname, ftype in re.findall(r"^\s{2}final ([\w<>?, ]+?) (\w+);",
                                       block, re.M):
            if ftype.endswith("?"):
                continue
            if re.search(rf"{fname}: json\['[^']+'\] as \w+\?", block):
                errors.append(
                    f"{path.name}: 类 {cls} 的非空字段 {fname} 用了可空读取"
                    f"（as T?），Dart 编译会失败"
                )
    return errors


def _extract_block(text: str, header: str) -> str | None:
    """从 header 起，取到配对的闭合花括号。"""
    start = text.find(header)
    if start < 0:
        return None
    i = text.find("{", start)
    if i < 0:
        return None
    depth, j, n = 0, i, len(text)
    while j < n:
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return None


# ---------------------------------------------------------------------------
# 展示
# ---------------------------------------------------------------------------

def list_all(gen) -> None:
    models, enums = gen._ordered()
    print(f"模型 {len(models)} 个，枚举 {len(enums)} 个")
    print()
    print("=== 模型 ===")
    for name in models:
        m = gen.models[name]
        print(f"  {name:22s} {len(m.fields):2d} 字段")
    print()
    print("=== 枚举 ===")
    for name in enums:
        e = gen.enums[name]
        print(f"  {name:38s} [{len(e.values):2d}] {', '.join(e.values[:4])}"
              + (" ..." if len(e.values) > 4 else ""))


def show_model(gen, name: str) -> None:
    if name not in gen.models:
        near = [n for n in gen.models if name.lower() in n.lower()]
        raise SystemExit(
            f"[FAIL] 没有模型 {name}。相近的有：{near or sorted(gen.models)}"
        )
    m = gen.models[name]
    print(f"class {name}")
    if m.doc:
        print(f"  /// {m.doc}")
    for f in m.fields:
        mark = "  " if f.required else "? "
        print(f"  {mark}{f.dart_type:28s} {f.dart_name:24s} "
              f"<- {f.json_name!r}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="生成结果自检")
    ap.add_argument("--list", action="store_true", help="列出全部模型与枚举")
    ap.add_argument("--model", help="查看某个模型的字段")
    args = ap.parse_args()

    contracts = g.load_contracts()
    gen = g.Generator(contracts)
    gen.build()

    if args.list:
        list_all(gen)
        return
    if args.model:
        show_model(gen, args.model)
        return

    print("=" * 68)
    print("生成结果自检")
    print("=" * 68)

    if not MODELS.exists():
        raise SystemExit("[FAIL] 尚未生成 models.dart，"
                         "请先运行 python scripts/gen_models.py")

    errors: list[str] = []
    for path in (MODELS, ENUMS):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        errors += check_balanced(text, path)
        errors += check_structure(text, path)

    models, enums = gen._ordered()
    print(f"模型：{len(models)} 个")
    print(f"枚举：{len(enums)} 个")
    print()

    if errors:
        print(f"[FAIL] 发现 {len(errors)} 处问题：")
        for e in errors:
            print(f"    {e}")
        sys.exit(1)

    print("[OK] 结构自检通过：")
    print("     - 括号配对")
    print("     - 无重复定义、无空壳类")
    print("     - 构造函数字段完整")
    print("     - 字段类型引用均已定义")
    print("     - 非空字段未使用可空读取")
    print()
    print("注意：本检查不能替代 Dart 编译。Flutter 环境就绪后请跑一次 "
          "`flutter analyze`。")


if __name__ == "__main__":
    main()
