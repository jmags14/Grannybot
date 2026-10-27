"""
brain.py — GrannyBot's decision-maker (state machine). No ROS, no hardware, so it's
easy to test (tests/test_brain.py) and reuse from the laptop demo.

Modes:
  PATROL    don't see granny -> drive room to room looking for her
  WATCH     see granny -> park and keep her in view
  APPROACH  fall confirmed -> drive to ~1 m from her
  CHECK_IN  ask "Are you okay?" and listen
  ALERT     call the caregiver's phone, stay with her

  PATROL --person seen--> WATCH --person lost 30s--> PATROL
  WATCH --UPRIGHT/POSSIBLE_FALL--> (periodically face her, stay in WATCH)
  WATCH --FALLEN--> APPROACH --arrived/timeout--> CHECK_IN --"I'm okay"--> WATCH (snooze 10 min)
                                                            --"help"/silence--> ALERT --5 min--> WATCH/PATROL
  any mode --emergency button--> ALERT

The brain never touches hardware. It calls functions you give it:
  nav(cmd)            "patrol" | "stop" | "face" | "approach" | "goto:<room>"
  start_checkin()     begin the voice check-in; later call on_checkin_result(result)
  alert(reason, room) call the caregiver (run it in a thread, it can take a minute)
  say(text)           speak something

Alert adapters must call on_alert_result(delivered, now, attempt_id) after delivery;
capture alert_attempt_id when the attempt starts to reject stale worker results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

PATROL, WATCH, APPROACH, CHECK_IN, ALERT = "PATROL", "WATCH", "APPROACH", "CHECK_IN", "ALERT"
OK, HELP, NO_RESPONSE = "OK", "HELP", "NO_RESPONSE"


@dataclass
class BrainConfig:
    checkin_timeout_s: float = 90.0
    recovery_s: float = 3.0
    alert_retry_s: float = 15.0
    alert_delivery_timeout_s: float = 900.0
    alert_max_attempts: int = 3
    lost_person_s: float = 30.0        # WATCH -> PATROL if granny not seen for this long
    face_cooldown_s: float = 5.0       # don't spam "face" commands
    approach_timeout_s: float = 40.0   # backup: check in even if nav never answers (nav's own limit is 30 s)
    snooze_after_ok_s: float = 600.0   # suppress same incident until recovery or 10 min
    alert_hold_s: float = 300.0        # stay in ALERT this long before resuming
    min_alert_gap_s: float = 300.0     # don't call again within 5 min (button always calls)


class Brain:
    def __init__(self, nav: Callable[[str], None], start_checkin: Callable[[], None],
                 alert: Callable[[str, Optional[str]], None], say: Callable[[str], None],
                 cfg: Optional[BrainConfig] = None,
                 on_event: Optional[Callable[[float, str, str], None]] = None):
        self.nav, self.start_checkin, self.alert, self.say = nav, start_checkin, alert, say
        self.cfg = cfg or BrainConfig()
        self.on_event = on_event
        self.events: List[Tuple[float, str, str]] = []
        self.mode = PATROL
        self.room: Optional[str] = None
        self.fall_state = "NO_PERSON"
        self.fall_reason = ""
        self._last_seen = -1e9
        self._mode_since = 0.0
        self._last_face = -1e9
        self._snooze_until = -1e9
        self._last_alert = -1e9
        self._started = False
        self._upright_since = None
        self._alert_pending = False
        self._alert_retry_at = None
        self._alert_attempts = 0
        self._alert_reason = ""
        self._alert_room = None
        self.alert_attempt_id = 0
        self._alert_sent_at = 0.0

    # ---- helpers ------------------------------------------------------
    def _set(self, mode: str, now: float, why: str) -> None:
        self.mode, self._mode_since = mode, now
        self.events.append((now, mode, why))
        if self.on_event:
            self.on_event(now, mode, why)

    def _do_alert(self, reason: str, now: float, force: bool = False) -> None:
        self._set(ALERT, now, reason)
        if not force and (self._alert_pending or self._alert_retry_at is not None):
            return
        if force or now - self._last_alert >= self.cfg.min_alert_gap_s:
            self._alert_reason, self._alert_room = reason, self.room
            self._alert_attempts = 0
            self._alert_retry_at = None
            self._send_alert(now)

    def _send_alert(self, now: float) -> None:
        self._alert_pending = True
        self._alert_sent_at = now
        self._alert_attempts += 1
        self.alert_attempt_id += 1
        self.alert(self._alert_reason, self._alert_room)

    def on_alert_result(self, delivered: bool, now: float, attempt_id=None) -> None:
        if not self._alert_pending or (attempt_id is not None and attempt_id != self.alert_attempt_id):
            return
        self._alert_pending = False
        if delivered:
            self._last_alert = now
            self._alert_retry_at = None
        elif self._alert_attempts < self.cfg.alert_max_attempts:
            self._alert_retry_at = now + self.cfg.alert_retry_s
        else:
            self._alert_retry_at = None
            if self.on_event:
                self.on_event(now, ALERT, "notification delivery failed; retries exhausted")

    # ---- inputs ---------------------------------------------------------
    def start(self, now: float) -> None:
        self._started = True
        self._set(PATROL, now, "startup")
        self.nav("patrol")

    def _ensure_started(self, now: float) -> None:
        if not self._started:
            self.start(now)

    def on_room(self, room: str) -> None:
        self.room = room

    def on_vision(self, fall_state: str, person_seen: bool, now: float, reason: str = "") -> None:
        self._ensure_started(now)
        self.fall_state = fall_state
        if reason:
            self.fall_reason = reason
        if person_seen:
            self._last_seen = now
        if person_seen and fall_state == "UPRIGHT":
            if self._upright_since is None:
                self._upright_since = now
            if now - self._upright_since >= self.cfg.recovery_s:
                self._snooze_until = -1e9
        else:
            self._upright_since = None

        if self.mode == PATROL and person_seen:
            self._set(WATCH, now, "found person")
            self.nav("stop")
        elif self.mode == WATCH:
            if fall_state == "FALLEN" and now >= self._snooze_until:
                self._set(APPROACH, now, f"fall confirmed ({self.fall_reason or 'fallen'})")
                self.nav("approach")
            elif person_seen and fall_state in ("UPRIGHT", "POSSIBLE_FALL") and now - self._last_face >= self.cfg.face_cooldown_s:
                self._last_face = now
                self.nav("face")

    def on_nav_status(self, status: str, now: float) -> None:
        self._ensure_started(now)
        if self.mode == APPROACH and status in ("ARRIVED", "FAILED", "LOST"):
            self._begin_checkin(now, f"approach {status.lower()}")

    def on_button(self, now: float) -> None:
        self._ensure_started(now)
        self.nav("stop")
        self.say("Emergency button pressed. I'm calling for help now.")
        self._do_alert("emergency button pressed", now, force=True)

    def on_checkin_result(self, result: str, now: float) -> None:
        if self.mode != CHECK_IN:
            return
        if result == OK:
            self._snooze_until = now + self.cfg.snooze_after_ok_s
            self._set(WATCH, now, "person said they are okay")
        else:
            what = "asked for help" if result == HELP else "did not respond"
            self._do_alert(f"possible fall ({self.fall_reason or 'fallen'}); person {what}", now)

    def tick(self, now: float) -> None:
        """Call regularly (e.g. every 0.5 s) for timeouts."""
        if not self._started:
            self.start(now)
            return
        in_mode = now - self._mode_since
        if self._alert_pending and now - self._alert_sent_at > self.cfg.alert_delivery_timeout_s:
            self.on_alert_result(False, now)
        if self._alert_retry_at is not None and now >= self._alert_retry_at:
            self._alert_retry_at = None
            self._send_alert(now)
        if self.mode == CHECK_IN and in_mode > self.cfg.checkin_timeout_s:
            self.on_checkin_result(NO_RESPONSE, now)
            return
        if self.mode == WATCH and now - self._last_seen > self.cfg.lost_person_s:
            self._set(PATROL, now, "lost sight of person")
            self.nav("patrol")
        elif self.mode == APPROACH and in_mode > self.cfg.approach_timeout_s:
            self._begin_checkin(now, "approach timeout")
        elif self.mode == ALERT and in_mode > self.cfg.alert_hold_s and not self._alert_pending and self._alert_retry_at is None:
            if now - self._last_seen < self.cfg.lost_person_s:
                self._set(WATCH, now, "alert hold finished")
            else:
                self._set(PATROL, now, "alert hold finished, person not visible")
                self.nav("patrol")

    def _begin_checkin(self, now: float, why: str) -> None:
        self.nav("stop")
        self._set(CHECK_IN, now, why)
        self.start_checkin()
