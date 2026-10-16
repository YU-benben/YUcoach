"""
验证真实标准值在条件不足时不会产生错误结论。

真实库只审计已声明的条件，不在验证脚本中补造负荷、人群或测量窗口。
正向规则触发、出处和契约结构由backend/tests/test_rules.py独立覆盖。
"""

from __future__ import annotations

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
    """用真实库检查严格匹配，正向触发由隔离条件的单元测试覆盖。"""
    from backend.standards.loader import load_standards
    lib = load_standards()
    if lib.problems:
        print("[FAIL] 标准库校验失败")
        return 1
    cases = [
        MetricResult(metric_id="step_frequency", value=180,
                     reference_phase="whole_run", reference_window="whole_run"),
        MetricResult(metric_id="knee_angle_touchdown", value=175,
                     reference_phase="max_velocity", reference_window="event_mean"),
        MetricResult(metric_id="trunk_lean", value=3,
                     reference_phase="acceleration", reference_window="whole_phase"),
    ]
    ctx = _ctx()
    # 用户条件未知：真实文献不能越过人群/负荷条件产生结论。
    for metric in cases:
        if evaluate_rules(ctx, [metric]):
            print(f"[FAIL] {metric.metric_id}: 未确认条件却产生判断")
            return 1
        if not metric.reliability_note:
            print(f"[FAIL] {metric.metric_id}: 未说明参考缺失")
            return 1
    # 即使确认部分用户信息，旧文献缺失负荷条件也不能由程序补造。
    ctx.athlete_gender = "male"
    ctx.athlete_level = "elite"
    ctx.athlete_event = "100m"
    ctx.athlete_age = 25
    ctx.running_condition = "unloaded"
    unknown = [e for e in lib.entries if e.running_condition == "unspecified"]
    for entry in unknown:
        if lib.lookup(entry.metric_id, entry.view, entry.phase,
                      level=entry.level, gender=entry.gender, event=entry.event,
                      age=25, window=entry.window,
                      running_condition="unloaded", step_number=entry.step_number):
            print(f"[FAIL] {entry.metric_id}: 未注明负荷条件的参考参与判定")
            return 1
    print(f"[OK] 真实库{len(lib.entries)}条已审计，{len(unknown)}条负荷条件待核验")
    print("[OK] 未确认的人群和窗口不产生偏差结论，测量值保留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
