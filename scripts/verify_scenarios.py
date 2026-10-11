#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成代码的语义自检：用 fixture 走一遍 fromJson 路径
====================================================

用法
----
    python scripts/verify_scenarios.py

为什么需要
----------
inspect_models.py 只做结构检查（括号、引用、空壳），无法回答：
「契约里的每个字段类型，是否真的能从真实 JSON 解析出来？」

本脚本按生成器将要产出 Dart 代码的那套规则，在 Python 里复现读取逻辑，
对 fixture 逐字段求值。能抓到：
    - 可空字段被当作非空处理（或反之）
    - 嵌套对象在 JSON 里为 null 时崩溃
    - 枚举取值不在契约枚举内
    - 数组元素类型不匹配

Dart 未安装时，这是最接近「跑一遍」的验证。
"""

from __future__ import annotations

import io
import json
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
FIXTURE_DIR = ROOT / "samples" / "fixtures"

KNOWN_FILES = {
    "analysis": "analysis.schema.json",
    "pose": "pose.schema.json",
    "task": "task.schema.json",
    "session": "session.schema.json",
    "metric": "metric.schema.json",
    "finding": "finding.schema.json",
    "error": "error.schema.json",
}


class Ctx:
    def __init__(self, gen: g.Generator):
        self.gen = gen
        self.errors: list[str] = []

    def fail(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    # -- 按生成器规则读取 ------------------------------------------------

    def read(self, model_name: str, value, path: str):
        """模拟生成的 <Model>.fromJson。"""
        if model_name not in self.gen.models:
            return value
        if not isinstance(value, dict):
            self.fail(path, f"期望对象，实际 {type(value).__name__}")
            return None

        model = self.gen.models[model_name]
        for f in model.fields:
            key = f.json_name
            nullable = f.dart_type.endswith("?")
            present = key in value and value[key] is not None

            if not present:
                if not nullable:
                    self.fail(path, f"缺少非空字段 '{key}'")
                continue

            raw = value[key]
            self.check_type(f, raw, f"{path}.{key}")
        return value

    def check_type(self, f: g.Field, raw, path: str) -> None:
        t = f.dart_type.rstrip("?")

        if f.enum_name and t == f.enum_name:
            self._check_enum(f.enum_name, raw, path)
            return

        if t.startswith("List<"):
            if not isinstance(raw, list):
                self.fail(path, f"期望数组，实际 {type(raw).__name__}")
                return
            inner = t[5:-1]
            for i, item in enumerate(raw):
                if f.enum_name:
                    self._check_enum(f.enum_name, item, f"{path}[{i}]")
                elif inner not in g.PRIMITIVES:
                    self.read(inner, item, f"{path}[{i}]")
            return

        simple = {
            "String": str, "int": int, "double": (int, float), "bool": bool,
        }
        if t in simple:
            if not isinstance(raw, simple[t]) or isinstance(raw, bool) != (t == "bool"):
                self.fail(path, f"期望 {t}，实际 {type(raw).__name__}（{raw!r}）")
            return

        if t == "Map<String, dynamic>":
            if not isinstance(raw, dict):
                self.fail(path, f"期望对象，实际 {type(raw).__name__}")
            return

        # Object? 表示契约里的联合类型（如 metric.value 可为数字或字符串），
        # 生成代码直接透传，不做转换。
        # 注意 f.dart_type.rstrip("?") 会把 "Object?" 剥成 "Object"，
        # 因此这里要连原类型一起判断，不能只看 t。
        if t == "Object" or f.dart_type == "Object?":
            return

        if t in self.gen.models:
            self.read(t, raw, path)
            return

        self.fail(path, f"未知类型 {t}")

    def _check_enum(self, enum_name: str, raw, path: str) -> None:
        e = self.gen.enums.get(enum_name)
        if e is None:
            self.fail(path, f"未知枚举 {enum_name}")
            return
        # 生成代码用 String 比对，数字枚举在 Dart 侧会取不到值
        if isinstance(raw, str):
            if raw not in e.values:
                self.fail(path, f"取值 {raw!r} 不在枚举 {enum_name} 中 {e.values}")
        elif isinstance(raw, int) and not isinstance(raw, bool):
            if str(raw) not in e.values:
                self.fail(path, f"数字取值 {raw} 不在枚举 {enum_name} 中 {e.values}")
        else:
            self.fail(path, f"枚举字段收到 {type(raw).__name__}（{raw!r}）")


def main() -> None:
    gen = g.Generator(g.load_contracts())
    gen.build()

    print("=" * 68)
    print("生成代码语义自检（fixture -> fromJson 路径）")
    print("=" * 68)
    print()

    if not FIXTURE_DIR.exists():
        raise SystemExit(f"[FAIL] fixture 目录不存在：{FIXTURE_DIR}")

    total = 0
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        prefix = path.stem.split("_")[0]
        schema_file = KNOWN_FILES.get(prefix)
        if schema_file is None:
            print(f"  - {path.name}  （无对应模型，跳过）")
            continue

        model_name = g.ENTRY_POINTS[schema_file]
        data = json.loads(path.read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if not k.startswith("_")}

        ctx = Ctx(gen)
        ctx.read(model_name, data, "$")
        total += 1

        if ctx.errors:
            print(f"  [FAIL] {path.name}  ->  {model_name}")
            for e in ctx.errors[:15]:
                print(f"        {e}")
            if len(ctx.errors) > 15:
                print(f"        ... 另有 {len(ctx.errors) - 15} 处")
        else:
            n_models = _count_visited(gen, model_name, data)
            print(f"  [OK]   {path.name}  ->  {model_name}"
                  f"  （{n_models} 个嵌套模型）")

    print()
    if total == 0:
        print("[WARN] 没有可校验的 fixture")
    else:
        print(f"合计 {total} 份 fixture")


def _count_visited(gen: g.Generator, model_name: str, data) -> int:
    """统计解析过程中触达的模型数，用于给个直观的覆盖感。"""
    seen: set[str] = set()

    def walk(name: str, value):
        if name in seen or name not in gen.models:
            return
        seen.add(name)
        if isinstance(value, dict):
            for f in gen.models[name].fields:
                if f.json_name in value and value[f.json_name] is not None:
                    walk(f.dart_type.rstrip("?").replace("List<", "").rstrip(">"),
                         value[f.json_name])

    walk(model_name, data)
    return len(seen)


if __name__ == "__main__":
    main()
