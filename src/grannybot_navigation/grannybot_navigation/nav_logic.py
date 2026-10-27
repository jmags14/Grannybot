"""
nav_logic.py — navigation behaviors as a plain state machine. No ROS, so it's testable
(tests/test_nav_logic.py) and the simulator can drive it (src/grannybot_sim).

Commands (from the brain on /grannybot/nav/command):
  patrol      visit rooms in order; at each room pause and slowly turn to look around; repeat
  goto:<room> drive to one room
  stop        cancel everything, zero velocity
  face        turn in place until the person is centered in the camera
  approach    face the person, then drive forward until ~approach_distance_m in front

Outputs (functions you pass in):
  send_goal(room, (x, y, yaw)) -> goal_id    ask Nav2 to drive to a pose
  cancel_goal()                              cancel the current Nav2 goal
  cmd_vel(linear_mps, angular_radps)         direct velocity (face / approach / look-around)
  status(s)                                  IDLE | MOVING | ARRIVED | FAILED | LOST
  room_reached(room)                         room the robot is in (for the alert message)

Inputs: on_command, on_bearing, on_front_distance, on_pose, on_goal_result, tick.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

IDLE, PATROL, GOTO, FACE, APPROACH = "idle", "patrol", "goto", "face", "approach"


@dataclass
class NavConfig:
    patrol_pause_s: float = 10.0          # time spent looking around at each room
    look_around_speed: float = 0.35       # rad/s while pausing (camera sees more of the room)
    approach_distance_m: float = 1.0      # stop this far from whatever is in front
    approach_speed: float = 0.12          # m/s near the person (slow on purpose)
    approach_speed_far: float = 0.30      # m/s when still far away
    slow_zone_m: float = 1.0              # start slowing down this far before the stop distance
    approach_timeout_s: float = 30.0
    face_timeout_s: float = 10.0
    max_turn: float = 0.6                 # rad/s
    turn_gain: float = 1.5
    face_tolerance_deg: float = 6.0       # "centered"
    drive_tolerance_deg: float = 15.0     # only drive forward when roughly centered
    scan_stale_s: float = 1.0
    bearing_stale_s: float = 1.5          # no bearing for this long => person LOST


class NavLogic:
    def __init__(self, rooms: Dict[str, Sequence[float]], patrol_order: Optional[List[str]],
                 send_goal: Callable[[str, Tuple[float, float, float]], int],
                 cancel_goal: Callable[[], None],
                 cmd_vel: Callable[[float, float], None],
                 status: Callable[[str], None],
                 room_reached: Callable[[str], None],
                 cfg: Optional[NavConfig] = None):
        self.rooms = {k: tuple(float(v) for v in xyz) for k, xyz in rooms.items()}
        self.order = list(patrol_order or self.rooms)
        self._send_goal, self._cancel_goal, self._cmd_vel = send_goal, cancel_goal, cmd_vel
        self._status, self._room_reached = status, room_reached
        self.cfg = cfg or NavConfig()
        self.mode = IDLE
        self.last_status = None
        self.goal_id: Optional[int] = None
        self.goal_room: Optional[str] = None
        self.patrol_i = 0
        self.pause_until: Optional[float] = None
        self.mode_t = 0.0
        self.bearing: Optional[float] = None
        self.bearing_t = -1e9
        self.front_m = float("nan")
        self.front_t = -1e9
        self.person_distance_m = None
        self.person_distance_t = -1e9
        self.current_room: Optional[str] = None

    # ---- small helpers ------------------------------------------------
    def status(self, s: str) -> None:
        self.last_status = s
        self._status(s)

    def _stop_motion(self) -> None:
        self._cmd_vel(0.0, 0.0)

    def _cancel(self) -> None:
        if self.goal_id is not None:
            self._cancel_goal()
            self.goal_id = None
        self.pause_until = None

    def _go(self, room: str) -> None:
        if room not in self.rooms:
            self.status("FAILED")
            return
        self.goal_room = room
        self.status("MOVING")
        self.goal_id = self._send_goal(room, self.rooms[room])

    def _turn_rate(self, bearing_deg: float) -> float:
        w = self.cfg.turn_gain * math.radians(bearing_deg)
        return max(-self.cfg.max_turn, min(self.cfg.max_turn, w))

    # ---- inputs -----------------------------------------------------------
    def on_command(self, cmd: str, now: float) -> None:
        cmd = cmd.strip()
        self._cancel()
        self._stop_motion()
        self.mode_t = now
        if cmd == "stop":
            self.mode = IDLE
            self.status("IDLE")
        elif cmd == "patrol":
            self.mode = PATROL
            self._go(self.order[self.patrol_i % len(self.order)])
        elif cmd.startswith("goto:"):
            self.mode = GOTO
            self._go(cmd.split(":", 1)[1])
        elif cmd in (FACE, APPROACH):
            self.mode = cmd
            self.status("MOVING")
        else:
            self.mode = IDLE
            self.status("FAILED")

    def on_bearing(self, deg: float, now: float) -> None:
        self.bearing, self.bearing_t = float(deg), now

    def on_front_distance(self, meters: float, now: float) -> None:
        self.front_m, self.front_t = float(meters), now

    def on_person_distance(self, meters: float, now: float) -> None:
        """Optional independently associated target range; LiDAR obstacles are not target ranges."""
        self.person_distance_m, self.person_distance_t = float(meters), now

    def on_pose(self, x: float, y: float) -> None:
        """Robot position on the map. Reports the nearest room whenever it changes, so the
        phone call names where the robot actually is, even if it stopped between rooms."""
        room = min(self.rooms, key=lambda r: (self.rooms[r][0] - x) ** 2 + (self.rooms[r][1] - y) ** 2)
        if room != self.current_room:
            self.current_room = room
            self._room_reached(room)

    def on_goal_result(self, goal_id: int, succeeded: bool, now: float) -> None:
        if goal_id != self.goal_id:          # result of an old/canceled goal
            return
        self.goal_id = None
        if succeeded:
            if self.goal_room != self.current_room:
                self.current_room = self.goal_room
                self._room_reached(self.goal_room)
            self.status("ARRIVED")
        else:
            self.status("FAILED")
        if self.mode == PATROL:
            self.patrol_i += 1
            self.pause_until = now + self.cfg.patrol_pause_s
        elif self.mode == GOTO:
            self.mode = IDLE

    def tick(self, now: float) -> None:
        c = self.cfg
        if self.mode == PATROL:
            if self.pause_until is not None:
                if now >= self.pause_until:
                    self._stop_motion()
                    self.pause_until = None
                    self._go(self.order[self.patrol_i % len(self.order)])
                else:
                    self._cmd_vel(0.0, c.look_around_speed)
            return
        if self.mode not in (FACE, APPROACH):
            return

        in_mode = now - self.mode_t
        if self.bearing is None or now - self.bearing_t > c.bearing_stale_s:
            self._finish("LOST")
            return
        b = self.bearing
        if self.mode == FACE:
            if abs(b) <= c.face_tolerance_deg:
                self._finish("ARRIVED")
            elif in_mode > c.face_timeout_s:
                self._finish("FAILED")
            else:
                self._cmd_vel(0.0, self._turn_rate(b))
            return
        # APPROACH
        if now - self.front_t > c.scan_stale_s or not math.isfinite(self.front_m) or self.front_m <= 0:
            self._finish("FAILED")
        elif (self.person_distance_m is not None
              and now - self.person_distance_t <= c.bearing_stale_s
              and math.isfinite(self.person_distance_m)
              and 0 < self.person_distance_m <= c.approach_distance_m
              and abs(b) <= c.drive_tolerance_deg):
            self._finish("ARRIVED")
        elif self.front_m <= c.approach_distance_m:
            # Obstruction or unverified target: stop and let the brain check in.
            self._finish("FAILED")
        elif in_mode > c.approach_timeout_s:
            self._finish("FAILED")
        else:
            v = 0.0
            if abs(b) <= c.drive_tolerance_deg:
                left = self.front_m - c.approach_distance_m      # meters still to go
                k = max(0.0, min(1.0, left / c.slow_zone_m))
                v = c.approach_speed + k * (c.approach_speed_far - c.approach_speed)
            self._cmd_vel(v, self._turn_rate(b))

    def _finish(self, s: str) -> None:
        self._stop_motion()
        self.mode = IDLE
        self.status(s)
