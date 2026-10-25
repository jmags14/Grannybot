"""
button_node.py — publishes std_msgs/Empty on /grannybot/hardware/button when the
emergency button is pressed.  [EE owns this]

Wiring: one leg of a momentary push button to a free GPIO pin, the other to GND.
The Pi's internal pull-up is used, so no resistor is needed.
CHECK FIRST which GPIO pins Hiwonder's expansion/controller board already uses.

Run:  ros2 run grannybot_hardware button_node --ros-args -p gpio_pin:=17
Test without a button:  ros2 topic pub --once /grannybot/hardware/button std_msgs/msg/Empty
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import Empty


class ButtonNode(Node):
    def __init__(self):
        super().__init__("grannybot_button")
        self.declare_parameter("gpio_pin", 17)
        self.declare_parameter("hold_s", 0.3)        # ignore taps shorter than this
        pin = int(self.get_parameter("gpio_pin").value)
        self.pub = self.create_publisher(Empty, "/grannybot/hardware/button", 10)
        try:
            from gpiozero import Button
            self.button = Button(pin, pull_up=True, bounce_time=0.05,
                                 hold_time=float(self.get_parameter("hold_s").value))
            self.button.when_held = self.pressed
            self.get_logger().info(f"emergency button on GPIO{pin}")
        except Exception as e:  # not on a Pi, or pin busy
            self.button = None
            self.get_logger().error(f"GPIO not available ({e}); use `ros2 topic pub` to simulate")

    def pressed(self):
        self.get_logger().warn("EMERGENCY BUTTON PRESSED")
        self.pub.publish(Empty())


def main():
    rclpy.init()
    node = ButtonNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
