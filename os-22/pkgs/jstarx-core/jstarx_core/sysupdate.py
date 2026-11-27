"""Whole-system updates (StarX Kernel, drivers, apps, services), not just the JStarx layer.

GitHub Actions publishes each new system as a release called system-<number> with:
  system.json            {"system": "/nix/store/...-nixos-system-jstarx-...", "version": "...", "deps": [...]}
  system-cache.tar.zst   the parts of the system that are not on cache.nixos.org (a small Nix cache)

Installing: fetch the parts from cache.nixos.org, unpack our cache, let Nix build nothing but copy
everything into place, then add the new system as the newest boot entry. The boot counter
(bootloader.nix) goes back to the last working system if the new one does not start.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request

from .common import REPO, STATE, log, merge_status, status

UA = {"User-Agent": "JStarx-SystemUpdate/1.0", "Accept": "application/vnd.github+json"}
WORK = os.path.join(STATE, "system-update")
PROFILE = os.environ.get("JSTARX_SYSTEM_PROFILE", "/nix/var/nix/profiles/system")
CURRENT = os.environ.get("JSTARX_CURRENT_SYSTEM", "/run/current-system")


def _get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def latest_release():
    """The newest system-* release of the repo, or None."""
    rels = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases?per_page=30"))
    rels = [r for r in rels if str(r.get("tag_name", "")).startswith("system-") and not r.get("draft")]
    if not rels:
        return None
    rels.sort(key=lambda r: (_build_number(r), r.get("published_at") or r.get("created_at") or ""), reverse=True)
    return rels[0]


def _build_number(rel):
    """system-N: the higher N, the newer the build (builds can finish out of order)."""
    tail = str(rel.get("tag_name", ""))[len("system-"):]
    return int(tail) if tail.isdigit() else -1


def _asset(rel, name):
    for a in rel.get("assets", []):
        if a.get("name") == name:
            return a
    return None


def _current_system():
    try:
        return os.path.realpath(CURRENT)
    except OSError:
        return ""


def _installed_systems():
    prof_dir = os.path.dirname(PROFILE)
    found = set()
    try:
        for n in os.listdir(prof_dir):
            if n.startswith("system-") and n.endswith("-link"):
                found.add(os.path.realpath(os.path.join(prof_dir, n)))
    except OSError:
        pass
    return found


def check():
    try:
        rel = latest_release()
    except Exception as e:
        return _publish(state="error", message=f"Could not reach GitHub: {str(e)[:150]}")
    if not rel or not _asset(rel, "system.json"):
        return _publish(state="up-to-date", message="No system updates have been published yet")
    info = json.loads(_get(_asset(rel, "system.json")["browser_download_url"]))
    target = info.get("system", "")
    if not target.startswith("/nix/store/"):
        return _publish(state="error", message="The system update description is damaged")
    if target == _current_system():
        return _publish(state="up-to-date", version=info.get("version"), message="JStarx is up to date")
    if target in _installed_systems():
        return _publish(state="ready", version=info.get("version"), message="The update is installed: restart to finish")
    size = (_asset(rel, "system-cache.tar.zst") or {}).get("size", 0)
    return _publish(state="available", version=info.get("version"), release=rel.get("tag_name"), size=size,
                    message=f"A system update is ready to download ({size / 1e6:.0f} MB)")


def _publish(**fields):
    merge_status("sysupdate", **fields)
    return fields


def _run(cmd, step, timeout=6 * 3600):
    log("system update:", step)
    _publish(state="installing", message=step)
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{step} failed: {r.stdout.strip()[-300:]}")
    return r.stdout


def apply():
    rel = latest_release()
    if not rel:
        raise RuntimeError("no system update has been published")
    info = json.loads(_get(_asset(rel, "system.json")["browser_download_url"]))
    target = info["system"]
    if not target.startswith("/nix/store/") or "/" in target[len("/nix/store/"):]:
        raise RuntimeError("the system update description is damaged")
    cache = _asset(rel, "system-cache.tar.zst")
    if not cache:
        raise RuntimeError("the system update has no files")
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    free = shutil.disk_usage(WORK).free
    if free < cache.get("size", 0) * 4 + (1 << 30):
        raise RuntimeError(f"not enough free space for the system update ({free / 1e9:.1f} GB free)")
    try:
        # 1. download our part of the system (with progress)
        archive = os.path.join(WORK, "system-cache.tar.zst")
        req = urllib.request.Request(cache["browser_download_url"], headers={"User-Agent": UA["User-Agent"]})
        total, got, last = cache.get("size", 0), 0, 0
        with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if time.time() - last > 1:
                    last = time.time()
                    _publish(state="downloading", progress=round(100 * got / total) if total else None,
                             message="Downloading the system update")
        if total and got != total:
            raise RuntimeError("the download did not finish, try again")
        cache_dir = os.path.join(WORK, "cache")
        os.makedirs(cache_dir)
        _run(["tar", "-I", "zstd", "-xf", archive, "-C", cache_dir], "Unpacking the update")
        os.remove(archive)
        # 2. everything else comes from cache.nixos.org; ours from the unpacked cache
        _run(["nix-store", "--realise", target,
              "--option", "extra-substituters", f"file://{cache_dir}",
              "--option", "require-sigs", "false",   # our cache is checked by its download from this repo
              "--option", "builders", ""],          # never try to build anything on the Jetson
             "Installing the new system")
        # 3. make it the newest boot entry (the boot counter keeps the old one as a safety net)
        _run(["nix-env", "-p", PROFILE, "--set", target], "Adding the new system")
        _run([os.path.join(target, "bin", "switch-to-configuration"), "boot"], "Updating the boot menu", timeout=1800)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    done = {"state": "ready", "version": info.get("version"), "message": "System update installed: restart to finish"}
    status("sysupdate", **done)
    return done


def auto():
    res = check()
    if res.get("state") == "available":
        try:
            return apply()
        except Exception as e:
            log("system update failed:", e)
            return _publish(state="error", message=str(e)[:300])
    return res
