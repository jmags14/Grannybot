"""
e2e_check.py — watches a running system and reports PASS/FAIL against a scenario's `expect:`.
Works the same on the simulator and on the real robot (watching the real topics).

  ros2 run grannybot_sim e2e_check --ros-args -p scenario:=01_fall_no_answer -p timeout_s:=200

It listens to /grannybot/brain/mode, /grannybot/nav/command and /grannybot/nav/room and
prints a timeline. Exit code 0 = pass, 1 = fail (so it can be used in scripts).
"""
import os
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .sim_core import Scenario
from .sim_node import share_dir


class E2ECheck(Node):
    def __init__(self):
        super().__init__("grannybot_e2e_check")
        self.declare_parameter("scenario", "01_fall_no_answer")
        self.declare_parameter("timeout_s", 0.0)
        name = self.get_parameter("scenario").value
        path = name if name.endswith(".yaml") else os.path.join(share_dir(), name + ".yaml")
        self.sc = Scenario.load(path)
        self.timeout = self.get_parameter("timeout_s").value or self.sc.duration_s + 20
        self.t0 = time.monotonic()
        self.modes, self.cmds, self.room = [], [], None
        self.create_subscription(String, "/grannybot/brain/mode", self.on_mode, 50)
        self.create_subscription(String, "/grannybot/nav/command", self.on_cmd, 50)
        self.create_subscription(String, "/grannybot/nav/room", self.on_room, 10)

    def t(self):
        return time.monotonic() - self.t0

    def on_mode(self, msg):
        if not self.modes or self.modes[-1][1] != msg.data:
            self.modes.append((self.t(), msg.data))
            print(f"{self.t():7.1f}s  MODE  {msg.data}   (room={self.room})", flush=True)

    def on_cmd(self, msg):
        self.cmds.append((self.t(), msg.data))
        print(f"{self.t():7.1f}s  NAV   {msg.data}", flush=True)

    def on_room(self, msg):
        self.room = msg.data

    def done(self):
        e = self.sc.expect
        if self.t() > self.timeout:
            return True
        if e.get("alert") and any(m == "ALERT" for _, m in self.modes):
            return True
        return False

    def verdict(self):
        e, problems = self.sc.expect, []
        seen = {m for _, m in self.modes}
        if e.get("alert") is True and "ALERT" not in seen:
            problems.append("never reached ALERT (no phone call)")
        if e.get("alert") is False and "ALERT" in seen:
            problems.append("reached ALERT but no call was expected")
        if e.get("alert_room") and "ALERT" in seen and self.room != e["alert_room"]:
            problems.append(f"room was {self.room}, expected {e['alert_room']}")
        if e.get("checkin") is False and "CHECK_IN" in seen:
            problems.append("checked in but shouldn't have")
        for m in e.get("modes_seen", []):
            if m not in seen:
                problems.append(f"never entered {m}")
        return problems


def main():
    rclpy.init()
    node = E2ECheck()
    print(f"watching for scenario '{node.sc.name}' (up to {node.timeout:.0f}s)...", flush=True)
    while rclpy.ok() and not node.done():
        rclpy.spin_once(node, timeout_sec=0.2)
    problems = node.verdict()
    print("PASS" if not problems else "FAIL: " + "; ".join(problems), flush=True)
    node.destroy_node()
    rclpy.try_shutdown()
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
