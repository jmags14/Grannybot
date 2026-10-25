import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for pkg in ("grannybot_vision", "grannybot_brain", "grannybot_navigation", "grannybot_sim"):
    sys.path.insert(0, os.path.join(ROOT, "src", pkg))
