"""Boot health: remember the last build that started fine.

The initrd counts boot tries in /boot/jstarx/tries. If a new build fails to reach a working
system 3 times, the initrd switches the boot menu back to /boot/jstarx/known-good and reboots.
mark_ok() runs once the system (and desktop) is up: it resets the counter.
"""
import os
import re
import time

from . import layers
from .common import BOOT_DIR, log, read_json, write_json


def booted_generation(cmdline_path="/proc/cmdline"):
    try:
        with open(cmdline_path) as f:
            m = re.search(r"jstarx\.gen=(\d+)", f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def _write(name, value):
    os.makedirs(BOOT_DIR, exist_ok=True)
    tmp = os.path.join(BOOT_DIR, f".{name}.tmp")
    with open(tmp, "w") as f:
        f.write(str(value) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(BOOT_DIR, name))


def mark_ok(reason="system up"):
    gen = booted_generation()
    if gen:
        _write("known-good", gen)
    _write("tries", 0)
    st = read_json(os.path.join(BOOT_DIR, "status.json"))
    st.update({"last_ok": time.time(), "generation": gen, "reason": reason})
    write_json(os.path.join(BOOT_DIR, "status.json"), st)
    # the layer we are running is good too
    lst = layers.state()
    cur = layers.current_slot()
    if cur and cur != "factory":
        lst["good"][cur] = True
    lst["pending"] = False
    layers.save_state(lst)
    log("boot ok, generation", gen, "-", reason)
    return st


def info():
    def rd(name):
        try:
            with open(os.path.join(BOOT_DIR, name)) as f:
                return f.read().strip()
        except OSError:
            return None
    return {"generation": booted_generation(), "known_good": rd("known-good"), "tries": rd("tries"),
            "log": (rd("repair.log") or "").splitlines()[-10:]}
