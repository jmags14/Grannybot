"""
fall_node.py — ROS 2 node: camera image in, fall state out.

Subscribes:
  <image_topic>                       sensor_msgs/Image   (robot camera, set by parameter)
Publishes:
  /grannybot/vision/fall_state        std_msgs/String     NO_PERSON | UPRIGHT | POSSIBLE_FALL | FALLEN
  /grannybot/vision/fall_reason       std_msgs/String     e.g. "sudden fall, down for 3s" (on change)
  /grannybot/vision/person_seen       std_msgs/Bool
  /grannybot/vision/person_bearing    std_msgs/Float32    deg, + = person is LEFT of center (only when seen)
  /grannybot/vision/debug_image       sensor_msgs/Image   annotated frame (watch with rqt_image_view)

Parameters: image_topic, detector (pose|mediapipe), weights, every_n, imgsz,
            camera_hfov_deg, publish_debug
Run:  ros2 run grannybot_vision fall_node --ros-args -p image_topic:=/your/camera/topic
"""
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String

from .detectors import make_detector
from .fall_logic import FallLogic
from .pipeline import draw, observation_from


class FallNode(Node):
    def __init__(self):
        super().__init__("grannybot_fall_detector")
        p = self.declare_parameter
        p("image_topic", "/image_raw")
        p("detector", "pose")
        p("weights", "")
        p("every_n", 2)
        p("imgsz", 320)
        p("camera_hfov_deg", 120.0)      # MentorPi camera is very wide; measure yours
        p("publish_debug", True)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        self.every_n = int(g("every_n"))
        self.hfov = float(g("camera_hfov_deg"))
        self.publish_debug = bool(g("publish_debug"))
        self.detector = make_detector(g("detector"), g("weights") or None, int(g("imgsz")))
        self.logic = FallLogic()
        self.bridge = CvBridge()
        self.count = 0
        self.last_state = None

        self.state_pub = self.create_publisher(String, "/grannybot/vision/fall_state", 10)
        self.reason_pub = self.create_publisher(String, "/grannybot/vision/fall_reason", 10)
        self.last_reason = None
        self.seen_pub = self.create_publisher(Bool, "/grannybot/vision/person_seen", 10)
        self.bearing_pub = self.create_publisher(Float32, "/grannybot/vision/person_bearing", 10)
        self.debug_pub = self.create_publisher(Image, "/grannybot/vision/debug_image", 2)
        self.create_subscription(Image, g("image_topic"), self.on_image, qos_profile_sensor_data)
        self.get_logger().info(f"detector={g('detector')} listening on {g('image_topic')}")

    def on_image(self, msg: Image):
        self.count += 1
        if self.count % self.every_n:
            return
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        if t == 0.0:
            t = self.get_clock().now().nanoseconds * 1e-9
        det = self.detector.detect(frame)
        state = self.logic.update(observation_from(det, t))

        if self.logic.reason != self.last_reason:      # publish before the state that uses it
            self.reason_pub.publish(String(data=self.logic.reason))
            self.last_reason = self.logic.reason
        self.state_pub.publish(String(data=state))
        self.seen_pub.publish(Bool(data=det is not None))
        if det:
            cx = (det["bbox"][0] + det["bbox"][2]) / 2
            self.bearing_pub.publish(Float32(data=float((0.5 - cx) * self.hfov)))
        if self.publish_debug and self.debug_pub.get_subscription_count() > 0:
            out = draw(frame.copy(), det, state, self.logic.reason)
            self.debug_pub.publish(self.bridge.cv2_to_imgmsg(out, encoding="bgr8"))
        if state != self.last_state:
            self.get_logger().info(f"{state}: {self.logic.reason}")
            self.last_state = state


def main():
    rclpy.init()
    node = FallNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
