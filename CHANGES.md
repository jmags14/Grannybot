# Changelog

## Latest: node reference, MentorPi integration guide, Hiwonder names

## New
| File | What it is |
|---|---|
| `docs/06_nodes_reference.md` | Every node: job, topics in/out, parameters, how to run it, how to test it alone; full graph; debugging commands |
| `docs/07_mentorpi_integration.md` | Step by step on the real robot: VNC/hotspot, Hiwonder's Docker container, stopping their app, their mapping/navigation/camera commands, installing our code as an overlay, verifying topic names, bring-up order, hardware-in-Docker checks, common problems |
| `tools/robot_up.sh` | One command inside the container: stops Hiwonder's app, starts their navigation + camera, starts all GrannyBot nodes, runs the health check |

## Changed
| File | Change |
|---|---|
| `src/grannybot_bringup/config/grannybot.yaml` | Now the MentorPi config: `scan_raw`, `/controller/cmd_vel`, `base_footprint` (from Hiwonder's docs), health-check section, notes on finding the camera topic |
| `health_check.py` | Topic and frame names are parameters (reads the same config file) |
| `nav_commander_node.py` | Repeats the room name every 2 s so late-starting nodes get it |
| `sim_node.py` | `base_frame` parameter so the simulator can mimic the MentorPi's names |
| docs 00, 01, 02, README | Real Hiwonder details and links to docs 06/07 |

## Tested
- 31 unit + end-to-end tests pass; 6/6 simulator scenarios pass
- ROS 2: simulator running under the MentorPi's names (`/scan_raw`, `/controller/cmd_vel`, `base_footprint`) with the real
  `grannybot.yaml`: health check 10/10, "asks for help" scenario PASS, alert names the right room
- Not tested on the real MentorPi. Hiwonder names come from their docs and must be verified (docs/07 step 5)
