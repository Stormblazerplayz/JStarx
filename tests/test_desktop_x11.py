"""Tests for the JStarx desktop on JetPack's X11 session (openbox + StarShell).

The pure parts (window list, screen modes, sound) run everywhere. The smoke test starts the real
session on a virtual screen, and is skipped unless Xvfb, openbox, wmctrl, xcompmgr and GTK with
WebKit2 are installed (they are on a Linux desktop; not in the CI image).

Run: python3 -m pytest -q tests
"""
import importlib
import os
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = os.path.join(ROOT, "layer")
JETPACK = os.path.join(ROOT, "jetpack", "files")
sys.path.insert(0, LAYER)


def fresh(modname):
    top = modname.split(".")[0]
    for name in list(sys.modules):
        if name == top or name.startswith(top + "."):
            del sys.modules[name]
    return importlib.import_module(modname)


# ---------------------------------------------------------------- window list (wmctrl)
WMCTRL = """\
0x00600003 -1 shell.py.Shell.py     vm starx-desktop
0x00800007  0 os.jstarx.settings.JStarxApp  vm Settings
0x00a0000c  0 Navigator.firefox  vm Mozilla Firefox
0x00a00010  0 xterm.XTerm  vm xterm
0x00b00010  0 shell.py.Shell.py     vm starx-overlay
"""


def test_x11_window_list_maps_app_ids_and_hides_the_panels(monkeypatch):
    wm = fresh("starx.wm")
    monkeypatch.setattr(wm.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(wm, "_run", lambda args, timeout=2: WMCTRL if args[:2] == ["wmctrl", "-l"] else "")
    monkeypatch.setattr(wm, "_on_wayland", lambda: False)
    assert wm.windows() == [
        {"app_id": "os.jstarx.settings", "title": "Settings"},
        {"app_id": "firefox", "title": "Mozilla Firefox"},
        {"app_id": "xterm", "title": "xterm"},
    ]


def test_x11_focus_and_close_use_the_window_id(monkeypatch):
    wm = fresh("starx.wm")
    monkeypatch.setattr(wm.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(wm, "_run", lambda args, timeout=2: WMCTRL if args[:2] == ["wmctrl", "-l"] else "")
    monkeypatch.setattr(wm, "_on_wayland", lambda: False)
    calls = []
    monkeypatch.setattr(wm, "_ok", lambda args, timeout=2: calls.append(args) or True)
    assert wm.focus("os.jstarx.settings") and wm.close("xterm")
    assert calls == [["wmctrl", "-i", "-a", "0x00800007"], ["wmctrl", "-i", "-c", "0x00a00010"]]
    assert wm.focus("no.such.app") is False  # never reports success for a window it cannot find


def test_logout_ends_the_right_session(monkeypatch):
    wm = fresh("starx.wm")
    monkeypatch.setattr(wm, "_on_wayland", lambda: False)
    assert wm.logout_command() == ["openbox", "--exit"]
    monkeypatch.setattr(wm, "_on_wayland", lambda: True)
    assert wm.logout_command() == ["labwc", "--exit"]


# ---------------------------------------------------------------- screens (xrandr) and sound (pactl)
XRANDR = """\
Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767
HDMI-0 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+  50.00    59.94
   1280x720      60.00    50.00
DP-0 disconnected (normal left inverted right x axis y axis)
"""


def test_xrandr_lists_connected_screens_and_the_mode_in_use(monkeypatch):
    system = fresh("starx.system")

    class Done:
        returncode, stdout = 0, XRANDR

    monkeypatch.setattr(system, "_run", lambda args, timeout=8: Done() if args[:2] == ["xrandr", "--query"] else None)
    monkeypatch.setattr(system.shutil, "which", lambda name: "/usr/bin/" + name if name == "xrandr" else None)
    out = system.outputs()
    assert [o["name"] for o in out] == ["HDMI-0"]  # the disconnected DP-0 is left out
    assert out[0]["mode"] == "1920x1080@60"
    assert out[0]["modes"] == ["1920x1080", "1280x720"]


def test_pactl_reads_and_sets_the_volume(monkeypatch):
    system = fresh("starx.system")
    monkeypatch.setattr(system.shutil, "which", lambda name: "/usr/bin/" + name if name == "pactl" else None)

    class Out:
        def __init__(self, text):
            self.returncode, self.stdout = 0, text

    answers = {"get-sink-volume": "Volume: front-left: 39322 /  60% / -13.31 dB,   front-right: 39322 /  60%",
               "get-sink-mute": "Mute: yes"}
    sent = []

    def fake_run(args, timeout=8):
        sent.append(args)
        if args[1] in answers:
            return Out(answers[args[1]])
        return Out("")

    monkeypatch.setattr(system, "_run", fake_run)
    assert system.audio_get() == {"available": True, "volume": 60, "muted": True}
    system.audio_set(volume=35, muted=False)
    assert ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "35%"] in sent
    assert ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"] in sent


# ---------------------------------------------------------------- the session files
def test_session_files_are_in_place():
    session = os.path.join(JETPACK, "starx-session-x11")
    assert os.access(session, os.X_OK)
    text = open(session).read()
    assert "exec openbox" in text and "--startup" in text and "xcompmgr" in text
    assert 'GTK_THEME="${GTK_THEME:-JStarx}"' in text
    assert "/etc/jstarx/factory-layer" in text  # the same factory layer as the SD card image
    entry = {}
    for line in open(os.path.join(JETPACK, "jstarx.desktop")):
        if "=" in line:
            k, _, v = line.strip().partition("=")
            entry[k] = v
    assert entry["Type"] == "Application" and entry["Exec"] == "/opt/jstarx/bin/starx-session-x11"


def test_openbox_settings_are_valid_xml_with_the_jstarx_keys():
    tree = ET.parse(os.path.join(JETPACK, "openbox", "rc.xml"))
    ns = {"o": "http://openbox.org/3.4/rc"}
    keys = {k.get("key") for k in tree.getroot().iterfind(".//o:keybind", ns)}
    assert {"W-space", "W-a", "W-c", "W-p", "W-e", "W-b", "W-Return", "Print"} <= keys
    assert tree.getroot().find(".//o:application[@type='normal']/o:maximized", ns) is not None


def test_panels_are_only_drawn_as_layer_shell_when_it_exists():
    # On the SD card image (Wayland) the shell uses gtk-layer-shell; on JetPack it uses X11 window hints.
    source = open(os.path.join(LAYER, "starx", "shell.py")).read()
    assert "LAYER_SHELL = bool(GtkLayerShell.is_supported())" in source
    assert "self._x11_hints(win, name, anchors, size, shell.screen)" in source


# ---------------------------------------------------------------- the real session on a virtual screen
def _gtk_python():
    candidates = [os.environ.get("STARX_PYTHON"), sys.executable, "/usr/bin/python3", "/usr/bin/python3.12"]
    check = ("import gi; gi.require_version('Gtk', '3.0'); gi.require_version('GdkX11', '3.0');"
             "from gi.repository import Gtk, GdkX11; import cairo")
    for path in filter(None, candidates):
        if os.path.exists(path) and subprocess.run([path, "-c", check], stdout=subprocess.DEVNULL,
                                                   stderr=subprocess.DEVNULL).returncode == 0:
            return path
    return None


def _free_display():
    for n in range(90, 100):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
            return f":{n}"
    return None


needs = [shutil.which(t) for t in ("Xvfb", "openbox", "wmctrl", "xcompmgr", "xprop")]
gtk = _gtk_python()


@pytest.mark.skipif(not all(needs) or gtk is None,
                    reason="needs Xvfb, openbox, wmctrl, xcompmgr, xprop and GTK 3 with WebKit2 in Python")
def test_the_desktop_session_shows_its_panels_on_x11(tmp_path):
    display = _free_display()
    assert display, "no free display number for the virtual screen"
    home = tmp_path / "home"
    (home / ".config" / "jstarx").mkdir(parents=True)
    (home / ".config" / "jstarx" / "settings.json").write_text('{"welcome_done": true}')
    runtime = tmp_path / "xdg"
    runtime.mkdir(mode=0o700)
    env = dict(os.environ, DISPLAY=display, HOME=str(home), XDG_RUNTIME_DIR=str(runtime),
               JSTARX_LAYER=LAYER, OPENBOX_CONFIG=os.path.join(JETPACK, "openbox", "rc.xml"),
               STARX_PYTHON=gtk, WEBKIT_DISABLE_COMPOSITING_MODE="1", LIBGL_ALWAYS_SOFTWARE="1",
               PATH=os.path.join(ROOT, "os", "pkgs", "jstarx-core", "bin") + os.pathsep + os.path.join(LAYER, "bin")
               + os.pathsep + os.environ.get("PATH", ""))
    procs = []

    def start(args):
        p = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(p)
        return p

    def windows():
        return subprocess.run(["wmctrl", "-l", "-x"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              universal_newlines=True).stdout

    try:
        start(["Xvfb", display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"])
        deadline = time.time() + 30
        while not os.path.exists("/tmp/.X11-unix/X" + display[1:]) and time.time() < deadline:
            time.sleep(0.2)
        start(["bash", os.path.join(JETPACK, "starx-session-x11")])
        panels = ("starx-desktop", "starx-dock", "starx-island")
        deadline = time.time() + 120
        while time.time() < deadline and not all(p in windows() for p in panels):
            time.sleep(0.5)
        listing = windows()
        assert all(p in listing for p in panels), listing
        # the panels show at once; wait until the shell has reported its pages as loaded (healthy)
        health = os.path.join(str(runtime), "jstarx", "healthy")

        def healthy():
            try:
                return '"healthy": true' in open(health).read()
            except OSError:
                return False

        deadline = time.time() + 90
        while time.time() < deadline and not healthy():
            time.sleep(0.5)
        assert healthy(), "the desktop pages did not finish loading"
        dock = next(line.split()[0] for line in listing.splitlines() if line.endswith("starx-dock"))
        strut = subprocess.run(["xprop", "-id", dock, "_NET_WM_STRUT_PARTIAL"], env=env, stdout=subprocess.PIPE,
                               universal_newlines=True).stdout
        assert "_NET_WM_STRUT_PARTIAL" in strut and ", 0, 0, 0, 0," not in strut.split("=", 1)[1].split(",")[3] + ","
    finally:
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(1)
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
