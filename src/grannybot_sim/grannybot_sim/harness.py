"""
harness.py — runs the REAL brain (brain.py) and REAL navigation logic (nav_logic.py) against
the simulated world, all in one Python process, with simulated time. A 3-minute scenario
runs in well under a second, so it works as an automated end-to-end test.

Messages between the pieces go through a small queue, the way ROS topics would, so one
component never calls straight into another in the middle of handling a message.

  python tools/run_sim.py                        # run every scenario and print timelines
  python -m pytest tests/test_end_to_end.py      # same scenarios as pass/fail tests
"""
from __future__ import annotations

import glob
import os
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from grannybot_brain.brain import Brain, BrainConfig
from grannybot_navigation.nav_logic import NavConfig, NavLogic

from .sim_core import Scenario, SimWorld, load_rooms

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIO_DIR = os.path.join(os.path.dirname(HERE), "scenarios")
HOUSE = os.path.join(SCENARIO_DIR, "house.yaml")


@dataclass
class SimResult:
    scenario: Scenario
    modes: List[Tuple[float, str, str]] = field(default_factory=list)       # t, mode, why
    alerts: List[Tuple[float, str, Optional[str]]] = field(default_factory=list)  # t, reason, room
    nav_commands: List[Tuple[float, str]] = field(default_factory=list)
    nav_status: List[Tuple[float, str]] = field(default_factory=list)
    checkins: List[float] = field(default_factory=list)
    said: List[Tuple[float, str]] = field(default_factory=list)
    fall_states: List[Tuple[float, str]] = field(default_factory=list)      # changes only

    def first(self, mode: str) -> Optional[float]:
        return next((t for t, m, _ in self.modes if m == mode), None)

    def timeline(self) -> str:
        rows = [(t, "MODE", f"{m:9s} {why}") for t, m, why in self.modes]
        rows += [(t, "NAV", c) for t, c in self.nav_commands]
        rows += [(t, "STATUS", s) for t, s in self.nav_status if s != "MOVING"]
        rows += [(t, "VISION", s) for t, s in self.fall_states]
        rows += [(t, "ASK", "Are you okay?") for t in self.checkins]
        rows += [(t, "CALL", f"{r} (room={room})") for t, r, room in self.alerts]
        rows.sort(key=lambda r: r[0])
        return "\n".join(f"{t:7.1f}s  {kind:7s} {text}" for t, kind, text in rows)


class SimSystem:
    def __init__(self, scenario: Scenario, house: str = HOUSE, dt: float = 0.1,
                 brain_cfg: Optional[BrainConfig] = None, nav_cfg: Optional[NavConfig] = None):
        rooms, order = load_rooms(house)
        self.sc, self.dt, self.t = scenario, dt, 0.0
        self.world = SimWorld(rooms, scenario)
        self.res = SimResult(scenario)
        self.q: deque = deque()
        self._goal_ids = 0
        self._checkin_due: Optional[float] = None
        self._buttons = sorted(scenario.button_at)
        self._last_fall_state = None

        self.nav = NavLogic(rooms, order, self._send_goal, self._cancel_goal, self._cmd_vel,
                            self._nav_status, self._nav_room, nav_cfg)
        self.brain = Brain(nav=self._brain_nav, start_checkin=self._start_checkin,
                           alert=self._alert, say=lambda s: self.res.said.append((self.t, s)),
                           cfg=brain_cfg,
                           on_event=lambda t, m, why: self.res.modes.append((t, m, why)))

    # ---- "topics": everything is queued and delivered after the current step ----
    def post(self, fn, *args):
        self.q.append((fn, args))

    def _flush(self):
        n = 0
        while self.q and n < 1000:
            fn, args = self.q.popleft()
            fn(*args)
            n += 1

    # brain -> nav
    def _brain_nav(self, cmd):
        self.res.nav_commands.append((self.t, cmd))
        self.post(lambda c=cmd: self.nav.on_command(c, self.t))

    # nav -> fake Nav2 / wheels
    def _send_goal(self, room, xyz):
        self._goal_ids += 1
        self.world.start_goal(self._goal_ids, *xyz)
        return self._goal_ids

    def _cancel_goal(self):
        self.world.cancel_goal()

    def _cmd_vel(self, v, w):
        self.world.set_cmd_vel(v, w)

    # nav -> brain
    def _nav_status(self, s):
        self.res.nav_status.append((self.t, s))
        self.post(lambda: self.brain.on_nav_status(s, self.t))

    def _nav_room(self, room):
        self.post(lambda: self.brain.on_room(room))

    # brain -> voice / phone (faked)
    def _start_checkin(self):
        self.res.checkins.append(self.t)
        self._checkin_due = self.t + self.sc.checkin_delay_s

    def _alert(self, reason, room):
        self.res.alerts.append((self.t, reason, room))

    # ---- main loop -------------------------------------------------------
    def run(self) -> SimResult:
        steps = int(self.sc.duration_s / self.dt)
        for _ in range(steps):
            finished = self.world.step(self.dt)
            self.t = self.world.t
            if finished:
                gid, ok = finished
                self.post(lambda g=gid, o=ok: self.nav.on_goal_result(g, o, self.t))

            cam = self.world.camera()          # camera + vision node, 10 frames/s
            if cam["fall_state"] != self._last_fall_state:
                self.res.fall_states.append((self.t, cam["fall_state"]))
                self._last_fall_state = cam["fall_state"]
            self.post(lambda c=cam: self.brain.on_vision(c["fall_state"], c["seen"], self.t, c["reason"]))
            if cam["seen"]:
                self.post(lambda b=cam["bearing_deg"]: self.nav.on_bearing(b, self.t))
            self.post(lambda d=self.world.front_distance(): self.nav.on_front_distance(d))
            self.post(lambda x=self.world.rx, y=self.world.ry: self.nav.on_pose(x, y))

            while self._buttons and self._buttons[0] <= self.t:      # emergency button
                self._buttons.pop(0)
                self.post(lambda: self.brain.on_button(self.t))
            if self._checkin_due is not None and self.t >= self._checkin_due:
                self._checkin_due = None
                ans = self.sc.checkin_answer
                self.post(lambda a=ans: self.brain.on_checkin_result(a, self.t))

            self.post(lambda: self.brain.tick(self.t))
            self.post(lambda: self.nav.tick(self.t))
            self._flush()
        return self.res


def all_scenarios() -> List[str]:
    return sorted(p for p in glob.glob(os.path.join(SCENARIO_DIR, "*.yaml"))
                  if os.path.basename(p) != "house.yaml")


def check(res: SimResult) -> List[str]:
    """Compare a result against the scenario's `expect:` block. Returns a list of problems."""
    e, problems = res.scenario.expect, []
    if "alert" in e:
        if e["alert"] and not res.alerts:
            problems.append("expected a phone call, none was made")
        if not e["alert"] and res.alerts:
            problems.append(f"expected NO phone call, got: {res.alerts[0][1]}")
    if e.get("alert_room") and res.alerts and res.alerts[0][2] != e["alert_room"]:
        problems.append(f"call said room={res.alerts[0][2]}, expected {e['alert_room']}")
    if e.get("max_alerts") is not None and len(res.alerts) > e["max_alerts"]:
        problems.append(f"{len(res.alerts)} calls, expected at most {e['max_alerts']}")
    if e.get("alert_within_s") and res.alerts:
        t0 = min([ev["t"] for ev in res.scenario.events if ev["do"] in ("fall", "lie")]
                 + res.scenario.button_at or [0.0])
        if res.alerts[0][0] - t0 > e["alert_within_s"]:
            problems.append(f"call came {res.alerts[0][0] - t0:.0f}s after the event, "
                            f"expected within {e['alert_within_s']}s")
    if e.get("reason_contains") and res.alerts and e["reason_contains"] not in res.alerts[0][1]:
        problems.append(f"call reason '{res.alerts[0][1]}' missing '{e['reason_contains']}'")
    for m in e.get("modes_seen", []):
        if res.first(m) is None:
            problems.append(f"robot never entered {m}")
    if e.get("checkin") is not None and bool(res.checkins) != bool(e["checkin"]):
        problems.append("expected a check-in" if e["checkin"] else "expected NO check-in")
    if e.get("final_mode") and res.modes and res.modes[-1][1] != e["final_mode"]:
        problems.append(f"ended in {res.modes[-1][1]}, expected {e['final_mode']}")
    return problems
