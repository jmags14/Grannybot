"""
sim_core.py — a tiny 2D world for testing GrannyBot without the robot. No ROS.

What it simulates:
  * a house = the named rooms from rooms.yaml (you're "in" whichever room center is closest)
  * the robot: position + heading; drives to Nav2 goals in a straight line, or follows cmd_vel
  * the person: a position and a posture (standing / falling / lying), scripted by a scenario
  * the camera: sees the person if they're in the same room, inside the field of view, and
    within range. It turns the person's posture into the same numbers the real detector
    produces (box, torso angle, hip height), and runs the REAL fall_logic on them.
  * the LiDAR: distance straight ahead (person if they're in front, otherwise a wall)

It's deliberately simple. It tests the decisions and the wiring between nodes, not
perception accuracy (that's what tools/evaluate_clips.py on real video is for).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import yaml
from grannybot_vision.fall_logic import FallLogic, Observation

STANDING, FALLING, LYING = "standing", "falling", "lying"


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


@dataclass
class Scenario:
    name: str
    duration_s: float
    robot_start: Tuple[float, float, float]
    person_position: Tuple[float, float]
    events: List[dict] = field(default_factory=list)       # {t, do: fall|lie|stand|move_to, room?}
    checkin_answer: str = "NO_RESPONSE"                    # OK | HELP | NO_RESPONSE
    checkin_delay_s: float = 15.0
    button_at: List[float] = field(default_factory=list)
    expect: dict = field(default_factory=dict)
    description: str = ""

    @staticmethod
    def load(path: str) -> "Scenario":
        with open(path) as f:
            d = yaml.safe_load(f)
        return Scenario(
            name=d["name"], duration_s=float(d["duration_s"]),
            robot_start=tuple(d.get("robot_start", [0, 0, 0])),
            person_position=tuple(d["person"]["position"]),
            events=d.get("events", []), checkin_answer=d.get("checkin_answer", "NO_RESPONSE"),
            checkin_delay_s=float(d.get("checkin_delay_s", 15)),
            button_at=[float(t) for t in d.get("button_at", [])],
            expect=d.get("expect", {}), description=d.get("description", ""))


class SimWorld:
    def __init__(self, rooms: Dict[str, Sequence[float]], scenario: Scenario,
                 hfov_deg: float = 120.0, camera_range_m: float = 6.0,
                 nav_speed: float = 0.4, wall_m: float = 4.0):
        self.rooms = {k: tuple(float(v) for v in xyz) for k, xyz in rooms.items()}
        self.sc = scenario
        self.hfov = math.radians(hfov_deg)
        self.camera_range = camera_range_m
        self.nav_speed = nav_speed
        self.wall_m = wall_m
        self.t = 0.0
        self.rx, self.ry, self.ryaw = (float(v) for v in scenario.robot_start)
        self.v, self.w = 0.0, 0.0
        self.goal: Optional[Tuple[int, float, float, float]] = None   # id, x, y, yaw
        self.px, self.py = (float(v) for v in scenario.person_position)
        self.posture, self.posture_t = STANDING, 0.0
        self._pending = sorted(scenario.events, key=lambda e: e["t"])
        self.fall_logic = FallLogic()

    # ---- geometry --------------------------------------------------------
    def room_of(self, x: float, y: float) -> str:
        return min(self.rooms, key=lambda r: (self.rooms[r][0] - x) ** 2 + (self.rooms[r][1] - y) ** 2)

    def person_room(self) -> str:
        return self.room_of(self.px, self.py)

    def robot_room(self) -> str:
        return self.room_of(self.rx, self.ry)

    def bearing_to_person(self) -> float:
        """radians, + = left of the robot's heading"""
        return wrap(math.atan2(self.py - self.ry, self.px - self.rx) - self.ryaw)

    def distance_to_person(self) -> float:
        return math.hypot(self.px - self.rx, self.py - self.ry)

    def person_visible(self) -> bool:
        return (self.person_room() == self.robot_room()
                and abs(self.bearing_to_person()) <= self.hfov / 2
                and self.distance_to_person() <= self.camera_range)

    # ---- robot motion ----------------------------------------------------
    def start_goal(self, goal_id: int, x: float, y: float, yaw: float) -> None:
        self.goal = (goal_id, x, y, yaw)
        self.v = self.w = 0.0

    def cancel_goal(self) -> None:
        self.goal = None

    def set_cmd_vel(self, v: float, w: float) -> None:
        if self.goal is None:            # Nav2 owns the wheels while it has a goal
            self.v, self.w = v, w

    def step(self, dt: float) -> Optional[Tuple[int, bool]]:
        """Advance the world. Returns (goal_id, succeeded) when a Nav2 goal finishes."""
        self.t += dt
        self._run_events()
        finished = None
        if self.goal is not None:
            gid, gx, gy, gyaw = self.goal
            dx, dy = gx - self.rx, gy - self.ry
            d = math.hypot(dx, dy)
            step = self.nav_speed * dt
            if d <= step:
                self.rx, self.ry, self.ryaw = gx, gy, gyaw
                self.goal = None
                finished = (gid, True)
            else:
                self.ryaw = math.atan2(dy, dx)
                self.rx += dx / d * step
                self.ry += dy / d * step
        else:
            self.ryaw = wrap(self.ryaw + self.w * dt)
            nx = self.rx + self.v * math.cos(self.ryaw) * dt
            ny = self.ry + self.v * math.sin(self.ryaw) * dt
            if math.hypot(self.px - nx, self.py - ny) >= 0.35:   # don't drive through her
                self.rx, self.ry = nx, ny
        return finished

    # ---- person ----------------------------------------------------------
    def _run_events(self) -> None:
        while self._pending and self._pending[0]["t"] <= self.t:
            e = self._pending.pop(0)
            do = e["do"]
            if do == "fall":
                self.posture, self.posture_t = FALLING, self.t
            elif do == "lie":
                self.posture, self.posture_t = LYING, self.t
            elif do == "stand":
                self.posture, self.posture_t = STANDING, self.t
            elif do == "move_to":
                x, y, _ = self.rooms[e["room"]]
                self.px, self.py = x + 0.8, y + 0.8

    def _posture_now(self) -> Tuple[str, float]:
        if self.posture == FALLING:
            k = (self.t - self.posture_t) / 0.5
            if k >= 1.0:
                self.posture = LYING
                return LYING, 1.0
            return FALLING, k
        return self.posture, 1.0 if self.posture == LYING else 0.0

    # ---- sensors ---------------------------------------------------------
    def camera(self) -> dict:
        """What the vision node would publish this frame."""
        if not self.person_visible():
            obs = Observation(t=self.t, person=False)
            state = self.fall_logic.update(obs)
            return {"seen": False, "bearing_deg": None, "fall_state": state,
                    "reason": self.fall_logic.reason}
        b = self.bearing_to_person()
        cx = 0.5 - b / self.hfov                       # position in the image, 0..1
        h_stand = min(0.9, 1.6 / max(self.distance_to_person(), 0.5))
        _, k = self._posture_now()                     # 0 = standing ... 1 = lying
        h = h_stand * (1 - 0.65 * k)
        w = h_stand * (0.4 + 0.5 * k)
        y2 = 0.5 + h_stand / 2
        y1 = y2 - h
        bbox = (cx - w / 2, y1, cx + w / 2, y2)
        torso = 5 + 80 * k
        hip_y = y1 + h * (0.55 + 0.05 * k)
        state = self.fall_logic.update(Observation(t=self.t, person=True, bbox=bbox,
                                                   torso_angle=torso, hip_y=hip_y))
        return {"seen": True, "bearing_deg": math.degrees(b), "fall_state": state,
                "reason": self.fall_logic.reason}

    def front_distance(self) -> float:
        if self.person_room() == self.robot_room() and abs(math.degrees(self.bearing_to_person())) <= 15:
            return max(0.0, self.distance_to_person() - 0.25)
        return self.wall_m


def load_rooms(path: str):
    with open(path) as f:
        d = yaml.safe_load(f)
    return d["rooms"], d.get("patrol_order")
