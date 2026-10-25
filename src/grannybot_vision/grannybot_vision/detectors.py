"""
detectors.py — two interchangeable ways to measure a person's body in a frame.

  YoloPoseDetector       one model (yolo11n-pose) finds the person AND 17 keypoints   <- main
  YoloMediaPipeDetector  YOLO (yolo11n) finds the person, MediaPipe Pose finds 33
                         landmarks on the crop                                         <- comparison

Both return the same dict, so fall_logic and everything downstream doesn't care
which one you use. That's what makes the comparison in the paper fair.

  {
    "bbox":        (x1, y1, x2, y2)   normalized 0..1
    "bbox_px":     (x1, y1, x2, y2)   pixels (for drawing)
    "torso_angle": degrees from vertical, or None if shoulders/hips not visible
    "hip_y":       normalized hip height, or None
    "points":      ((shoulder_x, shoulder_y), (hip_x, hip_y)) in pixels, or None
    "skeleton":    list of (x, y) pixel keypoints for drawing, or None
  }
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .paths import model_path


def torso_from_points(l_sh, r_sh, l_hip, r_hip):
    """Torso angle (deg from vertical) from 4 pixel points. Returns angle, mid_sh, mid_hip."""
    sh = (np.asarray(l_sh, float) + np.asarray(r_sh, float)) / 2
    hp = (np.asarray(l_hip, float) + np.asarray(r_hip, float)) / 2
    dx, dy = sh[0] - hp[0], sh[1] - hp[1]
    angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))
    return angle, sh, hp


def _largest(boxes: np.ndarray) -> int:
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return int(areas.argmax())


def _empty(bbox_px, W, H):
    x1, y1, x2, y2 = (float(v) for v in bbox_px)
    return {"bbox": (x1 / W, y1 / H, x2 / W, y2 / H), "bbox_px": (x1, y1, x2, y2),
            "torso_angle": None, "hip_y": None, "points": None, "skeleton": None}


class YoloPoseDetector:
    """yolo11n-pose: COCO 17 keypoints. Shoulders = 5, 6. Hips = 11, 12."""
    name = "pose"
    L_SH, R_SH, L_HIP, R_HIP = 5, 6, 11, 12

    def __init__(self, weights: str = "yolo11n-pose.pt", imgsz: int = 320, conf: float = 0.25,
                 kpt_conf: float = 0.5):
        from ultralytics import YOLO
        self.model = YOLO(model_path(weights))
        self.imgsz, self.conf, self.kpt_conf = imgsz, conf, kpt_conf

    def detect(self, frame: np.ndarray) -> Optional[dict]:
        H, W = frame.shape[:2]
        r = self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, classes=[0], verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return None
        boxes = r.boxes.xyxy.cpu().numpy()
        i = _largest(boxes)                               # biggest box = closest person
        out = _empty(boxes[i], W, H)
        if r.keypoints is None or r.keypoints.xy is None or len(r.keypoints.xy) <= i:
            return out
        xy = r.keypoints.xy[i].cpu().numpy()             # (17, 2) pixels
        kc = r.keypoints.conf
        conf = kc[i].cpu().numpy() if kc is not None else np.ones(len(xy))
        out["skeleton"] = [tuple(p) for p, c in zip(xy.astype(int), conf) if c >= self.kpt_conf]
        idx = (self.L_SH, self.R_SH, self.L_HIP, self.R_HIP)
        if min(conf[j] for j in idx) < self.kpt_conf:
            return out                                    # torso hidden: box shape only
        angle, sh, hp = torso_from_points(*(xy[j] for j in idx))
        out.update(torso_angle=angle, hip_y=hp[1] / H,
                   points=(tuple(sh.astype(int)), tuple(hp.astype(int))))
        return out


class YoloMediaPipeDetector:
    """yolo11n finds the person, MediaPipe Pose Landmarker measures them on the crop."""
    name = "mediapipe"
    L_SH, R_SH, L_HIP, R_HIP = 11, 12, 23, 24

    def __init__(self, weights: str = "yolo11n.pt", pose_model: str = "pose_landmarker_lite.task",
                 imgsz: int = 320, conf: float = 0.25, vis: float = 0.4):
        import os

        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        from ultralytics import YOLO

        self.yolo = YOLO(model_path(weights))
        self.imgsz, self.conf, self.vis = imgsz, conf, vis
        task = model_path(pose_model)
        if not os.path.exists(task):
            raise FileNotFoundError(f"{task} not found. Run: python tools/setup_models.py")
        self._mp = mp
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=task),
            running_mode=vision.RunningMode.IMAGE, num_poses=1))

    def detect(self, frame: np.ndarray) -> Optional[dict]:
        import cv2
        H, W = frame.shape[:2]
        r = self.yolo.predict(frame, imgsz=self.imgsz, conf=self.conf, classes=[0], verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return None
        boxes = r.boxes.xyxy.cpu().numpy()
        x1, y1, x2, y2 = boxes[_largest(boxes)]
        out = _empty((x1, y1, x2, y2), W, H)

        pw, ph = (x2 - x1) * 0.15, (y2 - y1) * 0.15      # pad crop so whole body is in it
        cx1, cy1 = int(max(0, x1 - pw)), int(max(0, y1 - ph))
        cx2, cy2 = int(min(W, x2 + pw)), int(min(H, y2 + ph))
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return out
        rgb = np.ascontiguousarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        res = self.pose.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        if not res.pose_landmarks:
            return out
        lm = res.pose_landmarks[0]
        cw, ch = cx2 - cx1, cy2 - cy1

        def pt(j):
            return (cx1 + lm[j].x * cw, cy1 + lm[j].y * ch)

        out["skeleton"] = [tuple(int(v) for v in pt(j)) for j in range(len(lm)) if lm[j].visibility >= self.vis]
        idx = (self.L_SH, self.R_SH, self.L_HIP, self.R_HIP)
        if min(lm[j].visibility for j in idx) < self.vis:
            return out
        angle, sh, hp = torso_from_points(*(pt(j) for j in idx))
        out.update(torso_angle=angle, hip_y=hp[1] / H,
                   points=(tuple(sh.astype(int)), tuple(hp.astype(int))))
        return out


def make_detector(kind: str = "pose", weights: Optional[str] = None, imgsz: int = 320):
    """kind = 'pose' (yolo11n-pose) or 'mediapipe' (yolo11n + MediaPipe)."""
    if kind == "pose":
        return YoloPoseDetector(weights or "yolo11n-pose.pt", imgsz=imgsz)
    if kind == "mediapipe":
        return YoloMediaPipeDetector(weights or "yolo11n.pt", imgsz=imgsz)
    raise ValueError(f"unknown detector '{kind}' (use 'pose' or 'mediapipe')")
