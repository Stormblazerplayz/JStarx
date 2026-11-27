"""JStarx layer slots: factory (read-only, from the image), A and B (updates)."""
import os
import shutil
import time

from .common import CURRENT, FACTORY, LAYERS, STATE, read_json, sha256_file, write_json

STATE_FILE = os.path.join(STATE, "layers.json")
SLOTS = ("a", "b")


def state():
    st = read_json(STATE_FILE)
    st.setdefault("previous", None)
    st.setdefault("pending", False)
    st.setdefault("good", {})
    st.setdefault("history", [])
    return st


def save_state(st):
    write_json(STATE_FILE, st)


def slot_path(name):
    return os.path.realpath(FACTORY) if name == "factory" else os.path.join(LAYERS, name)


def current_slot():
    try:
        target = os.readlink(CURRENT)
    except OSError:
        return None
    base = os.path.basename(target.rstrip("/"))
    return base if base in SLOTS else "factory"


def set_current(name):
    """Point layers/current at a slot. A symlink swap is atomic, so a power cut can't leave it half done."""
    os.makedirs(LAYERS, exist_ok=True)
    target = slot_path(name)
    tmp = CURRENT + ".new"
    try:
        os.unlink(tmp)
    except OSError:
        pass
    os.symlink(target, tmp)
    os.replace(tmp, CURRENT)


def layer_info(path):
    info = read_json(os.path.join(path, "layer.json"))
    return {"version": info.get("version", "0.0.0"), "codename": info.get("codename", ""), "notes": info.get("notes", [])}


def verify(path):
    """Check every file of a layer against its MANIFEST.json. Returns (ok, problems)."""
    manifest = read_json(os.path.join(path, "MANIFEST.json"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return False, [("MANIFEST.json", "missing")]
    problems = []
    for rel, digest in files.items():
        full = os.path.join(path, rel)
        if not os.path.isfile(full):
            problems.append((rel, "missing"))
        elif sha256_file(full) != digest:
            problems.append((rel, "damaged"))
    return not problems, problems


def ensure_initialized():
    """First boot, or the 'current' link is missing or broken: use the factory layer."""
    os.makedirs(LAYERS, exist_ok=True)
    cur = current_slot()
    if cur is None or not os.path.isdir(os.path.realpath(CURRENT)):
        set_current("factory")
        return "factory"
    return cur


def inactive_slot():
    cur = current_slot()
    return "b" if cur == "a" else "a"


def install_tree(src, slot):
    """Copy a verified layer into a slot (staging dir first, then a quick rename)."""
    dest = slot_path(slot)
    staging = os.path.join(LAYERS, f".staging-{slot}-{int(time.time())}")
    shutil.copytree(src, staging, symlinks=False)
    if os.path.exists(dest):
        old = dest + ".old"
        shutil.rmtree(old, ignore_errors=True)
        os.replace(dest, old)
        os.replace(staging, dest)
        shutil.rmtree(old, ignore_errors=True)
    else:
        os.replace(staging, dest)
    return dest


def repair_files(path, problems):
    """Fix damaged/missing files in a slot by copying good copies from another layer."""
    fixed, left = [], []
    manifest = read_json(os.path.join(path, "MANIFEST.json")).get("files", {})
    donors = [slot_path(s) for s in ("a", "b", "factory") if slot_path(s) != os.path.realpath(path)]
    for rel, _kind in problems:
        want = manifest.get(rel)
        done = False
        for donor in donors:
            cand = os.path.join(donor, rel)
            if want and os.path.isfile(cand) and sha256_file(cand) == want:
                dest = os.path.join(path, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(cand, dest)
                fixed.append(f"Restored {rel}")
                done = True
                break
        if not done:
            left.append(rel)
    return fixed, left
