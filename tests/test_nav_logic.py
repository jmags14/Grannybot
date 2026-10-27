"""NavLogic tests with a fake Nav2. Run: python -m pytest tests"""
from grannybot_navigation.nav_logic import NavConfig, NavLogic

ROOMS = {"living": [0, 0, 0], "kitchen": [3, 1, 1.57], "bedroom": [-2, 3, 3.14]}


class Fake:
    def __init__(self):
        self.goals, self.cancels, self.vel, self.status, self.rooms = [], 0, [], [], []

    def make(self, **cfg):
        def send_goal(room, xyz):
            self.goals.append(room)
            return len(self.goals)

        def cancel():
            self.cancels += 1
        return NavLogic(ROOMS, ["living", "kitchen", "bedroom"], send_goal, cancel,
                        lambda v, w: self.vel.append((v, w)), self.status.append,
                        self.rooms.append, NavConfig(**cfg))


def test_patrol_visits_rooms_in_order_with_pause():
    f = Fake()
    n = f.make(patrol_pause_s=5)
    n.on_command("patrol", 0)
    assert f.goals == ["living"] and f.status[-1] == "MOVING"
    n.on_goal_result(1, True, 3)
    assert f.rooms == ["living"] and f.status[-1] == "ARRIVED"
    n.tick(4)
    assert f.vel[-1][1] > 0                 # looking around during pause
    n.tick(8.1)
    assert f.goals == ["living", "kitchen"]
    n.on_goal_result(2, False, 12)          # blocked: keeps patrolling
    n.tick(17.2)
    assert f.goals[-1] == "bedroom"


def test_stop_cancels_goal_and_zeroes_velocity():
    f = Fake()
    n = f.make()
    n.on_command("patrol", 0)
    n.on_command("stop", 1)
    assert f.cancels == 1 and f.vel[-1] == (0.0, 0.0) and f.status[-1] == "IDLE"
    n.on_goal_result(1, True, 2)            # late result from canceled goal is ignored
    assert f.rooms == []


def test_face_turns_toward_person_then_arrives():
    f = Fake()
    n = f.make()
    n.on_command("face", 0)
    n.on_bearing(30, 0.1)
    n.tick(0.1)
    assert f.vel[-1][0] == 0 and f.vel[-1][1] > 0       # person on the left -> turn left
    n.on_bearing(-30, 0.2)
    n.tick(0.2)
    assert f.vel[-1][1] < 0
    n.on_bearing(2, 0.3)
    n.tick(0.3)
    assert f.status[-1] == "ARRIVED" and f.vel[-1] == (0.0, 0.0)


def test_approach_drives_until_close():
    f = Fake()
    n = f.make(approach_distance_m=1.0)
    n.on_command("approach", 0)
    n.on_bearing(3, 0.1)
    n.on_front_distance(2.5, 0.1)
    n.tick(0.1)
    assert f.vel[-1][0] > 0
    n.on_bearing(40, 0.2)                   # way off-center: turn only, don't drive
    n.tick(0.2)
    assert f.vel[-1][0] == 0
    n.on_bearing(1, 0.3)
    n.on_front_distance(0.95, 0.3)
    n.on_person_distance(0.95, 0.3)
    n.tick(0.3)
    assert f.status[-1] == "ARRIVED"


def test_person_lost_during_approach():
    f = Fake()
    n = f.make()
    n.on_command("approach", 0)
    n.on_bearing(0, 0.1)
    n.on_front_distance(3, 0.1)
    n.tick(0.2)
    n.tick(2.0)                             # no new bearing for > 1.5 s
    assert f.status[-1] == "LOST" and f.vel[-1] == (0.0, 0.0)


def test_unknown_room_fails():
    f = Fake()
    n = f.make()
    n.on_command("goto:garage", 0)
    assert f.status[-1] == "FAILED" and f.goals == []


def test_approach_without_scan_stops():
    f = Fake()
    n = f.make()
    n.on_command("approach", 0)
    n.on_bearing(0, .1)
    n.tick(.1)
    assert f.status[-1] == "FAILED" and f.vel[-1] == (0, 0)


def test_stale_or_invalid_scan_cannot_drive():
    for distance in (3, float("nan"), float("inf"), -1):
        f = Fake()
        n = f.make()
        n.on_command("approach", 0)
        n.on_front_distance(distance, 0)
        n.on_bearing(0, 1.1)
        n.tick(1.1)
        assert f.status[-1] == "FAILED" and f.vel[-1] == (0, 0)


def test_obstacle_is_not_reported_as_person_arrival():
    f = Fake()
    n = f.make()
    n.on_command("approach", 0)
    n.on_front_distance(.8, .1)
    n.on_bearing(0, .1)
    n.on_person_distance(3, .1)
    n.tick(.1)
    assert f.status[-1] == "FAILED" and f.vel[-1] == (0, 0)
