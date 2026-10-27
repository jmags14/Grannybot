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

## Failure handling and approach limits

Check-in has a 90-second deadline; audio failures trigger the no-response path.
Failed notifications retry up to three times, 15 seconds apart. When phone calling
is configured, a failed call remains retryable even if the backup email was sent.
Delivery status describes service delivery, not caregiver acknowledgment.
The ROS brain exposes the fields of `BrainConfig` as parameters.

Approach requires a finite, positive LiDAR distance received within one second.
An obstacle within the stop distance ends approach as FAILED and starts check-in;
it does not establish that the robot reached the person. Confirmed ARRIVED requires
a fresh, independently associated range on `/grannybot/vision/person_distance`
(`std_msgs/Float32`, meters). The monocular vision node does not produce this range;
the simulator does. Physical target ranging needs a calibrated depth or sensor
association implementation. Do not publish the nearest obstacle as person distance.

WATCH periodically faces the visible person. After an okay response, three seconds
of observed upright posture rearms detection for a new fall before snooze expires.
These software checks still require physical validation of motion, audio and alerts.
