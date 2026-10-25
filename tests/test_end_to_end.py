"""End-to-end: real brain + real nav logic + real fall logic in the simulated house.
Each YAML in src/grannybot_sim/scenarios/ is one test. Run: python -m pytest tests"""
import os

import pytest
from grannybot_sim.harness import SimSystem, all_scenarios, check
from grannybot_sim.sim_core import Scenario


@pytest.mark.parametrize("path", all_scenarios(), ids=lambda p: os.path.basename(p)[:-5])
def test_scenario(path):
    res = SimSystem(Scenario.load(path)).run()
    problems = check(res)
    assert not problems, "\n".join(problems) + "\n\n" + res.timeline()
