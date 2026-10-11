#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON Schema -> Dart 模型生成器
==============================

用法
----
    python scripts/gen_models.py
    python scripts/gen_models.py --check      # 只检查是否需要重新生成

输入
----
    backend/contracts/*.schema.json

输出
----
    mobile/lib/models/models.dart   —— 全部模型与枚举（单文件，零依赖）
    mobile/lib/models/enums.dart    —— 全部枚举

为什么必须生成，不能手写
------------------------
手写客户端模型与契约的漂移是必然的：契约改了字段名，前端不会报错，
只会静默收到 null，然后在某个界面上显示成空白 —— 而且可能在两周后才被发现。

这条约束对应 docs/10-工程规范与验收.md 质量门 G2。

为什么输出单文件而不是每个契约一个文件
--------------------------------------
契约之间存在交叉引用：analysis 引用 session / metric / finding，
session 又引用 common 的 Athlete，metric 引用 common 的 ReferenceRange。
按契约分文件就必须处理跨文件 import 与重复类名，收益很低、出错概率很高。

单文件零依赖对 App 侧也更省事：一句
    import 'package:yu_coach/models/models.dart';
就能拿到全部类型。

支持的范围
----------
只处理契约中实际用到的 JSON Schema 子集：
    type / required / properties / items / $ref / enum
    type 为数组（可空）/ oneOf（枚举的可空写法）/ allOf（叠加 description）
遇到不支持的构造会明确报错，而不是静默生成错误的代码。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 输出编码
# ---------------------------------------------------------------------------
#
# Windows 上两个坑：
#   1. 输出到控制台时用控制台代码页（中文 Windows 为 GBK），少数符号无法编码
#      会抛 UnicodeEncodeError 直接终止脚本。
#   2. 输出到管道/文件时 sys.stdout.encoding 报告的仍是控制台编码，
#      而下游按 UTF-8 解码 -> 中文乱码。
# 因此判定依据是 isatty()，而不是当前 encoding 值。

def _init_console() -> None:
    import io
    stream = sys.stdout
    try:
        if stream.isatty():
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass
            return
    except Exception:
        pass
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
# 路径与配置
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "backend" / "contracts"
OUT_DIR = ROOT / "mobile" / "lib" / "models"

# 生成文件里的运行时辅助函数。
#
# 为什么必须有它 —— 这是踩过的坑，代价很高：
#
#   Dart 里字面量 {'a': 1, 'b': false} 的类型是 Map<String, Object>，
#   **不是** Map<String, dynamic>。所以
#       json['nested'] as Map<String, dynamic>
#   在运行时**转换失败并返回 null**（`as` 在失败时抛错，但这里因为目标
#   类型可空，实际得到 null；无论如何嵌套对象都读不出来）。
#
#   后果：fromJson 拿到 null map，接着就是
#       Null check operator used on a null value
#   报错位置在模型内部，跟 JSON 内容看不出任何关系，极难定位。
#
# 服务端返回的嵌套对象一定会踩到这个（JSON 解码的嵌套 map 未必是
# Map<String, dynamic>）。用显式重建代替强转，彻底避开类型差异。
_AS_MAP_HELPER = '''/// 把任意 Map 安全地转成 `Map<String, dynamic>`。
///
/// 不能用 `as Map<String, dynamic>` —— 字面量与部分 JSON 解码结果的实际类型
/// 是 `Map<String, Object>`，强转会失败，得到 null 而不是抛错，
/// 随后在模型内部炸出与真正原因无关的空指针异常。
Map<String, dynamic> _asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  throw FormatException('期望 JSON 对象，实际是 ${value.runtimeType}');
}

/// 同 [_asMap]，但允许 null —— 供契约声明为可空的字段使用。
Map<String, dynamic>? _asMapOrNull(Object? value) {
  if (value == null) return null;
  return _asMap(value);
}

/// 解析枚举，失败时给出**能直接定位问题**的错误信息。
///
/// 为什么需要它：枚举解析失败原本只会让 fromJson 得到 null，
/// 随后在 `!` 处抛出 "Null check operator used on a null value" ——
/// 报错位置在模型内部的某一行，既没说哪个字段，也没说收到了什么值，
/// 排查成本极高（本项目在此处浪费过大量时间）。
///
/// 现在会直接指明：字段名、收到的值、期望的取值集合。
T _enumFromJson<T>(
  Object? value,
  T? Function(Object?) parse,
  String fieldName,
  Map<T, String> allowed,
) {
  final parsed = parse(value);
  if (parsed != null) return parsed;
  if (value == null) {
    throw FormatException('字段 "$fieldName" 缺失或为 null，期望取值为 ${allowed.values.toList()}');
  }
  throw FormatException(
    '字段 "$fieldName" 收到未知取值 "$value"，期望取值为 ${allowed.values.toList()}',
  );
}'''

# 只有接口响应的根才是模型入口。
# common.schema.json 不在此列：它是定义仓库，根上没有任何数据字段，
# 它的内容全部通过 $defs 引用惰性实例化。把它列为入口只会生成一个空壳类。
ENTRY_POINTS: dict[str, str] = {
    "session.schema.json": "Session",
    "pose.schema.json": "PoseResponse",
    "metric.schema.json": "Metric",
    "finding.schema.json": "Finding",
    "analysis.schema.json": "AnalysisResult",
    "task.schema.json": "AnalysisTask",
    "error.schema.json": "ApiError",
}

JSON_TO_DART = {
    "string": "String",
    "integer": "int",
    "number": "double",
    "boolean": "bool",
    "object": "Map<String, dynamic>",
}

PRIMITIVES = set(JSON_TO_DART.values()) | {"Object?", "String", "int", "double", "bool"}

# 叶子定义：没有 properties、也不是枚举或数组，只能当标量处理。
# 正常契约不会出现，出现即表示契约写漏了内容 —— 必须显式暴露，不能静默当成对象。
LEAF_DEF_TYPES = ("string", "integer", "number", "boolean")


# ---------------------------------------------------------------------------
# 命名
# ---------------------------------------------------------------------------

_IDENT_SPLIT = re.compile(r"[_\-.\s]+")
_DART_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 字段名里的常见缩略词，还原成完整词，避免生成 AthleteAthleteLevel 这种重复名字
_WORD_EXPANSIONS = {
    "id": "Id",
    "ids": "Ids",
    "fps": "Fps",
    "url": "Url",
    "uri": "Uri",
    "api": "Api",
    "json": "Json",
    "ui": "Ui",
}


def _capitalize_words(name: str) -> str:
    """按分隔符切分并逐词首字母大写，同时还原常见缩略词。"""
    parts = [p for p in _IDENT_SPLIT.split(name) if p]
    return "".join(_WORD_EXPANSIONS.get(p.lower(), p[:1].upper() + p[1:])
                   for p in parts)


def to_pascal(name: str) -> str:
    """把任意命名转成 PascalCase。

    分隔符包含点号：契约文件名是 "common.schema.json"，
    取 stem 后是 "common.schema"，若只按下划线/连字符切分会得到
    "Common.schema" —— 含点号，是非法 Dart 标识符。
    """
    return _capitalize_words(name)


def to_camel(name: str) -> str:
    p = to_pascal(name)
    return p[:1].lower() + p[1:] if p else p


def assert_dart_ident(name: str, what: str) -> None:
    """守卫：生成的类名/枚举名必须是合法 Dart 标识符。

    这类问题不会在生成阶段报错，只会在 Flutter 编译时以一行晦涩的
    parser 错误暴露。在生成阶段拦住，能省掉大量排查时间。
    """
    if not _DART_IDENT.match(name):
        raise SystemExit(
            f"[FAIL] 生成出的{what} '{name}' 不是合法的 Dart 标识符。"
            f"请检查契约里的定义名或文件名是否为纯 ASCII 且以字母/下划线开头。"
        )


# Dart 保留字不能用作标识符。枚举取值若恰好是保留字（如契约里的 unit 取值
# "enum"），必须改名，否则生成 `enum MetricUnit { enum; }` 这种无法编译的代码。
_DART_RESERVED = {
    "abstract", "as", "assert", "async", "await", "base", "break", "case",
    "catch", "class", "const", "continue", "covariant", "default", "deferred",
    "do", "dynamic", "else", "enum", "export", "extends", "extension",
    "external", "factory", "false", "final", "finally", "for", "function",
    "get", "hide", "if", "implements", "import", "in", "interface", "is",
    "late", "library", "mixin", "new", "null", "on", "operator", "part",
    "required", "rethrow", "return", "sealed", "set", "show", "static",
    "super", "switch", "sync", "this", "throw", "true", "try", "type",
    "typedef", "var", "void", "when", "while", "with", "yield",
}

# 与 Flutter 自带类型重名的枚举，必须改名。否则 App 里每个
# `import 'package:flutter/material.dart'` 的文件都会报
# ambiguous_import，必须写 import 前缀才能用 —— 纯粹的负担。
#
# 目前已知：契约的 View（拍摄视角）撞上 Flutter 的 View（渲染视图）。
# 由 _ENUM_NAME_OVERRIDES 把它改名为 SessionView 解决。
#
# 按「取值集合」把过于冗长或与 Flutter 冲突的枚举改成更好的名字。
# 键是取值集合的字典序前 3 项，足以唯一识别。
_ENUM_NAME_OVERRIDES: dict[tuple[str, ...], str] = {
    ("side", "front", "back"): "SessionView",
    ("major", "minor", "info", "insufficient_data"): "FindingSeverity",
    ("low_frame_rate", "view_mismatch", "no_reference_scale"): "InsufficientReason",
}

# 短单位名保持原样更贴近契约含义（ms = 毫秒，m = 米），
# 但对净化后会发生碰撞的取值（"m/s" -> ms 撞上毫秒）必须用可区分的名字。
# 注意 Dart 大小写敏感，"mS" 与 "ms" 是两个不同标识符。
_MEMBER_OVERRIDES = {
    "m/s": "mPerS",
    "steps/min": "stepsPerMin",
    "km/h": "kmPerH",
}

# 只有前导数字需要补前缀，不要加 v 前缀 —— 否则 "0" 会变成 v0，
# 与真实取值 "v0" 撞名，凭空制造冲突。
_LEADING_DIGIT_PREFIX = "n"


def to_member_ident(value: str) -> str:
    """
    把枚举的**取值**转成合法且唯一的 Dart 枚举成员名。

    取值允许包含任意字符（如单位 "m/s"、"steps/min"），但 Dart 标识符只能是
    字母、数字、下划线，且不能是保留字。必须净化，否则会生成
    `enum MetricUnit { m/s }` 或 `enum MetricUnit { enum; }` 这类无法编译的代码。

        "m/s"           -> mPerS      （有覆盖表，避免与 ms 撞名）
        "steps/min"     -> stepsPerMin
        "sub_elite"     -> subElite
        "left_to_right" -> leftToRight
        "enum"          -> enumValue  （保留字）
        "0"             -> n0
    """
    if value in _MEMBER_OVERRIDES:
        return _MEMBER_OVERRIDES[value]

    parts = [p for p in _IDENT_SPLIT.split(value) if p]
    if not parts:
        return "empty"
    head, *rest = parts
    ident = head[:1].lower() + head[1:] + "".join(
        p[:1].upper() + p[1:] for p in rest
    )
    ident = re.sub(r"[^A-Za-z0-9_]", "", ident)
    if not ident:
        return "empty"
    if ident[0].isdigit():
        ident = f"{_LEADING_DIGIT_PREFIX}{ident}"
    if ident in _DART_RESERVED:
        ident = f"{ident}Value"
    return ident


def unique_member_idents(values: list[str]) -> list[str]:
    """为每个取值生成唯一成员名（同名字加序号后缀）。"""
    used: dict[str, int] = {}
    out: list[str] = []
    for v in values:
        base = to_member_ident(v)
        n = used.get(base, 0)
        used[base] = n + 1
        out.append(base if n == 0 else f"{base}{n + 1}")
    return out


def dart_string(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _doc_comment(text: str, indent: str = "") -> str:
    text = " ".join(text.split())
    if len(text) <= 86:
        return f"{indent}/// {text}"
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 82:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(f"{indent}/// {l}" for l in lines)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Field:
    json_name: str
    dart_name: str
    dart_type: str
    required: bool              # 契约里 required：键必须存在
    ctor_required: bool         # Dart 构造函数是否要求传入
    nullable: bool              # JSON 值是否可以为 null
    doc: str | None = None
    enum_name: str | None = None
    is_list_of_enum: bool = False


@dataclass
class EnumDef:
    name: str
    values: list[str]


@dataclass
class Model:
    name: str
    fields: list[Field] = field(default_factory=list)
    doc: str | None = None


# ---------------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------------

class Generator:

    def __init__(self, contracts: dict[str, dict]):
        self.contracts = contracts
        self.models: dict[str, Model] = {}
        self.enums: dict[str, EnumDef] = {}
        self._enum_by_values: dict[tuple[str, ...], str] = {}
        self._def_by_name: dict[str, tuple[str, str]] = {}
        self._building: set[str] = set()
        self._current_class: str | None = None

    # -- 引用 -------------------------------------------------------------

    def _resolve(self, ref: str, current_file: str) -> tuple[str, dict]:
        if ref.startswith("#/"):
            target_file, pointer = current_file, ref[2:]
        else:
            file_part, _, pointer = ref.partition("#")
            target_file = file_part.lstrip("/") or current_file
            pointer = pointer.lstrip("/")

        if target_file not in self.contracts:
            raise SystemExit(f"[FAIL] $ref 指向不存在的文件：{ref}")

        node = self.contracts[target_file]
        if pointer:
            for part in pointer.split("/"):
                if not part:
                    continue
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or part not in node:
                    raise SystemExit(f"[FAIL] $ref 无法解析：{ref}（缺 '{part}'）")
                node = node[part]
        return target_file, node

    # -- 枚举 -------------------------------------------------------------

    def _enum_for(self, values: list[str], hint: str,
                  parent: str | None = None) -> str:
        """
        取得（或创建）Dart 枚举名。

        去重按**取值集合**进行，而不是按字段名。
        原因：契约里 View 类型的字段叫 declared / detected / direction，
        状态类字段叫 status / stage_status，字段名各不相同但取值完全一样。
        若按字段名建枚举，会得到 SessionView 与 ViewDirection 两个取值相同
        却互不兼容的类型，App 侧必须写转换函数才能互相赋值 —— 纯粹的负担。

        代价是枚举名取自最先遇到的那个字段（如 ViewDirection 而非 SessionView）。
        名字略不完美，但类型正确、数量可控，这个取舍是划算的。

        命名优先 <所属类><字段名>（如 MetricUnit），因此 status / unit / name
        这类过于宽泛的字段名不会生成出 Status、Unit 这类类型名。
        """
        key = tuple(values)
        if key in self._enum_by_values:
            return self._enum_by_values[key]

        # 先用覆盖表：某些枚举名过长（InsufficientInfoInsufficientReason）
        # 或与 Flutter 类型冲突（View），必须由生成器统一改名，
        # 否则每个使用它的文件都要写 import 前缀。
        if key[:3] in _ENUM_NAME_OVERRIDES:
            name = _ENUM_NAME_OVERRIDES[key[:3]]
            assert_dart_ident(name, "枚举名")
            self.enums[name] = EnumDef(name=name, values=list(values))
            self._enum_by_values[key] = name
            return name

        base = to_pascal(hint) or "Value"
        name = f"{parent}{base}" if parent else base
        # 去掉与父类重复的前缀：Athlete + AthleteLevel -> AthleteLevel
        if parent and base.startswith(parent) and len(base) > len(parent):
            name = base
        name = re.sub(r"[^A-Za-z0-9_]", "", name) or "Value"
        if name[:1].isdigit():
            name = f"E{name}"

        # 名称被**别的**取值集合占用时降级：先用字段名，再退到字段名+序号。
        # 注意不能沿用 name 自身加序号，否则会得到 MetricUnit2 这种既丑
        # 又看不出含义的名字。
        if name in self.enums:
            base_clean = re.sub(r"[^A-Za-z0-9_]", "", base) or "Value"
            candidate = base_clean
            n = 2
            while candidate in self.enums:
                candidate = f"{base_clean}{n}"
                n += 1
            name = candidate

        assert_dart_ident(name, "枚举名")
        self.enums[name] = EnumDef(name=name, values=list(values))
        self._enum_by_values[key] = name
        return name

    # -- 类型 -------------------------------------------------------------

    def _dart_type(self, sch: dict, current_file: str, hint: str,
                   ) -> tuple[str, str | None, bool]:
        """返回 (dart 类型, 枚举名, 是否枚举列表)。"""
        if "$ref" in sch:
            target_file, node = self._resolve(sch["$ref"], current_file)
            pointer = sch["$ref"].partition("#")[2]

            # 指向 $defs 里的具名定义。跨文件写法（"common.schema.json#/$defs/X"）
            # 与同文件写法（"#/$defs/X"）必须走同一条路径：
            # 早期版本只识别后者，导致 common 的每个定义都被当成「整个文件」，
            # 统一退化成根类名，生成出 22 个字段全是 CommonSchema 的废代码。
            if "/$defs/" in pointer:
                ref_name = pointer.rsplit("/", 1)[-1]
                return self._type_for_def(ref_name, node, target_file, hint)

            cls = ENTRY_POINTS.get(target_file, to_pascal(Path(target_file).stem))
            self._build_object(cls, node, target_file)
            return cls, None, False

        if "allOf" in sch:
            for sub in sch["allOf"]:
                return self._dart_type(sub, current_file, hint)
            raise SystemExit(f"[FAIL] allOf 为空：{hint}")

        if "oneOf" in sch:
            non_null = [v for v in sch["oneOf"] if v.get("type") != "null"]
            if len(non_null) == 1:
                return self._dart_type(non_null[0], current_file, hint)
            raise SystemExit(f"[FAIL] 不支持的 oneOf（多个非 null 分支）：{hint}")

        t = sch.get("type")
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            if len(non_null) == 1:
                return self._dart_type({**sch, "type": non_null[0]}, current_file, hint)
            return "Object?", None, False

        if t == "array":
            item_hint = hint.rstrip("s") or f"{hint}Item"
            item_type, item_enum, _ = self._dart_type(
                sch.get("items", {"type": "object"}), current_file,
                to_pascal(item_hint),
            )
            return f"List<{item_type}>", item_enum, item_enum is not None

        if t == "object":
            if "properties" in sch:
                name = to_pascal(hint)
                self._build_object(name, sch, current_file)
                return name, None, False
            return "Map<String, dynamic>", None, False

        if "enum" in sch:
            values = [str(v) for v in sch["enum"] if v is not None]
            enum_name = self._enum_for(values, hint, parent=self._current_class)
            return enum_name, enum_name, False

        if t in JSON_TO_DART:
            return JSON_TO_DART[t], None, False

        raise SystemExit(f"[FAIL] 无法处理的 schema 类型：type={t!r} 位置={hint}")

    def _type_for_def(self, def_name: str, node: dict, source_file: str,
                      hint: str) -> tuple[str, str | None, bool]:
        """
        把一个 $defs 定义解析成 Dart 类型。

        枚举 / 数组走 _dart_type 递归（会按需建 enum 或 List），
        有 properties 的建成模型类。

        叶子标量（如 Confidence 是带 0-1 约束的 number）本身就是有效定义：
        Dart 侧无法为约束建类型，内联为标量即可，JSON 解析行为完全正确 ——
        唯一的损失是把 minimum/maximum 的校验推迟到服务端。

        真正的契约缺陷是「叶子且没有任何取值约束」（如裸的 {"type":"string"}）：
        这种定义既不表达结构也不表达取值，只是把 String 换了个名字。
        此时报错，要求作者写明 enum 或直接内联。
        """
        if "enum" in node or node.get("type") == "array":
            return self._dart_type(node, source_file, to_pascal(def_name))

        if "properties" in node:
            cls = to_pascal(def_name)
            self._build_object(cls, node, source_file)
            return cls, None, False

        t = node.get("type")
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            if len(non_null) == 1:
                t = non_null[0]

        if t in LEAF_DEF_TYPES:
            constraints = {
                k for k in ("pattern", "minimum", "maximum", "minLength",
                            "maxLength", "enum", "const", "format")
                if k in node
            }
            if not constraints:
                raise SystemExit(
                    f"[FAIL] 定义 '{def_name}'（{source_file}）是没有任何取值约束的"
                    f"叶子类型（{t}）。这样的定义只把 {t} 换了个名字，不表达任何语义。"
                    f"请改为写明取值约束（enum / pattern / 范围），或在使用处直接内联。"
                )
            return JSON_TO_DART[t], None, False

        return self._dart_type(node, source_file, to_pascal(def_name))

    # -- 对象 -------------------------------------------------------------

    def _build_object(self, name: str, sch: dict, current_file: str):
        if name in self.models or name in self._building:
            return
        if not isinstance(sch, dict) or "properties" not in sch:
            return
        # 只处理真正的数据对象。common.schema.json 这类文件根部只有
        # title / description / $defs，是 schema 容器而非数据模型。
        # 判据必须是"有 $defs 但没有 properties"：
        #   - 不能只看 $defs 是否存在：pose / analysis 的根**是**数据模型，
        #     只是同时带了自己的 $defs
        #   - 不能看 $schema / $id：所有契约文件都有这两个键
        if "$defs" in sch and "properties" not in sch:
            return

        self._building.add(name)
        assert_dart_ident(name, "模型类名")
        prev_class = self._current_class
        self._current_class = name
        model = Model(name=name, doc=(sch.get("description") or "").strip() or None)
        required = set(sch.get("required", []))

        for prop_name, prop_sch in sch["properties"].items():
            dart_name = to_camel(prop_name)
            assert_dart_ident(dart_name, f"字段名（{prop_name}）")

            dart_type, enum_name, is_list_enum = self._dart_type(
                prop_sch, current_file, to_pascal(prop_name)
            )
            is_required = prop_name in required

            # 三个概念必须分清，混在一起就会生成自相矛盾的代码：
            #
            #   is_required —— 键是否必须出现在 JSON 里（契约 required）
            #   nullable    —— 值是否可以为 null（类型含 null）
            #   ctor_required —— Dart 构造函数是否强制传参
            #
            # 映射关系（Dart 只有「可空/非空」一维，必须这样落）：
            #
            #   契约                  Dart 类型   读取时        构造函数
            #   required，非空    ->  非空       `json[k]!`    required
            #   required，可空    ->  可空       `json[k]`     可选
            #   非 required，可空 ->  可空       `json[k]`     可选
            #
            # 两条硬规则：
            #   1. 可空类型不能标 required —— Dart 报
            #      missing_default_value_for_parameter
            #   2. 非空类型**必须**标 required —— 否则参数没有默认值也没人传，
            #      同样报错
            # 所以 ctor_required 直接由最终 Dart 类型推出，不由契约 required 推。
            #
            # 契约 required 的作用体现在读取上：`json[k]!` 保证键必须存在，
            # 缺失立刻抛错，契约不会被静默绕过。
            nullable = self._is_nullable(prop_sch)
            if nullable and not dart_type.endswith("?"):
                dart_type = f"{dart_type}?"
            ctor_required = not dart_type.endswith("?")

            model.fields.append(Field(
                json_name=prop_name,
                dart_name=dart_name,
                dart_type=dart_type,
                required=is_required,
                ctor_required=ctor_required,
                nullable=nullable,
                doc=(prop_sch.get("description") or "").strip() or None,
                enum_name=enum_name,
                is_list_of_enum=is_list_enum,
            ))

        self._current_class = prev_class
        self._building.discard(name)
        self.models[name] = model

    @staticmethod
    def _is_nullable(sch: dict) -> bool:
        t = sch.get("type")
        if isinstance(t, list):
            if "null" in t:
                return True
            if len([x for x in t if x != "null"]) > 1:
                return True
        for sub in sch.get("allOf", []) + sch.get("oneOf", []):
            if sub.get("type") == "null":
                return True
            if isinstance(sub.get("type"), list) and "null" in sub["type"]:
                return True
        return False

    # -- 构建 -------------------------------------------------------------

    def build(self) -> None:
        """
        构建各入口类。

        注意：本函数**不**构建根级 $defs。根级 $defs 中的定义一律惰性创建 ——
        只有被某个 $ref 真正引用到时才生成 Dart 类型。
        早期版本一次性构建全部定义，把契约文件顶层的 schema 元数据也当成
        数据模型，生成出 "Common.schema" 这种含点号的非法类名。
        """
        for filename, class_name in ENTRY_POINTS.items():
            if filename not in self.contracts:
                raise SystemExit(f"[FAIL] 缺少契约文件：{filename}")
            self._build_object(class_name, self.contracts[filename], filename)

    # -- 拓扑排序 ---------------------------------------------------------

    def _ordered(self) -> tuple[list[str], list[str]]:
        """
        全部模型与枚举，按依赖顺序排列（被依赖者在前）。

        这一步不能省：契约里存在相互引用（Analysis 引用 Session 与 Metric，
        Session 又引用 common 的 Athlete），直接按构建顺序输出会得到
        「类在使用前未定义」的 Dart 代码。
        """
        models: list[str] = []
        enums: list[str] = []
        seen_m: set[str] = set()
        seen_e: set[str] = set()

        def visit(name: str, chain: tuple[str, ...]):
            if name not in self.models or name in seen_m:
                return
            if name in chain:
                return          # 循环引用：跳过，Dart 允许类之间互相引用
            seen_m.add(name)
            for f in self.models[name].fields:
                if f.enum_name and f.enum_name not in seen_e:
                    seen_e.add(f.enum_name)
                    enums.append(f.enum_name)
                base = f.dart_type.rstrip("?")
                if base.startswith("List<"):
                    base = base[5:-1]
                if base in self.models and base not in seen_m:
                    visit(base, chain + (name,))
            models.append(name)

        for class_name in ENTRY_POINTS.values():
            visit(class_name, ())

        return models, enums

    # -- 输出 -------------------------------------------------------------

    def _emit_enum(self, e: EnumDef) -> str:
        members = unique_member_idents(e.values)
        lines = [f"enum {e.name} {{"]
        for i, m in enumerate(members):
            comma = "," if i < len(members) - 1 else ";"
            lines.append(f"  {m}{comma}")
        lines += [
            "",
            "  String toJson() => _values[this]!;",
            "",
            "  /// 契约允许的全部取值。用于在解析失败时给出可定位的错误信息。",
            f"  static Map<{e.name}, String> get valuesJson => _values;",
            "",
            "  /// 未知取值返回 null，而不是抛异常。",
            "  /// 契约新增枚举值时（Minor 版本），旧客户端应能降级处理而非崩溃。",
            f"  static {e.name}? fromJson(Object? v) {{",
            "    if (v == null) return null;",
            "    final key = v.toString();",
            "    for (final entry in _values.entries) {",
            "      if (entry.value == key) return entry.key;",
            "    }",
            "    return null;",
            "  }",
            "",
            f"  static const _values = <{e.name}, String>{{",
        ]
        for m, v in zip(members, e.values):
            lines.append(f"    {e.name}.{m}: {dart_string(v)},")
        lines += ["  };", "}"]
        return "\n".join(lines)

    def _emit_model(self, m: Model) -> str:
        lines: list[str] = []
        if m.doc:
            lines.append(_doc_comment(m.doc))
        lines.append(f"class {m.name} {{")

        for f in m.fields:
            if f.doc:
                lines.append(_doc_comment(f.doc, indent="  "))
            lines.append(f"  final {f.dart_type} {f.dart_name};")
        lines.append("")

        ctor = ",\n".join(
            _ctor_param(f) for f in m.fields
        )
        lines += [f"  const {m.name}({{", ctor, "  });", ""]

        lines.append(f"  static {m.name} fromJson(Map<String, dynamic> json) {{")
        lines.append(f"    return {m.name}(")
        for f in reversed(m.fields):
            lines.append(f"      {f.dart_name}: {_reader(f)},")
        lines += ["    );", "  }", ""]

        lines.append("  Map<String, dynamic> toJson() {")
        lines.append("    return {")
        for f in sorted(m.fields, key=lambda x: x.json_name):
            lines.append(f"      {dart_string(f.json_name)}: {_writer(f)},")
        lines += ["    };", "  }", "}"]
        return "\n".join(lines)

    def emit_models(self) -> str:
        models, enums = self._ordered()
        header = (
            "// GENERATED FILE - DO NOT EDIT BY HAND\n"
            "//\n"
            "// 生成命令： python scripts/gen_models.py\n"
            "// 来源契约： backend/contracts/*.schema.json\n"
            "//\n"
            "// 契约版本变更后必须重新生成。手写修改会在下次生成时被覆盖。\n"
            "//\n"
            "// 本文件零依赖，只需：\n"
            "//   import 'package:yu_coach/models/models.dart';\n"
        )
        parts = [_AS_MAP_HELPER]
        parts += [self._emit_enum(self.enums[e]) for e in enums]
        parts += [self._emit_model(self.models[m]) for m in models]
        return header + "\n" + "\n\n".join(parts) + "\n"

    def emit_enums(self) -> str:
        _, enums = self._ordered()
        header = (
            "// GENERATED FILE - DO NOT EDIT BY HAND\n"
            "//\n"
            "// 生成命令： python scripts/gen_models.py\n"
            "// 仅含枚举定义，便于只想引用枚举的场合。\n"
        )
        parts = [self._emit_enum(self.enums[e]) for e in enums]
        return header + "\n" + "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# JSON 读写辅助
# ---------------------------------------------------------------------------

def _base_type(t: str) -> str:
    return t.rstrip("?")


def _ctor_param(f: Field) -> str:
    """
    生成构造函数参数。

    契约 required 的字段一律标 `required`。注意不要给可空字段写 `= null`：
    Dart 会把「有默认值的参数」视为可省略，进而推断字段实际上不会被显式传入，
    在调用处产生 dead_code / dead_null_aware_expression 警告。
    """
    if f.ctor_required:
        return f"    required this.{f.dart_name}"
    return f"    this.{f.dart_name}"


def _reader(f: Field) -> str:
    """
    生成 fromJson 的取值表达式。

    要区分两个层次，它们现在可以不同：
      · f.required      —— 契约层：键必须出现在 JSON 里
      · dart 可空性     —— Dart 层：字段类型是否可空

    组合有四种，其中两种容易搞错：
      required + 类型可空（如 metric.value）：
          schema 允许 null，但生成代码在键缺失时会抛错 —— 这正是 required 的价值
      required + 类型非空：
          读取表达式必须产出非空值，标量要加 `!`，不能返回 `?.toDouble()`
    """
    t = _base_type(f.dart_type)
    # 可空性以契约声明为准，而不是最终 Dart 类型。
    # 两者的区别只出现在「required 且类型可空」的字段上（如 source.fps_verified）：
    #   Dart 类型是非空 double?… 不，是 double? 但构造函数要求传入。
    # 这类字段 JSON 里仍可能出现 null，因此读取必须走可空路径，
    # 再用 `!` 快速失败 —— 契约说不为 null 却给了 null，就该立刻暴露。
    nullable = f.nullable
    key = dart_string(f.json_name)
    suffix = "?" if nullable else ""
    bang = "" if nullable else "!"

    # 键不存在时的兜底：契约要求必填就不能静默给 null，否则契约形同虚设
    src = f"json[{key}]"
    if f.required and not nullable:
        src = f"json[{key}]!"

    if f.enum_name and t == f.enum_name:
        if nullable:
            # 可空字段：解析不出就返回 null，由上层决定怎么降级
            return f"{f.enum_name}.fromJson({src})"
        # 非空字段：用带诊断信息的包装，失败时直接指出字段名与收到的值。
        # 裸写 `X.fromJson(v)!` 只会抛 "Null check operator used on a null
        # value"，既不知字段也不知取值，排查成本极高。
        return (f"_enumFromJson<{f.enum_name}>({src}, "
                f"{f.enum_name}.fromJson, '{f.json_name}', "
                f"{f.enum_name}.valuesJson)")
    if f.is_list_of_enum and f.enum_name:
        # 列表里的未知枚举值用 whereType 丢弃，不需要断言
        if nullable:
            return (f"({src} as List<dynamic>?)"
                    f"?.map((e) => {f.enum_name}.fromJson(e))"
                    f".whereType<{f.enum_name}>().toList()")
        return (f"({src} as List<dynamic>)"
                f".map((e) => {f.enum_name}.fromJson(e))"
                f".whereType<{f.enum_name}>().toList()")
    if t.startswith("List<"):
        inner = t[5:-1]
        if inner in PRIMITIVES:
            # 非空字段必须断言源列表本身，用 `as List<dynamic>` 而非 `?.cast()`：
            # `(x as List?)?.cast<T>()` 的结果仍是 List<T>?，赋给非空字段报错
            if nullable:
                return f"({src} as List<dynamic>?)?.cast<{inner}>()"
            return f"({src} as List<dynamic>).cast<{inner}>()"
        # 非空字段必须让源列表本身就不可空。
        # 写成 `(x as List?)?.map(...).toList()!` 是错的：`?.` 短路后 `!`
        # 作用在 List 而非 List? 上，Dart 会报 "unnecessary_non_null_assertion"
        # 且整条链仍是可空。所以非空时用 `as List<dynamic>` 直接断言源值。
        if nullable:
            return (f"({src} as List<dynamic>?)"
                    f"?.map((e) => {inner}.fromJson(_asMap(e)))"
                    f".toList()")
        return (f"({src} as List<dynamic>)"
                f".map((e) => {inner}.fromJson(_asMap(e)))"
                f".toList()")
    if t == "Map<String, dynamic>":
        # 注意不能用 suffix（那会拼出 `_asMap(...)?` 这种非法语法）。
        # 可空性交给 _asMapOrNull —— 它对 null 返回 null，而不是抛错。
        return (f"_asMapOrNull({src})" if nullable
                else f"_asMap({src})")
    # 契约里的联合类型（如 metric.value 可为数字或字符串）直接透传。
    # 注意要连原类型一起判断：rstrip("?") 会把 "Object?" 变成 "Object"。
    if t == "Object" or f.dart_type == "Object?":
        return src
    if t == "double":
        # 契约可空 -> 走 `?.` 返回可空；契约非空 -> 走非空 cast，
        # 不用 `!`（对非空接收者用 `!` 会触发 unnecessary_non_null_assertion）
        return (f"({src} as num?)?.toDouble()" if nullable
                else f"({src} as num).toDouble()")
    if t == "int":
        return (f"({src} as num?)?.toInt()" if nullable
                else f"({src} as num).toInt()")
    if t in ("String", "bool"):
        return f"{src} as {t}{suffix}"
    # 嵌套模型
    if nullable:
        return f"{src} == null ? null : {t}.fromJson(_asMap({src}))"
    return f"{t}.fromJson(_asMap({src}))"


def _writer(f: Field) -> str:
    """
    生成 toJson 的写出表达式。

    可空字段用 `?.` 链，非空字段用直接调用 —— 对非空值用 `?.`
    会触发 invalid_null_aware_operator 警告，在严格 lint 下是错误。
    """
    t = _base_type(f.dart_type)
    # toJson 的可空性看 **Dart 类型**，不看契约声明。
    # 原因：最终类型才决定静态分析结果。`??` 会让 Dart 推断字段永不为 null，
    # 从而对 `?.` 报 invalid_null_aware_operator；直接用 `?.` 则没有这个副作用，
    # 且对非空类型是安全的冗余。
    nullable = f.dart_type.endswith("?")
    opt = "?" if nullable else ""

    if f.enum_name and t == f.enum_name:
        return f"{f.dart_name}{opt}.toJson()"
    if f.is_list_of_enum and f.enum_name:
        return f"{f.dart_name}{opt}.map((e) => e.toJson()).toList()"
    if t.startswith("List<"):
        inner = t[5:-1]
        if inner in PRIMITIVES:
            return f.dart_name
        return f"{f.dart_name}{opt}.map((e) => e.toJson()).toList()"
    # 基础类型与契约里的联合类型（Object?）都原样透传。
    # 必须在最后的嵌套模型分支之前判断，否则会被加上不存在的 .toJson()。
    if t in ("String", "int", "double", "bool", "Map<String, dynamic>"):
        return f.dart_name
    if t == "Object" or f.dart_type == "Object?":
        return f.dart_name
    return f"{f.dart_name}{opt}.toJson()"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def write_dart(path: Path, code: str) -> None:
    """
    写 Dart 源文件，必须带 UTF-8 BOM。

    这是中文 Windows 上生成 Dart 代码的经典坑：Dart 分析器对**不带 BOM** 的
    源文件按 Latin-1 解码，于是所有中文注释变成乱码，更糟的是会破坏词法分析，
    报出一堆莫名其妙的 `undefined_method`（类型名解析被污染）。

    加 BOM 后 Dart 工具链按 UTF-8 读取，中文正常，类型也能正确解析。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\ufeff" + code, encoding="utf-8")


def read_dart(path: Path) -> str | None:
    """读取 Dart 源文件并剥掉 BOM，用于比对是否需要重新生成。"""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").lstrip("\ufeff")


def load_contracts() -> dict[str, dict]:
    files = sorted(CONTRACT_DIR.glob("*.schema.json"))
    if not files:
        raise SystemExit(f"[FAIL] 在 {CONTRACT_DIR} 找不到任何 *.schema.json")
    out: dict[str, dict] = {}
    for p in files:
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"[FAIL] {p.name} 不是合法 JSON：{e}")
    return out
    files = sorted(CONTRACT_DIR.glob("*.schema.json"))
    if not files:
        raise SystemExit(f"[FAIL] 在 {CONTRACT_DIR} 找不到任何 *.schema.json")
    out: dict[str, dict] = {}
    for p in files:
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"[FAIL] {p.name} 不是合法 JSON：{e}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="JSON Schema -> Dart 模型生成器")
    ap.add_argument("--check", action="store_true",
                    help="只检查生成结果是否与现有文件一致，不写文件")
    args = ap.parse_args()

    contracts = load_contracts()
    print("=" * 68)
    print("契约 -> Dart 模型")
    print("=" * 68)
    print(f"契约目录：{CONTRACT_DIR}")
    print(f"输出目录：{OUT_DIR}")
    print(f"载入契约：{len(contracts)} 份")
    print()

    gen = Generator(contracts)
    gen.build()

    targets = {
        OUT_DIR / "models.dart": gen.emit_models(),
        OUT_DIR / "enums.dart": gen.emit_enums(),
    }

    stale: list[str] = []
    written = 0

    for path, code in targets.items():
        rel = path.relative_to(ROOT)
        old = read_dart(path)
        if old == code:
            print(f"  = {rel}  （无变化）")
            continue
        if args.check:
            print(f"  ! {rel}  （需要重新生成）")
            stale.append(str(rel))
            continue
        write_dart(path, code)
        print(f"  + {rel}  ({len(code.splitlines())} 行)")
        written += 1

    print()
    if args.check and stale:
        print(f"[FAIL] {len(stale)} 个文件与契约不一致。"
              f"请运行： python scripts/gen_models.py")
        sys.exit(1)

    if not args.check:
        models, enums = gen._ordered()
        print(f"模型：{len(models)} 个")
        print(f"枚举：{len(enums)} 个")
        print(f"写入：{written} 个文件")
        print()
        print("[OK] 完成。本目录下的文件由契约生成，请勿手写修改。")


if __name__ == "__main__":
    main()
