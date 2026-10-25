#!/usr/bin/env bash
# Start everything on the MentorPi in one command. Run INSIDE Hiwonder's Docker container
# (docs/07, step 2), from the repo folder, after `colcon build` (docs/07, step 4).
#
#   bash tools/robot_up.sh                         # Hiwonder nav (map_01) + camera + all GrannyBot nodes
#   MAP=my_house bash tools/robot_up.sh            # a different saved map
#   NAV=false bash tools/robot_up.sh               # robot stays parked: camera + vision + brain + button
#   CAMERA_CMD="ros2 launch peripherals depth_camera.launch.py" bash tools/robot_up.sh
#
# Hiwonder's own launches write to logs/robot_up/*.log; GrannyBot's output stays on screen.
# Ctrl+C stops everything this script started.
#
# NOT YET TESTED ON A REAL MENTORPI: the Hiwonder commands come from their docs. If one
# fails, run the steps by hand from docs/07 and fix the variables below.

set -u
MAP="${MAP:-map_01}"
NAV="${NAV:-true}"
# Depth-camera kit per Hiwonder docs. Monocular kit: find the launch in ~/ros2_ws/src/peripherals/launch
CAMERA_CMD="${CAMERA_CMD:-ros2 launch peripherals depth_camera.launch.py}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$REPO/logs/robot_up"
mkdir -p "$LOGS"

echo "== stopping Hiwonder's app autostart (it uses the camera and motors)"
[ -x "$HOME/.stop_ros.sh" ] && "$HOME/.stop_ros.sh" || echo "   (~/.stop_ros.sh not found; stop the app manually if it's running)"

[ -f "$HOME/ros2_ws/install/setup.bash" ] && source "$HOME/ros2_ws/install/setup.bash"
if [ ! -f "$REPO/install/setup.bash" ]; then
  echo "!! $REPO/install not found. Build first: cd $REPO && colcon build --symlink-install"; exit 1
fi
source "$REPO/install/setup.bash"
export GRANNYBOT_MODELS="${GRANNYBOT_MODELS:-$REPO/models}"
export GRANNYBOT_ENV="${GRANNYBOT_ENV:-$REPO/.env}"

PIDS=()
cleanup() {
  echo; echo "== stopping"
  for p in "${PIDS[@]}"; do kill -INT "$p" 2>/dev/null; done
  sleep 2
  for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; done
}
trap cleanup EXIT INT TERM

if [ "$NAV" = "true" ]; then
  echo "== Hiwonder navigation with map '$MAP' (log: $LOGS/navigation.log)"
  ros2 launch navigation navigation.launch.py map:="$MAP" > "$LOGS/navigation.log" 2>&1 &
  PIDS+=($!)
fi
echo "== camera: $CAMERA_CMD (log: $LOGS/camera.log)"
$CAMERA_CMD > "$LOGS/camera.log" 2>&1 &
PIDS+=($!)

echo "== waiting 20 s for the robot drivers to come up..."
sleep 20
if [ "$NAV" = "true" ]; then
  echo "!! Set the robot's starting position in RViz ('2D Pose Estimate') if you haven't yet."
fi

echo "== GrannyBot nodes"
ros2 launch grannybot_bringup grannybot.launch.py nav:="$NAV" &
PIDS+=($!)
sleep 8
echo "== health check"
ros2 run grannybot_bringup health_check --ros-args \
  --params-file "$REPO/install/grannybot_bringup/share/grannybot_bringup/config/grannybot.yaml" || true
echo "== running. Ctrl+C to stop everything."
wait
