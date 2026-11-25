"""starxd: the JStarx system helper (runs as root).

Apps talk to it through /run/starxd.sock (group 'jstarx'). It only knows a fixed list of
operations with checked arguments; it never runs arbitrary commands.
"""
import grp
import json
import os
import pwd
import socket
import socketserver
import struct
import subprocess
import threading
import time

from . import boot, layers, power, repair, spark, updater
from .common import STATE, log, read_json, run, status, write_json

SOCKET = os.environ.get("STARXD_SOCKET", "/run/starxd.sock")
UNIX_CHKPWD = os.environ.get("JSTARX_UNIX_CHKPWD", "unix_chkpwd")
FLAGS = os.path.join(STATE, "flags")
_update_lock = threading.Lock()


def flag(name, on=None):
    path = os.path.join(FLAGS, name)
    if on is None:
        return os.path.exists(path)
    os.makedirs(FLAGS, exist_ok=True)
    if on:
        open(path, "w").close()
    elif os.path.exists(path):
        os.remove(path)
    return on


def op_system_set(key, value):
    if key == "timezone":
        tz = str(value)
        if not os.path.exists(os.path.join("/etc/zoneinfo", tz)) and not os.path.exists(os.path.join("/usr/share/zoneinfo", tz)):
            zi = run(["timedatectl", "list-timezones"], timeout=20)
            if not zi or tz not in zi.stdout.split():
                raise ValueError("unknown time zone")
        r = run(["timedatectl", "set-timezone", tz], timeout=20)
        if not r or r.returncode != 0:
            raise RuntimeError("could not set the time zone")
        return {"timezone": tz}
    if key == "autologin":
        flag("no-autologin", not bool(value))
        return {"autologin": bool(value), "note": "Takes effect at the next start"}
    if key == "ssh":
        flag("ssh", bool(value))
        run(["systemctl", "start" if value else "stop", "sshd.service"], timeout=30)
        return {"ssh": bool(value)}
    if key == "hostname":
        name = "".join(c for c in str(value) if c.isalnum() or c == "-")[:40]
        if not name:
            raise ValueError("invalid name")
        run(["hostnamectl", "set-hostname", name], timeout=20)
        return {"hostname": name}
    raise ValueError("unknown setting")


def op_password_set(old, new, _uid=None):
    """Change the caller's own password. The current password has to be right."""
    if not _uid:
        raise PermissionError("only a signed-in user can change their password")
    user = pwd.getpwuid(_uid).pw_name
    old, new = str(old), str(new)
    if len(new) < 4:
        raise ValueError("the new password needs at least 4 characters")
    if any(c in new for c in ":\n\r\0"):
        raise ValueError("the new password can't contain : or line breaks")
    chk = subprocess.run([UNIX_CHKPWD, user, "nullok"], input=old.encode() + b"\0",
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    if chk.returncode != 0:
        raise ValueError("the current password is not right")
    r = subprocess.run(["chpasswd"], input=f"{user}:{new}\n".encode(), stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("could not change the password")
    log("password changed for", user)
    return {"user": user, "changed": True}


def op_storage_clean():
    before = os.statvfs("/")
    run(["nix-collect-garbage", "--delete-older-than", "14d"], timeout=3600)
    for d in ("/var/cache/jstarx",):
        run(["rm", "-rf", d], timeout=60)
    after = os.statvfs("/")
    return {"freed": max(0, (after.f_bavail - before.f_bavail) * after.f_frsize)}


def op_shell_failed():
    """The session supervisor reports the desktop crashed 3 times."""
    return repair.shell_failed()


def op_update_apply():
    if not _update_lock.acquire(blocking=False):
        raise RuntimeError("an update is already running")
    try:
        return updater.apply()
    finally:
        _update_lock.release()


OPS = {
    "ping": lambda: {"pong": True, "time": time.time()},
    "power_get": power.get,
    "power_set": lambda profile: power.set_profile(profile),
    "ai247_set": lambda on: power.set_ai247(on),
    "update_check": updater.check,
    "update_apply": op_update_apply,
    "update_rollback": lambda: updater.rollback(),
    "update_config": lambda auto=None, branch=None: updater.set_config(auto, branch),
    "repair_run": lambda mode="quick": {"quick": repair.quick, "deep": repair.deep, "factory": repair.factory}[mode](),
    "session_healthy": lambda: boot.mark_ok("desktop is healthy"),
    "shell_failed": op_shell_failed,
    "storage_clean": op_storage_clean,
    "system_set": op_system_set,
    "spark_download": lambda url=None: spark.download(url or ""),
    "spark_import": lambda path: spark.import_file(path),
    "spark_service": lambda action, threads=None, ctx=None: (spark.set_cfg(threads, ctx), spark.service(action))[1],
    "boot_info": boot.info,
    "password_set": op_password_set,
}
# operations that are told which user is asking (never taken from the request itself)
NEEDS_UID = {"password_set"}


def peer_uid(sock):
    """The user id of the program on the other end, or None if it isn't allowed to ask."""
    try:
        _pid, uid, gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    except OSError:
        return None
    if uid == 0:
        return uid
    try:
        g = grp.getgrnam("jstarx")
        return uid if (gid == g.gr_gid or pwd.getpwuid(uid).pw_name in g.gr_mem) else None
    except KeyError:
        return None


def peer_ok(sock):
    return peer_uid(sock) is not None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        uid = peer_uid(self.request)
        if uid is None:
            self.wfile.write(b'{"ok": false, "error": "not allowed"}\n')
            return
        try:
            req = json.loads(self.rfile.readline(1 << 20) or b"{}")
            op = req.get("op")
            fn = OPS.get(op)
            if fn is None:
                raise ValueError("unknown operation")
            args = {k: v for k, v in (req.get("args") or {}).items() if not str(k).startswith("_")}
            if op in NEEDS_UID:
                args["_uid"] = uid
            res = fn(**args)
            self.wfile.write((json.dumps({"ok": True, "result": res}) + "\n").encode())
        except TypeError as e:
            self.wfile.write((json.dumps({"ok": False, "error": f"bad arguments: {e}"}) + "\n").encode())
        except Exception as e:
            log("op failed:", e)
            self.wfile.write((json.dumps({"ok": False, "error": str(e)}) + "\n").encode())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    layers.ensure_initialized()
    try:
        power.restore()
    except Exception as e:
        log("power restore failed:", e)
    st = updater.current_info()
    status("update", **{**read_json(os.path.join(STATE, "update-status.json")), "current": st})
    try:
        os.unlink(SOCKET)
    except OSError:
        pass
    srv = Server(SOCKET, Handler)
    try:
        os.chown(SOCKET, 0, grp.getgrnam("jstarx").gr_gid)
    except (KeyError, PermissionError):
        pass
    os.chmod(SOCKET, 0o660)
    log("starxd ready")
    srv.serve_forever()


if __name__ == "__main__":
    main()
