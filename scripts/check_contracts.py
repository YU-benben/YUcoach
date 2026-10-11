#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
契约校验（质量门 G2）
=====================

用法
----
    python scripts/check_contracts.py --dir samples/fixtures
    python scripts/check_contracts.py --fixture samples/fixtures/analysis_normal.json
    python scripts/check_contracts.py --self-test

作用
----
把「文档里的契约」变成「可执行的检查」。没有这一步，契约文档会在两周内
与代码脱节，而且没有任何信号。

对应 docs/10-工程规范与验收.md 质量门 G2。

实现说明
--------
各 schema 通过 $ref 引用 common.schema.json 的共用定义。为了让校验器完全
自包含、不依赖外部解析器行为，本脚本在载入时把被引用的 common 定义**内联**
进各 schema 的 $defs 中，生成一份自洽的 schema 再校验。

这样做的好处：无论用 jsonschema 库还是内置校验器，结果都一致；
也避免了不同版本解析器对跨文件 $ref 的处理差异。
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "backend" / "contracts"
FIXTURE_DIR = ROOT / "samples" / "fixtures"

try:
    import jsonschema  # type: ignore
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# ---------------------------------------------------------------------------
# 输出编码
# ---------------------------------------------------------------------------
#
# Windows 上的编码有两个坑，都会让脚本在毫无预兆的情况下崩溃或输出乱码：
#
#   1. 直接输出到控制台时，Python 用控制台代码页（中文 Windows 为 cp936/GBK）。
#      GBK 无法编码少数符号，print 会抛 UnicodeEncodeError 直接终止脚本。
#
#   2. 输出被重定向到管道或文件时，sys.stdout.encoding 报告的仍是控制台的
#      cp936，而下游读取方（编辑器、CI、bash）通常按 UTF-8 解码 -> 中文乱码。
#
# 因此判定依据必须是 isatty()，而不是 sys.stdout.encoding 的当前值。

def _init_console() -> None:
    import io
    stream = sys.stdout

    try:
        if stream.isatty():
            # 真实控制台：沿用系统编码以保持正常显示，但加容错，
            # 保证个别无法编码的字符只会显示成替代符，而不是让脚本崩溃。
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass
            return
    except Exception:
        pass

    # 管道 / 文件：统一 UTF-8，这是下游最可能的预期编码
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return
    except Exception:
        pass
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    except Exception:
        pass


_init_console()


# ---------------------------------------------------------------------------
# 契约载入与内联
# ---------------------------------------------------------------------------

def load_raw_contracts() -> dict[str, dict]:
    files = sorted(CONTRACT_DIR.glob("*.schema.json"))
    if not files:
        raise SystemExit(f"[FAIL] 在 {CONTRACT_DIR} 找不到 *.schema.json")
    out: dict[str, dict] = {}
    for p in files:
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"[FAIL] {p.name} 不是合法 JSON：{e}")
    return out


def _collect_external_defs(node, current_file: str,
                           needed: dict[str, set[str]],
                           on_file_ref=None) -> None:
    """
    遍历 schema，收集跨文件 $ref。

    区分两种跨文件引用：
        common.schema.json#/$defs/View   指向某个具名定义 -> 记入 needed
        session.schema.json              指向整份文件（含空 fragment）-> 交给 on_file_ref
    """
    if isinstance(node, list):
        for item in node:
            _collect_external_defs(item, current_file, needed, on_file_ref)
        return
    if not isinstance(node, dict):
        return

    ref = node.get("$ref")
    if isinstance(ref, str) and not ref.startswith("#"):
        file_part, _, pointer = ref.partition("#")
        target = file_part.lstrip("/")
        if "/$defs/" in pointer:
            name = pointer.rsplit("/", 1)[-1]
            if target != current_file and name:
                needed.setdefault(target, set()).add(name)
        elif target and on_file_ref is not None:
            on_file_ref(target)

    for key, val in node.items():
        if key in ("$defs", "definitions"):
            continue
        _collect_external_defs(val, current_file, needed, on_file_ref)


def bundle_schema(filename: str, raw: dict[str, dict]) -> dict:
    """
    把一份 schema 变成完全自洽的 schema。

    做法：把所有**被引用到的**跨文件定义扁平化提升到根级 $defs，统一加文件名
    前缀消歧（如 common 的 Athlete -> common_Athlete）。

    为什么要扁平化：如果递归打包成嵌套 $defs，每份文件内部的
    "$ref": "#/$defs/X" 在嵌套后会指向错误的层级，必须逐层加前缀，脆弱易错。
    扁平化后所有 $ref 都是简单的 #/$defs/Name，无论嵌套多深。

    为什么要惰性展开：定位一个跨文件引用的前提是「已经遍历到那个引用」。
    若先扫描收集再展开，就要写两遍遍历逻辑，容易漏掉根级 $defs 内部的定义体。
    惰性展开只有一条代码路径，且天然处理任意深度的引用链。
    """
    root = raw[filename]
    root_name = f"{_stem(filename)}_root"

    flat_defs: dict[str, dict] = {}   # 扁平名 -> 已渲染的定义体
    name_map: dict[str, str] = {}     # "文件::原名" -> 扁平名
    in_progress: set[str] = set()

    def alloc(src_file: str, name: str) -> str:
        if src_file not in raw:
            raise SystemExit(f"[FAIL] 引用了不存在的契约文件：{src_file}")
        key = f"{src_file}::{name}"
        if key in name_map:
            return name_map[key]
        if name not in raw[src_file].get("$defs", {}):
            raise SystemExit(f"[FAIL] {src_file} 中不存在定义：{name}")
        flat = f"{_stem(src_file)}_{name}"
        name_map[key] = flat
        return flat

    def alloc_root(src_file: str) -> str:
        """
        为「整份文件」引用分配名字。

        必须按文件分别命名：本文件自身用 <自身>_root，外部文件用 <对方>_root。
        早期版本对所有整份引用复用同一个 root_name，导致 analysis 里的
        session / metric / finding 三处引用全部指向 analysis_root ，
        校验时表现为「Metric 缺少 session_id」这类莫名其妙的错误。
        """
        key = f"{src_file}::__root__"
        if key in name_map:
            return name_map[key]
        flat = f"{_stem(src_file)}_root"
        name_map[key] = flat
        return flat

    def render(node, source_file: str):
        """把节点里的 $ref 全部改写为扁平化后的本地引用。"""
        if isinstance(node, list):
            return [render(x, source_file) for x in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref == "#":
                return {"$ref": "#"}

            if ref.startswith("#/"):
                # 文件内部引用（如 common 里的 "#/$defs/Gender"）。
                # 关键：它指向的是 **source_file 自己**的 $defs。一旦这段定义被
                # 内联进别的文档，裸的 "#/$defs/Gender" 就会指向错误的文档。
                # 因此同样要按 source_file 加前缀重写。
                if "/$defs/" in ref:
                    orig = ref.rsplit("/", 1)[-1]
                    flat = alloc(source_file, orig)
                    if flat not in flat_defs and flat not in in_progress:
                        in_progress.add(flat)
                        flat_defs[flat] = render(
                            copy.deepcopy(raw[source_file]["$defs"][orig]),
                            source_file,
                        )
                        in_progress.discard(flat)
                    return {"$ref": f"#/$defs/{flat}"}
                return {"$ref": ref}

            file_part, _, pointer = ref.partition("#")
            target = file_part.lstrip("/") or source_file

            if "/$defs/" in pointer:
                orig = pointer.rsplit("/", 1)[-1]
                flat = alloc(target, orig)
                if flat not in flat_defs and flat not in in_progress:
                    in_progress.add(flat)
                    flat_defs[flat] = render(
                        copy.deepcopy(raw[target]["$defs"][orig]), target
                    )
                    in_progress.discard(flat)
                return {"$ref": f"#/$defs/{flat}"}

            # 引用整份文件
            if target == source_file:
                return {"$ref": "#"}
            ref_root = alloc_root(target)
            if ref_root not in flat_defs and ref_root not in in_progress:
                in_progress.add(ref_root)
                flat_defs[ref_root] = render(copy.deepcopy(raw[target]), target)
                in_progress.discard(ref_root)
            return {"$ref": f"#/$defs/{ref_root}"}

        out = {}
        for key, val in node.items():
            if key == "$schema":
                continue
            out[key] = render(val, source_file)
        return out

    bundled = render(copy.deepcopy(root), filename)

    own_defs = bundled.get("$defs", {})
    collision = set(own_defs) & set(flat_defs)
    if collision:
        raise SystemExit(
            f"[FAIL] {filename} 的 $defs 与展开后的定义重名：{sorted(collision)}"
        )
    bundled["$defs"] = {**flat_defs, **own_defs}
    bundled["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return bundled


def _stem(filename: str) -> str:
    return filename.replace(".schema.json", "").replace(".json", "")


def load_contracts() -> dict[str, dict]:
    raw = load_raw_contracts()
    return {name: bundle_schema(name, raw) for name in raw}


# ---------------------------------------------------------------------------
# 内置轻量校验器（未安装 jsonschema 时使用）
# ---------------------------------------------------------------------------

class ContractError(Exception):
    pass


def resolve_bundled_ref(schema: dict, ref: str):
    """解析已内联 schema 内部的 $ref（只可能是 # 或 #/$defs/...）。"""
    node = schema
    if ref == "#":
        return node
    if not ref.startswith("#/"):
        raise ContractError(f"未内联的外部引用：{ref}")
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise ContractError(f"$ref 无法解析：{ref}")
        node = node[part]
    return node


class MiniValidator:
    """覆盖本契约用到的 JSON Schema 关键字子集。"""

    SUPPORTED = {
        "$schema", "$id", "$defs", "title", "description", "examples", "default",
        "$ref", "type", "enum", "const", "required", "properties",
        "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "pattern", "format", "minLength", "maxLength",
        "allOf", "oneOf", "anyOf", "not",
    }

    def __init__(self, contracts: dict[str, dict]):
        self.contracts = contracts

    @staticmethod
    def _type_ok(value, expected: str) -> bool:
        if expected == "null":
            return value is None
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "string":
            return isinstance(value, str)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        raise ContractError(f"不支持的 type：{expected!r}")

    def validate(self, value, sch: dict, path: str, errors: list[str]) -> None:
        if not isinstance(sch, dict):
            raise ContractError(f"{path}: schema 不是对象")

        unknown = set(sch) - self.SUPPORTED
        if unknown:
            raise ContractError(
                f"{path}: 遇到不支持的关键字 {sorted(unknown)}。"
                f"请安装 jsonschema 以启用完整校验：pip install jsonschema"
            )

        if "$ref" in sch:
            ref = sch["$ref"]
            try:
                node = resolve_bundled_ref(self.contracts["__bundled__"], ref)
            except ContractError as e:
                raise ContractError(f"{path}: {e}")
            self.validate(value, node, path, errors)
            return

        for kw in ("allOf", "anyOf", "oneOf"):
            if kw not in sch:
                continue
            branches = sch[kw]
            if kw == "allOf":
                for b in branches:
                    self.validate(value, b, path, errors)
                return

            matched, branch_errors = 0, []
            for b in branches:
                sub: list[str] = []
                self.validate(value, b, path, sub)
                if not sub:
                    matched += 1
                else:
                    branch_errors.extend(sub)

            if matched == 0:
                errors.append(
                    f"{path}: 不满足 {kw}；" + "; ".join(branch_errors[:3])
                )
            elif kw == "oneOf" and matched > 1:
                errors.append(f"{path}: 同时满足 oneOf 的 {matched} 个分支")
            return

        if "not" in sch:
            sub: list[str] = []
            self.validate(value, sch["not"], path, sub)
            if not sub:
                errors.append(f"{path}: 命中了 not 排除的约束")
            return

        if "type" in sch:
            allowed = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
            if not any(self._type_ok(value, t) for t in allowed):
                errors.append(
                    f"{path}: 期望 {'/'.join(allowed)}，实际 {type(value).__name__}"
                    f"（值={_short(value)}）"
                )
                return

        if value is None:
            return

        if "enum" in sch and value not in sch["enum"]:
            errors.append(f"{path}: 取值 {_short(value)} 不在枚举 {sch['enum']} 中")
        if "const" in sch and value != sch["const"]:
            errors.append(f"{path}: 期望常量 {sch['const']!r}，实际 {_short(value)}")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in sch and value < sch["minimum"]:
                errors.append(f"{path}: {value} 小于最小值 {sch['minimum']}")
            if "maximum" in sch and value > sch["maximum"]:
                errors.append(f"{path}: {value} 大于最大值 {sch['maximum']}")
            if "exclusiveMinimum" in sch and value <= sch["exclusiveMinimum"]:
                errors.append(
                    f"{path}: {value} 未大于 {sch['exclusiveMinimum']}"
                )
            if "exclusiveMaximum" in sch and value >= sch["exclusiveMaximum"]:
                errors.append(
                    f"{path}: {value} 未小于 {sch['exclusiveMaximum']}"
                )

        if isinstance(value, str):
            if "pattern" in sch and not re.search(sch["pattern"], value):
                errors.append(f"{path}: {_short(value)} 不匹配模式 {sch['pattern']}")
            if "minLength" in sch and len(value) < sch["minLength"]:
                errors.append(
                    f"{path}: 字符串长度 {len(value)} 少于 minLength {sch['minLength']}"
                )
            if "maxLength" in sch and len(value) > sch["maxLength"]:
                errors.append(
                    f"{path}: 字符串长度 {len(value)} 超过 maxLength {sch['maxLength']}"
                )
            if sch.get("format") == "date-time" and not re.match(
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
                errors.append(f"{path}: {_short(value)} 不是合法的 date-time")

        if isinstance(value, list):
            if "minItems" in sch and len(value) < sch["minItems"]:
                errors.append(
                    f"{path}: 数组长度 {len(value)} 少于 minItems {sch['minItems']}"
                )
            if "maxItems" in sch and len(value) > sch["maxItems"]:
                errors.append(
                    f"{path}: 数组长度 {len(value)} 超过 maxItems {sch['maxItems']}"
                )
            if sch.get("uniqueItems"):
                seen, dupes = [], []
                for item in value:
                    key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if key in seen:
                        dupes.append(item)
                    else:
                        seen.append(key)
                if dupes:
                    errors.append(f"{path}: uniqueItems 约束下有重复元素")
            if "items" in sch:
                for i, item in enumerate(value):
                    self.validate(item, sch["items"], f"{path}[{i}]", errors)

        if isinstance(value, dict):
            for key in sch.get("required", []):
                if key not in value:
                    errors.append(f"{path}: 缺少必填字段 '{key}'")

            props = sch.get("properties", {})
            for key, sub_sch in props.items():
                if key in value:
                    self.validate(value[key], sub_sch, f"{path}.{key}", errors)

            extra = sch.get("additionalProperties")
            if extra is False:
                for key in value:
                    if key not in props:
                        errors.append(
                            f"{path}: 出现未定义字段 '{key}'"
                            f"（schema 为 additionalProperties: false）"
                        )
            elif isinstance(extra, dict):
                for key, val in value.items():
                    if key not in props:
                        self.validate(val, extra, f"{path}.{key}", errors)


def _short(v) -> str:
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def strip_fixture_meta(instance):
    """
    剥离 fixture 顶层的元数据字段（以 _ 开头）。

    契约文件对本项目的数据结构使用 additionalProperties: false，用于抓拼写错误。
    但 docs/11-Fixture规范.md 要求 fixture 带 _comment / _covers 等溯源信息，
    否则一份假数据在半年后无人知道它是干什么的。

    两者冲突时，在校验前剥离元数据，而不是放宽契约 —— 契约的严格性更有价值。
    """
    if not isinstance(instance, dict):
        return instance
    return {k: v for k, v in instance.items() if not k.startswith("_")}


# Flutter 的 asset 必须是包内路径（不支持 ../ 引用包外文件），
# 而 fixture 的「单一事实来源」在仓库根的 samples/fixtures/。
# 因此每次校验通过后，把它们同步到 App 包内，避免两份漂移。
MOBILE_FIXTURE_DIR = ROOT / "mobile" / "assets" / "fixtures"


def sync_mobile_fixtures() -> list[str]:
    """把 samples/fixtures 同步到 mobile/assets/fixtures。返回变化的文件名。"""
    MOBILE_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []

    for src in sorted(FIXTURE_DIR.glob("*.json")):
        if src.name.startswith("_"):
            continue
        dst = MOBILE_FIXTURE_DIR / src.name
        data = src.read_bytes()
        if dst.exists() and dst.read_bytes() == data:
            continue
        dst.write_bytes(data)
        changed.append(src.name)

    # 清掉 App 包里已被删除的 fixture，避免残留导致误加载
    for dst in sorted(MOBILE_FIXTURE_DIR.glob("*.json")):
        if not (FIXTURE_DIR / dst.name).exists():
            dst.unlink()
            changed.append(f"-{dst.name}")

    return changed


def validate_instance(contracts: dict[str, dict], schema_name: str,
                      instance: dict) -> list[str]:
    filename = schema_name if schema_name.endswith(".json") \
        else f"{schema_name}.schema.json"
    if filename not in contracts:
        raise SystemExit(
            f"[FAIL] 找不到契约 {filename}。可用的有：{sorted(contracts)}"
        )

    schema = contracts[filename]
    instance = strip_fixture_meta(instance)

    if HAS_JSONSCHEMA:
        validator = jsonschema.Draft202012Validator(schema)
        return [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        ]

    errors: list[str] = []
    MiniValidator({**contracts, "__bundled__": schema}).validate(
        instance, schema, "$", errors
    )
    return errors


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="契约校验（质量门 G2）")
    ap.add_argument("--fixture", type=Path, help="要校验的 JSON 文件")
    ap.add_argument("--schema", help="对应的契约名，如 analysis / pose / task")
    ap.add_argument("--dir", type=Path,
                    help="批量校验目录，文件名前缀即契约名（analysis_normal.json -> analysis）")
    ap.add_argument("--self-test", action="store_true", help="只检查契约自身是否自洽")
    ap.add_argument("--sync-mobile", action="store_true",
                    help="校验通过后，把 fixture 同步到 mobile/assets/fixtures/")
    args = ap.parse_args()

    contracts = load_contracts()
    engine = "jsonschema（完整校验）" if HAS_JSONSCHEMA else "内置轻量校验器"

    print("=" * 68)
    print("契约校验（质量门 G2）")
    print("=" * 68)
    print(f"契约目录：{CONTRACT_DIR}")
    print(f"载入契约：{len(contracts)} 份")
    print(f"校验引擎：{engine}")
    print()
    if not HAS_JSONSCHEMA:
        print("提示：pip install jsonschema 可获得更完整的校验（format、复杂组合）")
        print()

    print("[OK] 契约自洽性通过（跨文件引用已全部内联，无未解析引用）")
    print()

    if args.self_test:
        return

    if args.dir:
        if not args.dir.exists():
            raise SystemExit(f"[FAIL] 目录不存在：{args.dir}")
        total = failed = 0
        for path in sorted(args.dir.glob("*.json")):
            if path.name.startswith("_"):
                continue
            schema_name = path.stem.split("_")[0]
            total += 1
            try:
                instance = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                failed += 1
                print(f"[FAIL] {path.name}  不是合法 JSON：{e}")
                continue
            errors = validate_instance(contracts, schema_name, instance)
            if errors:
                failed += 1
                print(f"[FAIL] {path.name}  （按 {schema_name} 校验）")
                for e in errors[:12]:
                    print(f"    {e}")
                if len(errors) > 12:
                    print(f"    ... 另有 {len(errors) - 12} 处")
            else:
                print(f"[OK] {path.name}  （按 {schema_name} 校验）")
        print()
        print(f"合计 {total} 份，失败 {failed} 份")
        if failed:
            sys.exit(1)

        if args.sync_mobile:
            # 只有全部校验通过才同步 —— 不能把不合格的数据带进 App
            changed = sync_mobile_fixtures()
            print()
            if changed:
                print(f"已同步到 mobile/assets/fixtures/：{', '.join(changed)}")
            else:
                print("mobile/assets/fixtures/ 已是最新")
        return

    if not args.fixture:
        ap.print_help()
        print()
        print("示例：")
        print("  python scripts/check_contracts.py --dir samples/fixtures")
        print("  python scripts/check_contracts.py "
              "--fixture samples/fixtures/analysis_normal.json --schema analysis")
        return

    if not args.fixture.exists():
        raise SystemExit(f"[FAIL] 文件不存在：{args.fixture}")

    schema_name = args.schema or args.fixture.stem.split("_")[0]
    instance = json.loads(args.fixture.read_text(encoding="utf-8"))
    errors = validate_instance(contracts, schema_name, instance)

    if errors:
        print(f"[FAIL] {args.fixture.name} 不符合 {schema_name} 契约：")
        for e in errors:
            print(f"    {e}")
        sys.exit(1)

    print(f"[OK] {args.fixture.name} 符合 {schema_name} 契约")


if __name__ == "__main__":
    main()
