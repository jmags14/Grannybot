"""
Run the fall detector on a webcam or video, no ROS needed.

  python tools/run_detector.py                                   # webcam, yolo11n-pose
  python tools/run_detector.py --detector mediapipe              # webcam, yolo11n + MediaPipe
  python tools/run_detector.py --source data/clips/fall_01.mp4 --log data/logs/fall_01.csv
  python tools/run_detector.py --headless --every-n 2 --weights yolo11n-pose_ncnn_model   # on the Pi
"""
import argparse

import _paths  # noqa: F401
from grannybot_vision.detectors import make_detector
from grannybot_vision.pipeline import run

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="0", help="camera index, video file or stream URL")
ap.add_argument("--detector", default="pose", choices=["pose", "mediapipe"])
ap.add_argument("--weights", default=None)
ap.add_argument("--imgsz", type=int, default=320)
ap.add_argument("--every-n", type=int, default=1)
ap.add_argument("--headless", action="store_true")
ap.add_argument("--log", default=None, help="CSV of per-frame measurements for tuning")
a = ap.parse_args()

det = make_detector(a.detector, a.weights, a.imgsz)
stats = run(a.source, det, every_n=a.every_n, show=not a.headless, log_path=a.log,
            on_fall=lambda r: print(f"   >>> FALL DETECTED: {r}"))
print(f"\nprocessed {stats['processed']} frames, model speed {stats['infer_fps']:.1f} fps")
