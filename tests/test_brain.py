"""Brain state machine tests with fake nav/voice/alert. Run: python -m pytest tests"""
from grannybot_brain.brain import (ALERT, APPROACH, CHECK_IN, HELP, NO_RESPONSE, OK, PATROL,
                                   WATCH, Brain)


class Fake:
    def __init__(self):
        self.nav, self.checkins, self.alerts, self.said = [], 0, [], []

    def make(self):
        def checkin():
            self.checkins += 1
        return Brain(nav=self.nav.append, start_checkin=checkin,
                     alert=lambda r, room: self.alerts.append((r, room)), say=self.said.append)


def started():
    f = Fake()
    b = f.make()
    b.tick(0.0)
    return f, b


def test_starts_patrolling():
    f, b = started()
    assert b.mode == PATROL and f.nav == ["patrol"]


def test_full_fall_no_response_calls_once():
    f, b = started()
    b.on_room("kitchen")
    b.on_vision("UPRIGHT", True, 1.0)
    assert b.mode == WATCH and f.nav[-1] == "stop"
    b.on_vision("POSSIBLE_FALL", True, 2.0, "sudden drop")
    assert f.nav[-1] == "face"
    b.on_vision("FALLEN", True, 5.0, "sudden fall, down for 3s")
    assert b.mode == APPROACH and f.nav[-1] == "approach"
    b.on_nav_status("ARRIVED", 9.0)
    assert b.mode == CHECK_IN and f.checkins == 1
    b.on_checkin_result(NO_RESPONSE, 30.0)
    assert b.mode == ALERT
    assert len(f.alerts) == 1 and f.alerts[0][1] == "kitchen"
    assert "did not respond" in f.alerts[0][0]


def test_help_answer_alerts():
    f, b = started()
    b.on_vision("UPRIGHT", True, 1.0)
    b.on_vision("FALLEN", True, 2.0)
    b.on_nav_status("ARRIVED", 3.0)
    b.on_checkin_result(HELP, 10.0)
    assert b.mode == ALERT and "asked for help" in f.alerts[0][0]


def test_okay_answer_snoozes():
    f, b = started()
    b.on_vision("UPRIGHT", True, 1.0)
    b.on_vision("FALLEN", True, 2.0)
    b.on_nav_status("ARRIVED", 3.0)
    b.on_checkin_result(OK, 10.0)
    assert b.mode == WATCH and not f.alerts
    b.on_vision("FALLEN", True, 20.0)          # still lying (e.g. doing yoga): snoozed
    assert b.mode == WATCH
    b.on_vision("FALLEN", True, 10.0 + 601)    # snooze over: check again
    assert b.mode == APPROACH


def test_approach_timeout_still_checks_in():
    f, b = started()
    b.on_vision("UPRIGHT", True, 1.0)
    b.on_vision("FALLEN", True, 2.0)
    b.on_vision("FALLEN", True, 30.0)          # keep "seen" fresh
    b.tick(2.0 + 41)
    assert b.mode == CHECK_IN


def test_lost_person_goes_back_to_patrol():
    f, b = started()
    b.on_vision("UPRIGHT", True, 1.0)
    b.tick(20.0)
    assert b.mode == WATCH
    b.tick(32.0)
    assert b.mode == PATROL and f.nav[-1] == "patrol"


def test_button_always_calls_even_right_after_alert():
    f, b = started()
    b.on_button(5.0)
    b.on_button(6.0)
    assert b.mode == ALERT and len(f.alerts) == 2 and f.nav[-1] == "stop"


def test_no_repeat_call_within_gap():
    f, b = started()
    for t0 in (1.0, 100.0):
        b.mode = WATCH
        b.on_vision("FALLEN", True, t0)
        b.on_nav_status("ARRIVED", t0 + 1)
        b.on_checkin_result(NO_RESPONSE, t0 + 20)
    assert len(f.alerts) == 1
