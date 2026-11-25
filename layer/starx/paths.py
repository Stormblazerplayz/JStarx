"""Where JStarx keeps things."""
import os

LAYER = os.environ.get("JSTARX_LAYER") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(LAYER, "web")
ASSETS = os.path.join(LAYER, "assets")

HOME = os.path.expanduser("~")
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "jstarx")
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "jstarx")
RUNTIME = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "jstarx")

USER_APPS = os.path.join(DATA, "apps")          # web apps installed from the Star Store
SETTINGS_FILE = os.path.join(CONFIG, "settings.json")
HOME_FILE = os.path.join(CONFIG, "home.json")
SHELL_SOCKET = os.path.join(RUNTIME, "shell.sock")
HEALTH_FILE = os.path.join(RUNTIME, "healthy")

# Written by root services, read by the shell (event driven, no polling)
RUN_SYSTEM = os.environ.get("JSTARX_RUN", "/run/jstarx")
STATE_SYSTEM = os.environ.get("JSTARX_STATE", "/var/lib/jstarx")
STARXD_SOCKET = os.environ.get("STARXD_SOCKET", "/run/starxd.sock")
STARAI_SOCKET = os.environ.get("STARAI_SOCKET", "/run/starai.sock")
SPARK_URL = os.environ.get("SPARK_URL", "http://127.0.0.1:8090")


def ensure_user_dirs():
    for d in (CONFIG, DATA, USER_APPS, RUNTIME):
        os.makedirs(d, exist_ok=True)
