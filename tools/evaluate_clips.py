"""
Compare detectors on your recorded test clips. This produces the Results table for the paper.

Put clips in data/clips/ and name them by what happens:
  fall_forward_01.mp4, fall_side_02.mp4, fall_slow_01.mp4 ...   -> should end in FALLEN
  nofall_walk_01.mp4, nofall_bend_01.mp4, nofall_couch_01.mp4 ... -> should NOT
Optional data/clips/labels.csv with columns: file,label,fall_time_s
  (label = fall|nofall; fall_time_s = when the person hits the floor, for time-to-detect)

  python tools/evaluate_clips.py --detectors pose mediapipe
  python tools/evaluate_clips.py --detectors pose --every-n 2        # simulate the Pi setting

Writes data/results/per_clip.csv and prints a summary table (also saved as summary.md).
"""
import argparse
import csv
import glob
import os
import statistics

import _paths  # noqa: F401
from grannybot_vision.detectors import make_detector
from grannybot_vision.pipeline import run

ap = argparse.ArgumentParser()
ap.add_argument("--clips", default=os.path.join(_paths.ROOT, "data", "clips"))
ap.add_argument("--out", default=os.path.join(_paths.ROOT, "data", "results"))
ap.add_argument("--detectors", nargs="+", default=["pose", "mediapipe"])
ap.add_argument("--every-n", type=int, default=1)
ap.add_argument("--imgsz", type=int, default=320, help="try 320 vs 480 vs 640 for the paper")
a = ap.parse_args()

videos = sorted(f for ext in ("mp4", "mov", "avi", "mkv")
                for f in glob.glob(os.path.join(a.clips, f"*.{ext}")))
if not videos:
    raise SystemExit(f"No videos in {a.clips}. See the docstring for naming.")

labels = {}
lab_path = os.path.join(a.clips, "labels.csv")
if os.path.exists(lab_path):
    for row in csv.DictReader(open(lab_path)):
        labels[row["file"]] = (row["label"].strip(), float(row["fall_time_s"]) if row.get("fall_time_s") else None)


def label_for(path):
    name = os.path.basename(path)
    if name in labels:
        return labels[name]
    return ("nofall" if name.lower().startswith("nofall") else "fall"), None


os.makedirs(a.out, exist_ok=True)
rows = []
for kind in a.detectors:
    det = make_detector(kind, imgsz=a.imgsz)
    for v in videos:
        label, fall_t = label_for(v)
        s = run(v, det, every_n=a.every_n, show=False, verbose=False)
        detected = s["first_fallen_t"] is not None
        ttd = (s["first_fallen_t"] - fall_t) if (detected and fall_t is not None) else None
        rows.append({"detector": kind, "clip": os.path.basename(v), "label": label,
                     "detected": int(detected),
                     "first_fallen_s": round(s["first_fallen_t"], 2) if detected else "",
                     "time_to_detect_s": round(ttd, 2) if ttd is not None else "",
                     "model_fps": round(s["infer_fps"], 1)})
        print(f"{kind:9s} {os.path.basename(v):30s} label={label:6s} detected={detected}")

with open(os.path.join(a.out, "per_clip.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

lines = ["| Detector | Falls detected | False alarms | Avg time to detect (s) | Model FPS |",
         "|---|---|---|---|---|"]
for kind in a.detectors:
    r = [x for x in rows if x["detector"] == kind]
    falls = [x for x in r if x["label"] == "fall"]
    nofalls = [x for x in r if x["label"] == "nofall"]
    caught = sum(x["detected"] for x in falls)
    fa = sum(x["detected"] for x in nofalls)
    ttds = [x["time_to_detect_s"] for x in falls if x["time_to_detect_s"] != ""]
    fps = statistics.mean(x["model_fps"] for x in r)
    rate = 100 * caught / max(len(falls), 1)
    ttd = f"{statistics.mean(ttds):.1f}" if ttds else "n/a"
    lines.append(f"| {kind} | {caught}/{len(falls)} ({rate:.0f}%) | {fa}/{len(nofalls)} | {ttd} | {fps:.1f} |")
summary = "\n".join(lines)
open(os.path.join(a.out, "summary.md"), "w").write(summary + "\n")
print("\n" + summary)
