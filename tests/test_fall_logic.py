"""Fake-data tests for fall_logic. Run: python -m pytest tests"""
from grannybot_vision.fall_logic import FALLEN, NO_PERSON, POSSIBLE_FALL, UPRIGHT, FallLogic, Observation

STAND = dict(bbox=(0.4, 0.1, 0.6, 0.9), torso_angle=5.0, hip_y=0.5)
LIE = dict(bbox=(0.2, 0.7, 0.8, 0.95), torso_angle=85.0, hip_y=0.85)
BEND = dict(bbox=(0.35, 0.3, 0.65, 0.9), torso_angle=70.0, hip_y=0.55)  # tying shoes: tall-ish box


def play(frames, fps=10):
    logic, states = FallLogic(), []
    for i, f in enumerate(frames):
        s = logic.update(Observation(t=i / fps, person=f is not None, **(f or {})))
        states.append(s)
    return logic, states


def test_sudden_fall():
    # stand 2s, fall over 0.5s, lie 5s
    fall = [dict(bbox=(0.4, 0.1 + 0.12 * k, 0.6 + 0.04 * k, 0.9 + 0.01 * k),
                 torso_angle=5 + 16 * k, hip_y=0.5 + 0.07 * k) for k in range(5)]
    logic, s = play([STAND] * 20 + fall + [LIE] * 50)
    assert s[19] == UPRIGHT
    assert POSSIBLE_FALL in s
    assert s[-1] == FALLEN and "sudden" in logic.reason, (s[-1], logic.reason)
    first = s.index(FALLEN) / 10
    assert 4.5 < first < 6.0, first


def test_slow_lie_down_needs_longer():
    logic, s = play([LIE] * 150)        # 15s lying, no drop seen
    assert FALLEN not in s
    logic, s = play([LIE] * 210)        # 21s
    assert s[-1] == FALLEN and "floor" in logic.reason


def test_bending_is_not_a_fall():
    _, s = play([STAND] * 20 + [BEND] * 100)
    assert FALLEN not in s and POSSIBLE_FALL not in s


def test_yolo_flicker_keeps_timer():
    frames = [LIE] * 100 + [None] * 10 + [LIE] * 120   # 1s dropout
    _, s = play(frames)
    assert s[-1] == FALLEN


def test_person_leaves():
    _, s = play([STAND] * 10 + [None] * 40)
    assert s[-1] == NO_PERSON


def test_sideways_partial_angle_wide_box_counts_as_lying():
    # small/sideways person: keypoints say ~47 deg, but the box is wide
    side = dict(bbox=(0.2, 0.6, 0.8, 0.95), torso_angle=47.0, hip_y=0.8)
    _, s = play([side] * 210)
    assert s[-1] == FALLEN


def test_camera_gap_does_not_count_as_sustained_lying():
    logic = FallLogic()
    logic.update(Observation(0, True, **LIE))
    assert logic.update(Observation(60, True, **LIE)) == POSSIBLE_FALL
    assert logic.update(Observation(61, True, **LIE)) == POSSIBLE_FALL


def test_aspect_ratio_uses_frame_dimensions():
    # Identical pixel shape encoded in square, landscape and portrait frames.
    for aspect in (1.0, 16 / 9, 9 / 16):
        logic = FallLogic()
        obs = Observation(0, True, bbox=(0, 0, .6 / aspect, .4), image_aspect=aspect)
        assert logic.update(obs) == POSSIBLE_FALL
