from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.analysis.manual_timing import inspect_video, timing_metrics, validate_review, read_frame


def review():
    return {"protocol": "manual_side_v1", "original_cfr_confirmed": True,
            "fixed_side_confirmed": True, "same_athlete_confirmed": True,
            "all_contacts_confirmed": True,
            "events": [
                {"frame": f, "side": s, "type": t}
                for f, s, t in [(0, "left", "touchdown"), (24, "left", "toe_off"),
                                (48, "right", "touchdown"), (72, "right", "toe_off"),
                                (96, "left", "touchdown"), (120, "left", "toe_off")]]}


def test_physical_timing_and_same_foot_denominator():
    labels = validate_review(review(), {"frame_count": 144}, view="side", camera_followed=False)
    result = {r.metric_id: r for r in timing_metrics(labels, 240)}
    assert result["ground_contact_time"].value == 100
    assert result["flight_time"].value == 100
    assert result["step_frequency"].value == 300
    assert result["duty_factor"].value == .25  # 100ms / 400ms, NOT .5
    assert result["duty_factor"].aggregate["n"] == 1
    assert result["step_length"].value is None
    assert result["knee_angle_touchdown"].value is None


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(original_cfr_confirmed=False),
    lambda r: r.update(all_contacts_confirmed=1),
    lambda r: r["events"][1].update(side="right"),
    lambda r: r["events"][1].update(frame=0),
    lambda r: r["events"][1].update(frame=True),
    lambda r: r["events"][1].update(frame=200),
    lambda r: r["events"].pop(),
    lambda r: r["events"][2].update(type="toe_off"),
])
def test_reject_bad_or_unconfirmed_annotations(mutation):
    r = review()
    mutation(r)
    with pytest.raises(ValueError):
        validate_review(r, {"frame_count": 144}, view="side", camera_followed=False)


@pytest.mark.parametrize("view,followed", [("front", False), ("side", True), ("side", None)])
def test_acquisition_gate(view, followed):
    with pytest.raises(ValueError):
        validate_review(review(), {"frame_count": 144}, view=view, camera_followed=followed)


def make_video(path: Path, fps=240):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (96, 64))
    assert writer.isOpened()
    for i in range(144):
        writer.write(np.full((64, 96, 3), i, np.uint8))
    writer.release()


def test_actual_decode_frame_index_and_timing(tmp_path):
    path = tmp_path / "high.avi"
    make_video(path)
    meta = inspect_video(path)
    assert meta["fps"] == 240
    assert meta["frame_count"] == 144
    frame = cv2.imdecode(np.frombuffer(read_frame(path, 96), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert float(frame.mean()) == pytest.approx(96, abs=2)
    with pytest.raises(ValueError):
        read_frame(path, 144)
    make_video(path, fps=60)
    with pytest.raises(ValueError, match="120"):
        inspect_video(path)


def test_manual_pipeline_never_loads_pose_and_validates_contract(tmp_path, monkeypatch):
    from backend.analysis import analyze
    from scripts.check_contracts import load_contracts, validate_instance
    path = tmp_path / "high.avi"
    make_video(path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Manual timing must not depend on pose or camera inference")
    monkeypatch.setattr(analyze, "_build_estimator", forbidden)
    monkeypatch.setattr(analyze, "estimate_camera_motion", forbidden)
    report = analyze.run_pipeline(path, athlete_id="at00001", camera_followed=False, manual_review=review())
    assert report["findings"] == []
    assert report["phases_detected"] == []
    assert "manual-contact" in report["versions"]["model_version"]
    assert all(m["phase"] == "whole_run" for m in report["metrics"])
    assert not validate_instance(load_contracts(), "analysis", report)
