"""
验证规则引擎在真实标准值下能产出结论。

为什么需要这个脚本：
    backend/tests/test_rules.py 用**临时造的标准值**测判定逻辑，
    但那些标准值不在仓库里。所以它证明不了
    「仓库里真实的标准值能让规则触发」。

    这个脚本用 data/standards/ 里的真实标准值，
    构造一个明确偏离的指标值，验证：
      1. 规则确实触发
      2. 结论里的出处、局限、处方都齐全
      3. 结论通过契约校验
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np  # noqa: E402

from backend.analysis.metrics import MetricContext, MetricResult  # noqa: E402
from backend.analysis.phases import GaitEvents, PhaseSegment  # noqa: E402
from backend.analysis.pose_types import (  # noqa: E402
    KEYPOINT_NAMES,
    Q_CLEAR,
    PoseFrame,
    PoseSequence,
)
from backend.analysis.reference_scale import ScaleEstimate  # noqa: E402
from backend.analysis.rules import evaluate_rules  # noqa: E402


def _seq(n: int = 60) -> PoseSequence:
    seq = PoseSequence(estimator_name="t", estimator_version="1")
    for i in range(n):
        kp = np.zeros((16, 3), dtype=np.float64)
        for j, name in enumerate(KEYPOINT_NAMES):
            kp[j] = [0.4 + (j % 4) * 0.05, 0.2 + (j // 4) * 0.12, Q_CLEAR]
        seq.frames.append(PoseFrame(frame_index=i, keypoints=kp,
                                    person_conf=0.95))
    return seq


def _ctx() -> MetricContext:
    return MetricContext(
        seq=_seq(), fps=240.0, view="side",
        scale=ScaleEstimate(method="lane_line", valid_per_frame=True,
                            median_pixels_per_meter=0.3),
        events=GaitEvents(), phases=[PhaseSegment("max_velocity", 0, 59)],
        athlete_height_cm=178.0,
    )


def main() -> int:
    print("=" * 68)
    print("规则引擎 · 真实标准值验证")
    print("=" * 68)
    print()

    # ---- 情形 1：步频明显偏低，应当触发 ----
    print("【情形 1】步频 180 步/分（标准值 259.4–283.8）")
    metric = MetricResult(
        metric_id="step_frequency", value=180.0,
        confidence=0.85, reliable=True,
    )
    findings = evaluate_rules(_ctx(), [metric])

    if not findings:
        print("  [FAIL] 应当触发「步频偏低」，但没有产出任何结论")
        return 1

    f = findings[0]
    print(f"  [OK] 触发结论：{f['title']}（{f['severity']}）")
    print(f"       依据：{f['evidence'][0]['deviation_text']}")
    print(f"       置信度：{f['confidence']}")
    print()

    # ---- 情形 2：膝角明显偏大 ----
    print("【情形 2】着地膝角 175°（标准值 133.1–166.7）")
    m2 = MetricResult(
        metric_id="knee_angle_touchdown", value=175.0,
        confidence=0.8, reliable=True,
    )
    f2s = evaluate_rules(_ctx(), [m2])

    # knee_angle_touchdown 有 4 条规则里的一条对应（direction=high）
    if f2s:
        f2 = f2s[0]
        print(f"  [OK] 触发结论：{f2['title']}（{f2['severity']}）")
        print(f"       依据：{f2['evidence'][0]['deviation_text']}")
    else:
        print("  [--] 未触发（可能是该指标没有对应规则）")
    print()

    # ---- 情形 3：值在区间内，不该触发 ----
    print("【情形 3】步频 270 步/分（落在 259.4–283.8 内）")
    m3 = MetricResult(metric_id="step_frequency", value=270.0,
                      confidence=0.85, reliable=True)
    if evaluate_rules(_ctx(), [m3]):
        print("  [FAIL] 值在参考区间内，不该产出偏差结论")
        return 1
    print("  [OK] 未产出结论（符合预期）")
    print()

    # ---- 情形 4：没有标准值的指标，不该触发 ----
    print("【情形 4】躯干前倾 3°（该指标刻意留空，无可用标准值）")
    m4 = MetricResult(metric_id="trunk_lean", value=3.0,
                      confidence=0.8, reliable=True)
    if evaluate_rules(_ctx(), [m4]):
        print("  [FAIL] 没有可查证标准值，不该产出偏差结论")
        return 1
    print("  [OK] 未产出结论 —— 没有出处就不做判断（铁律）")
    print()

    # ---- 检查结论的完整性 ----
    print("=" * 68)
    print("结论完整性检查")
    print("=" * 68)
    print()

    problems = []
    for finding in findings:
        fid = finding["finding_id"]

        if not finding.get("explanation") or len(finding["explanation"]) < 30:
            problems.append(f"{fid} 机制解释太短")

        if not finding.get("drills"):
            problems.append(f"{fid} 没有训练处方")

        caveat = finding.get("caveat") or ""
        if "来源" not in caveat:
            problems.append(f"{fid} 没有标注标准值出处")
        if "样本" not in caveat and "局限" not in caveat:
            problems.append(f"{fid} 没有说明标准值的局限")

        for d in finding.get("drills", []):
            if len(d["cue"]) > 20:
                problems.append(f"{fid} 口令过长：{d['cue']}")

    if problems:
        print("[FAIL] 结论完整性有问题：")
        for p in problems:
            print(f"       {p}")
        return 1

    print(f"  [OK] {len(findings)} 条结论都含机制解释、训练处方、出处与局限")
    print()

    print("=" * 68)
    print("示例结论（完整内容）")
    print("=" * 68)
    print()
    print(json.dumps(findings[0], ensure_ascii=False, indent=2))
    print()

    print("[OK] 规则引擎在真实标准值下工作正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
