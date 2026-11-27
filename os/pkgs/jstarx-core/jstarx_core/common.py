"""Shared helpers for the JStarx system services (run as root)."""
import hashlib
import json
import os
import subprocess
import tempfile
import time

STATE = os.environ.get("JSTARX_STATE", "/var/lib/jstarx")
RUN = os.environ.get("JSTARX_RUN", "/run/jstarx")
LAYERS = os.path.join(STATE, "layers")
CURRENT = os.path.join(LAYERS, "current")
FACTORY = os.environ.get("JSTARX_FACTORY_LAYER", "/etc/jstarx/factory-layer")
REPO = os.environ.get("JSTARX_REPO", "Stormblazerplayz/JStarx")
BOOT_DIR = os.environ.get("JSTARX_BOOT", "/boot/jstarx")
NIX_DIR = os.environ.get("JSTARX_NIX_DIR", "/nix/var/nix")
NV_RELEASE = os.environ.get("JSTARX_NV_RELEASE", "/etc/nv_tegra_release")


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def status(name, **fields):
    """Publish a status file in /run/jstarx (the shell watches these, no polling)."""
    data = dict(fields)
    data.setdefault("time", time.time())
    write_json(os.path.join(RUN, f"{name}.json"), data)
    return data


def merge_status(name, **fields):
    data = read_json(os.path.join(RUN, f"{name}.json"))
    data.update(fields)
    data["time"] = time.time()
    write_json(os.path.join(RUN, f"{name}.json"), data)
    return data


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def run(args, timeout=120, check=False):
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise RuntimeError(f"{args[0]} failed: {e}")
        return None
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def log(*parts):
    print("[jstarx]", *parts, flush=True)


def platform():
    """Where JStarx runs: "nixos" (the JStarx SD card image), "jetpack" (NVIDIA JetPack on Ubuntu,
    the original Jetson Nano) or "other" (any other computer). JSTARX_PLATFORM overrides the check."""
    forced = os.environ.get("JSTARX_PLATFORM")
    if forced:
        return forced
    if os.path.isdir(NIX_DIR):
        return "nixos"
    if os.path.exists(NV_RELEASE):
        return "jetpack"
    return "other"


def version_tuple(v):
    out = []
    for p in str(v).split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])
