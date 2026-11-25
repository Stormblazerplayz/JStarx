"""System information and simple controls (Wi-Fi, sound) for the shell and Settings."""
import glob
import os
import platform
import re
import shutil
import socket
import subprocess
import time

from . import __version__


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _run(args, timeout=8):
    if not shutil.which(args[0]):
        return None
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r
    except (OSError, subprocess.TimeoutExpired):
        return None


def os_release():
    info = {}
    for line in _read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        info[k] = v.strip().strip('"')
    return info


CPU_PARTS = {"0xd03": "Cortex-A53", "0xd04": "Cortex-A35", "0xd05": "Cortex-A55", "0xd07": "Cortex-A57",
             "0xd08": "Cortex-A72", "0xd09": "Cortex-A73", "0xd0b": "Cortex-A76", "0xd42": "Cortex-A78AE"}


def cpu_name():
    text = _read("/proc/cpuinfo")
    m = re.search(r"model name\s*:\s*(.+)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"CPU part\s*:\s*(0x[0-9a-f]+)", text)
    if m:
        return "ARM " + CPU_PARTS.get(m.group(1), m.group(1))
    return platform.processor() or platform.machine()


def model():
    m = _read("/proc/device-tree/model").replace("\x00", "")
    if m:
        return m
    vendor = _read("/sys/class/dmi/id/sys_vendor")
    product = _read("/sys/class/dmi/id/product_name")
    return " ".join(x for x in (vendor, product) if x) or "Unknown computer"


def meminfo():
    vals = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        parts = v.split()
        if parts:
            vals[k] = int(parts[0]) * 1024
    total = vals.get("MemTotal", 0)
    avail = vals.get("MemAvailable", 0)
    return {"total": total, "available": avail, "used": max(0, total - avail),
            "swap_total": vals.get("SwapTotal", 0), "swap_used": max(0, vals.get("SwapTotal", 0) - vals.get("SwapFree", 0))}


APP_NAMES = {"firefox": "Firefox", "WebKitWebProcess": "JStarx pages", "WebKitNetworkProcess": "JStarx pages",
             "llama-server": "Spark 1", "labwc": "Window manager", "foot": "Terminal", "Xwayland": "X11 apps",
             "pipewire": "Sound", "wireplumber": "Sound", "gimp": "GIMP", "vlc": "VLC", "codium": "VSCodium",
             "thunar": "Files", "starxd": "JStarx system", "starai": "AI Center"}


def _app_name(pid):
    comm = _read(f"/proc/{pid}/comm")
    if comm.startswith("python"):
        cmd = _read(f"/proc/{pid}/cmdline").replace("\0", " ")
        if "starx.shell" in cmd:
            return "JStarx desktop"
        if "starx.app" in cmd:
            return "JStarx apps"
        if "starx.starcast" in cmd:
            return "Wireless display"
        if "trainer" in cmd or "starai" in cmd:
            return "AI Center"
        return "Python"
    for key, name in APP_NAMES.items():
        if comm.lower().startswith(key.lower()):
            return name
    return comm or "?"


def memory_details(top=6):
    """RAM, compressed RAM (zram), swap file, and which apps use memory (in RAM and in swap)."""
    m = meminfo()
    vals = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.split():
            vals[k] = int(v.split()[0]) * 1024
    zram = {"total": 0, "used": 0, "stored": 0}
    swapfile = {"total": 0, "used": 0}
    for line in _read("/proc/swaps").splitlines()[1:]:
        f = line.split()
        if len(f) < 4:
            continue
        size, used = int(f[2]) * 1024, int(f[3]) * 1024
        target = zram if "zram" in f[0] else swapfile
        target["total"] += size
        target["used"] += used
    mm = _read("/sys/block/zram0/mm_stat").split()
    if len(mm) >= 3:
        zram["stored"] = int(mm[0])          # app memory kept in zram
        zram["ram_cost"] = int(mm[2])        # real RAM it takes after compression
    apps = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        rss = swap = 0
        for line in _read(f"/proc/{pid}/status").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
            elif line.startswith("VmSwap:"):
                swap = int(line.split()[1]) * 1024
        if not rss and not swap:
            continue
        name = _app_name(pid)
        a = apps.setdefault(name, {"name": name, "ram": 0, "swap": 0})
        a["ram"] += rss
        a["swap"] += swap
    ranked = sorted(apps.values(), key=lambda a: a["ram"] + a["swap"], reverse=True)[:top]
    return {"ram": {"total": m["total"], "used": m["used"], "available": m["available"], "cache": vals.get("Cached", 0)},
            "zram": zram, "swapfile": swapfile, "usable": m["total"] + swapfile["total"],
            "swap_total": m["swap_total"], "swap_used": m["swap_used"], "apps": ranked}


def disk(path="/"):
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return {"total": total, "free": free, "used": total - free}
    except OSError:
        return {"total": 0, "free": 0, "used": 0}


def temps():
    out = []
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        t = _read(os.path.join(zone, "temp"))
        if t.lstrip("-").isdigit():
            c = int(t) / 1000.0
            if -40 < c < 150:
                out.append({"name": _read(os.path.join(zone, "type"), os.path.basename(zone)), "c": round(c, 1)})
    return out


def static_info():
    rel = os_release()
    return {
        "hostname": socket.gethostname(),
        "os": rel.get("PRETTY_NAME", "JStarx OS"),
        "layer": __version__,
        "kernel": platform.release(),
        "arch": platform.machine(),
        "model": model(),
        "cpu": cpu_name(),
        "cores": os.cpu_count() or 1,
        "memory": meminfo()["total"],
        "disk": disk()["total"],
    }


class CpuMeter:
    """CPU use in percent since the previous call (reads /proc/stat, no busy loop)."""

    def __init__(self):
        self.prev = self._sample()

    @staticmethod
    def _sample():
        parts = _read("/proc/stat").splitlines()[0].split()[1:] if _read("/proc/stat") else []
        nums = [int(x) for x in parts]
        if len(nums) < 4:
            return (0, 0)
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return (sum(nums), idle)

    def percent(self):
        cur = self._sample()
        dt = cur[0] - self.prev[0]
        di = cur[1] - self.prev[1]
        self.prev = cur
        if dt <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * (dt - di) / dt)), 1)


_cpu = CpuMeter()


def stats():
    t = temps()
    try:
        uptime = float(_read("/proc/uptime", "0").split()[0])
    except (ValueError, IndexError):
        uptime = 0.0
    try:
        load = os.getloadavg()
    except OSError:
        load = (0, 0, 0)
    return {
        "cpu": _cpu.percent(),
        "memory": meminfo(),
        "disk": disk(),
        "temps": t,
        "temp": max((x["c"] for x in t), default=None),
        "uptime": uptime,
        "load": [round(x, 2) for x in load],
        "time": time.time(),
    }


# ---------------- networking (NetworkManager) ----------------
def _nm_split(line):
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


def net_status():
    r = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    devices = []
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            p = _nm_split(line)
            if len(p) >= 4 and p[1] in ("wifi", "ethernet"):
                devices.append({"device": p[0], "type": p[1], "state": p[2], "connection": p[3]})
    wifi_on = None
    r2 = _run(["nmcli", "-t", "radio", "wifi"])
    if r2 and r2.returncode == 0:
        wifi_on = r2.stdout.strip() == "enabled"
    signal = None
    ssid = None
    r3 = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi"])
    if r3 and r3.returncode == 0:
        for line in r3.stdout.splitlines():
            p = _nm_split(line)
            if len(p) >= 3 and p[0] == "yes":
                ssid, signal = p[1], int(p[2]) if p[2].isdigit() else None
    if not devices:  # no NetworkManager: fall back to kernel state
        for path in glob.glob("/sys/class/net/*"):
            name = os.path.basename(path)
            if name == "lo":
                continue
            kind = "wifi" if os.path.isdir(os.path.join(path, "wireless")) else "ethernet"
            state = _read(os.path.join(path, "operstate"))
            devices.append({"device": name, "type": kind, "state": "connected" if state == "up" else state, "connection": ""})
    online = any(d["state"].startswith("connected") for d in devices)
    return {"devices": devices, "wifi_on": wifi_on, "ssid": ssid, "signal": signal, "online": online}


def wifi_list(rescan=False):
    r = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes" if rescan else "no"], timeout=20)
    nets, seen = [], set()
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            p = _nm_split(line)
            if len(p) >= 4 and p[1] and p[1] not in seen:
                seen.add(p[1])
                nets.append({"active": p[0] == "*", "ssid": p[1], "signal": int(p[2]) if p[2].isdigit() else 0,
                             "secure": bool(p[3] and p[3] != "--")})
    nets.sort(key=lambda n: (not n["active"], -n["signal"]))
    return nets


def wifi_connect(ssid, password=None):
    args = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    r = _run(args, timeout=45)
    if r is None:
        return {"ok": False, "message": "NetworkManager is not available"}
    return {"ok": r.returncode == 0, "message": (r.stdout or r.stderr).strip()}


def wifi_radio(on):
    r = _run(["nmcli", "radio", "wifi", "on" if on else "off"])
    return bool(r and r.returncode == 0)


# ---------------- sound (PipeWire / WirePlumber) ----------------
def audio_get():
    r = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    if not r or r.returncode != 0:
        return {"available": False, "volume": 0, "muted": False}
    m = re.search(r"Volume:\s*([0-9.]+)", r.stdout)
    return {"available": True, "volume": round(float(m.group(1)) * 100) if m else 0, "muted": "MUTED" in r.stdout}


def audio_set(volume=None, muted=None):
    if volume is not None:
        v = max(0, min(100, int(volume))) / 100.0
        _run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{v:.2f}"])
    if muted is not None:
        _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"])
    return audio_get()


# ---------------- display ----------------
def outputs():
    r = _run(["wlr-randr", "--json"])
    if r and r.returncode == 0:
        import json
        try:
            data = json.loads(r.stdout)
            res = []
            for o in data:
                cur = next((m for m in o.get("modes", []) if m.get("current")), None)
                res.append({"name": o.get("name"), "description": o.get("description", ""), "enabled": o.get("enabled", True),
                            "scale": o.get("scale", 1.0),
                            "mode": f"{cur['width']}x{cur['height']}@{round(cur.get('refresh', 60))}" if cur else None,
                            "modes": sorted({f"{m['width']}x{m['height']}" for m in o.get("modes", [])},
                                            key=lambda s: -int(s.split('x')[0]) * int(s.split('x')[1]))})
            return res
        except (ValueError, KeyError, TypeError):
            pass
    return []


def set_output(name, mode=None, scale=None):
    args = ["wlr-randr", "--output", name]
    if mode:
        args += ["--mode", mode]
    if scale:
        args += ["--scale", str(scale)]
    r = _run(args)
    return bool(r and r.returncode == 0)


def backlight_get():
    for d in glob.glob("/sys/class/backlight/*"):
        try:
            cur = int(_read(os.path.join(d, "brightness"), "0"))
            mx = int(_read(os.path.join(d, "max_brightness"), "1")) or 1
            return {"available": True, "level": round(cur * 100 / mx)}
        except ValueError:
            continue
    return {"available": False, "level": 100}


def casting_available():
    return bool(shutil.which("gnome-network-displays"))
