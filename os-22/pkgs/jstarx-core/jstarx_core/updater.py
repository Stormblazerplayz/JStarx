"""JStarx auto-update from GitHub.

check:    reads layer/layer.json from the repo branch and compares versions
apply:    downloads the branch tarball, keeps only layer/, verifies every file against
          MANIFEST.json, installs into the spare slot (A/B) and switches to it
rollback: switches back to the previous slot
If the new version makes the desktop crash, auto-repair rolls it back by itself.
"""
import io
import json
import os
import shutil
import tarfile
import tempfile
import time
import urllib.request

from . import layers
from .common import REPO, STATE, log, merge_status, read_json, status, version_tuple, write_json

CONFIG = os.path.join(STATE, "update-config.json")
MAX_DOWNLOAD = 300 * 1024 * 1024
UA = {"User-Agent": "JStarx-Updater/1.0"}


def config():
    c = read_json(CONFIG)
    c.setdefault("auto", True)
    c.setdefault("branch", "main")
    return c


def set_config(auto=None, branch=None):
    c = config()
    if auto is not None:
        c["auto"] = bool(auto)
    if branch:
        safe = "".join(ch for ch in str(branch) if ch.isalnum() or ch in "-_./")[:100]
        c["branch"] = safe or "main"
    write_json(CONFIG, c)
    return c


def current_info():
    cur = layers.current_slot() or "factory"
    info = layers.layer_info(layers.slot_path(cur))
    info["slot"] = cur
    return info


def _publish(**fields):
    st = read_json(os.path.join(STATE, "update-status.json"))
    st.update(fields)
    st["current"] = current_info()
    st["history"] = layers.state().get("history", [])[-20:]
    st["time"] = time.time()
    write_json(os.path.join(STATE, "update-status.json"), st)
    status("update", **st)
    return st


def remote_version(branch):
    url = f"https://raw.githubusercontent.com/{REPO}/{branch}/layer/layer.json"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def check():
    c = config()
    _publish(state="checking")
    try:
        remote = remote_version(c["branch"])
    except Exception as e:
        return _publish(state="error", message=f"Could not reach GitHub ({e.__class__.__name__})", checked=time.time())
    cur = current_info()
    newer = version_tuple(remote.get("version", "0")) > version_tuple(cur["version"])
    return _publish(state="available" if newer else "up-to-date", available=remote.get("version") if newer else None,
                    remote_notes=remote.get("notes", []), checked=time.time(), message="")


def _download(branch, dest_dir):
    url = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{branch}"
    req = urllib.request.Request(url, headers=UA)
    buf = io.BytesIO()
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_DOWNLOAD:
                raise RuntimeError("download is too big")
            buf.write(chunk)
            if total:
                merge_status("update", state="downloading", progress=round(100 * got / total))
    buf.seek(0)
    return extract_layer(buf, dest_dir)


def extract_layer(fileobj, dest_dir):
    """Extract only <top>/layer/** regular files and folders (no links, no '..')."""
    count = 0
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
        for m in tar.getmembers():
            parts = m.name.split("/")
            if len(parts) < 3 or parts[1] != "layer":
                continue
            rel = "/".join(parts[2:])
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            target = os.path.join(dest_dir, rel)
            if m.isdir():
                os.makedirs(target, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, 0o755 if m.mode & 0o111 else 0o644)
                count += 1
    if not count:
        raise RuntimeError("no JStarx layer found in that branch")
    return dest_dir


def apply(source_dir=None):
    """Install the newest layer. source_dir lets tests (and USB updates) skip the download."""
    c = config()
    st = layers.state()
    tmp = tempfile.mkdtemp(prefix="jstarx-update-", dir=STATE)
    try:
        if source_dir is None:
            _publish(state="downloading", progress=0)
            _download(c["branch"], tmp)
            source = tmp
        else:
            source = source_dir
        ok, problems = layers.verify(source)
        if not ok:
            raise RuntimeError(f"the update failed its safety check ({len(problems)} file(s): {problems[0][0]})")
        new_info = layers.layer_info(source)
        old = layers.current_slot() or "factory"
        slot = layers.inactive_slot()
        layers.install_tree(source, slot)
        layers.set_current(slot)
        st["previous"] = old
        st["pending"] = True
        st["pending_since"] = time.time()
        st["good"][slot] = False
        st["history"].append({"version": new_info["version"], "time": time.time(), "ok": True, "note": f"installed into slot {slot.upper()}"})
        layers.save_state(st)
        log("updated to", new_info["version"], "in slot", slot)
        return _publish(state="updated", version=new_info["version"], available=None, progress=100, message="Restart the desktop to finish")
    except Exception as e:
        st["history"].append({"version": "?", "time": time.time(), "ok": False, "note": str(e)[:200]})
        layers.save_state(st)
        return _publish(state="error", message=str(e)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def rollback(reason="You chose to undo the update"):
    st = layers.state()
    prev = st.get("previous") or "factory"
    if prev != "factory" and not os.path.isdir(layers.slot_path(prev)):
        prev = "factory"
    if prev != "factory":
        ok, _ = layers.verify(layers.slot_path(prev))
        if not ok:
            prev = "factory"
    cur = layers.current_slot()
    layers.set_current(prev)
    st["previous"] = cur
    st["pending"] = False
    st["history"].append({"version": layers.layer_info(layers.slot_path(prev))["version"], "time": time.time(), "ok": True, "note": f"rolled back: {reason}"})
    layers.save_state(st)
    return _publish(state="rolled-back", message=reason)


def auto():
    """Timer entry point: check, and install if allowed (the JStarx layer, then the whole system)."""
    layers.ensure_initialized()
    c = config()
    res = check()
    if c["auto"] and res.get("state") == "available":
        res = apply()
    if c["auto"]:
        from . import sysupdate
        try:
            res = dict(res, system=sysupdate.auto())
        except Exception as e:
            log("system update check failed:", e)
    return res
