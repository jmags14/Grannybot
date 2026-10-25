"""
Full GrannyBot software in simulation: fake world + REAL brain_node + REAL nav_commander.
No robot, camera, LiDAR, Nav2, microphone or phone call needed.

  ros2 launch grannybot_sim sim.launch.py                                  # default scenario
  ros2 launch grannybot_sim sim.launch.py scenario:=02_fall_says_okay
  ros2 launch grannybot_sim sim.launch.py scenario:=01_fall_no_answer check:=true   # PASS/FAIL

The check-in answer comes from the scenario file (fake_checkin_answer), and the phone
call is a dry run (printed, not dialed), unless you pass real_call:=true.
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def nodes(context):
    sdir = os.path.join(get_package_share_directory("grannybot_sim"), "scenarios")
    name = LaunchConfiguration("scenario").perform(context)
    with open(os.path.join(sdir, name + ".yaml")) as f:
        sc = yaml.safe_load(f)
    real_call = LaunchConfiguration("real_call").perform(context) == "true"
    return [
        Node(package="grannybot_sim", executable="sim_node", output="screen",
             parameters=[{"scenario": name}]),
        Node(package="grannybot_brain", executable="brain_node", output="screen",
             parameters=[{"no_voice": True,
                          "fake_checkin_answer": sc.get("checkin_answer", "NO_RESPONSE"),
                          "fake_checkin_delay_s": float(sc.get("checkin_delay_s", 5)),
                          "dry_run_alert": not real_call}]),
        Node(package="grannybot_navigation", executable="nav_commander", output="screen",
             parameters=[{"rooms_file": os.path.join(sdir, "house.yaml")}]),
        Node(package="grannybot_sim", executable="e2e_check", output="screen",
             parameters=[{"scenario": name}],
             condition=IfCondition(LaunchConfiguration("check")),
             on_exit=Shutdown()),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("scenario", default_value="01_fall_no_answer"),
        DeclareLaunchArgument("check", default_value="false"),
        DeclareLaunchArgument("real_call", default_value="false"),
        OpaqueFunction(function=nodes),
    ])
