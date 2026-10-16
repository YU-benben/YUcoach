"""Run a real local pose model on an explicitly selected short interval.

Outputs frames and association trace for human inspection, not accuracy claims.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import cv2
    from backend.analysis.video_io import iter_frames
    from backend.analysis.target_lock import AthleteLock, TargetLostError
    from backend.analysis.pose_estimator import YoloPoseEstimator
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=0)
    parser.add_argument("--bbox", type=float, nargs=4)
    parser.add_argument("--output", type=Path, default=ROOT/"output"/"target_lock_verification")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.bbox is None:
        for idx, image in iter_frames(args.video, start=args.start, end=args.start+1):
            cv2.imwrite(str(args.output/f"source_{idx:06d}.jpg"), image)
        return
    estimator = YoloPoseEstimator()
    lock = AthleteLock({"protocol": "athlete_lock_v1", "frame": args.start,
                        "end_frame": args.end, "bbox": args.bbox, "confirmed": True})
    estimator.target_lock = lock
    try:
        for idx, image in iter_frames(args.video, start=args.start, end=args.end+1):
            pf = estimator.estimate(image, idx)
            h,w = image.shape[:2]
            x1,y1,x2,y2 = (int(v*d) for v,d in zip(pf.bbox, [w,h,w,h]))
            cv2.rectangle(image, (x1,y1), (x2,y2), (0,255,0), 3)
            cv2.putText(image, f"selected athlete | frame {idx}", (15,35), cv2.FONT_HERSHEY_SIMPLEX, .8, (0,255,0), 2)
            if idx == args.start or idx == args.end or (idx-args.start)%10 == 0:
                cv2.imwrite(str(args.output/f"locked_{idx:06d}.jpg"), image)
    except TargetLostError as exc:
        print(str(exc))
    finally:
        (args.output/"trace.json").write_text(json.dumps({"selection": lock.selection,
            "status": "lost" if lock.failed else "completed", "frames": lock.records},
            ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"status={'lost' if lock.failed else 'completed'}, frames={len(lock.records)}")


if __name__ == "__main__":
    main()
