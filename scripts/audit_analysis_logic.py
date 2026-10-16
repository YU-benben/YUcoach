"""Read-only deterministic probes of analysis logic; not accuracy validation on real videos."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from backend.analysis.metrics import MetricContext, metric_ground_contact_time, _value_at
from backend.analysis.metrics_base import angle_at, segment_angle_from_vertical
from backend.analysis.phases import detect_gait_events, detect_phases, GaitEvents, _midstances_within_stance
from backend.analysis.pose_types import KEYPOINT_NAMES, PoseFrame, PoseSequence
from backend.analysis.reference_scale import ScaleEstimate, normalized_span_to_meters


def frame(i, ankle_y=.85, pelvis_y=.5, pelvis_x=.5):
    kp = np.tile([.5, .5, 2.], (len(KEYPOINT_NAMES), 1))
    for name, xy in {
        'head': (.5,.1), 'pelvis_center': (pelvis_x,pelvis_y),
        'hip_r': (.51,pelvis_y), 'hip_l': (.49,pelvis_y),
        'ankle_r': (.51,ankle_y), 'ankle_l': (.49,ankle_y),
        'heel_r': (.50,ankle_y+.01), 'toe_r': (.53,ankle_y+.01),
    }.items(): kp[KEYPOINT_NAMES.index(name)] = [*xy,2.]
    return PoseFrame(i,kp)


def main():
    results = []
    w,h=1920.,1080.
    a,b,c=(600.,600.),(800.,800.),(1000.,600.)
    norm=lambda p:(p[0]/w,p[1]/h)
    results.append(dict(probe='aspect_ratio_angle',true_degrees=angle_at(a,b,c),
                        current_degrees=angle_at(norm(a),norm(b),norm(c)),
                        trunk_true=segment_angle_from_vertical((0,0),(200,200)),
                        trunk_current=segment_angle_from_vertical((0,0),(200/w,200/h))))
    # One visible foot is sufficient for the threshold; both have the same height
    # here to isolate height convention from side assignment.
    seq=PoseSequence(frames=[frame(i, .85 if i%48<12 else .60) for i in range(240)])
    events=detect_gait_events(seq,240.)
    td_heights=[seq.frames[i].point('ankle_r')[1] for i in events.touchdowns]
    ctx=MetricContext(seq=seq,fps=240.,view='side',events=events,phases=[],
                      scale=ScaleEstimate('none',False))
    gct=metric_ground_contact_time(ctx)
    results.append(dict(probe='contact_threshold_direction',expected_contact_ms=50.,
                        reported_contact_ms=gct.value,touchdowns=events.touchdowns,
                        touchdown_ankle_y=td_heights,event_reliability=events.reliability,
                        reported_metric_reliable=gct.reliable,
                        caveat='Artificial contact waveform isolates threshold polarity; not a real-video accuracy estimate'))
    results.append(dict(probe='midstance_direction',
                        expected_lowest_hip_frame=2,
                        reported_frame=_midstances_within_stance([0,1,2,3,4],np.array([.5,.6,.7,.6,.5]),
                                       GaitEvents(touchdowns=[0],toe_offs=[4]))))
    gapped=PoseSequence(frames=[frame(i,pelvis_x=.2+.001*i) for i in [0,1,2,3,4,100,101,102,103,104]])
    full=PoseSequence(frames=[frame(i,pelvis_x=.2+.001*i) for i in range(105)])
    _,notes_gap=detect_phases(gapped,100.)
    _,notes_full=detect_phases(full,100.)
    results.append(dict(probe='gaps_constant_velocity',true_normalized_velocity=.1,
                        gapped_notes=notes_gap,continuous_notes=notes_full))
    results.append(dict(probe='duty_factor_definition',contact_ms=100.,step_frequency_spm=300.,
                        current_formula=100/(60000/300),
                        same_leg_stride_definition=100/(2*60000/300)))
    results.append(dict(probe='horizontal_scale_aspect_ratio',true_horizontal_distance_m=1.,
                        pixels_per_meter=100.,
                        current_m=normalized_span_to_meters(100/w,100/h)))
    results.append(dict(probe='nearest_event_without_limit',event_frame=500,
                        available_frames=[0,1],returned_value=_value_at([0,1],np.array([100.,110.]),500)))
    # Camera tracking cancels screen movement even when world motion is nonzero.
    tracked=PoseSequence(frames=[frame(i,pelvis_x=.5) for i in range(100)])
    ph,notes=detect_phases(tracked,100.)
    results.append(dict(probe='tracking_phase_unobservable',detected_phases=[p.phase for p in ph],notes=notes))
    out=ROOT/'output'/'analysis_logic_audit_20261015'
    out.mkdir(parents=True,exist_ok=True)
    (out/'reproduction_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))


if __name__=='__main__': main()
