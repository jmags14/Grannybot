"""
The whole GrannyBot flow on a laptop, no ROS and no robot:
webcam -> detector -> brain -> "Are you okay?" -> phone call.

Navigation is faked (it just prints and reports ARRIVED), so you can test your entire
part before the robot is driving.

  python tools/run_local_demo.py                 # full demo (needs mic, speaker, .env)
  python tools/run_local_demo.py --no-voice      # skip the check-in, call right away
  python tools/run_local_demo.py --no-call       # print the alert instead of calling
  Press 'b' in the video window to simulate the emergency button.
"""
import argparse
import threading
import time

import cv2

import _paths  # noqa: F401
from grannybot_brain.brain import NO_RESPONSE, Brain
from grannybot_vision.detectors import make_detector
from grannybot_vision.fall_logic import FallLogic
from grannybot_vision.pipeline import draw, observation_from

ap = argparse.ArgumentParser()
ap.add_argument("--source", default="0")
ap.add_argument("--detector", default="pose", choices=["pose", "mediapipe"])
ap.add_argument("--no-voice", action="store_true")
ap.add_argument("--no-call", action="store_true")
a = ap.parse_args()

lock = threading.Lock()
listener = None
if not a.no_voice:
    from grannybot_brain.checkin import Listener, ask_are_you_okay, speak
else:
    def speak(text):
        print(f"[say] {text}")


def fake_nav(cmd):
    print(f"[nav] {cmd}")
    if cmd in ("approach", "face"):            # pretend we drove there
        threading.Timer(2.0, lambda: brain_call("on_nav_status", "ARRIVED")).start()


def start_checkin():
    incident = brain._mode_since
    def work():
        global listener
        try:
            if not a.no_voice and listener is None:
                listener = Listener()
            result = ask_are_you_okay(listener) if listener else NO_RESPONSE
        except Exception as exc:
            print(f"[check-in failed] {exc}")
            result = NO_RESPONSE
        with lock:
            if brain._mode_since == incident:
                brain.on_checkin_result(result, time.monotonic())
    threading.Thread(target=work, daemon=True).start()


def alert(reason, room):
    attempt = brain.alert_attempt_id
    def work():
        from grannybot_brain.alert import notification_delivered, send_alert
        try:
            if a.no_call:
                print(f"[ALERT would call] {reason} (room={room})")
                result = {"dry_run": True}
            else:
                result = send_alert(reason, room)
        except Exception as exc:
            result = {"error": str(exc)}
        with lock:
            brain.on_alert_result(notification_delivered(result), time.monotonic(), attempt)
    threading.Thread(target=work, daemon=True).start()


brain = Brain(nav=fake_nav, start_checkin=start_checkin, alert=alert, say=speak,
              on_event=lambda t, m, why: print(f"=== MODE {m}: {why}"))
brain.on_room("living room")


def brain_call(method, *args):
    with lock:
        getattr(brain, method)(*args, time.monotonic())


src = int(a.source) if a.source.isdigit() else a.source
cap = cv2.VideoCapture(src)
det_model = make_detector(a.detector)
logic = FallLogic()
while True:
    ok, frame = cap.read()
    if not ok:
        break
    det = det_model.detect(frame)
    state = logic.update(observation_from(det, time.monotonic()))
    with lock:
        brain.on_vision(state, det is not None, time.monotonic(), logic.reason)
        brain.tick(time.monotonic())
    draw(frame, det, state, logic.reason)
    cv2.putText(frame, f"MODE: {brain.mode}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 200, 0), 2)
    cv2.imshow("GrannyBot local demo (q quit, b button)", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == ord("b"):
        brain_call("on_button")
cap.release()
cv2.destroyAllWindows()
