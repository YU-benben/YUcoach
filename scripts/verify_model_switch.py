"""Run both pose backends on the same sample and save reviewable reports."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.analysis.analyze import run_pipeline
from backend.analysis.report import write_report


def main():
    video = ROOT / "samples/videos/训练素材刘珉宇.mp4"
    out = ROOT / "output/model_switch"
    results = []
    for estimator in ("yolo", "rtm"):
        started = time.perf_counter()
        report = run_pipeline(video, estimator=estimator, rtm_mode="lightweight",
                              height_cm=178, max_frames=60, log=print)
        write_report(report, out / f"{estimator}_analysis.json")
        version = report["versions"]["model_version"]
        assert ("yolov8n-pose.pt" if estimator == "yolo" else "mode=lightweight") in version
        results.append({"estimator": estimator, "model_version": version,
                        "seconds": round(time.perf_counter() - started, 2),
                        "metrics": len(report["metrics"]),
                        "findings": len(report["findings"])})
    (out / "verification.json").write_text(
        json.dumps({"sample": str(video), "max_frames": 60,
                    "purpose": "integration verification, not accuracy evaluation",
                    "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
