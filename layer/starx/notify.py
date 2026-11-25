"""freedesktop.org notification server: app notifications appear in the dynamic island."""
import time

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities"><arg direction="out" type="as"/></method>
    <method name="Notify">
      <arg direction="in" type="s" name="app_name"/><arg direction="in" type="u" name="replaces_id"/>
      <arg direction="in" type="s" name="app_icon"/><arg direction="in" type="s" name="summary"/>
      <arg direction="in" type="s" name="body"/><arg direction="in" type="as" name="actions"/>
      <arg direction="in" type="a{sv}" name="hints"/><arg direction="in" type="i" name="expire_timeout"/>
      <arg direction="out" type="u"/>
    </method>
    <method name="CloseNotification"><arg direction="in" type="u" name="id"/></method>
    <method name="GetServerInformation">
      <arg direction="out" type="s"/><arg direction="out" type="s"/><arg direction="out" type="s"/><arg direction="out" type="s"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  </interface>
</node>
"""


class NotificationServer:
    def __init__(self, on_notify, on_close):
        self.on_notify = on_notify
        self.on_close = on_close
        self.next_id = 1
        self.history = []
        self.conn = None
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.REPLACE,
                         self._on_bus, None, None)

    def _on_bus(self, conn, _name):
        self.conn = conn
        conn.register_object("/org/freedesktop/Notifications", self.node.interfaces[0], self._call, None, None)

    def _call(self, conn, sender, path, iface, method, params, invocation):
        if method == "GetCapabilities":
            invocation.return_value(GLib.Variant("(as)", (["body", "actions", "icon-static"],)))
        elif method == "GetServerInformation":
            invocation.return_value(GLib.Variant("(ssss)", ("StarShell", "JStarx", "1.0", "1.2")))
        elif method == "CloseNotification":
            nid = params.unpack()[0]
            self.close(nid, 3)
            invocation.return_value(None)
        elif method == "Notify":
            app_name, replaces, icon, summary, body, actions, hints, timeout = params.unpack()
            nid = replaces or self.next_id
            if not replaces:
                self.next_id += 1
            note = {"id": nid, "app": app_name or "App", "icon": icon, "summary": summary, "body": body[:400],
                    "actions": [{"key": actions[i], "label": actions[i + 1]} for i in range(0, len(actions) - 1, 2)],
                    "urgency": int(hints.get("urgency", 1)) if isinstance(hints.get("urgency", 1), int) else 1,
                    "time": time.time()}
            self.add(note)
            invocation.return_value(GLib.Variant("(u)", (nid,)))

    def add(self, note):
        """Also used by the shell itself for its own messages (updates, repair, AI jobs)."""
        if "id" not in note:
            note["id"] = self.next_id
            self.next_id += 1
        note.setdefault("time", time.time())
        self.history = [n for n in self.history if n["id"] != note["id"]][-49:] + [note]
        self.on_notify(note)
        return note["id"]

    def close(self, nid, reason=2):
        self.history = [n for n in self.history if n["id"] != nid]
        if self.conn:
            self.conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                  "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))
        self.on_close(nid)

    def invoke(self, nid, key):
        if self.conn:
            self.conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                  "ActionInvoked", GLib.Variant("(us)", (nid, key)))
        self.close(nid, 2)

    def clear(self):
        for n in list(self.history):
            self.close(n["id"], 2)
