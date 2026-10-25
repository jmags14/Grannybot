"""
checkin.py — GrannyBot asks "Are you okay?" and listens for the answer.

Everything runs offline: pyttsx3 (espeak) for speech, Vosk for recognition.
No audio leaves the robot.

Test:  python -m grannybot_brain.checkin
"""
from __future__ import annotations

import json
import os
import queue
import time

from .paths import models_dir

VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"

from .brain import HELP, NO_RESPONSE, OK  # noqa: E402  same constants the brain uses

# Limiting Vosk to these phrases makes it MUCH more accurate on a cheap mic.
GRAMMAR = [
    "help", "help me", "call", "call for help", "hurt", "i'm hurt", "i fell",
    "no", "not okay", "i'm not okay", "emergency",
    "yes", "i'm okay", "i am okay", "okay", "i'm fine", "i am fine", "fine", "i'm good",
    "[unk]",
]
HELP_WORDS = {"help", "call", "hurt", "fell", "no", "not", "emergency"}
OK_WORDS = {"yes", "okay", "fine", "good"}


def classify(text: str) -> str | None:
    words = set(text.lower().replace("'", " ").split())
    if words & HELP_WORDS:          # check HELP first so "not okay" = HELP
        return HELP
    if words & OK_WORDS:
        return OK
    return None


_tts = None


def speak(text: str) -> None:
    global _tts
    print(f"[GrannyBot says] {text}")
    try:
        import pyttsx3
        if _tts is None:
            _tts = pyttsx3.init()
            _tts.setProperty("rate", 140)      # slower = easier for older listeners
        _tts.say(text)
        _tts.runAndWait()
    except Exception as e:                      # fall back to the espeak command
        print(f"(pyttsx3 failed: {e}; trying espeak-ng)")
        import subprocess
        subprocess.run(["espeak-ng", "-s", "140", text], check=False)


class Listener:
    def __init__(self, model_path=None, device=None):
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        model_path = model_path or os.path.join(models_dir(), VOSK_MODEL_NAME)
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"Vosk model not found at {model_path}. Run: python tools/setup_models.py")
        self.model = Model(model_path)
        self.device = device

    def listen(self, timeout_s: float = 12.0) -> tuple[str, str]:
        """Returns (OK | HELP | NO_RESPONSE, what was heard)."""
        import sounddevice as sd
        from vosk import KaldiRecognizer

        rate = int(sd.query_devices(self.device, "input")["default_samplerate"])
        rec = KaldiRecognizer(self.model, rate, json.dumps(GRAMMAR))
        q: queue.Queue = queue.Queue()

        def cb(indata, frames, t, status):
            q.put(bytes(indata))

        heard = []
        end = time.time() + timeout_s
        with sd.RawInputStream(samplerate=rate, blocksize=rate // 4, device=self.device,
                               dtype="int16", channels=1, callback=cb):
            while time.time() < end:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                else:
                    text = json.loads(rec.PartialResult()).get("partial", "")
                text = text.replace("[unk]", "").strip()
                if text:
                    heard.append(text)
                    answer = classify(text)
                    if answer:
                        return answer, text
        return NO_RESPONSE, " / ".join(heard)


def ask_are_you_okay(listener: Listener, attempts: int = 2, timeout_s: float = 12.0) -> str:
    prompts = [
        "Hello, this is GrannyBot. Are you okay? Say I'm okay, or say help.",
        "I didn't hear you. Are you okay? Say I'm okay, or say help. "
        "If you don't answer, I will call for help.",
    ]
    for i in range(attempts):
        speak(prompts[min(i, len(prompts) - 1)])
        answer, heard = listener.listen(timeout_s)
        print(f"[heard] '{heard}' -> {answer}")
        if answer == OK:
            speak("Okay, glad you're alright. I'll keep an eye out.")
            return OK
        if answer == HELP:
            speak("Okay. I'm calling for help right now. Stay where you are.")
            return HELP
    speak("I didn't get an answer. I'm calling for help now.")
    return NO_RESPONSE


if __name__ == "__main__":
    print(ask_are_you_okay(Listener()))
