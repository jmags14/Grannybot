"""
fall_logic.py — decides "is granny down?" from per-frame measurements.

This file has NO camera or model code on purpose, so you can
unit-test and tune it with fake numbers (see tests/test_fall_logic.py).

Coordinates are normalized: 0.0 = top/left of image, 1.0 = bottom/right.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class FallConfig:
    # Torso angle from vertical (deg). 0 = standing straight, 90 = lying flat.
    torso_lying_deg: float = 60.0
    # Person box width / height. A standing person is ~0.3–0.5, lying is >1.
    aspect_lying: float = 1.2
    # With a torso angle available, also require the box not be tall/skinny.
    aspect_min_with_torso: float = 0.8
    # Backup rule: keypoints on small/sideways people are less accurate, so a clearly
    # tilted torso PLUS a wide box also counts as lying. (Bending over keeps a tall box.)
    torso_partial_deg: float = 45.0
    aspect_partial: float = 1.0
    # "Sudden drop": hips move down by at least this fraction of the person's standing
    # height (box height). Measuring against body height instead of image height means
    # the rule works the same whether she's 1 m or 4 m from the camera.
    drop_fraction_of_height: float = 0.25
    # ...within this many seconds.
    drop_window_s: float = 1.0
    # A drop counts toward a fall if lying starts within this many seconds of it.
    drop_to_lying_s: float = 2.0
    # Sudden drop + lying for this long => FALLEN.
    confirm_after_drop_s: float = 3.0
    # Lying with NO sudden drop seen (robot arrived late, slow slide) => FALLEN after this long.
    confirm_no_drop_s: float = 20.0
    # If the person disappears for less than this, keep the timers (YOLO flickers).
    lost_grace_s: float = 2.0


@dataclass
class Observation:
    t: float                                    # timestamp in seconds
    person: bool                                # did the detector find a person?
    bbox: Optional[Tuple[float, float, float, float]] = None  # x1, y1, x2, y2 (normalized)
    torso_angle: Optional[float] = None         # degrees from vertical (from pose keypoints)
    hip_y: Optional[float] = None               # normalized hip height (from pose keypoints)


# States, in order of seriousness
NO_PERSON = "NO_PERSON"
UPRIGHT = "UPRIGHT"
POSSIBLE_FALL = "POSSIBLE_FALL"
FALLEN = "FALLEN"


class FallLogic:
    def __init__(self, cfg: Optional[FallConfig] = None):
        self.cfg = cfg or FallConfig()
        self.reset()

    def reset(self) -> None:
        self.state = NO_PERSON
        self.reason = ""
        self._hips: deque = deque()          # (t, hip_y, box_height)
        self._lying_since: Optional[float] = None
        self._last_drop_t: Optional[float] = None
        self._last_seen_t: Optional[float] = None

    # ---- helpers -------------------------------------------------------
    def _is_lying(self, obs: Observation) -> bool:
        c = self.cfg
        x1, y1, x2, y2 = obs.bbox
        w, h = max(x2 - x1, 1e-6), max(y2 - y1, 1e-6)
        aspect = w / h
        if obs.torso_angle is not None:
            if obs.torso_angle >= c.torso_lying_deg and aspect >= c.aspect_min_with_torso:
                return True
            return obs.torso_angle >= c.torso_partial_deg and aspect >= c.aspect_partial
        return aspect >= c.aspect_lying

    def _check_drop(self, t: float, hip_y: float, box_h: float) -> None:
        c = self.cfg
        self._hips.append((t, hip_y, box_h))
        while self._hips and t - self._hips[0][0] > c.drop_window_s:
            self._hips.popleft()
        highest = min(y for _, y, _ in self._hips)       # y grows downward
        tallest = max(h for _, _, h in self._hips)       # her height while still standing
        if hip_y - highest >= c.drop_fraction_of_height * tallest:
            self._last_drop_t = t

    # ---- main entry ----------------------------------------------------
    def update(self, obs: Observation) -> str:
        c = self.cfg
        t = obs.t

        if not obs.person or obs.bbox is None:
            if self._last_seen_t is None or t - self._last_seen_t > c.lost_grace_s:
                self._lying_since = None
                self._hips.clear()
                self.state, self.reason = NO_PERSON, ""
            return self.state

        self._last_seen_t = t
        hip_y = obs.hip_y if obs.hip_y is not None else (obs.bbox[1] + obs.bbox[3]) / 2
        self._check_drop(t, hip_y, obs.bbox[3] - obs.bbox[1])

        if not self._is_lying(obs):
            self._lying_since = None
            self.state, self.reason = UPRIGHT, ""
            return self.state

        if self._lying_since is None:
            self._lying_since = t
        down_for = t - self._lying_since
        fell_fast = (
            self._last_drop_t is not None
            and self._lying_since - c.drop_to_lying_s <= self._last_drop_t <= t
        )

        if fell_fast and down_for >= c.confirm_after_drop_s:
            self.state, self.reason = FALLEN, f"sudden fall, down for {down_for:.0f}s"
        elif down_for >= c.confirm_no_drop_s:
            self.state, self.reason = FALLEN, f"on the floor for {down_for:.0f}s"
        else:
            self.state = POSSIBLE_FALL
            self.reason = "sudden drop, waiting to confirm" if fell_fast else "lying down, watching"
        return self.state
