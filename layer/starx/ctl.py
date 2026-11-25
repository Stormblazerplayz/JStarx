"""starx-ctl: send a command to the running shell.

Examples:  starx-ctl launchpad | start | control | spark | power | close
           starx-ctl osd volume | launch firefox | idle on | health | state
           starx-ctl notify '{"summary": "Hello", "body": "From a script"}'
"""
import json
import socket
import sys

from . import paths


def send(command, timeout=3):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(paths.SHELL_SOCKET)
    s.sendall((command + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data.decode() or "{}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    try:
        reply = send(" ".join(sys.argv[1:]))
    except OSError as e:
        print(f"StarShell is not running ({e})", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(reply))
    sys.exit(0 if reply.get("ok") else 1)


if __name__ == "__main__":
    main()
