"""Where model files live. Set GRANNYBOT_MODELS to override."""
import os


def models_dir() -> str:
    env = os.getenv("GRANNYBOT_MODELS")
    if env:
        return os.path.expanduser(env)
    for candidate in (os.path.join(os.getcwd(), "models"),
                      os.path.expanduser("~/grannybot/models")):
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(os.getcwd(), "models")


def model_path(name: str) -> str:
    """Full path for a model file; YOLO names that aren't downloaded yet are returned as-is
    so Ultralytics can download them automatically."""
    p = os.path.join(models_dir(), name)
    if os.path.exists(p) or name.endswith(".task"):
        return p
    return name
