"""
sim_node.py — the simulated world as a ROS 2 node, so the REAL brain_node and
nav_commander can be tested together with no robot, camera, LiDAR or Nav2.

It pretends to be everything that isn't ours:
  * Nav2:     action server  navigate_to_pose  (drives the fake robot to the goal)
  * wheels:   subscribes /cmd_vel
  * LiDAR:    publishes /scan
  * TF:       publishes map -> base_link (robot position)
  * vision:   publishes /grannybot/vision/fall_state, person_seen, person_bearing
              (instead of fall_node; uses the real fall_logic on simulated poses)
  * button:   publishes /grannybot/hardware/button at the scenario's button_at times

  ros2 launch grannybot_sim sim.launch.py scenario:=01_fall_no_answer

To mimic the MentorPi's names (scan_raw, /controller/cmd_vel, base_footprint):
  ros2 run grannybot_sim sim_node --ros-args -p base_frame:=base_footprint \
      -r /scan:=/scan_raw -r /cmd_vel:=/controller/cmd_vel
"""
import math
import os
import threading
import time

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Empty, Float32, String
from tf2_ros import TransformBroadcaster

from .sim_core import Scenario, SimWorld, load_rooms


def share_dir():
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory("grannybot_sim"), "scenarios")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")


class SimNode(Node):
    def __init__(self):
        super().__init__("grannybot_sim")
        self.declare_parameter("scenario", "01_fall_no_answer")
        self.declare_parameter("house", "")
        self.declare_parameter("base_frame", "base_link")   # base_footprint to mimic the MentorPi
        sdir = share_dir()
        name = self.get_parameter("scenario").value
        path = name if name.endswith(".yaml") else os.path.join(sdir, name + ".yaml")
        house = self.get_parameter("house").value or os.path.join(sdir, "house.yaml")
        self.base_frame = self.get_parameter("base_frame").value
        self.sc = Scenario.load(path)
        rooms, _ = load_rooms(house)
        self.world = SimWorld(rooms, self.sc)
        self.lock = threading.Lock()
        self.goal_done = {}            # goal_id -> True when finished
        self.goal_counter = 0
        self.buttons = sorted(self.sc.button_at)
        self.t0 = time.monotonic()
        cb = ReentrantCallbackGroup()

        self.state_pub = self.create_publisher(String, "/grannybot/vision/fall_state", 10)
        self.reason_pub = self.create_publisher(String, "/grannybot/vision/fall_reason", 10)
        self.last_reason = None
        self.seen_pub = self.create_publisher(Bool, "/grannybot/vision/person_seen", 10)
        self.bearing_pub = self.create_publisher(Float32, "/grannybot/vision/person_bearing", 10)
        self.distance_pub = self.create_publisher(Float32, "/grannybot/vision/person_distance", 10)
        self.button_pub = self.create_publisher(Empty, "/grannybot/hardware/button", 10)
        self.scan_pub = self.create_publisher(LaserScan, "/scan", 10)
        self.tf = TransformBroadcaster(self)
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd_vel, 10, callback_group=cb)
        self.nav_server = ActionServer(
            self, NavigateToPose, "navigate_to_pose", execute_callback=self.execute_goal,
            goal_callback=lambda g: GoalResponse.ACCEPT,
            cancel_callback=lambda g: CancelResponse.ACCEPT, callback_group=cb)
        self.create_timer(0.1, self.step, callback_group=cb)
        self.get_logger().info(f"scenario '{self.sc.name}': {self.sc.description.strip()}")

    def on_cmd_vel(self, msg):
        with self.lock:
            self.world.set_cmd_vel(msg.linear.x, msg.angular.z)

    def execute_goal(self, handle):
        p = handle.request.pose.pose
        yaw = 2 * math.atan2(p.orientation.z, p.orientation.w)
        with self.lock:
            self.goal_counter += 1
            gid = self.goal_counter
            self.goal_done[gid] = False
            self.world.start_goal(gid, p.position.x, p.position.y, yaw)
        while rclpy.ok():
            time.sleep(0.05)
            with self.lock:
                if handle.is_cancel_requested:
                    if self.world.goal and self.world.goal[0] == gid:
                        self.world.cancel_goal()
                    handle.canceled()
                    return NavigateToPose.Result()
                if self.goal_done.get(gid):
                    handle.succeed()
                    return NavigateToPose.Result()
                if self.world.goal is None or self.world.goal[0] != gid:   # replaced
                    handle.abort()
                    return NavigateToPose.Result()
        return NavigateToPose.Result()

    def step(self):
        with self.lock:
            finished = self.world.step(0.1)
            if finished:
                self.goal_done[finished[0]] = True
            cam = self.world.camera()
            front = self.world.front_distance()
            person_distance = self.world.distance_to_person()
            x, y, yaw = self.world.rx, self.world.ry, self.world.ryaw
            t = self.world.t
        if cam["reason"] != self.last_reason:
            self.reason_pub.publish(String(data=cam["reason"]))
            self.last_reason = cam["reason"]
        self.state_pub.publish(String(data=cam["fall_state"]))
        self.seen_pub.publish(Bool(data=cam["seen"]))
        if cam["seen"]:
            self.bearing_pub.publish(Float32(data=float(cam["bearing_deg"])))
            self.distance_pub.publish(Float32(data=float(person_distance)))
        while self.buttons and self.buttons[0] <= t:
            self.buttons.pop(0)
            self.get_logger().warn("simulated EMERGENCY BUTTON press")
            self.button_pub.publish(Empty())
        self.publish_scan(front)
        self.publish_tf(x, y, yaw)

    def publish_scan(self, front):
        s = LaserScan()
        s.header.stamp = self.get_clock().now().to_msg()
        s.header.frame_id = self.base_frame
        s.angle_min, s.angle_max = -math.pi, math.pi
        n = 360
        s.angle_increment = 2 * math.pi / n
        s.range_min, s.range_max = 0.05, 12.0
        s.ranges = [front if abs(-math.pi + i * s.angle_increment) <= math.radians(15)
                    else self.world.wall_m for i in range(n)]
        self.scan_pub.publish(s)

    def publish_tf(self, x, y, yaw):
        tf = TransformStamped()
        tf.header.stamp = self.get_clock().now().to_msg()
        tf.header.frame_id, tf.child_frame_id = "map", self.base_frame
        tf.transform.translation.x, tf.transform.translation.y = x, y
        tf.transform.rotation.z, tf.transform.rotation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.tf.sendTransform(tf)


def main():
    rclpy.init()
    node = SimNode()
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
