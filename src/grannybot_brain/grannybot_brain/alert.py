"""
alert.py — tells the caregiver. Two channels, both need nothing installed on their phone:

  1. EMAIL (free, never expires): sent through a Gmail account with an "app password".
     Arrives in their normal email app. Sent first because it's instant.
  2. PHONE CALL (Twilio free trial: 75 minutes, 30 days, no credit card): calls each
     number in CAREGIVER_PHONES in order and reads the alert out loud. If nobody answers
     (no-answer / busy / failed), it tries the next number, up to CALL_ROUNDS times.

Configure either one or both. Only text is sent. Camera images and audio never leave the robot.

.env (email):
  EMAIL_USER=grannybot.team@gmail.com
  EMAIL_APP_PASSWORD=abcd efgh ijkl mnop   # Google Account > Security > App passwords
  EMAIL_TO=you@example.com,parent@example.com
.env (phone call):
  TWILIO_ACCOUNT_SID=ACxxxx
  TWILIO_AUTH_TOKEN=xxxx
  TWILIO_FROM_NUMBER=+14075550100        # the number Twilio gives you
  CAREGIVER_PHONES=+14075550123,+14075550199   # first = called first
  PERSON_NAME=Grandma
  CALL_ROUNDS=2                          # optional
  SEND_SMS=false                         # optional, see docs/04 (US SMS needs registration)

Test:  python -m grannybot_brain.alert            (from src/grannybot_brain, or after colcon build)
"""
from __future__ import annotations

import os
import time
from typing import Optional
from xml.sax.saxutils import escape

from .paths import load_env

FAILED_EMAIL_HINT = ("Gmail needs 2-Step Verification ON and an App Password "
                     "(not your normal password)")

FAILED_STATUSES = {"no-answer", "busy", "failed", "canceled"}


def build_message(reason: str, place: Optional[str] = None) -> str:
    who = os.getenv("PERSON_NAME", "Grandma")
    msg = f"This is GrannyBot. {who} may need help. {reason}."
    if place:
        msg += f" Last seen in the {place}."
    msg += f" Time {time.strftime('%I:%M %p').lstrip('0')}. Please check on {who} now."
    return msg


def _twiml(message: str) -> str:
    m = escape(message)
    return (f'<Response><Pause length="1"/><Say voice="alice">{m}</Say><Pause length="1"/>'
            f'<Say voice="alice">Repeating. {m}</Say></Response>')


def _phones() -> list:
    raw = os.getenv("CAREGIVER_PHONES") or os.getenv("CAREGIVER_PHONE", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def call_caregivers(message: str, wait_per_call_s: int = 75, poll_s: float = 3.0) -> dict:
    """Call numbers in order until someone answers. Returns what happened."""
    from twilio.rest import Client
    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    from_ = os.environ["TWILIO_FROM_NUMBER"]
    phones = _phones()
    if not phones:
        return {"answered": False, "error": "CAREGIVER_PHONES is empty"}
    rounds = int(os.getenv("CALL_ROUNDS", "2"))
    attempts = []
    for _ in range(rounds):
        for to in phones:
            call = client.calls.create(to=to, from_=from_, twiml=_twiml(message), timeout=30)
            status, end = "queued", time.time() + wait_per_call_s
            while time.time() < end:
                time.sleep(poll_s)
                status = client.calls(call.sid).fetch().status
                if status == "completed" or status in FAILED_STATUSES:
                    break
            attempts.append({"to": to, "status": status})
            print(f"[alert] call to {to}: {status}")
            if status in ("completed", "in-progress"):
                return {"answered": True, "by": to, "attempts": attempts}
    return {"answered": False, "attempts": attempts}


def send_sms(message: str) -> list:
    from twilio.rest import Client
    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    return [client.messages.create(to=to, from_=os.environ["TWILIO_FROM_NUMBER"], body=message).sid
            for to in _phones()]


def _emails() -> list:
    return [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]


def send_email(message: str) -> dict:
    """Free backup channel via Gmail SMTP (or any SMTP server via EMAIL_SMTP_HOST/PORT)."""
    import smtplib
    import ssl
    from email.message import EmailMessage

    who = os.getenv("PERSON_NAME", "Grandma")
    msg = EmailMessage()
    msg["Subject"] = f"GrannyBot ALERT: {who} may need help"
    msg["From"] = os.environ["EMAIL_USER"]
    msg["To"] = ", ".join(_emails())
    msg.set_content(message + "\n\n(Sent automatically by GrannyBot. No images or audio are included.)")
    host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as s:
        s.login(os.environ["EMAIL_USER"], os.environ["EMAIL_APP_PASSWORD"].replace(" ", ""))
        s.send_message(msg)
    return {"sent_to": _emails()}


def send_alert(reason: str, place: Optional[str] = None) -> dict:
    """Blocking (can take a couple of minutes if nobody answers). Run it in a thread."""
    load_env()
    message = build_message(reason, place)
    print(f"[ALERT] {message}")
    result = {"message": message}
    email_ok = bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_APP_PASSWORD") and _emails())
    twilio_ok = all(os.getenv(k) for k in
                    ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")) and _phones()
    if not email_ok and not twilio_ok:
        print("[ALERT] no alert channel configured, fill in .env (see .env.example)")
        result["error"] = "not configured"
        return result
    if email_ok:                          # first: instant and free
        try:
            result["email"] = send_email(message)
        except Exception as e:
            result["email_error"] = f"{e} ({FAILED_EMAIL_HINT})"
    if twilio_ok:
        try:
            result.update(call_caregivers(message))
        except Exception as e:
            result["call_error"] = str(e)
    if twilio_ok and os.getenv("SEND_SMS", "false").lower() == "true":
        try:
            result["sms"] = send_sms(message)
        except Exception as e:
            result["sms_error"] = str(e)
    print(f"[ALERT] result: {result}")
    return result


if __name__ == "__main__":
    send_alert("This is only a test of the alert system", place="living room")
