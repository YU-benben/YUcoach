"""Adversarial association tests do not establish real sprint accuracy."""
from types import SimpleNamespace

import numpy as np
import pytest

from backend.analysis.target_lock import AthleteLock, TargetLostError, keypoint_boxes, validate_target


def selection(start=0, end=10):
    return {"protocol": "athlete_lock_v1", "frame": start, "end_frame": end,
            "bbox": [.1, .1, .3, .9], "confirmed": True}


def scene(boxes, colors):
    image = np.zeros((200, 400, 3), dtype=np.uint8)
    for b, color in zip(boxes, colors):
        x1, y1, x2, y2 = [int(x) for x in b]
        image[max(0,y1):y2, max(0,x1):x2] = color
    return image


def test_tracks_selected_smaller_person_when_order_and_size_change():
    lock = AthleteLock(selection())
    a, b = [40, 20, 120, 180], [250, 0, 390, 200]
    assert lock.select(scene([a,b], [(0,0,255), (255,0,0)]), 0, [a,b]) == 0
    # Larger bystander is first detection, and detections change order every frame.
    for frame in range(1, 10):
        moving = np.asarray(a)+[frame*4, 0, frame*4, 0]
        boxes = [b, moving] if frame % 2 else [moving, b]
        colors = [(255,0,0), (0,0,255)] if frame % 2 else [(0,0,255), (255,0,0)]
        pick = lock.select(scene(boxes, colors), frame, boxes)
        np.testing.assert_array_equal(lock.last_box, moving)
        assert pick == (1 if frame % 2 else 0)


@pytest.mark.parametrize("mode", ["missing", "replacement", "crossing", "jump", "gap"])
def test_fail_closed_never_reacquires(mode):
    lock = AthleteLock(selection())
    a = [40, 20, 120, 180]
    red = scene([a], [(0,0,255)])
    lock.select(red, 0, [a])
    boxes = [a]
    image = red
    index = 1
    if mode == "missing":
        boxes = []
    elif mode == "replacement":
        image = scene([a], [(255,0,0)])  # different person occupying the exact same box
    elif mode == "crossing":
        boxes = [a, [55,20,135,180]]
    elif mode == "jump":
        boxes = [[260,20,340,180]]
    else:
        index = 2
    with pytest.raises(TargetLostError, match="锁定中断"):
        lock.select(image, index, boxes)
    with pytest.raises(TargetLostError, match="禁止自动重选"):
        lock.select(red, 3, [a])
    assert lock.records[1]["status"] == "lost"


def test_reject_initial_overlap_even_with_clear_best_roi():
    lock = AthleteLock(selection())
    boxes = [[40,20,120,180], [70,20,150,180]]
    with pytest.raises(TargetLostError, match="起始帧人物重叠"):
        lock.select(scene(boxes, [(0,0,255)]*2), 0, boxes)


@pytest.mark.parametrize("field,value", [
    ("frame", True), ("frame", -1), ("end_frame", 100), ("end_frame", 0),
    ("confirmed", 1), ("bbox", [0,0,float('nan'),1]),
    ("bbox", [0,0,True,1]), ("bbox", [1,1,0,0]), ("bbox", [0,0,1]),
    ("protocol", "unknown"),
])
def test_invalid_selection(field, value):
    params = selection()
    params[field] = value
    with pytest.raises(ValueError):
        validate_target(params, 100)


class Tensor:
    def __init__(self, data): self.data = np.asarray(data)
    def cpu(self): return self
    def numpy(self): return self.data
    def __getitem__(self, i): return Tensor(self.data[i])


def test_yolo_adapter_uses_selected_box_not_largest_without_loading_weights():
    from backend.analysis.pose_estimator import YoloPoseEstimator
    boxes = np.asarray([[40,20,120,180], [250,0,390,200]])
    class Boxes:
        xyxy = Tensor(boxes)
        conf = Tensor([.8, .99])
        def __len__(self): return 2
    pose = SimpleNamespace(xy=Tensor(np.full((2,17,2), [80., 100.])),
                           conf=Tensor(np.ones((2,17))))
    class Keypoints:
        xy = pose.xy
        conf = pose.conf
        def __len__(self): return 2
    est = object.__new__(YoloPoseEstimator)
    est.device, est.imgsz, est.conf, est.verbose = "cpu", 640, .3, False
    est.target_lock = AthleteLock(selection())
    est._model = SimpleNamespace(predict=lambda *a, **k: [SimpleNamespace(keypoints=Keypoints(), boxes=Boxes())])
    result = est.estimate(scene(boxes, [(0,0,255), (255,0,0)]), 0)
    assert result.bbox == pytest.approx((.1, .1, .3, .9))
    est._model = SimpleNamespace(predict=lambda *a, **k: [])
    with pytest.raises(TargetLostError):
        est.estimate(np.zeros((200,400,3), np.uint8), 1)


def test_rtm_adapter_uses_selected_body_not_confidence_winner():
    from backend.analysis.pose_estimator_rtm import RtmPoseEstimator
    from backend.tests.test_pose_estimator_rtm import make_halpe
    # Build two actual Halpe body layouts and derive visible-point boxes.
    bodies = []
    for x in (.2, .75):
        body = make_halpe()
        body[:,0] += x-.5
        bodies.append(body)
    bodies = np.asarray(bodies)
    kp = bodies[:,:,:2]*[400,200]
    scores = bodies[:,:,2]
    boxes = keypoint_boxes(kp, scores)
    roi = (boxes[0]/[400,200,400,200]).clip(0,1).tolist()
    est = object.__new__(RtmPoseEstimator)
    est.target_lock = AthleteLock({**selection(), "bbox": roi})
    est._model = lambda image: (kp, scores)
    image = scene(boxes, [(0,0,255), (255,0,0)])
    result = est.estimate(image, 0)
    assert result.bbox == pytest.approx(roi)


def test_selected_pipeline_crops_time_range_and_persists_track(tmp_path, monkeypatch):
    import json
    from backend.analysis import analyze
    from backend.analysis.pose_types import PoseFrame, PoseSequence
    from backend.tests.test_manual_timing import make_video
    path = tmp_path / "video.avi"
    make_video(path)
    class FakeEstimator:
        name, version, device, provides_foot_keypoints = "fake", "1", "cpu", False
        def estimate_sequence(self, frames):
            seq = PoseSequence(estimator_name=self.name)
            for idx, image in frames:
                self.target_lock.select(image, idx, [[9.6,6.4,28.8,57.6]])
                seq.frames.append(PoseFrame(idx, np.ones((16,3))))
            return seq
    monkeypatch.setattr(analyze, "_build_estimator", lambda *a, **k: FakeEstimator())
    monkeypatch.setattr(analyze, "estimate_camera_motion", lambda p: ("fixed",0,[]))
    target = selection(start=5, end=10)
    report = analyze.run_pipeline(path, camera_followed=False, target_selection=target,
                                 keyframe_dir=tmp_path / "keyframes")
    track = json.loads((tmp_path/"keyframes"/"target_tracking.json").read_text())
    assert [e["frame"] for e in track["frames"]] == list(range(5,11))
    assert track["status"] == "completed"
    assert "target_lock" in report["versions"]["model_version"]


def test_pipeline_loss_preserves_failed_frame_without_building_report(tmp_path, monkeypatch):
    import json
    from backend.analysis import analyze
    from backend.tests.test_manual_timing import make_video
    path = tmp_path / "video.avi"
    make_video(path)
    class LostEstimator:
        name, device, provides_foot_keypoints = "fake", "cpu", False
        def estimate_sequence(self, frames):
            for idx, image in frames:
                self.target_lock.select(image, idx, [[9.6,6.4,28.8,57.6]] if idx == 0 else [])
    monkeypatch.setattr(analyze, "_build_estimator", lambda *a, **k: LostEstimator())
    monkeypatch.setattr(analyze, "estimate_camera_motion", lambda p: ("fixed",0,[]))
    def forbidden(*a, **k): raise AssertionError("Cannot report a lost identity")
    monkeypatch.setattr(analyze, "build_report", forbidden)
    with pytest.raises(TargetLostError):
        analyze.run_pipeline(path, camera_followed=False, target_selection=selection(),
                             keyframe_dir=tmp_path/"keyframes")
    trace = json.loads((tmp_path/"keyframes"/"target_tracking.json").read_text(encoding="utf-8"))
    assert trace["status"] == "lost"
    assert trace["frames"][-1]["frame"] == 1


def test_manual_events_cannot_escape_target_range(tmp_path):
    from backend.analysis.analyze import run_pipeline
    from backend.tests.test_manual_timing import make_video, review
    path = tmp_path / "video.avi"
    make_video(path)
    with pytest.raises(ValueError, match="超出"):
        run_pipeline(path, camera_followed=False, target_selection=selection(start=5, end=130),
                     manual_review=review())
