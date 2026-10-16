"""
参考标准值库的加载与校验。

这个模块的存在理由，是 docs/04-参考标准值规范.md §1 里那句话：

    标准值编造是**全项目唯一无法通过测试发现的错误类型**。
    指标算错可以对比真值，契约写错有 Schema 校验，
    规则写错有用例验证 —— 而标准值编造没有任何自动检测手段。

所以这里做的就是把"没有自动检测手段"变成"有"。

三道机械校验：
  1. metric_id 必须在指标清单里存在（防拼写错误、防已删指标残留）
  2. source.locator 必须非空（防"我记得是 45-60 度"这类凭印象填写）
  3. view/phase 必须与指标定义匹配（防跨视角、跨阶段套用）

第 3 条尤其重要：**同一个数字在不同阶段含义可能相反**。
把途中跑的标准值用来判加速段，会对所有正常运动员报出
"躯干前倾过大"，而且报出的数字看起来很合理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from ..analysis.metrics_base import METRIC_SPECS

STANDARDS_DIR = Path(__file__).resolve().parents[2] / "data" / "standards"

# 契约允许的相位
VALID_PHASES = {
    "set", "start", "acceleration", "transition", "max_velocity",
    "deceleration",
    # whole_run 不是契约枚举里的相位，但标准值库需要它 ——
    # 有些文献报告的是全程平均值（如步频），
    # 强行归到某个阶段会造成系统性偏差。
    "whole_run",
}

VALID_VIEWS = {"side", "front", "back"}

# ---------------------------------------------------------------------------
# 测量窗口
#
# 标准值的"测量窗口"必须与指标的取值方式对齐，否则不可比。
#
# 这是第三次拒绝数据时总结出来的教训：
#   第一次 IAAF 躯干角 —— 怀疑取错了行（数据可能错）
#   第二次 IAAF 步频   —— 有更好的替代（重复）
#   第三次 Walker 2021 —— 数据质量很高，但窗口不对齐（瞬间 vs 均值）
#
# 第三次最难防：来源权威、数值合理、口径也讲得清。
# ---------------------------------------------------------------------------

VALID_WINDOWS = {
    #: 该阶段所有帧的均值。本项目的 per-phase 指标用的就是这个。
    "whole_phase",

    #: 某一次事件发生的那一帧（如"第一次着地瞬间"）。
    #: 与 whole_phase **不可互换** —— 这是最常见的误用来源。
    "single_event",

    #: 某一次事件在多次重复上的均值（如同一阶段内所有着地帧的平均）。
    #: 与 whole_phase 接近但更窄：只取事件帧，不取中间帧。
    "event_mean",

    #: 整段素材的平均值。
    "whole_run",

    #: 原文未说明测量窗口。
    #: 允许入库但会在校验里告警 —— 未声明窗口的数值有对齐风险。
    "unspecified",
}

#: 窗口的中文说明，用于报错信息。
WINDOW_LABELS = {
    "whole_phase": "阶段均值（该阶段所有帧的平均）",
    "single_event": "单次事件瞬间（某一帧）",
    "event_mean": "事件均値（只取事件帧的平均）",
    "whole_run": "全程平均",
    "unspecified": "未说明",
}
VALID_LEVELS = {"elite", "sub_elite", "college", "high_school", "amateur"}
VALID_GENDERS = {"male", "female", "mixed"}
VALID_EVENTS = {"100m", "200m", "400m"}

# ---------------------------------------------------------------------------
# 单位换算
#
# ⚠️ 为什么必须有这张表：
#     文献报告时间的单位在「秒」和「毫秒」之间摇摆，
#     本项目的 ground_contact_time / flight_time 用**毫秒**。
#
#     0.101 和 101 描述的是同一个事实。如果直接入库不做换算，
#     规则引擎会拿 0.101 去和实测的 101 ms 比，判出
#     "触地时间比参考值低 100 倍" —— 一个荒谬但看起来像数字的结论。
#
#     这类错误无法通过"看数值是否合理"发现，因为两边的数字
#     各自都合理。只能在加载时按指标声明的单位统一换算。
# ---------------------------------------------------------------------------

#: 指标 -> 标准值文件里用的单位到指标单位的换算系数
#:
#: ⚠️ 入库的 YAML 必须写**换算后**的值（即与指标单位一致），
#:    换算系数只用于核对：加载器会检查"原始值 × 系数"是否落在
#:    生理可信范围内，借此发现"忘了换算"或"换算两次"。
#:
#:    为什么不做成"加载时自动乘"：
#:      · YAML 里存换算前的值，读文件的人无法直接看出量级对不对
#:      · 一旦有人手工换算过，加载时再乘一次就翻了 1000 倍 ——
#:        而 85000 ms 这种值在文件里看着只是"一个大数"
#:    写成换算后的值 + 加载时校验，两个错误方向都能被发现。
UNIT_CONVERSION: dict[str, tuple[str, float]] = {
    "ground_contact_time": ("文献常以秒报告（如 0.101 s），×1000 得毫秒", 1000.0),
    "flight_time": ("文献常以秒报告（如 0.134 s），×1000 得毫秒", 1000.0),
}


@dataclass
class StandardEntry:
    """一条通过校验的标准值。"""

    metric_id: str
    view: str
    phase: str
    low: float | None
    high: float | None
    mean: float | None
    sd: float | None
    n: int | None

    gender: str
    level: str
    event: str
    age_range: str | None

    source_authors: str
    source_year: int | None
    source_title: str
    source_journal: str
    source_doi: str
    source_locator: str

    measurement_note: str
    extraction_note: str
    verified_by: str
    verified_date: str
    std_version: str

    caveats: list[str] = field(default_factory=list)

    #: 中文出处简称。**报告里给教练看的就是这个**。
    #:
    #: 为什么不直接用 citation()：教练不需要读外文作者名，
    #: 而且那些名字里的特殊字符（如 Š）在 Windows 控制台输出时
    #: 会因为 GBK 编码失败 —— 一个"出处显示不出来"的报告
    #: 等于没有出处。
    #:
    #: citation() 仍然保留，用于开发排查与元数据导出。
    citation_zh: str = ""

    #: 该条目的来源层级。当前只有 literature ——
    #: team / global 需要积累真实数据后才能生成。
    tier: str = "literature"

    #: 单位换算说明。非空表示入库时做过换算，会一并展示给用户。
    unit_note: str = ""

    #: 测量窗口：这条数值覆盖的是**一段时期**还是**一个瞬间**。
    #:
    #: ⚠️ 这个字段是补上第五道校验时加的，起因是一次真实的拒绝：
    #:
    #:     Walker et al. 2021 报告了世界级短跑选手起跑第一次着地/离地
    #:     瞬间的躯干角（39±3° 相对水平）。数据质量很高 ——
    #:     世界锦标赛决赛选手、150 Hz 高速摄影、顶刊发表。
    #:     但**没有采用**，因为：
    #:         论文 = 第 1 步着地那一瞬间
    #:         我们的 metric_trunk_lean = 该阶段所有帧的均值（5–8 步）
    #:     加速段躯干单调抬起（51° → 28°），所以论文的区间是**峰值区间**。
    #:     用它去判阶段均值，会让每一个正常运动员都被报「躯干抬起过早」。
    #:
    #:     这类错误最难发现：来源权威、数值合理、口径也说得清 ——
    #:     错的只是"测的是瞬间，而我们比的是均值"。
    #:
    #: 取值见 VALID_WINDOWS。空字符串表示未声明（会告警，不阻塞）。
    window: str = ""
    # 缺失条件的旧文献可保存，但不能自动参与判定。
    running_condition: str = "unspecified"
    step_number: int | None = None
    load_protocol: str | None = None



    def citation(self) -> str:
        """完整出处（含作者与 DOI）。用于开发排查与元数据导出。"""
        parts = []
        if self.source_authors:
            parts.append(self.source_authors)
        if self.source_year:
            parts.append(f"({self.source_year})")
        if self.source_title:
            parts.append(self.source_title)
        if self.source_journal:
            parts.append(self.source_journal)
        if self.source_locator:
            parts.append(self.source_locator)
        return ". ".join(parts)

    def display_source(self) -> str:
        """
        给用户看的出处。

        优先用中文简称；没填就退回"期刊 + 年份 + 图表号"，
        并且**剔除作者名** —— 作者名里的特殊字符最容易触发
        控制台编码问题，而它对教练没有信息量。
        """
        if self.citation_zh:
            return self.citation_zh
        parts = []
        if self.source_journal:
            parts.append(self.source_journal.split(",")[0])
        if self.source_year:
            parts.append(str(self.source_year))
        if self.source_locator:
            parts.append(self.source_locator)
        return "，".join(parts)


@dataclass
class ValidationProblem:
    """一条不合规的标准值条目。"""

    file: str
    index: int
    metric_id: str
    reason: str

    def __str__(self) -> str:
        return f"{self.file}[{self.index}] {self.metric_id}: {self.reason}"


@dataclass
class StandardsLibrary:
    """加载后的标准值库。"""

    version: str = ""
    entries: list[StandardEntry] = field(default_factory=list)
    problems: list[ValidationProblem] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)

    def lookup(
        self,
        metric_id: str,
        view: str,
        phase: str,
        level: str | None = None,
        *,
        gender: str | None = None,
        event: str | None = None,
        age: float | None = None,
        window: str | None = None,
        running_condition: str | None = None,
        step_number: int | None = None,
        load_protocol: str | None = None,
    ) -> StandardEntry | None:
        """
        仅返回完全匹配且唯一的参考。未知条件不是通配符。

        whole_run不再替代具体阶段；混合性别人群不替代男女分组。
        未注明年龄限制的文献不限制年龄；注明范围则必须知道实际年龄。
        多个同口径来源暂不自动择优，避免由文件排序决定结论。
        """
        if (level not in VALID_LEVELS or gender not in {"male", "female"}
                or event not in VALID_EVENTS
                or window not in VALID_WINDOWS - {"unspecified"}
                or running_condition not in {"unloaded", "resisted", "assisted"}):
            return None
        if step_number is not None and (type(step_number) is not int or step_number < 1):
            return None
        if age is not None and (type(age) not in (int, float) or not 0 < age < 120):
            return None
        if running_condition != "unloaded" and not load_protocol:
            return None
        matches = []
        for e in self.entries:
            if (e.metric_id != metric_id or e.view != view or e.phase != phase
                    or e.level != level or e.gender != gender or e.event != event
                    or e.window != window or e.running_condition != running_condition
                    or e.step_number != step_number or e.load_protocol != load_protocol):
                continue
            if e.age_range:
                limits = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*", str(e.age_range))
                if (not limits or age is None or isinstance(age, bool)
                        or not float(limits[1]) <= age <= float(limits[2])):
                    continue
            matches.append(e)
        return matches[0] if len(matches) == 1 else None

    def stats(self) -> dict[str, Any]:
        by_phase: dict[str, int] = {}
        for e in self.entries:
            by_phase[e.phase] = by_phase.get(e.phase, 0) + 1
        return {
            "version": self.version,
            "entries": len(self.entries),
            "by_phase": by_phase,
            "pending": len(self.pending),
            "problems": len(self.problems),
        }


# ---------------------------------------------------------------------------
# 加载与校验
# ---------------------------------------------------------------------------

def _validate_entry(
    raw: dict, file_name: str, index: int,
) -> tuple[StandardEntry | None, ValidationProblem | None]:
    """校验并转换单条条目。返回 (条目, 问题)，两者恰有一个非空。"""
    metric_id = str(raw.get("metric_id") or "").strip()

    def problem(reason: str) -> tuple[None, ValidationProblem]:
        return None, ValidationProblem(file_name, index, metric_id, reason)

    # ---- 1. metric_id 必须存在 ----
    if not metric_id:
        return problem("缺少 metric_id")
    if metric_id not in METRIC_SPECS:
        return problem(
            f"metric_id 「{metric_id}」不在指标清单里。"
            f"可能是拼写错误，或指标已被移除。"
        )

    spec = METRIC_SPECS[metric_id]

    # ---- 2. view 必须与指标的适用视角一致 ----
    view = str(raw.get("view") or "").strip()
    if view not in VALID_VIEWS:
        return problem(f"view 取值非法：「{view}」")
    if view not in spec.views:
        return problem(
            f"view「{view}」与指标定义不符。"
            f"{spec.name_zh} 只适用于 {'/'.join(spec.views)} 视角。"
            f"跨视角套用会让几何量完全变味。"
        )

    # ---- 3. phase 必须合法 ----
    phase = str(raw.get("phase") or "").strip()
    if phase not in VALID_PHASES:
        return problem(f"phase 取值非法：「{phase}」")

    # ---- 3b. 测量窗口 ----
    #
    # ⚠️ 这道检查是补上第三次拒绝数据时发现的漏洞。
    #
    # 只检查"视角一致""阶段一致"是不够的 —— 还要检查
    # **测的是一段时期的均值，还是一个瞬间**。
    #
    # 反例（真实发生的）：Walker et al. 2021 报告世界级短跑选手
    # 起跑第一次着地瞬间的躯干角（39±3° 相对水平）。数据质量极高，
    # 但我们的 metric_trunk_lean 取的是阶段所有帧的均值。
    # 加速段躯干单调抬起，所以那是**峰值区间**，用来判均值会让
    # 每一个正常运动员都被报「躯干抬起过早」。
    window = str(raw.get("window") or "").strip()
    if not window:
        # 未声明窗口：允许入库，但必须被告知风险。
        # 不直接拒绝的原因是存量条目需要时间补，且有些文献确实没写。
        return problem(
            "缺少 window 字段 —— 无法判断这条标准值覆盖的是"
            "「一段时期的均值」还是「某一个瞬间」。"
            f"请补上，取值见 {sorted(VALID_WINDOWS)}。"
            f"（如果原文确实没说明，填 unspecified）"
        )
    if window not in VALID_WINDOWS:
        return problem(
            f"window 取值非法：「{window}」。"
            f"合法值：{sorted(VALID_WINDOWS)}"
        )

    running_condition = raw.get("running_condition", "unspecified")
    if running_condition not in {"unloaded", "resisted", "assisted", "unspecified"}:
        return problem("running_condition 必须为 unloaded/resisted/assisted/unspecified")
    step_number = raw.get("step_number")
    if step_number is not None and (type(step_number) is not int or step_number < 1):
        return problem("step_number 必须为正整数")
    if step_number is not None and window != "single_event":
        return problem("指定 step_number 的条目必须使用 single_event 窗口")
    load_protocol = raw.get("load_protocol")
    if load_protocol is not None and (not isinstance(load_protocol, str) or not load_protocol.strip()):
        return problem("load_protocol 必须为非空字符串")
    if running_condition in {"resisted", "assisted"} and not load_protocol:
        return problem("阻力/助力参考必须声明 load_protocol（具体负荷方案）")
    if running_condition == "unloaded" and load_protocol is not None:
        return problem("unloaded 不应声明负荷方案")

    # ---- 4. 出处必须可查证 ----
    src = raw.get("source") or {}
    if not isinstance(src, dict):
        return problem("source 结构不合法")
    locator = str(src.get("locator") or "").strip()
    if not locator:
        return problem(
            "source.locator 为空 —— **这是铁律的核心**。"
            "没有页码或图表号就无法查证，等同于凭印象编造。"
        )

    # ---- 5. 必须有可用的数值 ----
    def num(key: str) -> float | None:
        v = raw.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    low, high = num("low"), num("high")
    mean, sd = num("mean"), num("sd")

    if low is None and high is None and mean is None:
        return problem("low/high/mean 全为空，没有可用的标准值")

    # ---- 5b. 单位核对 ----
    #
    # ⚠️ 这里做的是**核对**，不是换算。
    #
    # YAML 里必须写与指标单位一致的值（如 ground_contact_time 写毫秒）。
    # 如果写成了文献原始的秒值（0.101），它通常仍然落在
    # 通用角度/数值的合法范围里，但会落到该指标生理可信范围之外 ——
    # 下面的 5c 检查会把它拦下。
    #
    # 这里的核对针对另一个方向：值大得离谱（像是被换算过两次）。
    note = ""
    if metric_id in UNIT_CONVERSION:
        desc, factor = UNIT_CONVERSION[metric_id]
        # 若值 × 系数仍然在该指标的可信范围内，说明它**可能**是原始的秒值
        if mean is not None and spec.plausible_range is not None:
            lo, hi = spec.plausible_range
            if lo <= mean * factor <= hi and not (lo <= mean <= hi):
                return problem(
                    f"mean={mean} 看起来是**未换算**的原值"
                    f"（{desc}）。标准值库里应写入换算后的值。"
                )
        note = f"[单位核对：{desc}] "

    if low is not None and high is not None and low > high:
        return problem(f"low({low}) 大于 high({high})")

    # ---- 5c. 生理可信范围 ----
    #
    # ⚠️ 这一道专门拦「表格行列错位」。
    #
    # 实际踩过的坑：从 IAAF 报告提取 trunk_lean 标准值时，
    # PDF 表格的列标题在提取中丢失，取到的行换算出 61–68° 的前倾角。
    # 那个值在 0–180° 的合法角度范围内毫无问题，只有对照
    # 「人跑起来躯干能摆成什么样」才能发现它错了。
    #
    # 被拒绝时给出的信息要能看出「错在哪」，而不只是「非法」。
    for label, v in (("low", low), ("high", high), ("mean", mean)):
        if v is None:
            continue
        err = spec.plausibility_error(v)
        if err:
            return problem(
                f"{label} 不可信：{err}。"
                f"这通常意味着**从文献提取时取错了行/列**，"
                f"或单位没有统一。请回原文核对后再入库。"
            )

    # ---- 6. 口径说明必填 ----
    measurement_note = str(raw.get("measurement_note") or "").strip()
    if not measurement_note:
        return problem(
            "measurement_note 为空。必须核对测量口径 —— "
            "同一个指标名在不同研究里的定义可能不同，"
            "口径不符的标准值比没有更危险。"
        )
    extraction_note = str(raw.get("extraction_note") or "").strip()
    if not extraction_note:
        return problem(
            "extraction_note 为空。必须说明从哪个组、什么条件提取，"
            "以及区间是原文报告的还是推算的。"
        )

    # ---- 7. 人群字段 ----
    pop = raw.get("population") or {}
    gender = str(pop.get("gender") or "").strip()
    level = str(pop.get("level") or "").strip()
    event = str(pop.get("event") or "").strip()

    if gender not in VALID_GENDERS:
        return problem(f"population.gender 取值非法：「{gender}」")
    if level not in VALID_LEVELS:
        return problem(f"population.level 取值非法：「{level}」")
    if event not in VALID_EVENTS:
        return problem(f"population.event 取值非法：「{event}」")

    entry = StandardEntry(
        metric_id=metric_id,
        view=view,
        phase=phase,
        low=low,
        high=high,
        mean=mean,
        sd=sd,
        n=raw.get("n") if isinstance(raw.get("n"), int) else None,
        gender=gender,
        level=level,
        event=event,
        age_range=pop.get("age_range"),
        source_authors=str(src.get("authors") or ""),
        source_year=src.get("year") if isinstance(src.get("year"), int) else None,
        source_title=str(src.get("title") or "").strip(),
        source_journal=str(src.get("journal") or ""),
        source_doi=str(src.get("doi") or ""),
        source_locator=locator,
        measurement_note=measurement_note,
        extraction_note=extraction_note,
        verified_by=str(raw.get("verified_by") or ""),
        verified_date=str(raw.get("verified_date") or ""),
        std_version=str(raw.get("std_version") or ""),
        caveats=[str(c) for c in (raw.get("caveats") or [])],
        citation_zh=str(raw.get("citation_zh") or "").strip(),
        unit_note=note,
        window=window,
        running_condition=running_condition,
        step_number=step_number,
        load_protocol=load_protocol,
    )
    return entry, None


def load_standards(directory: Path | None = None) -> StandardsLibrary:
    """
    加载并校验全部标准值文件。

    不合规的条目**被拒绝加载**，同时记录问题 ——
    由调用方（门禁）决定是否因此失败。
    运行时遇到问题条目只会少几条标准值（表现为"不做偏离判断"），
    而不会用错误的数字去下结论。
    """
    d = directory or STANDARDS_DIR
    lib = StandardsLibrary()

    if not d.exists():
        return lib

    for path in sorted(d.glob("*.yaml")):
        # _ 开头的文件是元数据（如检索记录），不是标准值
        if path.name.startswith("_"):
            continue

        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            lib.problems.append(ValidationProblem(
                path.name, -1, "-", f"YAML 解析失败：{e}"))
            continue

        if not isinstance(doc, dict):
            lib.problems.append(ValidationProblem(
                path.name, -1, "-", "顶层结构不是映射"))
            continue

        if not lib.version:
            lib.version = str(doc.get("version") or "")

        for key in ("verified", "entries"):
            for i, raw in enumerate(doc.get(key) or []):
                if not isinstance(raw, dict):
                    lib.problems.append(ValidationProblem(
                        path.name, i, "-", f"{key}[{i}] 不是映射"))
                    continue
                entry, problem = _validate_entry(raw, path.name, i)
                if problem is not None:
                    lib.problems.append(problem)
                elif entry is not None:
                    lib.entries.append(entry)

        for raw in doc.get("pending") or []:
            if isinstance(raw, dict):
                lib.pending.append(raw)

    return lib


def load_or_empty(directory: Path | None = None) -> StandardsLibrary:
    """加载标准值；任何异常都退回空库，绝不让分析因此失败。"""
    try:
        return load_standards(directory)
    except Exception:  # noqa: BLE001
        return StandardsLibrary()
