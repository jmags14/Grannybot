"""
pipeline.py — the camera/video loop shared by the laptop tools and the evaluation script.
(The ROS node in fall_node.py does the same thing, but gets frames from a ROS topic.)
"""
from __future__ import annotations

import csv
import os
import time
from typing import Callable, Optional

import cv2

from .fall_logic import FALLEN, FallConfig, FallLogic, Observation

COLORS = {"UPRIGHT": (0, 200, 0), "POSSIBLE_FALL": (0, 200, 255), "FALLEN": (0, 0, 255)}


def observation_from(det: Optional[dict], t: float) -> Observation:
    return Observation(t=t, person=det is not None,
                       bbox=det["bbox"] if det else None,
                       torso_angle=det["torso_angle"] if det else None,
                       hip_y=det["hip_y"] if det else None)


def draw(frame, det, state, reason, fps=None, label=""):
    color = COLORS.get(state, (200, 200, 200))
    if det:
        x1, y1, x2, y2 = map(int, det["bbox_px"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        for p in det.get("skeleton") or []:
            cv2.circle(frame, (int(p[0]), int(p[1])), 3, (255, 255, 0), -1)
        if det["points"]:
            cv2.line(frame, det["points"][0], det["points"][1], (255, 0, 255), 3)
        if det["torso_angle"] is not None:
            cv2.putText(frame, f"torso {det['torso_angle']:.0f} deg", (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.putText(frame, f"{state} {reason}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    if fps is not None:
        cv2.putText(frame, f"{label} {fps:.1f} fps", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)
    return frame


def run(source, detector, cfg: Optional[FallConfig] = None, every_n: int = 1, show: bool = True,
        log_path: Optional[str] = None, on_fall: Optional[Callable[[str], None]] = None,
        verbose: bool = True) -> dict:
    """Process a camera or video. Returns stats used by tools/evaluate_clips.py."""
    src = int(source) if str(source).isdigit() else source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera/video: {source}")
    is_file = isinstance(src, str) and os.path.exists(src)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    logic = FallLogic(cfg)
    writer = None
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        log_file = open(log_path, "w", newline="")
        writer = csv.writer(log_file)
        writer.writerow(["t", "person", "torso_angle", "aspect", "hip_y", "state", "reason"])

    stats = {"frames": 0, "processed": 0, "infer_s": 0.0, "first_fallen_t": None,
             "first_possible_t": None, "states": set()}
    frame_i, det, last_state, fps, t_prev = 0, None, None, 0.0, time.time()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_i += 1
            stats["frames"] += 1
            t = frame_i / video_fps if is_file else time.time()
            if frame_i % every_n == 0:
                t0 = time.perf_counter()
                det = detector.detect(frame)
                stats["infer_s"] += time.perf_counter() - t0
                stats["processed"] += 1
                state = logic.update(observation_from(det, t))
                stats["states"].add(state)
                if state == "POSSIBLE_FALL" and stats["first_possible_t"] is None:
                    stats["first_possible_t"] = t
                if state == FALLEN and stats["first_fallen_t"] is None:
                    stats["first_fallen_t"] = t
                now = time.time()
                fps = 0.9 * fps + 0.1 / max(now - t_prev, 1e-6)
                t_prev = now
                if writer:
                    aspect = None
                    if det:
                        b = det["bbox"]
                        aspect = (b[2] - b[0]) / max(b[3] - b[1], 1e-6)
                    writer.writerow([f"{t:.2f}", int(det is not None), det and det["torso_angle"],
                                     aspect, det and det["hip_y"], state, logic.reason])
                if state != last_state:
                    if verbose:
                        print(f"[{t:8.2f}] {state:13s} {logic.reason}")
                    if state == FALLEN and on_fall:
                        on_fall(logic.reason)
                    last_state = state
            if show:
                draw(frame, det, logic.state, logic.reason, fps, getattr(detector, "name", ""))
                cv2.imshow("GrannyBot (q to quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        if writer:
            log_file.close()
        if show:
            cv2.destroyAllWindows()
    stats["infer_fps"] = stats["processed"] / stats["infer_s"] if stats["infer_s"] else 0.0
    stats["duration_s"] = stats["frames"] / video_fps if is_file else None
    return stats
