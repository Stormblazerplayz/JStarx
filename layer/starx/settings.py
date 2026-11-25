"""User settings with self-repair.

Settings live in ~/.config/jstarx/settings.json. Every load is checked against
DEFAULTS: wrong types or unknown values are replaced, and a broken file is
restored from the last good backup (or defaults). What was fixed is reported,
so Settings -> Repair can show it.
"""
import copy
import json
import os
import tempfile

from . import paths

DEFAULTS = {
    "user": {"name": "Storm"},
    "appearance": {
        "wallpaper": "nebula",          # nebula | aurora | midnight | sunset
        "accent": "mix",                # mix | purple | orange
        "glass": "high",                # high | medium | low | off
        "motion": "full",               # full | reduced | off
        "bounce": 0.6,                  # 0.0 - 1.0
        "icon_size": 64,
    },
    "dock": {
        "size": 54,
        "magnify": True,
        "autohide": False,
        "pinned": ["firefox", "spark", "claude", "store", "settings"],
    },
    "island": {"seconds": False, "ai_activity": True, "notifications": True, "dnd": False},
    "launchpad": {"columns": 7},
    "clock": {"h24": True},
    "power": {"screen_off_min": 5, "dim_min": 3},
    "spark": {
        "model_url": "https://github.com/Stormblazerplayz/JStarx/releases/download/spark-1/",
        "threads": 4,
        "ctx": 2048,
        "personality": "You are Spark 1, the friendly built-in assistant of JStarx OS. Keep answers short and clear.",
    },
    "updates": {"auto": True, "branch": "main", "interval_h": 6},
    "cast": {"auto": True, "device": "", "fps": 15, "resolution": "1280x720"},
    "welcome_done": False,
}

CHOICES = {
    "appearance.wallpaper": ["nebula", "aurora", "midnight", "sunset"],
    "appearance.accent": ["mix", "purple", "orange"],
    "appearance.glass": ["high", "medium", "low", "off"],
    "appearance.motion": ["full", "reduced", "off"],
    "cast.resolution": ["854x480", "1280x720", "1920x1080"],
}
RANGES = {
    "appearance.bounce": (0.0, 1.0),
    "appearance.icon_size": (40, 96),
    "dock.size": (36, 80),
    "launchpad.columns": (4, 10),
    "power.screen_off_min": (0, 240),
    "power.dim_min": (0, 240),
    "spark.threads": (1, 16),
    "spark.ctx": (256, 32768),
    "updates.interval_h": (1, 168),
    "cast.fps": (5, 30),
}


def _validate(data, defaults, prefix, fixes):
    """Return a clean copy of data shaped like defaults."""
    out = {}
    if not isinstance(data, dict):
        fixes.append(f"{prefix or 'settings'}: not a section, reset")
        return copy.deepcopy(defaults)
    for key, dval in defaults.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in data:
            out[key] = copy.deepcopy(dval)
            continue
        val = data[key]
        if isinstance(dval, dict):
            out[key] = _validate(val, dval, path, fixes)
        elif isinstance(dval, bool):
            if isinstance(val, bool):
                out[key] = val
            else:
                out[key] = dval
                fixes.append(f"{path}: expected on/off, reset")
        elif isinstance(dval, (int, float)):
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                out[key] = dval
                fixes.append(f"{path}: expected a number, reset")
            else:
                lo, hi = RANGES.get(path, (float("-inf"), float("inf")))
                v = min(hi, max(lo, val))
                if v != val:
                    fixes.append(f"{path}: {val} out of range, clamped")
                out[key] = type(dval)(v) if isinstance(dval, int) and not isinstance(dval, bool) else float(v)
        elif isinstance(dval, list):
            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                out[key] = val
            else:
                out[key] = copy.deepcopy(dval)
                fixes.append(f"{path}: expected a list, reset")
        else:  # string
            if isinstance(val, str) and (path not in CHOICES or val in CHOICES[path]):
                out[key] = val
            else:
                out[key] = dval
                fixes.append(f"{path}: invalid value, reset")
    return out


def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Settings:
    def __init__(self, path=None):
        self.path = path or paths.SETTINGS_FILE
        self.backup = self.path + ".bak"
        self.fixes = []
        self.data = self.load()

    def load(self):
        self.fixes = []
        raw = None
        for candidate, label in ((self.path, "settings"), (self.backup, "backup")):
            try:
                with open(candidate) as f:
                    raw = json.load(f)
                if label == "backup":
                    self.fixes.append("settings.json was damaged, restored from backup")
                break
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                self.fixes.append(f"{label} file was damaged")
                continue
        if raw is None:
            raw = {}
        data = _validate(raw, DEFAULTS, "", self.fixes)
        if self.fixes or not os.path.exists(self.path):
            self._write(data)
        return data

    def _write(self, data):
        atomic_write_json(self.path, data)
        try:
            atomic_write_json(self.backup, data)
        except OSError:
            pass

    def get(self, path=None):
        if not path:
            return copy.deepcopy(self.data)
        node = self.data
        for part in path.split("."):
            node = node[part]
        return copy.deepcopy(node)

    def set(self, path, value):
        parts = path.split(".")
        candidate = copy.deepcopy(self.data)
        node = candidate
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                raise KeyError(path)
            node = node[part]
        if parts[-1] not in node:
            raise KeyError(path)
        node[parts[-1]] = value
        fixes = []
        clean = _validate(candidate, DEFAULTS, "", fixes)
        if fixes:
            raise ValueError("; ".join(fixes))
        self.data = clean
        self._write(clean)
        return self.get()

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self._write(self.data)
        return self.get()


DEFAULT_HOME = {
    "items": [
        {"type": "folder", "id": "internet", "name": "Internet", "apps": ["firefox", "claude"]},
        {"type": "folder", "id": "ai", "name": "AI", "apps": ["spark", "ai"]},
        {"type": "folder", "id": "games", "name": "Games", "apps": ["snake", "dodge", "breaker"]},
        {"type": "folder", "id": "system", "name": "System", "apps": ["settings", "store", "terminal"]},
    ]
}


def load_home(path=None):
    """Home screen layout (folders of apps). Repaired if broken."""
    path = path or paths.HOME_FILE
    try:
        with open(path) as f:
            data = json.load(f)
        items = data["items"]
        assert isinstance(items, list)
        clean = []
        for it in items:
            if it.get("type") == "folder" and isinstance(it.get("apps"), list):
                clean.append({"type": "folder", "id": str(it.get("id") or f"f{len(clean)}"),
                              "name": str(it.get("name") or "Folder")[:24],
                              "apps": [str(a) for a in it["apps"]]})
            elif it.get("type") == "app" and it.get("id"):
                clean.append({"type": "app", "id": str(it["id"])})
        return {"items": clean}
    except (OSError, ValueError, KeyError, AssertionError, AttributeError, TypeError):
        save_home(DEFAULT_HOME, path)
        return copy.deepcopy(DEFAULT_HOME)


def save_home(layout, path=None):
    atomic_write_json(path or paths.HOME_FILE, layout)
