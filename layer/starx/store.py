"""Star Store installs: official JStarx web apps and Nix apps (installed per user, no root)."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

from . import paths
from .apps import NIX_APPS_FILE
from .settings import atomic_write_json


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _fetch(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def install_web(entry, bundled_base, branch, repo, progress):
    """Download every file of a web app, check its SHA-256, then move it into place."""
    app_id = entry["id"]
    files = entry.get("files", {})
    if not files:
        raise ValueError("catalog entry has no files")
    staging = tempfile.mkdtemp(prefix=f".{app_id}-", dir=paths.USER_APPS)
    try:
        for i, (rel, digest) in enumerate(sorted(files.items())):
            if rel.startswith("/") or ".." in rel.split("/"):
                raise ValueError(f"unsafe file name {rel}")
            progress(f"Downloading {rel}", round(100 * i / len(files)))
            data = None
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/layer/store/apps/{app_id}/{rel}"
            try:
                data = _fetch(url)
                if _sha256(data) != digest:
                    data = None  # newer file online than this catalog: use the bundled copy
            except OSError:
                data = None
            if data is None and bundled_base:
                local = os.path.join(bundled_base, "apps", app_id, rel)
                if os.path.exists(local):
                    with open(local, "rb") as f:
                        data = f.read()
            if data is None:
                raise RuntimeError(f"could not download {rel} (are you online?)")
            if _sha256(data) != digest:
                raise RuntimeError(f"{rel} failed its safety check (checksum mismatch)")
            dest = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
        final = os.path.join(paths.USER_APPS, app_id)
        if os.path.exists(final):
            shutil.rmtree(final)
        os.replace(staging, final)
        progress("Installed", 100)
        return {"ok": True, "id": app_id}
    finally:
        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _nix_records():
    try:
        with open(NIX_APPS_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def install_nix(entry, progress):
    """Install a package from the same nixpkgs the system was built from (binary cache, no compiling)."""
    if not shutil.which("nix"):
        raise RuntimeError("this app needs the JStarx SD card image (Nix is not on this system)")
    attr = entry["nix"]
    env = dict(os.environ, NIXPKGS_ALLOW_UNFREE="1" if entry.get("unfree") else "0")
    cmd = ["nix", "--extra-experimental-features", "nix-command flakes", "profile", "install", "--impure"]
    if entry.get("nix_expr"):  # e.g. a Python with AI libraries
        cmd += ["--expr", entry["nix_expr"]]
    else:
        cmd += [f"nixpkgs#{attr}"]
    progress(f"Installing {entry['name']} (this can take a few minutes)", None)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
    last = ""
    for line in proc.stdout:
        line = line.strip()
        if line:
            last = line
            if "copying path" in line or "downloading" in line or "building" in line:
                progress(line[:120], None)
    if proc.wait() != 0:
        raise RuntimeError(f"install failed: {last[:200]}")
    recs = [r for r in _nix_records() if r.get("id") != entry["id"]]
    recs.append({"id": entry["id"], "name": entry["name"], "exec": entry["exec"], "app_id": entry.get("app_id", entry["id"]),
                 "icon": entry.get("icon", "box"), "category": entry.get("category", "Apps"),
                 "description": entry.get("description", ""), "nix": attr})
    atomic_write_json(NIX_APPS_FILE, recs)
    progress("Installed", 100)
    return {"ok": True, "id": entry["id"]}


def install(entry, bundled_base, branch, repo, progress):
    if entry.get("type") == "nix":
        return install_nix(entry, progress)
    return install_web(entry, bundled_base, branch, repo, progress)


def uninstall(app_id):
    path = os.path.join(paths.USER_APPS, app_id)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return {"ok": True}
    recs = _nix_records()
    rec = next((r for r in recs if r.get("id") == app_id), None)
    if rec:
        subprocess.run(["nix", "--extra-experimental-features", "nix-command flakes", "profile", "remove", rec.get("nix", app_id)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        atomic_write_json(NIX_APPS_FILE, [r for r in recs if r.get("id") != app_id])
        return {"ok": True}
    raise ValueError("that app is not installed")
