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

from . import boot, layers, power, repair, spark, sysupdate, updater
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


# ---------------------------------------------------------------- memory: keep RAM free
# JStarx keeps only the memory that is in use in RAM. Everything idle (apps you are not using
# and background services) moves to swap: compressed RAM first (fast), then the swap file on
# the SD card / SSD. The code that is running and the data it is using have to stay in RAM
# (the CPU can only work on RAM), so most of it can move to swap, never all of it.
CGROUP_ROOT = os.environ.get("JSTARX_CGROUP_ROOT", "/sys/fs/cgroup")
CGROUP_USER = os.environ.get("JSTARX_USER_CGROUP", os.path.join(CGROUP_ROOT, "user.slice"))
CGROUP_SYSTEM = os.environ.get("JSTARX_SYSTEM_CGROUP", os.path.join(CGROUP_ROOT, "system.slice"))
TRIGGER_FREE = 0.45    # memory saver: when less than 45% of the RAM is free ...
KEEP_FREE = 0.50       # ... move idle memory to swap until half of it is free
SWEEP_SHARE = 50       # every 30 s, move 1/50 (2%) of each group's memory that nobody is using
PRESSURE_LIMIT = 0.2   # a group that waited for memory more than 0.2% of the last 10 s is left alone
MIN_SWAP_FREE = 128 << 20


def _meminfo():
    vals = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if v.split():
                    vals[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    return vals


def _cg_value(cg, name):
    try:
        with open(os.path.join(cg, name)) as f:
            return int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def _pressure(cg):
    """How much of the last 10 s the programs in a group waited for memory (PSI "some avg10", in %)."""
    try:
        with open(os.path.join(cg, "memory.pressure")) as f:
            for line in f:
                if line.startswith("some "):
                    for part in line.split():
                        if part.startswith("avg10="):
                            return float(part[6:])
    except (OSError, ValueError):
        pass
    return 0.0


def reclaim(nbytes, cg=None, minimum=16 << 20):
    """Move up to nbytes of the least-used memory of a group (apps by default) out of RAM
    (into compressed RAM, then the swap file)."""
    nbytes = int(max(minimum, min(nbytes, 2 << 30)))
    try:
        with open(os.path.join(cg or CGROUP_USER, "memory.reclaim"), "w") as f:
            f.write(str(nbytes))
        return True
    except OSError:  # the kernel could not free that much right now (or no cgroup support): fine
        return False


def free_ram(target, gentle=False):
    """Move idle memory to swap until `target` bytes of RAM are free: apps first, then background
    services. gentle (the automatic memory saver): a group whose programs are waiting for memory is
    skipped, and background services (Spark, StarAI jobs) give at most 256 MB per pass, so AI jobs
    that are using their memory keep running fast."""
    for cg in (CGROUP_USER, CGROUP_SYSTEM):
        need = target - _meminfo().get("MemAvailable", 0)
        if need <= 0:
            break
        if gentle:
            if _pressure(cg) > PRESSURE_LIMIT:
                continue
            if cg == CGROUP_SYSTEM:
                need = min(need, 256 << 20)
        reclaim(need, cg)


def sweep():
    """Move memory nobody is using to swap, a little at a time (the way big servers do it): 2% of
    the background services and 2% of the apps. A group whose programs had to wait for memory is
    left alone, so what is in use stays in RAM. Returns how many bytes it asked the kernel to move."""
    if _meminfo().get("SwapFree", 0) < MIN_SWAP_FREE:
        return 0  # swap is full: nothing more can go there
    moved = 0
    for cg in (CGROUP_SYSTEM, CGROUP_USER):
        cur = _cg_value(cg, "memory.current")
        if cur < (64 << 20) or _pressure(cg) > PRESSURE_LIMIT:
            continue
        step = max(4 << 20, min(cur // SWEEP_SHARE, 64 << 20))
        if reclaim(step, cg, minimum=4 << 20):
            moved += step
    return moved


def op_memory_free():
    m = _meminfo()
    before, total = m.get("MemAvailable", 0), m.get("MemTotal", 1)
    free_ram(max(int(total * 0.6), before + (256 << 20)))  # aim for 60% of RAM free (at least 256 MB more)
    try:
        with open("/proc/sys/vm/compact_memory", "w") as f:
            f.write("1")
    except OSError:
        pass
    after = _meminfo().get("MemAvailable", 0)
    return {"freed": max(0, after - before), "available": after, "total": total}


def op_memory_saver(on=None):
    if on is not None:
        flag("no-memory-saver", not bool(on))
    return {"on": not flag("no-memory-saver")}


def memory_saver_loop():
    """Memory saver (on unless turned off in Settings > Memory):
    every 15 s, when less than 45% of the RAM is free, move idle memory to swap until half is free;
    otherwise every 30 s, sweep a little memory nobody is using into swap.
    Every 5 s: keep the fan at full speed if Extreme / fan Max is on."""
    tick = 0
    while True:
        time.sleep(5)
        try:
            power.keep_fan()
        except Exception:
            pass
        tick += 1
        if tick % 3:
            continue
        try:
            if flag("no-memory-saver"):
                continue
            m = _meminfo()
            total, avail = m.get("MemTotal", 0), m.get("MemAvailable", 0)
            if total and avail < total * TRIGGER_FREE:
                free_ram(int(total * KEEP_FREE), gentle=True)
            elif tick % 6 == 0:
                sweep()
        except Exception as e:  # never let this stop starxd
            log("memory saver:", e)


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


_sys_lock = threading.Lock()


def op_system_update_apply():
    """Download and install the whole-system update in the background (it can take a while)."""
    if not _sys_lock.acquire(blocking=False):
        raise RuntimeError("a system update is already running")

    def work():
        try:
            sysupdate.apply()
        except Exception as e:
            log("system update failed:", e)
            status("sysupdate", state="error", message=str(e)[:300])
        finally:
            _sys_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


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
    "fan_set": lambda mode: {"fan": power.fan(mode)},
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
    "spark_service": lambda action, threads=None, ctx=None, fast=None: (spark.set_cfg(threads, ctx, fast), spark.service(action))[1],
    "boot_info": boot.info,
    "password_set": op_password_set,
    "memory_free": op_memory_free,
    "system_update_check": sysupdate.check,
    "system_update_apply": op_system_update_apply,
    "memory_saver": op_memory_saver,
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
    threading.Thread(target=memory_saver_loop, daemon=True).start()
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
