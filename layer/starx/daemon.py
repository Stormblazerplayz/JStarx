"""Clients for the JStarx system services (starxd, starai) and their status files."""
import json
import os
import socket

from . import paths


class DaemonError(Exception):
    pass


def request(sock_path, op, timeout=30, **args):
    """Send one JSON request over a UNIX socket and read one JSON reply."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall((json.dumps({"op": op, "args": args}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
    except (OSError, socket.timeout) as e:
        raise DaemonError(f"service not reachable ({os.path.basename(sock_path)}): {e}")
    try:
        reply = json.loads(buf.decode() or "{}")
    except ValueError:
        raise DaemonError("bad reply from service")
    if not reply.get("ok", False):
        raise DaemonError(reply.get("error", "request failed"))
    return reply.get("result")


def starxd(op, timeout=30, **args):
    return request(paths.STARXD_SOCKET, op, timeout=timeout, **args)


def starai(op, timeout=15, **args):
    return request(paths.STARAI_SOCKET, op, timeout=timeout, **args)


def status(name):
    """Read /run/jstarx/<name>.json written by a system service (empty dict if missing)."""
    for base in (paths.RUN_SYSTEM, os.path.join(paths.STATE_SYSTEM, "status")):
        try:
            with open(os.path.join(base, f"{name}.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}
