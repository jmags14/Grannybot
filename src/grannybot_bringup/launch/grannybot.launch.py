"""
Starts all GrannyBot nodes. Start Hiwonder's robot bringup (camera, LiDAR, base) and
Nav2 + map FIRST, using Hiwonder's launch commands (see docs/01 and docs/02).

  ros2 launch grannybot_bringup grannybot.launch.py
  ros2 launch grannybot_bringup grannybot.launch.py nav:=false button:=false   # vision + brain only
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("grannybot_bringup"), "config", "grannybot.yaml")
    nav, button = LaunchConfiguration("nav"), LaunchConfiguration("button")
    return LaunchDescription([
        DeclareLaunchArgument("nav", default_value="true"),
        DeclareLaunchArgument("button", default_value="true"),
        Node(package="grannybot_vision", executable="fall_node", parameters=[params], output="screen"),
        Node(package="grannybot_brain", executable="brain_node", parameters=[params], output="screen"),
        Node(package="grannybot_navigation", executable="nav_commander", parameters=[params],
             output="screen", condition=IfCondition(nav)),
        Node(package="grannybot_hardware", executable="button_node", parameters=[params],
             output="screen", condition=IfCondition(button)),
    ])
