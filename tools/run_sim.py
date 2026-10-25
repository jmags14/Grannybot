"""
Run simulated end-to-end scenarios (no robot, no ROS) and print what the robot did.

  python tools/run_sim.py                    # every scenario
  python tools/run_sim.py 01_fall_no_answer  # one scenario (file name without .yaml)
"""
import os
import sys

import _paths  # noqa: F401
from grannybot_sim.harness import SCENARIO_DIR, SimSystem, all_scenarios, check
from grannybot_sim.sim_core import Scenario

paths = ([os.path.join(SCENARIO_DIR, a + ".yaml") for a in sys.argv[1:]] or all_scenarios())
failed = 0
for p in paths:
    sc = Scenario.load(p)
    res = SimSystem(sc).run()
    problems = check(res)
    print("=" * 78)
    print(f"{sc.name}: {sc.description.strip()}")
    print("-" * 78)
    print(res.timeline())
    print("-" * 78)
    print("PASS" if not problems else "FAIL: " + "; ".join(problems))
    failed += bool(problems)
print("=" * 78)
print(f"{len(paths) - failed}/{len(paths)} scenarios passed")
sys.exit(1 if failed else 0)
