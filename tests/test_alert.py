"""Alert tests with fake Gmail and fake Twilio (no network, no cost). Run: python -m pytest tests"""
import sys
import types

import pytest
from grannybot_brain import alert


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("EMAIL_USER", "EMAIL_APP_PASSWORD", "EMAIL_TO", "TWILIO_ACCOUNT_SID",
              "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "CAREGIVER_PHONES", "CAREGIVER_PHONE",
              "SEND_SMS", "CALL_ROUNDS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(alert, "load_env", lambda: None)
    monkeypatch.setattr(alert.time, "sleep", lambda s: None)


def test_message_has_reason_room_and_name(monkeypatch):
    monkeypatch.setenv("PERSON_NAME", "Grandma Rose")
    m = alert.build_message("person did not respond", "kitchen")
    assert "Grandma Rose" in m and "did not respond" in m and "kitchen" in m


def test_nothing_configured_reports_error():
    assert alert.send_alert("test")["error"] == "not configured"


def test_email_sent_with_gmail(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            sent["login"] = (user, pw)

        def send_message(self, msg):
            sent["to"], sent["body"] = msg["To"], msg.get_content()

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("EMAIL_USER", "bot@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("EMAIL_TO", "a@x.com, b@x.com")
    r = alert.send_alert("person asked for help", "bedroom")
    assert r["email"]["sent_to"] == ["a@x.com", "b@x.com"]
    assert sent["host"] == "smtp.gmail.com" and sent["login"] == ("bot@gmail.com", "abcdefghijklmnop")
    assert "bedroom" in sent["body"]


def fake_twilio(monkeypatch, statuses_by_number):
    """Install a fake `twilio.rest.Client`. statuses_by_number: {"+1...": "completed"/"no-answer"}"""
    calls = []

    class Call:
        def __init__(self, sid, status):
            self.sid, self.status = sid, status

        def fetch(self):
            return self

    class Calls:
        def __init__(self):
            self.by_sid = {}

        def create(self, to, from_, twiml, timeout):
            calls.append(to)
            c = Call(f"CA{len(calls)}", statuses_by_number[to])
            self.by_sid[c.sid] = c
            return c

        def __call__(self, sid):
            return self.by_sid[sid]

    class Client:
        def __init__(self, sid, token):
            self.calls = Calls()

    rest = types.ModuleType("twilio.rest")
    rest.Client = Client
    monkeypatch.setitem(sys.modules, "twilio", types.ModuleType("twilio"))
    monkeypatch.setitem(sys.modules, "twilio.rest", rest)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+14070000000")
    return calls


def test_call_escalates_to_next_number_when_unanswered(monkeypatch):
    calls = fake_twilio(monkeypatch, {"+1111": "no-answer", "+2222": "completed"})
    monkeypatch.setenv("CAREGIVER_PHONES", "+1111,+2222")
    r = alert.send_alert("possible fall", "kitchen")
    assert calls == ["+1111", "+2222"] and r["answered"] and r["by"] == "+2222"


def test_call_gives_up_after_rounds(monkeypatch):
    calls = fake_twilio(monkeypatch, {"+1111": "busy"})
    monkeypatch.setenv("CAREGIVER_PHONES", "+1111")
    monkeypatch.setenv("CALL_ROUNDS", "3")
    r = alert.send_alert("possible fall")
    assert calls == ["+1111"] * 3 and not r["answered"]
