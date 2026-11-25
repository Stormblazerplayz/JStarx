"""The list of apps the shell knows about, and how to start them."""
import json
import os
import shlex
import subprocess

from . import paths

BUILTIN = [
    # id, name, kind, target, app_id, icon, category, description
    ("firefox", "Firefox", "exec", ["firefox"], "firefox", "theme:firefox|globe", "Internet", "Browse the web."),
    ("claude", "Claude", "exec", ["starx-claude"], "claude", "claude", "AI", "Chat with Claude by Anthropic."),
    ("spark", "Spark", "web", "apps/spark/index.html", "os.jstarx.spark", "spark", "AI", "Spark 1, your built-in assistant."),
    ("ai", "AI Center", "web", "apps/ai/index.html", "os.jstarx.ai", "ai", "AI", "Run and train AI models 24/7."),
    ("settings", "Settings", "web", "apps/settings/index.html", "os.jstarx.settings", "settings", "System", "Wi-Fi, look, power, updates and repair."),
    ("store", "Star Store", "web", "apps/store/index.html", "os.jstarx.store", "store", "System", "Install official JStarx apps."),
    ("terminal", "Terminal", "exec", ["foot"], "foot", "terminal", "System", "Type commands."),
    ("snake", "Star Snake", "web", "games/snake/index.html", "os.jstarx.snake", "snake", "Games", "Eat the stars, don't hit yourself."),
    ("dodge", "Nebula Dodge", "web", "games/dodge/index.html", "os.jstarx.dodge", "dodge", "Games", "Fly through the asteroid field."),
    ("breaker", "Starbreaker", "web", "games/breaker/index.html", "os.jstarx.breaker", "breaker", "Games", "Smash the glass bricks."),
]

NIX_APPS_FILE = os.path.join(paths.DATA, "nix-apps.json")


def _icon_url(spec):
    """'theme:firefox|globe' -> themed icon file if found, else our globe icon."""
    fallback = spec
    if spec.startswith("theme:"):
        names, _, fallback = spec[6:].partition("|")
        for name in names.split(","):
            found = lookup_theme_icon(name)
            if found:
                return "file://" + found
    if spec.startswith("/"):
        return "file://" + spec
    return "file://" + os.path.join(paths.WEB, "icons", f"{fallback or 'globe'}.svg")


def lookup_theme_icon(name, size=128):
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        theme = Gtk.IconTheme.get_default()
        if theme is None:
            return None
        info = theme.lookup_icon(name, size, 0)
        return info.get_filename() if info else None
    except Exception:
        return None


def _builtin_records():
    out = []
    for aid, name, kind, target, app_id, icon, cat, desc in BUILTIN:
        out.append({
            "id": aid, "name": name, "kind": kind, "app_id": app_id, "icon": _icon_url(icon if ":" in icon else icon),
            "category": cat, "description": desc, "builtin": True,
            "exec": target if kind == "exec" else None,
            "entry": os.path.join(paths.WEB, target) if kind == "web" else None,
        })
    return out


def _user_web_apps():
    out = []
    try:
        names = sorted(os.listdir(paths.USER_APPS))
    except OSError:
        return out
    for name in names:
        manifest = os.path.join(paths.USER_APPS, name, "app.json")
        try:
            with open(manifest) as f:
                m = json.load(f)
            entry = os.path.join(paths.USER_APPS, name, m.get("entry", "index.html"))
            icon = os.path.join(paths.USER_APPS, name, m.get("icon", "icon.svg"))
            out.append({
                "id": m["id"], "name": m.get("name", m["id"]), "kind": "web", "app_id": "os.jstarx." + m["id"],
                "icon": "file://" + icon if os.path.exists(icon) else _icon_url("globe"),
                "category": m.get("category", "Apps"), "description": m.get("description", ""), "builtin": False,
                "exec": None, "entry": entry, "version": m.get("version", "1.0.0"), "source": "store",
            })
        except (OSError, ValueError, KeyError):
            continue
    return out


def _nix_apps():
    try:
        with open(NIX_APPS_FILE) as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for m in items if isinstance(items, list) else []:
        try:
            out.append({
                "id": m["id"], "name": m["name"], "kind": "exec", "app_id": m.get("app_id", m["id"]),
                "icon": _icon_url(m.get("icon", "box")), "category": m.get("category", "Apps"),
                "description": m.get("description", ""), "builtin": False,
                "exec": m["exec"] if isinstance(m["exec"], list) else shlex.split(m["exec"]),
                "entry": None, "source": "store-nix",
            })
        except (KeyError, TypeError):
            continue
    return out


def all_apps():
    seen, out = set(), []
    for rec in _builtin_records() + _user_web_apps() + _nix_apps():
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        out.append(rec)
    return out


def find(app_id):
    for rec in all_apps():
        if rec["id"] == app_id:
            return rec
    return None


def launch(rec, extra_env=None):
    """Start an app in its own process (a crash never takes the shell down)."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    if rec["kind"] == "web":
        argv = shlex.split(os.environ.get("STARX_APP_BIN", "starx-app")) + [rec["id"]]
    else:
        argv = list(rec["exec"])
    try:
        subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=paths.HOME)
        return True
    except OSError as e:
        return str(e)
