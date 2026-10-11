"""
规则引擎：把测出来的数值转成可执行的训练建议。

这是整条链路里**唯一产生"判断"的环节**。
    metrics  是事实 —— 膝角 142°
    findings 是判断 —— "这个膝角偏大，说明着地时腿伸得太直，
                        会增加制动，建议做 XX 练习"

三条硬规矩：

  1. **没有标准值就不做偏差判定。**
     标准值从 data/standards/*.yaml 加载，由 backend/standards/loader.py
     做机械校验：没有页码/图表号的条目会被拒绝加载。
     找不到标准值时，规则**静默不生效** —— 报告里只有数值，没有对错判断。
     一个编造的标准比没有标准危害大得多。

  2. **每个结论必须有机制解释 + 可执行的练习。**
     只说"膝角偏大"等于没说。教练需要知道"为什么这是问题"
     和"具体练什么"。

  3. **练习口令必须是能在跑道上直接喊出来的话。**
     ≤20 字、不含术语。教练在训练现场没有时间解释概念。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..standards.loader import StandardEntry, load_or_empty
from .metrics import MetricContext, MetricResult

# 规则版本。改动了判据或处方，必须递增 ——
# 否则无法回答"为什么同样的数据这次结论不一样"。
RULE_VERSION = "0.2.0"


@dataclass
class Rule:
    """
    一条判定规则。

    规则本身只描述"什么算偏差"与"偏差了怎么办"；
    具体数值区间来自标准值库，不在代码里硬编码。
    这样补文献时只改 YAML，不用动代码，也不会漏改某处。
    """

    rule_id: str
    metric_id: str
    #: 结论标题（面向教练，不含术语）
    title: str
    #: 偏差方向：'low' 表示低于区间下限时报警，'high' 反之
    direction: str
    severity: str          # major / minor
    #: 机制解释：为什么这个偏差是问题
    mechanism: str
    #: 训练处方
    drills: list[dict] = field(default_factory=list)
    #: 附加说明（如"该判定仅在加速段才成立"）
    caveat: str | None = None
    #: 需要哪个相位的数据。None 表示不限定。
    phase: str | None = None


# ---------------------------------------------------------------------------
# 规则定义
#
# 注意这里**没有数值区间** —— 区间全部来自 data/standards/*.yaml。
# 这样做的直接好处：补文献时只改一个文件，
# 而且要过 loader 的机械校验（没有出处就加载不进来）。
# ---------------------------------------------------------------------------

RULES: list[Rule] = [
    Rule(
        rule_id="trunk_lean_accel_too_low",
        metric_id="trunk_lean",
        title="加速段躯干抬起过早",
        direction="low",
        severity="major",
        phase="acceleration",
        mechanism=(
            "加速阶段身体应保持较大前倾，把蹬地的力量用于水平推进。"
            "躯干过早抬起会让推进方向偏向上方，"
            "缩短有效做功距离，同时增加后腿的摆动负担。"
        ),
        drills=[
            {
                "drill_id": "wall_drive",
                "name": "靠墙蹬伸",
                "sets": "4", "reps": "8 次 × 每侧",
                "cue": "肩膀压低，屁股往前顶",
                "mechanism": "在无位移条件下建立前倾角的本体感觉",
            },
            {
                "drill_id": "pushup_start_hold",
                "name": "起跑器前倾保持",
                "sets": "5", "reps": "3 秒",
                "duration": "3 秒",
                "cue": "头别抬，看地面",
                "mechanism": "强化起跑后前 3 步的身体角度",
            },
        ],
        caveat=(
            "该判定仅在加速段成立。途中跑躯干接近直立才是正确的 —— "
            "同一个角度值在途中跑反而是问题。"
        ),
    ),
    Rule(
        rule_id="trunk_lean_maxvel_too_high",
        metric_id="trunk_lean",
        title="途中跑躯干前倾过大",
        direction="high",
        severity="major",
        phase="max_velocity",
        mechanism=(
            "达到最高速度后身体应接近直立。"
            "继续大幅前倾会让重心过分靠前，"
            "迫使支撑腿过早着地产生制动，同时限制髋关节的伸展幅度。"
        ),
        drills=[
            {
                "drill_id": "tall_running",
                "name": "高重心跑",
                "sets": "4", "reps": "30 米",
                "cue": "头顶往上顶，别趴着跑",
                "mechanism": "建立直立跑姿的本体感觉",
            },
        ],
        caveat=(
            "此判定只适用于已达到最高速度的阶段。"
            "如果素材本身不含完整的加速过程，"
            "相位划分可能把加速段误标为途中跑。"
        ),
    ),
    Rule(
        rule_id="step_frequency_low",
        metric_id="step_frequency",
        title="步频偏低",
        direction="low",
        severity="minor",
        mechanism=(
            "步频偏低意味着单步支撑时间较长、腾空时间较短。"
            "在速度相同的前提下，较低的步频通常伴随较大的步幅，"
            "这会让重心起伏加剧，增加触地时的冲击。"
        ),
        drills=[
            {
                "drill_id": "cadence_ladder",
                "name": "节拍跑",
                "sets": "6", "reps": "20 米",
                "cue": "步子踩密一点，别跨",
                "mechanism": "用外部节拍提高步频而不增大步幅",
            },
        ],
        caveat=(
            "步频与步长是此消彼长的关系，单看步频偏低不等于有问题 —— "
            "要结合步长一起判断。而且短跑的步频在加速段最高、"
            "途中跑略降，用全程平均值比较时需要留意这一点。"
        ),
    ),
    Rule(
        rule_id="knee_angle_touchdown_too_high",
        metric_id="knee_angle_touchdown",
        title="着地时膝关节过于伸直",
        direction="high",
        severity="minor",
        # ⚠️ 相位必须是 max_velocity，不能是 acceleration。
        #
        # 标准值（IAAF 报告）测的是**比赛中段**的着地膝角，
        # 也就是最高速度阶段。如果这里写 acceleration，
        # 运行时的相位匹配会把它拦下 —— 规则永远不触发。
        #
        # 这个不一致是 verify_rules_e2e.py 抓出来的：
        # 规则和标准值的相位各写各的，谁也没报错，
        # 表现只是"这条规则从来不生效"。
        phase="max_velocity",
        mechanism=(
            "着地瞬间膝角过大（腿伸得太直）时，"
            "地面反作用力与腿几乎在一条直线上，"
            "缺少膝关节的缓冲，冲击被直接传递到髋与脊柱；"
            "同时着地点会落在重心前方更远处，产生制动分量。"
        ),
        drills=[
            {
                "drill_id": "ankle_bounce",
                "name": "原地踝弹跳",
                "sets": "4", "reps": "15 次",
                "cue": "脚踝软一点，别锁死膝盖",
                "mechanism": "建立着地瞬间的缓冲意识",
            },
            {
                "drill_id": "a_skip",
                "name": "A 字跳",
                "sets": "4", "reps": "20 米",
                "cue": "脚往屁股下拉",
                "mechanism": "让小腿在着地前回到更垂直的位置",
            },
        ],
        caveat=(
            "参考区间来自比赛中段（最高速度阶段）的实测值。"
            "起跑加速的前几步着地方式与途中跑不同，"
            "不能用这个区间去判断起跑动作 —— "
            "加速段的着地膝角需要单独的标准值，目前尚未检索到。"
        ),
    ),
]


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------

def _phase_of_metric_entry(
    entry: StandardEntry,
    metric: MetricResult,
    ctx: MetricContext,
) -> str:
    """
    取该标准值对应的相位。

    标量指标（步频等）的相位由标准值自身决定；
    按相位统计的指标（躯干前倾）则由 aggregate 里的键决定。
    """
    return entry.phase


def _usable_entry(
    entry: StandardEntry | None,
    ctx: MetricContext,
    phase: str,
) -> bool:
    """
    标准值是否可用于本次判定。

    三道检查，任一不通过就不做偏差判定：
      1. 条目不存
      2. 出处为空（loader 已经拦过一道，这里是运行时兜底）
      3. 相位冲突 —— whole_run 的条目可以用在任何阶段，
         但具体阶段的条目只能用在对应阶段
    """
    if entry is None:
        return False
    if not entry.source_locator:
        return False
    if entry.phase != "whole_run" and entry.phase != phase:
        return False
    return True


def evaluate_rules(
    ctx: MetricContext,
    results: list[MetricResult],
) -> list[dict]:
    """
    跑全部规则，产出 findings。

    核心设计：**没有可用标准值时，不产生 finding。**
        宁可只报数值让教练自己看，也不做无依据的"诊断"。
        报告里那条指标会照常显示测量值，只是不带对错判断。
    """
    lib = load_or_empty()
    by_id = {r.metric_id: r for r in results}
    findings: list[dict] = []

    for rule in RULES:
        metric = by_id.get(rule.metric_id)
        if metric is None or metric.insufficient is not None:
            continue          # 指标没测出来，无从判定
        if metric.value is None:
            continue

        # 按相位逐条判定。
        # 标量指标只有一个值，用规则声明的相位；
        # 按相位统计的指标从 aggregate 里展开。
        phase_values = _extract_phase_values(metric, rule, ctx)

        for phase, value in phase_values.items():
            entry = lib.lookup(
                metric_id=rule.metric_id,
                view=ctx.view,
                phase=phase,
            )
            if not _usable_entry(entry, ctx, phase):
                continue

            # 需要 low/high 才能做区间判断。
            # 只有 mean/sd 的条目在本版本不做判定 ——
            # 标准化偏离（z 分数）留待有足够样本时再启用。
            if entry.low is None or entry.high is None:
                continue

            deviates, deviation_text = _check_deviation(
                value, entry, rule.direction)
            if not deviates:
                continue

            findings.append(_build_finding(
                rule=rule,
                phase=phase,
                value=value,
                entry=entry,
                deviation_text=deviation_text,
                metric=metric,
                view=ctx.view,
            ))

    # 按严重程度排序：major 在前。教练时间有限，先看要紧的。
    findings.sort(key=lambda f: (0 if f["severity"] == "major" else 1,))

    # 契约要求最多展示 3 条（详见 analysis.schema.json 的说明）。
    # 但**不能静默丢弃** —— 被截掉的条数要如实告知。
    return findings


def _extract_phase_values(
    metric: MetricResult,
    rule: Rule,
    ctx: MetricContext,
) -> dict[str, float]:
    """
    从指标结果里取出「相位 -> 数值」的映射。

    两种情形：
      · 按相位统计的指标（aggregate 里嵌着带 mean 的子字典）
      · 标量指标（只有一个值）
    """
    out: dict[str, float] = {}

    if metric.aggregate:
        for k, v in metric.aggregate.items():
            if isinstance(v, dict) and "mean" in v:
                out[k] = float(v["mean"])

    if out:
        return out

    # 标量指标：用规则声明的相位；没声明就按第一个检测到的相位
    phase = rule.phase
    if phase is None:
        phase = "whole_run"
    return {phase: float(metric.value)}


def _check_deviation(
    value: float,
    entry: StandardEntry,
    direction: str,
) -> tuple[bool, str]:
    """判断是否偏离，并生成人话的偏差描述。"""
    if direction == "low":
        if value >= entry.low:
            return False, ""
        delta = entry.low - value
        return True, (
            f"低于参考区间下限 {delta:.1f}"
            f"（当前 {value:.1f}，参考 {entry.low:.1f}–{entry.high:.1f}）"
        )

    if value <= entry.high:
        return False, ""
    delta = value - entry.high
    return True, (
        f"高于参考区间上限 {delta:.1f}"
        f"（当前 {value:.1f}，参考 {entry.low:.1f}–{entry.high:.1f}）"
    )


def _build_finding(
    *,
    rule: Rule,
    phase: str,
    value: float,
    entry: StandardEntry,
    deviation_text: str,
    metric: MetricResult,
    view: str,
) -> dict:
    """组装一条符合契约的 finding。"""
    # ---- 置信度 ----
    #
    # ⚠️ 契约硬性要求：依据的指标 reliable=false 时，结论置信度必须 ≤ 0.5。
    #
    # 这条规则的意义：不可靠的数据不能得出高置信度的结论。
    # 漏掉它的后果很严重 —— 报告会显示"置信度 90%"配上一句
    # "该数据不可靠"的注脚，两个信号互相矛盾，教练会采信前者。
    confidence = metric.confidence if metric.confidence is not None else 0.6
    if not metric.reliable:
        confidence = min(confidence, 0.5)

    finding: dict = {
        "finding_id": f"f_{rule.rule_id}_{phase}",
        "rule_id": rule.rule_id,
        "rule_version": RULE_VERSION,
        "severity": rule.severity,
        "view": view,
        "phase": _phase_to_contract(phase),
        "title": rule.title,
        "metric_ids": [rule.metric_id],
        "evidence": [{
            "metric_id": rule.metric_id,
            "value": round(float(value), 2),
            "ref_low": entry.low,
            "ref_high": entry.high,
            "deviation_text": deviation_text,
            "phase": _phase_to_contract(phase),
        }],
        "explanation": rule.mechanism,
        "confidence": round(confidence, 2),
        "basis": "normal" if metric.reliable else "low_reliability",
        "drills": [
            {
                "drill_id": d["drill_id"],
                "name": d["name"],
                "cue": d["cue"],
                **({"sets": d["sets"]} if d.get("sets") else {}),
                **({"reps": d["reps"]} if d.get("reps") else {}),
                **({"duration": d["duration"]}
                   if d.get("duration") else {}),
                **({"mechanism": d["mechanism"]}
                   if d.get("mechanism") else {}),
            }
            for d in rule.drills
        ],
    }

    # ---- caveat：把该说清的都说清 ----
    #
    # 出处放在这里而不是 evidence 里 ——
    # 契约对 Evidence 用了 additionalProperties: false，
    # 只有 metric_id / value / ref_low / ref_high /
    # deviation_text / phase / frame_index 这几个字段。
    # 硬塞 ref_source 会让报告校验失败。
    #
    # caveat 正好是"给用户的明确提示"，放出处很合适：
    # 它直接回答教练最容易问的那句"这个标准哪来的"。
    caveats: list[str] = []

    if rule.caveat:
        caveats.append(rule.caveat)

    source_text = entry.display_source()
    if source_text:
        caveats.append(f"参考区间来源：{source_text}")

    # 标准值自身的局限（样本量小、跨方法比较等）必须带出来 ——
    # 不说的后果是教练把这个数字当成权威结论。
    caveats.extend(entry.caveats)

    if not metric.reliable and metric.reliability_note:
        caveats.append(metric.reliability_note)

    if caveats:
        finding["caveat"] = " ".join(caveats)

    return finding


def _phase_to_contract(phase: str) -> str:
    """
    把内部相位名映射到契约的 Phase 枚举。

    ⚠️ 契约只允许六个相位，没有 whole_run。
       whole_run 的判定（如全程平均步频）归入 max_velocity ——
       这是最接近"全程代表值"的阶段，但必须在 caveat 里说明。
    """
    mapping = {
        "acceleration": "acceleration",
        "max_velocity": "max_velocity",
        "transition": "transition",
        "deceleration": "deceleration",
        "set": "set",
        "start": "start",
        "whole_run": "max_velocity",
    }
    return mapping.get(phase, "max_velocity")
