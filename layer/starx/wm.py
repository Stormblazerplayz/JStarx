"""Talk to the window manager about open windows.

The JStarx SD card image runs labwc (Wayland) and uses wlrctl. JetPack runs an X11 session with
openbox and uses wmctrl (and xdotool to minimize).
"""
import os
import shutil
import subprocess

# Firefox's window class on X11 is "Navigator"; everywhere else the app is called "firefox"
X11_CLASS_ALIASES = {"Navigator": "firefox"}


def _run(args, timeout=2):
    """stdout of a command ('' if it failed), or None if the program is not installed."""
    if not shutil.which(args[0]):
        return None
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ok(args, timeout=2):
    """True only if the program is installed and succeeded."""
    if not shutil.which(args[0]):
        return False
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _on_wayland():
    # a real Wayland display (labwc sets WAYLAND_DISPLAY); having wlrctl installed is not enough
    return bool(os.environ.get("WAYLAND_DISPLAY")) and shutil.which("wlrctl") is not None


def _is_panel(title):
    """The shell's own panels (desktop, dock, island, overlay) are named starx-<panel>."""
    return title.startswith("starx-")


def _x11_windows():
    """Open X11 windows as [{id, app_id, title}], from 'wmctrl -l -x'."""
    items = []
    for line in (_run(["wmctrl", "-l", "-x"]) or "").splitlines():
        parts = line.split(None, 3)  # window id, desktop, WM_CLASS, then "machine title"
        if len(parts) < 3:
            continue
        wm_class = parts[2]  # "os.jstarx.settings.JStarxApp": the app id, then the class
        instance = wm_class.rsplit(".", 1)[0] if "." in wm_class else wm_class
        title_part = parts[3].split(None, 1) if len(parts) > 3 else []
        title = title_part[1] if len(title_part) > 1 else ""
        items.append({"id": parts[0], "app_id": X11_CLASS_ALIASES.get(instance, instance), "title": title})
    return items


def _x11_id(app_id):
    for w in _x11_windows():
        if w["app_id"] == app_id and not _is_panel(w["title"]):
            return w["id"]
    return None


def windows():
    """List open windows as [{app_id, title}]."""
    if _on_wayland():
        out = _run(["wlrctl", "toplevel", "list"])
        items = []
        for line in (out or "").splitlines():
            app_id, sep, title = line.partition(":")
            if sep:
                items.append({"app_id": app_id.strip(), "title": title.strip()})
        return items
    return [{"app_id": w["app_id"], "title": w["title"]} for w in _x11_windows() if not _is_panel(w["title"])]


def focus(app_id):
    if _on_wayland():
        return _ok(["wlrctl", "toplevel", "focus", f"app_id:{app_id}"])
    wid = _x11_id(app_id)
    return wid is not None and _ok(["wmctrl", "-i", "-a", wid])


def close(app_id):
    if _on_wayland():
        return _ok(["wlrctl", "toplevel", "close", f"app_id:{app_id}"])
    wid = _x11_id(app_id)
    return wid is not None and _ok(["wmctrl", "-i", "-c", wid])


def minimize(app_id):
    if _on_wayland():
        return _ok(["wlrctl", "toplevel", "minimize", f"app_id:{app_id}"])
    wid = _x11_id(app_id)
    return wid is not None and _ok(["xdotool", "windowminimize", wid])


def logout_command():
    """The command that ends the desktop session."""
    return ["labwc", "--exit"] if _on_wayland() else ["openbox", "--exit"]
