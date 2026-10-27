"""
brain_node.py — ROS 2 wrapper around brain.Brain.

Subscribes:
  /grannybot/vision/fall_state      std_msgs/String
  /grannybot/vision/person_seen     std_msgs/Bool
  /grannybot/vision/fall_reason     std_msgs/String   why vision thinks she fell (goes in the alert)
  /grannybot/nav/status             std_msgs/String   IDLE | MOVING | ARRIVED | FAILED | LOST
  /grannybot/nav/room               std_msgs/String   e.g. "kitchen"
  /grannybot/hardware/button        std_msgs/Empty    emergency button pressed
Publishes:
  /grannybot/brain/mode             std_msgs/String   PATROL | WATCH | APPROACH | CHECK_IN | ALERT
  /grannybot/nav/command            std_msgs/String   patrol | stop | face | approach | goto:<room>

Parameters:
  no_voice              skip the real microphone/speaker check-in (use fake_checkin_answer)
  fake_checkin_answer   OK | HELP | NO_RESPONSE, used when no_voice is true (testing/sim)
  fake_checkin_delay_s  how long the fake check-in "takes"
  dry_run_alert         print the alert instead of placing a real call (testing/sim)
  log_dir               events are appended to <log_dir>/events.csv (useful for the paper)
"""
import csv
import os
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Empty, String

from .alert import send_alert
from .brain import NO_RESPONSE, Brain, BrainConfig
from .paths import load_env


class BrainNode(Node):
    def __init__(self):
        super().__init__("grannybot_brain")
        self.declare_parameter("no_voice", False)
        self.declare_parameter("fake_checkin_answer", NO_RESPONSE)
        self.declare_parameter("fake_checkin_delay_s", 5.0)
        self.declare_parameter("dry_run_alert", False)
        self.declare_parameter("log_dir", os.path.expanduser("~/grannybot_logs"))
        for name, default in vars(BrainConfig()).items():
            self.declare_parameter(name, default)
        load_env()
        self.lock = threading.Lock()
        self.no_voice = bool(self.get_parameter("no_voice").value)
        self.fake_answer = str(self.get_parameter("fake_checkin_answer").value).upper()
        self.fake_delay = float(self.get_parameter("fake_checkin_delay_s").value)
        self.dry_run = bool(self.get_parameter("dry_run_alert").value)
        self.listener = None

        log_dir = self.get_parameter("log_dir").value
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "events.csv")

        self.mode_pub = self.create_publisher(String, "/grannybot/brain/mode", 10)
        self.nav_pub = self.create_publisher(String, "/grannybot/nav/command", 10)
        self.brain = Brain(nav=self.send_nav, start_checkin=self.start_checkin,
                           alert=self.start_alert, say=self.say, on_event=self.on_event,
                           cfg=BrainConfig(**{k: self.get_parameter(k).value
                                              for k in vars(BrainConfig())}))

        self.person_seen = False
        self.fall_reason = ""
        self.create_subscription(Bool, "/grannybot/vision/person_seen", self.on_seen, 10)
        self.create_subscription(String, "/grannybot/vision/fall_reason", self.on_reason, 10)
        self.create_subscription(String, "/grannybot/vision/fall_state", self.on_fall_state, 10)
        self.create_subscription(String, "/grannybot/nav/status", self.on_nav_status, 10)
        self.create_subscription(String, "/grannybot/nav/room", self.on_room, 10)
        self.create_subscription(Empty, "/grannybot/hardware/button", self.on_button, 10)
        self.create_timer(0.5, self.on_tick)

    @staticmethod
    def now() -> float:
        return time.monotonic()

    # ---- outputs the brain calls ---------------------------------------
    def send_nav(self, cmd: str):
        self.nav_pub.publish(String(data=cmd))

    def say(self, text: str):
        if self.no_voice:
            self.get_logger().info(f"[say] {text}")
            return
        from .checkin import speak
        threading.Thread(target=speak, args=(text,), daemon=True).start()

    def start_checkin(self):
        incident = self.brain._mode_since
        def work():
            try:
                result = self.run_checkin()
            except Exception as exc:
                self.get_logger().error(f"Check-in failed: {exc}")
                result = NO_RESPONSE
            with self.lock:
                if self.brain._mode_since == incident:
                    self.brain.on_checkin_result(result, self.now())
        threading.Thread(target=work, daemon=True).start()

    def run_checkin(self):
        if self.no_voice:
            self.get_logger().info(f"[fake check-in] waiting {self.fake_delay:.0f}s, "
                                   f"answer will be {self.fake_answer}")
            time.sleep(self.fake_delay)
            result = self.fake_answer
        else:
            from .checkin import Listener, ask_are_you_okay
            if self.listener is None:
                self.listener = Listener()
            result = ask_are_you_okay(self.listener)
        return result

    def start_alert(self, reason: str, room):
        attempt = self.brain.alert_attempt_id
        def work():
            try:
                if self.dry_run:
                    self.get_logger().warn(f"[DRY RUN] would call caregiver: {reason} (room={room})")
                    result = {"dry_run": True, "reason": reason, "room": room}
                else:
                    result = send_alert(reason, room)
            except Exception as exc:
                result = {"error": str(exc)}
            from .alert import notification_delivered
            with self.lock:
                self.brain.on_alert_result(notification_delivered(result), self.now(), attempt)
            self.write_log("ALERT_RESULT", str(result))
        threading.Thread(target=work, daemon=True).start()

    def on_event(self, t: float, mode: str, why: str):
        self.mode_pub.publish(String(data=mode))
        self.get_logger().info(f"MODE {mode}: {why}")
        self.write_log(mode, why)

    def write_log(self, mode: str, why: str):
        new = not os.path.exists(self.log_path)
        with open(self.log_path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["wall_time", "mode", "detail"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), mode, why])

    # ---- inputs ------------------------------------------------------------
    def on_seen(self, msg):
        self.person_seen = msg.data

    def on_reason(self, msg):
        self.fall_reason = msg.data

    def on_fall_state(self, msg):
        with self.lock:
            self.brain.on_vision(msg.data, self.person_seen, self.now(), self.fall_reason)

    def on_nav_status(self, msg):
        with self.lock:
            self.brain.on_nav_status(msg.data, self.now())

    def on_room(self, msg):
        with self.lock:
            self.brain.on_room(msg.data)

    def on_button(self, _msg):
        with self.lock:
            self.brain.on_button(self.now())

    def on_tick(self):
        with self.lock:
            self.brain.tick(self.now())
        self.mode_pub.publish(String(data=self.brain.mode))


def main():
    rclpy.init()
    node = BrainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():                      # ROS may already be shut down by Ctrl-C/launch
            node.send_nav("stop")
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
