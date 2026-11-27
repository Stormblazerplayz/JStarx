"""Power profiles for the Jetson (works on any Linux with cpufreq / CPU hotplug).

low:         Low power: 1 CPU core at 40 % speed, slowest memory/GPU clocks (least heat and power)
saver:       2 CPU cores online, CPU speed capped at 60 %, quiet and cool
balanced:    all cores, schedutil picks the speed (default)
performance: all cores at full speed
extreme:     Extreme: all cores locked at full speed, GPU/memory at full speed, deep sleep states of
             the CPU off, fan at full speed (thermal protection stays on)
24/7 AI mode: never sleep (sleep targets masked), jobs keep running
"""
import glob
import os

from .common import STATE, read_json, run, status, write_json

STATE_FILE = os.path.join(STATE, "power.json")
PROFILES = {
    "low": {"governors": ["powersave", "conservative"], "max_pct": 40, "cpus": 1, "devfreq": "powersave"},
    "saver": {"governors": ["powersave", "schedutil", "ondemand"], "max_pct": 60, "cpus": 2, "devfreq": "powersave"},
    "balanced": {"governors": ["schedutil", "ondemand", "conservative"], "max_pct": 100, "cpus": None, "devfreq": "simple_ondemand"},
    "performance": {"governors": ["performance", "schedutil"], "max_pct": 100, "cpus": None, "devfreq": "performance"},
    "extreme": {"governors": ["performance"], "max_pct": 100, "cpus": None, "devfreq": "performance",
                "min_pct": 100, "no_deep_idle": True, "fan": "max"},
}
SYS = os.environ.get("JSTARX_SYSFS", "/sys")


def _w(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except OSError:
        return False


def _r(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def cpus():
    return sorted(int(p.rsplit("cpu", 1)[1]) for p in glob.glob(f"{SYS}/devices/system/cpu/cpu[0-9]*"))


def apply(profile):
    p = PROFILES[profile]
    applied = []
    all_cpus = cpus()
    want = len(all_cpus) if p["cpus"] is None else max(1, min(p["cpus"], len(all_cpus)))
    for n in all_cpus:
        online = f"{SYS}/devices/system/cpu/cpu{n}/online"
        if os.path.exists(online):  # cpu0 has no 'online' file
            if _w(online, 1 if n < want else 0):
                applied.append(f"cpu{n} {'on' if n < want else 'off'}")
    for pol in glob.glob(f"{SYS}/devices/system/cpu/cpufreq/policy*"):
        avail = _r(f"{pol}/scaling_available_governors").split()
        gov = next((g for g in p["governors"] if g in avail), None)
        if gov and _w(f"{pol}/scaling_governor", gov):
            applied.append(f"{os.path.basename(pol)} {gov}")
        lo, hi = _r(f"{pol}/cpuinfo_min_freq"), _r(f"{pol}/cpuinfo_max_freq")
        if lo.isdigit() and hi.isdigit():
            cap = int(int(lo) + (int(hi) - int(lo)) * p["max_pct"] / 100)
            floor = int(int(lo) + (int(hi) - int(lo)) * p.get("min_pct", 0) / 100)
            _w(f"{pol}/scaling_max_freq", cap)
            _w(f"{pol}/scaling_min_freq", floor)
    for dev in glob.glob(f"{SYS}/class/devfreq/*"):
        avail = _r(f"{dev}/available_governors").split()
        if p["devfreq"] in avail:
            _w(f"{dev}/governor", p["devfreq"])
    # CPU deep sleep states: off in Extreme (no wake-up delay), on otherwise (saves power)
    for st in glob.glob(f"{SYS}/devices/system/cpu/cpu[0-9]*/cpuidle/state[1-9]*/disable"):
        _w(st, 1 if p.get("no_deep_idle") else 0)
    # Extreme forces the fan to full speed; the other modes use your Fan setting (Auto by default)
    st = read_json(STATE_FILE)
    st["fan"] = "max" if p.get("fan") == "max" else st.get("fan_user", "auto")
    write_json(STATE_FILE, st)
    keep_fan()
    applied.append(f"fan {st['fan']}")
    return applied


# ---------------------------------------------------------------- the Jetson Nano's fan (pwm-fan)
def _fans():
    return [cd for cd in glob.glob(f"{SYS}/class/thermal/cooling_device*") if _r(f"{cd}/type") in ("pwm-fan", "pwm_fan")]


def fan(mode=None):
    """Your Fan setting. auto: the kernel speeds the fan up with temperature. max: always full speed.
    (Extreme mode always runs the fan at full speed.)"""
    st = read_json(STATE_FILE)
    if mode is not None:
        st["fan_user"] = "max" if mode == "max" else "auto"
        st["fan"] = "max" if st.get("profile") == "extreme" else st["fan_user"]
        write_json(STATE_FILE, st)
    keep_fan()
    return st.get("fan_user", "auto")


def keep_fan():
    """Called every few seconds by starxd: the kernel lowers the fan when it is cool, so set it again."""
    if read_json(STATE_FILE).get("fan") != "max":
        return False
    for cd in _fans():
        top = _r(f"{cd}/max_state")
        if top.isdigit() and _r(f"{cd}/cur_state") != top:
            _w(f"{cd}/cur_state", top)
    for h in glob.glob(f"{SYS}/class/hwmon/hwmon*"):
        if _r(f"{h}/name") == "pwmfan" and _r(f"{h}/pwm1") != "255":
            _w(f"{h}/pwm1", 255)
    return True


def get():
    st = read_json(STATE_FILE)
    st.setdefault("profile", "balanced")
    st.setdefault("ai_247", False)
    st["governor"] = _r(f"{SYS}/devices/system/cpu/cpu0/cpufreq/scaling_governor") or "not available"
    st["cpus_online"] = sum(1 for n in cpus() if n == 0 or _r(f"{SYS}/devices/system/cpu/cpu{n}/online") != "0")
    st["service"] = True
    st["fan"] = st.get("fan_user", "auto")
    st["has_fan"] = bool(_fans())
    return st


def set_profile(profile):
    if profile not in PROFILES:
        raise ValueError("unknown power mode")
    st = read_json(STATE_FILE)
    st["profile"] = profile
    write_json(STATE_FILE, st)
    applied = apply(profile)
    st = read_json(STATE_FILE)  # apply() updated the fan state
    st["applied"] = applied
    write_json(STATE_FILE, st)
    status("power", profile=profile, ai_247=st.get("ai_247", False))
    return get()


def set_ai247(on):
    st = read_json(STATE_FILE)
    st["ai_247"] = bool(on)
    write_json(STATE_FILE, st)
    targets = ["sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"]
    run(["systemctl", "mask" if on else "unmask", "--runtime", *targets], timeout=30)
    status("power", profile=st.get("profile", "balanced"), ai_247=bool(on))
    return get()


def restore():
    """At boot: re-apply the saved profile and 24/7 mode."""
    st = read_json(STATE_FILE)
    prof = st.get("profile", "balanced")
    apply(prof if prof in PROFILES else "balanced")
    if st.get("ai_247"):
        set_ai247(True)
    status("power", profile=prof, ai_247=bool(st.get("ai_247")))
    return get()
