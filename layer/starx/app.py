"""Window host for JStarx web apps (Settings, Star Store, AI Center, Spark, games, store apps).

Run with:  python3 -m starx.app <app-id>
Each app is its own process and its own single-instance GTK application.
"""
import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import apps, paths  # noqa: E402
from .api import Api, _notify_shell  # noqa: E402
from .bridge import Bridge, FileWatch  # noqa: E402

SIZES = {"settings": (1100, 740), "store": (1060, 740), "ai": (1120, 760), "spark": (760, 820),
         "snake": (980, 760), "dodge": (980, 760), "breaker": (980, 760)}

CSS = b"""
window.starx-app { background: #140430; }
window.starx-app decoration { border-radius: 14px 14px 0 0;
  box-shadow: 0 18px 50px rgba(8,0,24,.65), 0 0 0 1px rgba(255,255,255,.14); }
window.starx-app headerbar { background-image: linear-gradient(180deg, #2B0B57, #1B063D); background-color: #1B063D;
  border: none; box-shadow: inset 0 -1px rgba(255,255,255,.08), inset 0 1px rgba(255,255,255,.12);
  color: #F6F0FF; min-height: 40px; padding: 0 8px; border-radius: 14px 14px 0 0; }
window.starx-app headerbar .title { font-weight: 700; color: #F6F0FF; font-family: Inter, sans-serif; }
window.starx-app headerbar .subtitle { color: rgba(246,240,255,.6); }
window.starx-app headerbar button.titlebutton { background: rgba(255,255,255,.10); border-radius: 99px; min-width: 22px;
  min-height: 22px; margin: 0 3px; padding: 2px; color: #F6F0FF; border: none; box-shadow: none; -gtk-icon-shadow: none; }
window.starx-app headerbar button.titlebutton:hover { background: #FF8A00; color: #1A0A00; }
window.starx-app headerbar button.titlebutton.close:hover { background: #FF6B81; color: #fff; }
"""


class AppApi(Api):
    def __init__(self, app_id, host):
        super().__init__(role="app", app_id=app_id)
        self.host = host

    def m_window_close(self, view=None):
        self.host.win.close()
        return True

    def m_window_minimize(self, view=None):
        self.host.win.iconify()
        return True

    def m_window_title(self, title, view=None):
        self.host.header.set_subtitle(str(title)[:80])
        return True

    def m_window_fullscreen(self, on=None, view=None):
        on = (not self.host.fullscreen) if on is None else bool(on)
        (self.host.win.fullscreen if on else self.host.win.unfullscreen)()
        self.host.fullscreen = on
        return on

    def m_app_info(self, view=None):
        return self.host.rec

    def m_shell_open(self, panel, data=None, view=None):
        _notify_shell(panel)
        return True


class AppHost:
    def __init__(self, app, rec):
        self.app, self.rec = app, rec
        self.fullscreen = False
        self.api = AppApi(rec["id"], self)
        self.bridge = Bridge(self.api)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gtk.Window().get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = Gtk.ApplicationWindow(application=app)
        win.get_style_context().add_class("starx-app")
        w, h = SIZES.get(rec["id"], (1000, 720))
        win.set_default_size(w, h)
        header = Gtk.HeaderBar(title=rec["name"], show_close_button=True)
        header.set_decoration_layout("icon:minimize,maximize,close")
        icon = self._icon_pixbuf(rec, 22)
        if icon:
            win.set_icon(self._icon_pixbuf(rec, 128))
            header.pack_start(Gtk.Image.new_from_pixbuf(icon))
        win.set_titlebar(header)
        self.header = header

        page = os.path.relpath(rec["entry"], paths.WEB) if rec["entry"].startswith(paths.WEB) else None
        ctx = {"surface": "app", "app": {k: v for k, v in rec.items() if k != "exec"}, "role": "app"}
        if page:
            view = self.bridge.make_view(page, ctx, transparent=False)
        else:  # store-installed app outside the layer: load by absolute path
            view = self.bridge.make_view(os.path.relpath(rec["entry"], paths.WEB), ctx, transparent=False)
        win.add(view)
        win.connect("key-press-event", self._on_key)
        win.show_all()
        self.win = win
        self.view = view
        self._watch = FileWatch(paths.CONFIG, ["settings.json"], self._settings_changed)

    @staticmethod
    def _icon_pixbuf(rec, size):
        icon = (rec.get("icon") or "").replace("file://", "")
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_size(icon, size, size) if icon else None
        except GLib.Error:
            return None

    def _settings_changed(self):
        self.api.settings.data = self.api.settings.load()
        self.bridge.emit("settings-changed", self.api.settings.get())

    def _on_key(self, _w, event):
        from gi.repository import Gdk
        if event.keyval == Gdk.KEY_F11:
            self.api.m_window_fullscreen()
            return True
        if event.keyval in (Gdk.KEY_w, Gdk.KEY_q) and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.win.close()
            return True
        return False


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    if len(sys.argv) < 2:
        print("usage: python3 -m starx.app <app-id>", file=sys.stderr)
        sys.exit(2)
    rec = apps.find(sys.argv[1])
    if not rec or rec["kind"] != "web":
        print(f"no JStarx web app called {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)
    GLib.set_prgname(rec["app_id"])
    GLib.set_application_name(rec["name"])
    app = Gtk.Application(application_id=rec["app_id"], flags=Gio.ApplicationFlags.FLAGS_NONE)
    state = {}

    def activate(a):
        if "host" in state:
            state["host"].win.present()
            return
        state["host"] = AppHost(a, rec)

    app.connect("activate", activate)
    sys.exit(app.run([sys.argv[0]]))


if __name__ == "__main__":
    main()
