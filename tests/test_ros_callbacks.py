"""Exercise actual ROS callback bodies with fake futures/audio, without requiring ROS.

Only the ROS base class and imports are omitted; methods are compiled unchanged
from the source so delayed acceptance and worker failures can be tested locally.
"""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace

from grannybot_brain.brain import NO_RESPONSE

ROOT = Path(__file__).resolve().parents[1]


def callback_class(path, name, **namespace):
    tree = ast.parse((ROOT / path).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    cls.bases = []
    module = ast.Module(body=[cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def navigation_node():
    cls = callback_class(
        'src/grannybot_navigation/grannybot_navigation/nav_commander_node.py',
        'NavCommander')
    node = cls.__new__(cls)
    node.pending_goals = {1}
    node.goal_handles = {}
    node.lock = threading.Lock()
    node.results = []
    node.logic = SimpleNamespace(on_goal_result=lambda *args: node.results.append(args))
    node.now = lambda: 10
    node.get_logger = lambda: SimpleNamespace(error=lambda text: None)
    return node


def test_stop_cancels_goal_accepted_after_stop():
    node = navigation_node()
    canceled = []
    node.cancel_goal()
    handle = SimpleNamespace(accepted=True, cancel_goal_async=lambda: canceled.append(True))
    node.on_goal_accepted(1, SimpleNamespace(result=lambda: handle))
    assert canceled == [True]
    assert not node.goal_handles and not node.pending_goals


def test_cancel_existing_and_pending_goals_together():
    node = navigation_node()
    canceled = []
    node.goal_handles[2] = SimpleNamespace(cancel_goal_async=lambda: canceled.append(2))
    node.cancel_goal()
    assert canceled == [2] and not node.goal_handles and not node.pending_goals


def test_goal_request_exception_reports_failure():
    node = navigation_node()
    def failed():
        raise RuntimeError('server disconnected')
    node.on_goal_accepted(1, SimpleNamespace(result=failed))
    assert node.results == [(1, False, 10)] and not node.pending_goals


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


def test_audio_failure_reports_no_response():
    cls = callback_class('src/grannybot_brain/grannybot_brain/brain_node.py', 'BrainNode',
                         threading=SimpleNamespace(Thread=ImmediateThread), NO_RESPONSE=NO_RESPONSE)
    node = cls.__new__(cls)
    node.lock = threading.Lock()
    results = []
    node.brain = SimpleNamespace(_mode_since=3, on_checkin_result=lambda *args: results.append(args))
    node.now = lambda: 4
    node.get_logger = lambda: SimpleNamespace(error=lambda text: None)
    def failed():
        raise RuntimeError('microphone disconnected')
    node.run_checkin = failed
    node.start_checkin()
    assert results == [(NO_RESPONSE, 4)]


def test_late_audio_result_cannot_affect_new_incident():
    cls = callback_class('src/grannybot_brain/grannybot_brain/brain_node.py', 'BrainNode',
                         threading=SimpleNamespace(Thread=ImmediateThread), NO_RESPONSE=NO_RESPONSE)
    node = cls.__new__(cls)
    node.lock = threading.Lock()
    results = []
    node.brain = SimpleNamespace(_mode_since=3, on_checkin_result=lambda *args: results.append(args))
    node.now = lambda: 100
    def late():
        node.brain._mode_since = 99  # another incident started before the old worker returned
        return 'OK'
    node.run_checkin = late
    node.start_checkin()
    assert not results
