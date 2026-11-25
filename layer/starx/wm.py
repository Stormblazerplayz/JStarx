"""Talk to the window manager (labwc) about open windows, using wlrctl."""
import shutil
import subprocess


def _run(args, timeout=2):
    if not shutil.which("wlrctl"):
        return None
    try:
        r = subprocess.run(["wlrctl", *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return None


def windows():
    """List open windows as [{app_id, title}]."""
    out = _run(["toplevel", "list"])
    items = []
    for line in (out or "").splitlines():
        app_id, sep, title = line.partition(":")
        if sep:
            items.append({"app_id": app_id.strip(), "title": title.strip()})
    return items


def focus(app_id):
    return _run(["toplevel", "focus", f"app_id:{app_id}"]) is not None


def close(app_id):
    return _run(["toplevel", "close", f"app_id:{app_id}"]) is not None


def minimize(app_id):
    return _run(["toplevel", "minimize", f"app_id:{app_id}"]) is not None
