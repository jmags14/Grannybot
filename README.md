# GrannyBot

A home robot that keeps an elderly person in view, detects falls, asks if they're okay,
and **automatically phones a caregiver** if they need help. Built on a Hiwonder MentorPi M1
(Raspberry Pi 5, ROS 2 Humble, LiDAR). All camera and audio processing stays on the robot.

## Quick start on a laptop (no ROS, no robot)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tools/setup_models.py
python -m pytest tests                                 # logic tests
python tools/run_detector.py                           # webcam fall detection (YOLO11n-pose)
python tools/run_sim.py                                # whole system in a simulated house
cp .env.example .env                                   # add Gmail app password (+ Twilio in week 3)
python tools/run_local_demo.py                         # webcam: fall -> "Are you okay?" -> alert
```

## With ROS 2 (laptop simulation or the robot)

```bash
colcon build --symlink-install && source install/setup.bash
ros2 launch grannybot_sim sim.launch.py check:=true     # real nodes + fake world, prints PASS/FAIL
bash tools/robot_up.sh                                  # on the MentorPi: Hiwonder nav + camera + all our nodes
ros2 run grannybot_bringup health_check --ros-args --params-file src/grannybot_bringup/config/grannybot.yaml
```
