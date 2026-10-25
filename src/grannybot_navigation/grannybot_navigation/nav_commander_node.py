"""
nav_commander_node.py — ROS 2 wrapper around nav_logic.NavLogic.  [CpE owns this]

Subscribes:
  /grannybot/nav/command           std_msgs/String   patrol | stop | face | approach | goto:<room>
  /grannybot/vision/person_bearing std_msgs/Float32  deg, + = person LEFT of camera center
  <scan_topic>                     sensor_msgs/LaserScan
Publishes:
  /grannybot/nav/status            std_msgs/String   IDLE | MOVING | ARRIVED | FAILED | LOST
  /grannybot/nav/room              std_msgs/String   room the robot is in (on change + every 2 s)
  <cmd_vel_topic>                  geometry_msgs/Twist   (face / approach / look-around only)
Action client:
  <nav_action>  nav2_msgs/action/NavigateToPose  (Nav2 on the robot, or grannybot_sim's fake Nav2)
TF:
  <map_frame> -> <base_frame>   robot position, used to report which room the robot is in

All behavior lives in nav_logic.py. This file only converts between ROS messages and that logic.
"""
import math
import os
import threading
import time

import rclpy
import rclpy.time
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Float32, String
from tf2_ros import Buffer, TransformListener

from .nav_logic import NavConfig, NavLogic


def front_distance(msg: LaserScan, offset_deg: float, half_width_deg: float = 15.0) -> float:
    """Closest valid LiDAR range within +-half_width of the robot's front."""
    off = math.radians(offset_deg)
    half = math.radians(half_width_deg)
    best = float("inf")
    for i, r in enumerate(msg.ranges):
        a = msg.angle_min + i * msg.angle_increment - off
        a = math.atan2(math.sin(a), math.cos(a))
        if abs(a) <= half and msg.range_min < r < msg.range_max:
            best = min(best, r)
    return best


def load_rooms(path: str):
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("frame", "map"), data["rooms"], data.get("patrol_order")


class NavCommander(Node):
    def __init__(self):
        super().__init__("grannybot_nav_commander")
        p = self.declare_parameter
        p("rooms_file", "")
        p("scan_topic", "/scan")
        p("cmd_vel_topic", "/cmd_vel")
        p("nav_action", "navigate_to_pose")
        p("scan_front_offset_deg", 0.0)    # set so 0 deg after offset = robot's front
        p("map_frame", "map")
        p("base_frame", "base_link")
        for name, default in vars(NavConfig()).items():
            p(name, default)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        rooms_file = g("rooms_file")
        if not rooms_file:
            from ament_index_python.packages import get_package_share_directory
            rooms_file = os.path.join(get_package_share_directory("grannybot_navigation"),
                                      "config", "rooms.yaml")
        self.frame, rooms, order = load_rooms(rooms_file)
        cfg = NavConfig(**{k: type(v)(g(k)) for k, v in vars(NavConfig()).items()})
        self.offset = float(g("scan_front_offset_deg"))

        self.status_pub = self.create_publisher(String, "/grannybot/nav/status", 10)
        self.room_pub = self.create_publisher(String, "/grannybot/nav/room", 10)
        self.cmd_pub = self.create_publisher(Twist, g("cmd_vel_topic"), 10)
        self.nav = ActionClient(self, NavigateToPose, g("nav_action"))
        self.lock = threading.Lock()
        self.goal_handles = {}
        self.next_goal_id = 0
        self.failed_goals = []      # goals that couldn't be sent; reported on the next tick

        self.logic = NavLogic(rooms, order, self.send_goal, self.cancel_goal, self.cmd_vel,
                              self.publish_status, self.publish_room, cfg)
        self.create_subscription(String, "/grannybot/nav/command", self.on_command, 10)
        self.create_subscription(Float32, "/grannybot/vision/person_bearing", self.on_bearing, 10)
        self.create_subscription(LaserScan, g("scan_topic"), self.on_scan, qos_profile_sensor_data)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.map_frame, self.base_frame = g("map_frame"), g("base_frame")
        self.create_timer(0.1, self.on_tick)
        self.create_timer(0.5, self.update_pose)
        self.create_timer(2.0, self.repeat_room)     # so nodes started later still learn the room
        self.get_logger().info(f"rooms: {list(rooms)} (from {rooms_file})")

    @staticmethod
    def now() -> float:
        return time.monotonic()

    # ---- outputs used by NavLogic -------------------------------------------
    def publish_status(self, s):
        self.status_pub.publish(String(data=s))
        self.get_logger().info(f"status {s}")

    def publish_room(self, room):
        self.room_pub.publish(String(data=room))

    def cmd_vel(self, v, w):
        t = Twist()
        t.linear.x, t.angular.z = float(v), float(w)
        self.cmd_pub.publish(t)

    def send_goal(self, room, xyz):
        self.next_goal_id += 1
        gid = self.next_goal_id
        if not self.nav.wait_for_server(timeout_sec=2.0):
            self.get_logger().error("Nav2 action server not available")
            self.failed_goals.append(gid)
            return gid
        x, y, yaw = xyz
        goal = NavigateToPose.Goal()
        ps = PoseStamped()
        ps.header.frame_id = self.frame
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose.position.x, ps.pose.position.y = float(x), float(y)
        ps.pose.orientation.z, ps.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        goal.pose = ps
        self.get_logger().info(f"goal {gid}: {room} ({x:.2f}, {y:.2f})")
        fut = self.nav.send_goal_async(goal)
        fut.add_done_callback(lambda f, gid=gid: self.on_goal_accepted(gid, f))
        return gid

    def on_goal_accepted(self, gid, future):
        handle = future.result()
        if not handle.accepted:
            with self.lock:
                self.logic.on_goal_result(gid, False, self.now())
            return
        self.goal_handles[gid] = handle
        handle.get_result_async().add_done_callback(lambda f, gid=gid: self.on_goal_done(gid, f))

    def on_goal_done(self, gid, future):
        self.goal_handles.pop(gid, None)
        status = future.result().status
        if status == GoalStatus.STATUS_CANCELED:
            return
        with self.lock:
            self.logic.on_goal_result(gid, status == GoalStatus.STATUS_SUCCEEDED, self.now())

    def cancel_goal(self):
        for gid, h in list(self.goal_handles.items()):
            h.cancel_goal_async()
            self.goal_handles.pop(gid, None)

    # ---- inputs ------------------------------------------------------------------
    def on_command(self, msg):
        self.get_logger().info(f"command: {msg.data}")
        with self.lock:
            self.logic.on_command(msg.data, self.now())

    def on_bearing(self, msg):
        with self.lock:
            self.logic.on_bearing(msg.data, self.now())

    def on_scan(self, msg):
        with self.lock:
            self.logic.on_front_distance(front_distance(msg, self.offset))

    def repeat_room(self):
        if self.logic.current_room:
            self.room_pub.publish(String(data=self.logic.current_room))

    def update_pose(self):
        try:
            tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, rclpy.time.Time())
        except Exception:
            return                      # no localization yet (e.g. Nav2 not started)
        with self.lock:
            self.logic.on_pose(tf.transform.translation.x, tf.transform.translation.y)

    def on_tick(self):
        with self.lock:
            while self.failed_goals:
                self.logic.on_goal_result(self.failed_goals.pop(0), False, self.now())
            self.logic.tick(self.now())


def main():
    rclpy.init()
    node = NavCommander()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():                      # ROS may already be shut down by Ctrl-C/launch
            node.cmd_vel(0.0, 0.0)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
