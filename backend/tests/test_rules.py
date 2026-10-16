"""
规则引擎的测试。

这一组测试保护的核心是那条铁律在**运行时的行为**：
    没有可用标准值时，不产生 finding。

为什么它值得单独测：
    loader 保证了"没有出处的条目加载不进来"，
    但运行时还有第二道门 —— 相位不匹配、视角不匹配、
    条目只有 mean/sd 没有区间，这些都要在运行时拒绝。

    如果这道门失效，后果是**用错误的标准值去下结论**，
    而报告上的数字看起来完全合理。这是全项目最难发现的一类错误。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.metrics import MetricContext, MetricResult  # noqa: E402
from backend.analysis.metrics_base import METRIC_SPECS  # noqa: E402
from backend.analysis.phases import GaitEvents  # noqa: E402
from backend.analysis.pose_types import (  # noqa: E402
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)
from backend.analysis.reference_scale import ScaleEstimate  # noqa: E402
from backend.analysis.rules import RULES, evaluate_rules  # noqa: E402


@pytest.fixture(autouse=True)
def explicit_reference_conditions(monkeypatch):
    """规则单测使用已声明测试条件的副本，不给生产文献补造元数据。"""
    from dataclasses import replace
    from backend.standards.loader import load_standards
    lib = load_standards()
    lib.entries = [replace(e, age_range=None, running_condition="unloaded")
                   for e in lib.entries]
    monkeypatch.setattr("backend.analysis.rules.load_or_empty", lambda: lib)


# ---------------------------------------------------------------------------
# 构造
# ---------------------------------------------------------------------------

def _pose(frame_index: int, trunk_dx: float = 0.0) -> PoseFrame:
    """构造一帧姿态。trunk_dx 控制躯干倾斜量。"""
    kp = np.zeros((16, 3), dtype=np.float64)

    def put(name: str, x: float, y: float) -> None:
        kp[KEYPOINT_NAMES.index(name)] = [x, y, Q_CLEAR]

    # 髋在下方，颈在上方；trunk_dx > 0 表示颈偏向右（前倾）
    put("pelvis_center", 0.50, 0.55)
    put("hip_r", 0.51, 0.55)
    put("hip_l", 0.49, 0.55)
    put("neck", 0.50 + trunk_dx, 0.25)
    put("shoulder_center", 0.50 + trunk_dx, 0.25)
    put("shoulder_r", 0.53 + trunk_dx, 0.25)
    put("shoulder_l", 0.47 + trunk_dx, 0.25)
    put("head", 0.50 + trunk_dx, 0.15)
    put("knee_r", 0.51, 0.72)
    put("knee_l", 0.49, 0.72)
    put("ankle_r", 0.52, 0.88)
    put("ankle_l", 0.48, 0.88)
    put("heel_r", 0.51, 0.89)
    put("heel_l", 0.47, 0.89)
    put("toe_r", 0.54, 0.88)
    put("toe_l", 0.46, 0.88)

    return PoseFrame(frame_index=frame_index, keypoints=kp, person_conf=0.95)


def _ctx(n: int = 60, view: str = "side", phase: str = "acceleration",
         trunk_dx: float = 0.0) -> MetricContext:
    seq = PoseSequence(estimator_name="t", estimator_version="1")
    for i in range(n):
        seq.frames.append(_pose(i, trunk_dx=trunk_dx))

    from backend.analysis.phases import PhaseSegment
    phases = [PhaseSegment(phase, 0, n - 1)] if phase else []

    return MetricContext(
        seq=seq, fps=240.0, view=view,
        scale=ScaleEstimate(method="lane_line", valid_per_frame=True,
                            median_pixels_per_meter=0.3),
        events=GaitEvents(), phases=phases,
        athlete_height_cm=178.0,
        athlete_gender="male", athlete_level="elite", athlete_event="100m",
        running_condition="unloaded", complete_run=True,
    )


def _trunk_metric(mean_by_phase: dict[str, float]) -> MetricResult:
    """造一个带相位统计的 trunk_lean 结果。"""
    agg = {
        ph: {"mean": v, "sd": 1.0, "min": v - 1, "max": v + 1, "n": 20}
        for ph, v in mean_by_phase.items()
    }
    return MetricResult(
        metric_id="trunk_lean",
        value=float(np.mean(list(mean_by_phase.values()))),
        aggregate=agg,
        confidence=0.8,
        reliable=True,
    )


# ---------------------------------------------------------------------------
# 铁律：没有标准值就不判定
# ---------------------------------------------------------------------------

def test_no_findings_when_metric_unavailable():
    """指标本身没测出来时，不该产生任何结论。"""
    r = MetricResult(
        metric_id="trunk_lean",
        insufficient={"reason": "view_mismatch", "required": "x",
                      "actual": "y", "impact": ["z"], "suggestion": "w"},
    )
    findings = evaluate_rules(_ctx(), [r])
    assert findings == []


def test_no_findings_when_no_standard_exists():
    """
    ⚠️ 核心测试：没有标准值时**不产生结论**。

    trunk_lean 在标准值库里刻意留空（pending 状态），
    所以即使测出了数值，也不该报出任何"偏差"。

    这是"宁可沉默也不误导"的机械实现。
    """
    metric = _trunk_metric({"acceleration": 30.0})   # 明显偏离常规
    findings = evaluate_rules(_ctx(phase="acceleration"), [metric])

    trunk_findings = [f for f in findings if f["metric_id"] is None
                      or "trunk_lean" in f["metric_ids"]]
    assert trunk_findings == [], (
        "trunk_lean 没有可查证的标准值，不该产生偏差结论"
    )


def test_finding_produced_when_standard_exists():
    """
    有标准值时必须能正常产出结论 —— 否则规则引擎等于摆设。

    step_frequency 有一条已核实的标准值（259.4–283.8 步/分），
    构造一个明显低于下限的值，应当触发"步频偏低"。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run",
        value=180.0,          # 明显低于下限 259.4
        confidence=0.8,
        reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])

    assert findings, "有标准值时应当产出结论"
    f = findings[0]
    assert f["severity"] == "minor"
    assert "步频" in f["title"]
    assert f["metric_ids"] == ["step_frequency"]


def test_rule_does_not_invent_measurement_phase():
    metric = MetricResult(metric_id="knee_angle_touchdown", value=179,
                          reference_window="event_mean")
    assert evaluate_rules(_ctx(phase="max_velocity"), [metric]) == []
    assert "未确认" in metric.reliability_note


def test_population_mismatch_prevents_rule():
    metric = MetricResult(metric_id="step_frequency", value=180,
                          reference_phase="whole_run", reference_window="whole_run")
    ctx = _ctx()
    ctx.athlete_level = "amateur"
    assert evaluate_rules(ctx, [metric]) == []
    assert "未匹配" in metric.reliability_note


def test_rule_uses_only_matching_phase_statistics(monkeypatch):
    from dataclasses import replace
    from backend.standards.loader import load_standards
    lib = load_standards()
    knee = next(e for e in lib.entries if e.metric_id == "knee_angle_touchdown")
    lib.entries = [replace(knee, age_range=None, running_condition="unloaded")]
    monkeypatch.setattr("backend.analysis.rules.load_or_empty", lambda: lib)
    metric = MetricResult(metric_id="knee_angle_touchdown", value=179,
                          reference_window=knee.window,
                          aggregate={"acceleration": {"mean": 179},
                                     "max_velocity": {"mean": 150}})
    # 起跑很高，途中跑在区间内：不可将起跑均值套到途中跑规则。
    assert evaluate_rules(_ctx(), [metric]) == []
    metric.aggregate["max_velocity"]["mean"] = 179
    findings = evaluate_rules(_ctx(), [metric])
    assert len(findings) == 1
    assert findings[0]["evidence"][0]["value"] == 179


def test_real_knee_metric_splits_events_by_phase():
    from backend.analysis.metrics import metric_knee_angle_touchdown
    from backend.analysis.phases import PhaseSegment
    ctx = _ctx()
    ctx.phases = [PhaseSegment("acceleration", 0, 29),
                  PhaseSegment("max_velocity", 30, 59)]
    ctx.events.touchdowns = [10, 20, 40]
    metric = metric_knee_angle_touchdown(ctx)
    assert metric.insufficient is None
    assert metric.reference_window == "event_mean"
    assert metric.aggregate["acceleration"]["n"] == 2
    assert metric.aggregate["max_velocity"]["n"] == 1


def test_no_findings_summary_does_not_claim_normality():
    from backend.analysis.report import build_summary
    metric = MetricResult(metric_id="step_frequency", value=180)
    summary = build_summary([metric], [])
    assert "均在合理范围" not in summary["headline"]
    assert "不代表" in summary["headline"]


def test_no_finding_when_value_within_range():
    """落在参考区间内时不产生结论 —— 这不算偏差。"""
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run",
        value=271.0,          # 落在 259.4–283.8 内
        confidence=0.8,
        reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])
    assert findings == []


def test_no_finding_when_value_above_range_for_low_direction():
    """
    方向判定必须正确：direction='low' 的规则只在**低于**下限时报警。

    方向搞反会让所有正常运动员被报出问题，而且数字看起来合理。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run",
        value=400.0,          # 远高于上限
        confidence=0.8,
        reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])
    assert findings == [], "步频偏高不该触发'步频偏低'规则"


# ---------------------------------------------------------------------------
# 相位绑定
# ---------------------------------------------------------------------------

def test_phase_mismatch_prevents_judgement():
    """
    ⚠️ 相位不匹配时不判定。

    step_frequency 的标准值是 whole_run（全程平均）。
    它应当能用于任何阶段（作为参考），但反过来 ——
    如果标准值限定在具体阶段，就不能用到别的阶段。
    """
    # 构造一个没有标准值的相位组合：
    # trunk_lean 的标准值库里根本没有条目，无论什么相位都不该判定
    metric = _trunk_metric({"max_velocity": 45.0})
    findings = evaluate_rules(_ctx(phase="max_velocity"), [metric])
    assert not any("trunk_lean" in f["metric_ids"] for f in findings)


def test_finding_phase_is_contract_valid():
    """结论里的 phase 必须是契约枚举里的值，不能出现 whole_run。"""
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.8, reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])
    assert findings

    valid = {"set", "start", "acceleration", "transition",
             "max_velocity", "deceleration"}
    for f in findings:
        assert f["phase"] in valid, (
            f"phase「{f['phase']}」不在契约枚举里"
        )


# ---------------------------------------------------------------------------
# 结论的结构
# ---------------------------------------------------------------------------

def test_finding_satisfies_contract_structure():
    """
    结论必须满足契约：必填字段齐全，且**没有契约外的字段**。

    契约对 Finding 用了 additionalProperties: false ——
    曾经往 evidence 里塞了 ref_source 字段，直接导致报告校验失败。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.8, reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])
    assert findings
    f = findings[0]

    required = ["finding_id", "severity", "view", "phase", "title",
                "metric_ids", "evidence", "explanation", "drills"]
    for k in required:
        assert k in f, f"结论缺少必填字段 {k}"

    allowed = set(required) | {
        "rule_id", "rule_version", "confidence", "basis", "caveat",
        "reason", "required", "actual", "impact", "suggestion",
    }
    extra = set(f) - allowed
    assert not extra, f"结论含契约外字段：{extra}"

    # evidence 的字段也要合规
    ev = f["evidence"][0]
    ev_allowed = {"metric_id", "value", "ref_low", "ref_high",
                  "deviation_text", "phase", "frame_index"}
    ev_extra = set(ev) - ev_allowed
    assert not ev_extra, f"evidence 含契约外字段：{ev_extra}"


def test_finding_has_mechanism_and_drill():
    """
    每条结论都必须有机制解释和可执行的练习。

    只说"步频偏低"等于没说 —— 教练需要知道"为什么这是问题"
    和"具体练什么"。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.8, reliable=True,
    )
    f = evaluate_rules(_ctx(), [metric])[0]

    assert len(f["explanation"]) > 30, "机制解释太短，等于没说"
    assert f["drills"], "没有训练处方"

    for d in f["drills"]:
        assert d["cue"], "练习必须有一句能在跑道上直接喊的口令"
        assert len(d["cue"]) <= 20, (
            f"口令「{d['cue']}」超过 20 字 —— 现场喊不出来"
        )
        # 口令不能含术语，教练没有时间解释概念
        for jargon in ("角度", "离心", "向心", "等长", "关节角"):
            assert jargon not in d["cue"], (
                f"口令「{d['cue']}」含术语「{jargon}」"
            )


def test_finding_carries_source_citation():
    """
    ⚠️ 结论必须带出处。

    教练问"这个标准哪来的"，答不出来就失去了信任。
    一次说不清来源的数字，会让教练不再相信所有数字。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.8, reliable=True,
    )
    f = evaluate_rules(_ctx(), [metric])[0]

    caveat = f.get("caveat") or ""
    assert "来源" in caveat, "结论里没有出处说明"
    # 出处要能在界面上正常显示 —— 外文作者名的特殊字符会触发编码问题
    assert "Š" not in caveat


def test_finding_lists_standard_limitations():
    """
    标准值自身的局限必须带进结论。

    这一条标准值来自 7 名运动员、且是跨方法（激光 vs 视频）比较 ——
    不告诉教练的话，他会把它当成权威结论。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.8, reliable=True,
    )
    f = evaluate_rules(_ctx(), [metric])[0]
    caveat = f.get("caveat") or ""

    # 该条目在 YAML 里写了三条 caveat，至少有一条要带出来
    assert "样本量" in caveat or "激光" in caveat or "跨方法" in caveat


def test_low_reliability_metric_caps_confidence():
    """
    依据的指标 reliable=false 时，结论置信度必须 ≤ 0.5。

    这是契约的硬性要求：不可靠的数据不能得出高置信度的结论。
    """
    metric = MetricResult(
        metric_id="step_frequency", reference_phase="whole_run", reference_window="whole_run", value=180.0,
        confidence=0.9,
        reliable=False,
        reliability_note="几何推导的足部点导致取值时刻不确定",
    )
    f = evaluate_rules(_ctx(), [metric])[0]

    assert f["confidence"] <= 0.5, (
        f"依据不可靠指标时置信度应 ≤0.5，实得 {f['confidence']}"
    )
    assert f["basis"] == "low_reliability"
    assert f["caveat"], "低可靠结论必须给出原因"


# ---------------------------------------------------------------------------
# 规则表本身
# ---------------------------------------------------------------------------

def test_all_rules_reference_existing_metrics():
    """规则引用的指标必须真实存在 —— 防拼写错误与残留规则。"""
    for r in RULES:
        assert r.metric_id in METRIC_SPECS, (
            f"规则 {r.rule_id} 引用了不存在的指标 {r.metric_id}"
        )


def test_all_rules_have_nonempty_drills():
    """每条规则都必须有训练处方 —— 没有处方的结论对教练没用。"""
    for r in RULES:
        assert r.drills, f"规则 {r.rule_id} 没有训练处方"
        for d in r.drills:
            assert d.get("cue"), f"规则 {r.rule_id} 的练习缺少口令"


def test_rule_directions_are_valid():
    for r in RULES:
        assert r.direction in ("low", "high"), (
            f"规则 {r.rule_id} 的 direction 非法：{r.direction}"
        )
        assert r.severity in ("major", "minor"), (
            f"规则 {r.rule_id} 的 severity 非法：{r.severity}"
        )


def test_no_conflicting_rules_on_same_metric_phase():
    """
    同一个指标 + 同一相位不该有两条方向相反的规则 ——
    那会同时对同一个数值报出"偏低"和"偏高"。
    """
    seen: dict[tuple[str, str], str] = {}
    for r in RULES:
        key = (r.metric_id, r.phase or "*")
        if key in seen and seen[key] != r.direction:
            pytest.fail(
                f"{key} 上有方向冲突的规则：{seen[key]} 与 {r.direction}"
            )
        seen[key] = r.direction
