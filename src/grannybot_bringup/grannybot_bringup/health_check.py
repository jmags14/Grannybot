"""
health_check.py — "is everything running and connected?" in one command.
Run it on the robot (or a laptop on the same network) after starting things up.

  # on the MentorPi: use the same config file as the robot launch (has Hiwonder's topic names)
  ros2 run grannybot_bringup health_check --ros-args --params-file <repo>/src/grannybot_bringup/config/grannybot.yaml
  # anywhere else (defaults: /image_raw, /scan, /cmd_vel, base_link):
  ros2 run grannybot_bringup health_check

Checks that each topic exists, has a publisher, and (for streaming topics) actually
delivers messages; that the motor controller listens to the velocity topic; that Nav2's
action server is up; and that the robot's position (TF map -> base frame) is available.
"""
import sys
import time

import rclpy
import rclpy.time
from rclpy.action import ActionClient
from rclpy.node import Node
from rosidl_runtime_py.utilities import get_action, get_message
from tf2_ros import Buffer, TransformListener

# (topic, who fixes it). <...> names come from parameters.
STREAMING = [
    ("<image_topic>", "camera (EE / Hiwonder camera launch)"),
    ("<scan_topic>", "LiDAR (CpE / Hiwonder navigation launch)"),
    ("/grannybot/vision/fall_state", "fall_node (CS)"),
    ("/grannybot/vision/person_seen", "fall_node (CS)"),
    ("/grannybot/brain/mode", "brain_node (CS)"),
]
PUBLISHED_ON_CHANGE = [
    ("/grannybot/nav/status", "nav_commander (CpE)"),
    ("/grannybot/nav/command", "brain_node (CS)"),
]


class HealthCheck(Node):
    def __init__(self):
        super().__init__("grannybot_health_check")
        for name, default in (("image_topic", "/image_raw"), ("scan_topic", "/scan"),
                              ("cmd_vel_topic", "/cmd_vel"), ("map_frame", "map"),
                              ("base_frame", "base_link"), ("nav_action", "navigate_to_pose")):
            self.declare_parameter(name, default)
        self.declare_parameter("wait_s", 4.0)
        self.names = {k: self.get_parameter(k).value for k in
                      ("image_topic", "scan_topic", "cmd_vel_topic", "map_frame", "base_frame")}
        self.wait = float(self.get_parameter("wait_s").value)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.results = []

    def report(self, ok, what, hint=""):
        self.results.append(ok)
        print(f"  {'OK  ' if ok else 'FAIL'}  {what}" + ("" if ok else f"   -> {hint}"), flush=True)

    def wait_until(self, cond):
        """Spin until cond() is true or wait_s passes (ROS discovery takes a few seconds)."""
        end = time.time() + self.wait
        while time.time() < end:
            if cond():
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return cond()

    def types(self):
        return dict(self.get_topic_names_and_types())

    def check_streaming(self, topic, owner):
        if not self.wait_until(lambda: topic in self.types()):
            self.report(False, f"{topic} exists", f"not found; start {owner} or check the name")
            return
        got = []
        sub = self.create_subscription(get_message(self.types()[topic][0]), topic,
                                       lambda m: got.append(1), 10)
        self.wait_until(lambda: bool(got))
        self.destroy_subscription(sub)
        self.report(bool(got), f"{topic} is publishing", f"exists but silent; is {owner} stuck?")

    def run(self):
        print("GrannyBot health check", flush=True)

        print("Sensors and our nodes:")
        for topic, owner in STREAMING:
            if topic.startswith("<"):
                topic = self.names[topic[1:-1]]
            self.check_streaming(topic, owner)
        for topic, owner in PUBLISHED_ON_CHANGE:
            ok = self.wait_until(lambda t=topic: self.count_publishers(t) > 0)
            self.report(ok, f"{topic} has a publisher", f"start {owner}")

        print("Motion:")
        vel = self.names["cmd_vel_topic"]
        self.report(self.wait_until(lambda: self.count_subscribers(vel) > 0),
                    f"{vel} has a listener (motors)",
                    "robot base driver not running (Hiwonder bringup)")
        action = self.get_parameter("nav_action").value
        client = ActionClient(self, get_action("nav2_msgs/action/NavigateToPose"), action)
        self.report(client.wait_for_server(timeout_sec=self.wait), f"Nav2 action '{action}' ready",
                    "start Hiwonder's navigation launch with your saved map")
        mf, bf = self.names["map_frame"], self.names["base_frame"]
        ok = self.wait_until(lambda: self.tf_buffer.can_transform(mf, bf, rclpy.time.Time()))
        self.report(ok, f"robot position (TF {mf} -> {bf})",
                    "no localization: set the initial pose in RViz ('2D Pose Estimate')")

        passed = sum(self.results)
        print(f"\n{passed}/{len(self.results)} checks passed", flush=True)
        return passed == len(self.results)


def main():
    rclpy.init()
    node = HealthCheck()
    ok = node.run()
    node.destroy_node()
    rclpy.try_shutdown()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
