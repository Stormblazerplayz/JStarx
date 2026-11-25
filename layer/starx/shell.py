"""StarShell main process: desktop, dynamic island, dock and the overlay (launchpad, start menu,
control center, Spark). Run with:  python3 -m starx.shell
"""
import json
import os
import signal
import socket
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

try:
    import cairo  # noqa: E402
    gi.require_foreign("cairo")
except Exception:  # input regions are optional
    cairo = None

from . import apps, daemon, paths, wm  # noqa: E402
from .api import Api  # noqa: E402
from .bridge import Bridge, FileWatch  # noqa: E402
from .notify import NotificationServer  # noqa: E402

Edge, Layer, KB = GtkLayerShell.Edge, GtkLayerShell.Layer, GtkLayerShell.KeyboardMode
ISLAND_W, ISLAND_H = 620, 52


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class Surface:
    def __init__(self, shell, name, page, layer, anchors, size=None, exclusive=0, keyboard=KB.NONE, margins=None, visible=True):
        self.shell, self.name = shell, name
        win = Gtk.Window(title=f"starx-{name}")
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, f"starx-{name}")
        GtkLayerShell.set_layer(win, layer)
        for edge in anchors:
            GtkLayerShell.set_anchor(win, edge, True)
        for edge, px in (margins or {}).items():
            GtkLayerShell.set_margin(win, edge, px)
        GtkLayerShell.set_exclusive_zone(win, exclusive)
        GtkLayerShell.set_keyboard_mode(win, keyboard)
        # Shell surfaces are opaque: each one paints the wallpaper that sits behind it, so it looks
        # see-through but never needs alpha blending (more reliable, and cheaper for the compositor).
        if size:
            win.set_size_request(*size)
        ctx = {"surface": name, "screen": shell.screen, "role": "shell"}
        self.view = shell.bridge.make_view(page, ctx, transparent=False)
        win.add(self.view)
        self.win = win
        self.size = size
        win.connect("map-event", lambda *a: self.repaint())
        if visible:
            win.show_all()

    def repaint(self):
        from .bridge import run_js
        for delay in (80, 400):
            GLib.timeout_add(delay, lambda: (run_js(self.view, "window.StarX && StarX.repaint()"), False)[1])
        return False

    def resize(self, w, h):
        self.size = (int(w), int(h))
        self.win.set_size_request(*self.size)
        self.win.resize(*self.size)

    def set_input(self, rects):
        if cairo is None:
            return
        if not rects:
            self.win.input_shape_combine_region(None)
            return
        region = cairo.Region([cairo.RectangleInt(int(r["x"]), int(r["y"]), max(1, int(r["w"])), max(1, int(r["h"]))) for r in rects])
        self.win.input_shape_combine_region(region)

    def exclusive(self, px):
        GtkLayerShell.set_exclusive_zone(self.win, int(px))


class ShellApi(Api):
    def __init__(self, shell):
        super().__init__(role="shell")
        self.shell = shell

    # panels in the overlay
    def m_shell_open(self, panel, data=None, view=None):
        self.shell.open_overlay(panel, data)
        return True

    def m_shell_close(self, view=None):
        self.shell.close_overlay()
        return True

    def m_shell_input(self, surface, rects=None, view=None):
        s = self.shell.surfaces.get(surface)
        if s:
            s.set_input(rects)
        return True

    def m_shell_size(self, surface, w, h, exclusive=None, view=None):
        s = self.shell.surfaces.get(surface)
        if s:
            s.resize(w, h)
            if exclusive is not None:
                s.exclusive(exclusive)
        return True

    def m_shell_hint(self, text=None, icon=None, view=None):
        self.shell.bridge.emit("hint", {"text": text, "icon": icon}, [self.shell.surfaces["island"].view])
        return True

    def m_shell_dim(self, on=False, view=None):
        views = [self.shell.surfaces["island"].view, self.shell.surfaces["dock"].view]
        self.shell.bridge.emit("dim", {"on": bool(on)}, views)
        return True

    def m_shell_state(self, view=None):
        return self.shell.state()

    def m_shell_ready(self, view=None):
        self.shell.surface_ready(view)
        return True

    # windows
    def m_windows_list(self, view=None):
        return self.shell.windows

    def m_windows_focus(self, app_id, view=None):
        return wm.focus(app_id)

    def m_windows_close(self, app_id, view=None):
        return wm.close(app_id)

    def m_apps_launch(self, id, view=None):
        res = super().m_apps_launch(id)
        self.shell.watch_launch(id)
        return res

    # notifications
    def m_notifications_list(self, view=None):
        return self.shell.notes.history

    def m_notifications_dismiss(self, id, view=None):
        self.shell.notes.close(int(id))
        return True

    def m_notifications_action(self, id, key, view=None):
        self.shell.notes.invoke(int(id), key)
        return True

    def m_notifications_clear(self, view=None):
        self.shell.notes.clear()
        return True


class Shell:
    def __init__(self):
        display = Gdk.Display.get_default()
        if display is None:
            print("StarShell needs a Wayland display", file=sys.stderr)
            sys.exit(1)
        mon = display.get_primary_monitor() or display.get_monitor(0)
        geo = mon.get_geometry()
        self.screen = {"width": geo.width, "height": geo.height, "scale": mon.get_scale_factor()}
        self.api = ShellApi(self)
        self.bridge = Bridge(self.api)
        self.windows = []
        self.idle = False
        self.ready_views = set()
        self.launching = {}
        self.status_cache = {}
        self.started = time.time()
        self.overlay_panel = None

        self.notes = NotificationServer(self._on_note, lambda nid: self.bridge.emit("notification-closed", nid))

        W, H = self.screen["width"], self.screen["height"]
        dock_h = self._dock_zone()
        self.surfaces = {
            "desktop": Surface(self, "desktop", "shell/desktop.html", Layer.BACKGROUND, [Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT],
                               exclusive=-1, keyboard=KB.ON_DEMAND),
            "dock": Surface(self, "dock", "shell/dock.html", Layer.TOP, [Edge.BOTTOM], size=(min(W, 900), dock_h),
                            exclusive=dock_h, keyboard=KB.NONE),
            "island": Surface(self, "island", "shell/island.html", Layer.TOP, [Edge.TOP], size=(ISLAND_W, ISLAND_H),
                              exclusive=ISLAND_H, keyboard=KB.NONE),
            "overlay": Surface(self, "overlay", "shell/overlay.html", Layer.OVERLAY, [Edge.TOP, Edge.BOTTOM, Edge.LEFT, Edge.RIGHT],
                               exclusive=-1, keyboard=KB.EXCLUSIVE, visible=False),
        }
        self.surfaces["overlay"].win.realize()

        self._watches = [
            FileWatch(paths.CONFIG, ["settings.json"], self._settings_changed),
            FileWatch(paths.USER_APPS, None, lambda: self.bridge.emit("apps-changed")),
            FileWatch(paths.DATA, ["nix-apps.json"], lambda: self.bridge.emit("apps-changed")),
        ]
        self._watches.append(FileWatch(paths.RUNTIME, ["cast.json"], self._status_changed, delay_ms=300))
        if os.path.isdir(paths.RUN_SYSTEM):
            self._watches.append(FileWatch(paths.RUN_SYSTEM, None, self._status_changed, delay_ms=300))
        self._status_changed(initial=True)

        self._start_socket()
        GLib.timeout_add_seconds(3, self._poll_windows)
        GLib.timeout_add_seconds(20, self._report_health)
        GLib.timeout_add(2500, self._maybe_welcome)

    def _maybe_welcome(self):
        if not self.api.settings.get("welcome_done") and os.environ.get("STARX_NO_WELCOME") != "1":
            self.open_overlay("welcome")
        return False

    # ---------------------------------------------------------------- dock size
    def _dock_zone(self):
        # bar (icon + 16 padding) + 10 bottom gap + 22 headroom for magnify/bounce
        return int(self.api.settings.get("dock.size")) + 48

    # ---------------------------------------------------------------- settings
    def _settings_changed(self):
        self.api.settings.data = self.api.settings.load()
        s = self.api.settings.get()
        dock = self.surfaces["dock"]
        dock.resize(dock.size[0], self._dock_zone())
        dock.exclusive(self._dock_zone())
        self.bridge.emit("settings-changed", s)

    # ---------------------------------------------------------------- overlay
    def open_overlay(self, panel, data=None):
        ov = self.surfaces["overlay"]
        self.overlay_panel = panel
        ov.win.show_all()
        ov.repaint()
        self.bridge.emit("overlay-open", {"panel": panel, "data": data}, [ov.view])
        self.bridge.emit("overlay-state", {"panel": panel})

    def close_overlay(self):
        self.overlay_panel = None
        self.surfaces["overlay"].win.hide()
        self.bridge.emit("overlay-state", {"panel": None})

    def toggle_overlay(self, panel, data=None):
        if self.overlay_panel == panel:
            self.bridge.emit("overlay-close-request", None, [self.surfaces["overlay"].view])
        else:
            self.open_overlay(panel, data)

    # ---------------------------------------------------------------- notifications
    def _on_note(self, note):
        if self.api.settings.get("island.dnd") and note.get("urgency", 1) < 2:
            self.bridge.emit("notification-silent", note)
            return
        self.bridge.emit("notification", note)

    def notify(self, summary, body="", app="JStarx", icon="jstarx"):
        return self.notes.add({"app": app, "summary": summary, "body": body, "icon": icon, "actions": [], "urgency": 1})

    # ---------------------------------------------------------------- system status files
    def _status_changed(self, initial=False):
        changed = {}
        for name in ("ai", "update", "repair", "power", "spark", "cast"):
            st = _read_json(os.path.join(paths.RUNTIME, "cast.json")) if name == "cast" else daemon.status(name)
            if st != self.status_cache.get(name):
                old = self.status_cache.get(name)
                self.status_cache[name] = st
                changed[name] = st
                if not initial:
                    self._status_note(name, old or {}, st)
        if changed:
            self.bridge.emit("status", changed)

    def _status_note(self, name, old, new):
        if name == "update" and new.get("state") == "updated" and old.get("state") != "updated":
            self.notify("JStarx updated", f"Now on version {new.get('version', '?')}. Restart apps to use it.", icon="refresh")
        elif name == "update" and new.get("state") == "rolled-back" and old.get("state") != "rolled-back":
            self.notify("Update undone", "JStarx went back to the previous version because the new one had a problem.", icon="shield")
        elif name == "repair" and new.get("time") != old.get("time") and new.get("fixed"):
            self.notify("Auto-repair fixed JStarx", f"{len(new['fixed'])} problem(s) fixed.", icon="shield")
        elif name == "ai":
            done_old = {j["id"] for j in old.get("jobs", []) if j.get("state") == "finished"}
            for j in new.get("jobs", []):
                if j.get("state") == "finished" and j["id"] not in done_old:
                    self.notify("AI job finished", j.get("name", "Job"), app="AI Center", icon="chip")
        elif name == "cast" and new.get("state") == "casting" and old.get("state") != "casting":
            self.notify("Showing JStarx on " + new.get("device", "a wireless display"), "No screen was plugged in, so JStarx found one on Wi-Fi.", app="StarCast", icon="display")
        elif name == "spark" and new.get("state") == "ready" and old.get("state") != "ready":
            self.notify("Spark 1 is ready", "Your assistant's model is installed. Say hi!", app="Spark", icon="sparkle")

    # ---------------------------------------------------------------- windows
    def _poll_windows(self):
        if not self.idle:
            self._refresh_windows()
        return True

    def _refresh_windows(self):
        wins = wm.windows()
        if wins != self.windows:
            self.windows = wins
            self.bridge.emit("windows", wins)
            open_ids = {w["app_id"] for w in wins}
            for aid, rec_app_id in list(self.launching.items()):
                if rec_app_id in open_ids:
                    self.launching.pop(aid, None)
                    self.bridge.emit("launched", aid)
        return False

    def watch_launch(self, app_id):
        rec = apps.find(app_id)
        if not rec:
            return
        self.launching[app_id] = rec["app_id"]
        deadline = time.time() + 10

        def fast():
            self._refresh_windows()
            if app_id not in self.launching:
                return False
            if time.time() > deadline:
                self.launching.pop(app_id, None)
                self.bridge.emit("launched", app_id)
                return False
            return True
        GLib.timeout_add(500, fast)

    # ---------------------------------------------------------------- health (used by auto-repair)
    def surface_ready(self, view):
        self.ready_views.add(id(view))

    def _report_health(self):
        healthy = len(self.ready_views) >= 3
        state = {"healthy": healthy, "pid": os.getpid(), "time": time.time(), "surfaces": len(self.ready_views)}
        try:
            os.makedirs(paths.RUNTIME, exist_ok=True)
            with open(paths.HEALTH_FILE, "w") as f:
                json.dump(state, f)
        except OSError:
            pass
        if healthy:
            try:
                daemon.starxd("session_healthy", timeout=5)
            except daemon.DaemonError:
                pass
        return False

    def state(self):
        return {"screen": self.screen, "windows": self.windows, "notifications": self.notes.history,
                "status": self.status_cache, "overlay": self.overlay_panel, "idle": self.idle}

    # ---------------------------------------------------------------- control socket (starx-ctl)
    def _start_socket(self):
        os.makedirs(paths.RUNTIME, exist_ok=True)
        try:
            os.unlink(paths.SHELL_SOCKET)
        except OSError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(paths.SHELL_SOCKET)
        os.chmod(paths.SHELL_SOCKET, 0o600)
        self.sock.listen(8)
        self.sock.setblocking(False)
        GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self._accept)

    def _accept(self, *_):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(2)
            data = conn.recv(65536).decode("utf-8", "replace").strip()
            reply = self.command(data)
            conn.sendall((json.dumps(reply) + "\n").encode())
            conn.close()
        except OSError:
            pass
        return True

    def command(self, line):
        cmd, _, arg = line.partition(" ")
        if cmd in ("launchpad", "start", "control", "spark", "power", "welcome"):
            self.toggle_overlay(cmd, arg or None)
        elif cmd == "close":
            self.bridge.emit("overlay-close-request", None, [self.surfaces["overlay"].view])
        elif cmd == "osd":
            self.bridge.emit("osd", {"kind": arg}, [self.surfaces["island"].view])
        elif cmd == "apps-changed":
            self.bridge.emit("apps-changed")
        elif cmd == "reload":
            for s in self.surfaces.values():
                s.view.reload()
        elif cmd == "idle":
            self.idle = arg.strip() == "on"
            self.bridge.emit("idle", self.idle)
        elif cmd == "notify":
            try:
                n = json.loads(arg)
                self.notify(n.get("summary", ""), n.get("body", ""), n.get("app", "JStarx"), n.get("icon", "jstarx"))
            except ValueError:
                return {"ok": False, "error": "bad json"}
        elif cmd == "health":
            return {"ok": True, "healthy": len(self.ready_views) >= 3, "uptime": time.time() - self.started}
        elif cmd == "js" and os.environ.get("STARX_TEST") == "1":
            surface, _, code = arg.partition(" ")
            s = self.surfaces.get(surface)
            if not s:
                return {"ok": False, "error": "no such surface"}
            from .bridge import run_js
            run_js(s.view, code)
        elif cmd == "launch":
            try:
                self.api.m_apps_launch(arg.strip())
            except Exception as e:
                return {"ok": False, "error": str(e)}
        else:
            return {"ok": False, "error": f"unknown command {cmd}"}
        return {"ok": True}


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    Shell()
    Gtk.main()


if __name__ == "__main__":
    main()
