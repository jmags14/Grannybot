"""Where model files and the .env live. Override with GRANNYBOT_MODELS / GRANNYBOT_ENV."""
import os


def models_dir() -> str:
    env = os.getenv("GRANNYBOT_MODELS")
    if env:
        return os.path.expanduser(env)
    for c in (os.path.join(os.getcwd(), "models"), os.path.expanduser("~/grannybot/models")):
        if os.path.isdir(c):
            return c
    return os.path.join(os.getcwd(), "models")


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for c in (os.getenv("GRANNYBOT_ENV", ""), os.path.join(os.getcwd(), ".env"),
              os.path.expanduser("~/grannybot/.env")):
        if c and os.path.exists(c):
            load_dotenv(c)
            return
