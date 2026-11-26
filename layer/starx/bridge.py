"""WebKit views + the JS <-> Python bridge used by the shell and all JStarx apps."""
import json
import os
import subprocess
import threading
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:  # Ubuntu 18.04 (JetPack 4.6.1) only has WebKit2GTK 4.0
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, Gio, GLib, WebKit2  # noqa: E402

from . import paths  # noqa: E402

DEV = os.environ.get("STARX_DEVTOOLS") == "1"


def _js_literal(obj):
    return json.dumps(obj, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def run_js(view, script):
    try:
        view.evaluate_javascript(script, -1, None, None, None, None, None)
    except (AttributeError, TypeError):
        view.run_javascript(script, None, None, None)


def open_external(url):
    """Links to the internet open in Firefox, never inside a shell surface."""
    for cmd in (["firefox", "--new-tab", url], ["xdg-open", url]):
        try:
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


class Bridge:
    """Owns the web views of one process and routes calls to an Api object."""

    def __init__(self, api):
        self.api = api
        self.views = []
        self._first = None
        api.bridge = self

    # ---------- views ----------
    def make_view(self, page, context, transparent=True):
        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("starx")
        ucm.connect("script-message-received::starx", self._on_message)
        ctx = {
            "web": "file://" + paths.WEB,
            "assets": "file://" + paths.ASSETS,
            "settings": self.api.settings.get(),
            **context,
        }
        script = "window.STARX_CONTEXT = " + _js_literal(ctx) + ";"
        ucm.add_script(WebKit2.UserScript.new(script, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                              WebKit2.UserScriptInjectionTime.START, None, None))
        kwargs = {"user_content_manager": ucm}
        if self._first is None:
            try:  # smallest memory caches: every JStarx page is a local file
                WebKit2.WebContext.get_default().set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
            except (AttributeError, TypeError):
                pass
        if self._first is not None:
            kwargs["related_view"] = self._first  # share one web process: less memory, faster start
        view = WebKit2.WebView(**kwargs)
        if self._first is None:
            self._first = view
        s = view.get_settings()
        gpu = os.environ.get("STARX_GPU", "never")
        s.set_property("hardware-acceleration-policy",
                       WebKit2.HardwareAccelerationPolicy.ALWAYS if gpu == "always" else WebKit2.HardwareAccelerationPolicy.NEVER)
        for prop, val in (("allow-file-access-from-file-urls", True), ("allow-universal-access-from-file-urls", True),
                          ("javascript-can-access-clipboard", True), ("enable-developer-extras", DEV),
                          ("enable-write-console-messages-to-stdout", DEV or os.environ.get("STARX_CONSOLE") == "1"),
                          ("enable-webgl", False), ("enable-media-stream", False), ("default-font-family", "Inter"),
                          ("enable-back-forward-navigation-gestures", False),
                          # JStarx pages are local: no page cache, prefetching, web audio or DRM (less RAM and CPU)
                          ("enable-page-cache", False), ("enable-dns-prefetching", False), ("enable-webaudio", False),
                          ("enable-encrypted-media", False), ("enable-media-capabilities", False), ("enable-hyperlink-auditing", False)):
            try:
                s.set_property(prop, val)
            except TypeError:
                pass
        s.set_user_agent_with_application_details("JStarx", "2.0")
        if transparent:
            view.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        view.connect("decide-policy", self._on_policy)
        if not DEV:
            view.connect("context-menu", lambda *a: True)
        view.connect("web-process-terminated", self._on_crash, page)
        view._starx_page = page
        self.views.append(view)
        view.load_uri("file://" + os.path.join(paths.WEB, page))
        return view

    def _on_policy(self, view, decision, kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            if uri.startswith(("http://", "https://")):
                decision.ignore()
                open_external(uri)
                return True
            if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                decision.ignore()
                return True
        return False

    def _on_crash(self, view, reason, page):
        # The web view crashed: reload it once things settle (self-repair).
        print(f"[starx] web view for {page} stopped ({reason}); reloading", flush=True)
        GLib.timeout_add(800, lambda: (view.load_uri("file://" + os.path.join(paths.WEB, page)), False)[1])

    # ---------- messages ----------
    def _on_message(self, _manager, value):
        try:
            jsval = value.get_js_value() if hasattr(value, "get_js_value") else value
            msg = json.loads(jsval.to_string())
        except Exception:
            return
        view = None
        # find the view that owns this content manager
        for v in self.views:
            if v.get_user_content_manager() is _manager:
                view = v
                break
        if view is None:
            return
        self.dispatch(view, msg.get("id"), msg.get("method", ""), msg.get("args") or {})

    def dispatch(self, view, call_id, method, args):
        fn = getattr(self.api, "m_" + method.replace(".", "_"), None)
        if fn is None:
            self.reply(view, call_id, False, f"unknown method {method}")
            return
        if getattr(fn, "threaded", False):
            def work():
                try:
                    res = fn(view=view, **args)
                    GLib.idle_add(self.reply, view, call_id, True, res)
                except Exception as e:  # report to the page, never crash the shell
                    traceback.print_exc()
                    GLib.idle_add(self.reply, view, call_id, False, str(e))
            threading.Thread(target=work, daemon=True).start()
            return
        try:
            self.reply(view, call_id, True, fn(view=view, **args))
        except Exception as e:
            traceback.print_exc()
            self.reply(view, call_id, False, str(e))

    def reply(self, view, call_id, ok, payload):
        if call_id is None:
            return False
        run_js(view, f"StarX.__resolve({int(call_id)}, {'true' if ok else 'false'}, {_js_literal(payload)});")
        return False

    def emit(self, event, data=None, views=None):
        script = f"window.StarX && StarX.__event({_js_literal(event)}, {_js_literal(data)});"
        for v in views or self.views:
            run_js(v, script)
        return False

    def emit_threadsafe(self, event, data=None, views=None):
        GLib.idle_add(self.emit, event, data, views)


def threaded(fn):
    fn.threaded = True
    return fn


class FileWatch:
    """Call back when a file in a folder changes (inotify through Gio, no polling)."""

    def __init__(self, folder, names, callback, delay_ms=150):
        os.makedirs(folder, exist_ok=True)
        self.names = set(names) if names else None
        self.callback = callback
        self.delay = delay_ms
        self._pending = None
        self.monitor = Gio.File.new_for_path(folder).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", self._changed)

    def _changed(self, _m, f, other, event):
        name = (other or f).get_basename() if event in (Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED) else f.get_basename()
        if self.names is not None and name not in self.names and (f.get_basename() not in self.names):
            return
        if self._pending:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(self.delay, self._fire)

    def _fire(self):
        self._pending = None
        try:
            self.callback()
        except Exception:
            traceback.print_exc()
        return False
