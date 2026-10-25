"""Lets the laptop tools import the ROS packages' Python code without building ROS."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for pkg in ("grannybot_vision", "grannybot_brain", "grannybot_navigation", "grannybot_sim"):
    sys.path.insert(0, os.path.join(ROOT, "src", pkg))
os.environ.setdefault("GRANNYBOT_MODELS", os.path.join(ROOT, "models"))
os.environ.setdefault("GRANNYBOT_ENV", os.path.join(ROOT, ".env"))
