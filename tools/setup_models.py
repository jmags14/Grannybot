"""Downloads the model files GrannyBot needs into ./models (run once, from the repo root)."""
import os
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
os.makedirs(MODELS, exist_ok=True)

POSE_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
            "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task")
VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

pose_path = os.path.join(MODELS, "pose_landmarker_lite.task")
if not os.path.exists(pose_path):
    print("Downloading MediaPipe pose model...")
    urllib.request.urlretrieve(POSE_URL, pose_path)

vosk_dir = os.path.join(MODELS, "vosk-model-small-en-us-0.15")
if not os.path.isdir(vosk_dir):
    print("Downloading Vosk speech model (~40 MB)...")
    zpath = vosk_dir + ".zip"
    urllib.request.urlretrieve(VOSK_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(MODELS)
    os.remove(zpath)

# YOLO weights: Ultralytics can download these itself, but grabbing them now means the
# robot doesn't need internet later.
try:
    from ultralytics import YOLO
    cwd = os.getcwd()
    os.chdir(MODELS)
    for w in ("yolo11n-pose.pt", "yolo11n.pt"):
        if not os.path.exists(w):
            print(f"Downloading {w}...")
            YOLO(w)
    os.chdir(cwd)
except Exception as e:
    print(f"(Skipped YOLO download: {e}; it will download on first run)")

print(f"Done. Models are in {MODELS}")
