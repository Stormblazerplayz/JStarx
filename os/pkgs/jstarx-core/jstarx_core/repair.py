"""JStarx auto-repair.

quick   every boot: verify the active layer against its manifest and restore damaged or
        missing files from another slot or the factory copy; restart failed services
deep    quick + verify every system file in /nix/store and re-download damaged ones
factory go back to the layer that came on the SD card
shell_failed  called when the desktop crashed 3 times: undo a recent update, else factory
"""
import os
import time

from . import layers, updater
from .common import BOOT_DIR, log, read_json, run, status, write_json

REPORT = os.path.join(os.path.dirname(layers.STATE_FILE), "repair-report.json")
CRITICAL_UNITS = ("starxd.service", "starai.service", "NetworkManager.service", "greetd.service")


def _report(state, fixed, problems, mode):
    data = {"state": state, "fixed": fixed, "problems": problems, "mode": mode, "time": time.time(),
            "boot": read_json(os.path.join(BOOT_DIR, "status.json"))}
    write_json(REPORT, data)
    status("repair", **data)
    return data


def check_layer(fixed, problems):
    cur = layers.ensure_initialized()
    path = layers.slot_path(cur)
    ok, issues = layers.verify(path)
    if ok:
        return
    if cur == "factory":
        problems.append(f"The factory copy has {len(issues)} damaged file(s); run Deep repair")
        return
    restored, left = layers.repair_files(path, issues)
    fixed.extend(restored)
    if left:
        st = layers.state()
        target = st.get("previous") or "factory"
        if target != "factory" and not layers.verify(layers.slot_path(target))[0]:
            target = "factory"
        layers.set_current(target)
        st["pending"] = False
        layers.save_state(st)
        fixed.append(f"Slot {cur.upper()} was too damaged ({len(left)} file(s)), switched to {target}")


def check_units(fixed, problems):
    r = run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"], timeout=20)
    if not r:
        return
    for line in r.stdout.splitlines():
        unit = line.split()[0] if line.split() else ""
        if unit.startswith("●"):
            unit = line.split()[1]
        if unit in CRITICAL_UNITS:
            r2 = run(["systemctl", "restart", unit], timeout=60)
            if r2 and r2.returncode == 0:
                fixed.append(f"Restarted {unit}")
            else:
                problems.append(f"{unit} keeps failing")


def quick(mode="quick"):
    fixed, problems = [], []
    try:
        check_layer(fixed, problems)
    except Exception as e:  # never let repair itself crash the boot
        problems.append(f"layer check error: {e}")
    try:
        check_units(fixed, problems)
    except Exception as e:
        problems.append(f"service check error: {e}")
    log("repair", mode, "fixed:", fixed, "problems:", problems)
    return _report("problems" if problems else "healthy", fixed, problems, mode)


def deep():
    rep = quick("deep")
    fixed, problems = list(rep["fixed"]), list(rep["problems"])
    r = run(["nix-store", "--verify", "--check-contents", "--repair"], timeout=6 * 3600)
    if r is None:
        problems.append("Could not run the system file check")
    else:
        repaired = [l for l in (r.stdout + r.stderr).splitlines() if "repair" in l.lower() or "modified" in l.lower()]
        fixed.extend(f"System files: {l.strip()[:120]}" for l in repaired[:20])
        if r.returncode != 0 and not repaired:
            problems.append("Some system files could not be repaired (are you online?)")
    return _report("problems" if problems else "healthy", fixed, problems, "deep")


def factory():
    layers.set_current("factory")
    st = layers.state()
    st["pending"] = False
    layers.save_state(st)
    return _report("healthy", ["Reset the desktop and apps to the factory version"], [], "factory")


def shell_failed():
    """The desktop crashed several times in a row."""
    st = layers.state()
    if st.get("pending") or (layers.current_slot() not in (None, "factory")):
        reason = "the new version kept crashing" if st.get("pending") else "the desktop kept crashing"
        updater.rollback(reason=reason) if st.get("pending") else factory()
        return _report("healthy", [f"Undid the last change because {reason}"], [], "shell")
    return _report("problems", [], ["The desktop keeps crashing even on the factory version"], "shell")
