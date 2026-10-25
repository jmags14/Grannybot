"""
Check the microphone and speaker GrannyBot will use (EE + CS). Run on the robot.

  python tools/check_audio.py              # list devices, speak, record 4 s, play it back
  python tools/check_audio.py --device 2   # use input device 2 (number from the list)

If you hear the voice and then your own recording, the check-in will work.
Then try the real thing:  cd src/grannybot_brain && python -m grannybot_brain.checkin
"""
import argparse

import _paths  # noqa: F401

ap = argparse.ArgumentParser()
ap.add_argument("--device", type=int, default=None, help="input device number")
ap.add_argument("--seconds", type=float, default=4.0)
a = ap.parse_args()

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

print(sd.query_devices())
print(f"\ndefault input/output: {sd.default.device}")

from grannybot_brain.checkin import speak  # noqa: E402

speak("Hello, this is GrannyBot. After the beep, say something.")
rate = int(sd.query_devices(a.device, "input")["default_samplerate"])
sd.play(0.3 * np.sin(2 * np.pi * 880 * np.arange(int(rate * 0.2)) / rate), rate)
sd.wait()
print(f"recording {a.seconds:.0f} s...")
rec = sd.rec(int(a.seconds * rate), samplerate=rate, channels=1, dtype="float32", device=a.device)
sd.wait()
level = float(np.sqrt(np.mean(rec ** 2)))
print(f"recording level (RMS): {level:.4f}  " +
      ("OK" if level > 0.005 else "<- very quiet: wrong device, muted, or mic too far"))
print("playing it back...")
sd.play(rec, rate)
sd.wait()
