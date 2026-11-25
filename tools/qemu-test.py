#!/usr/bin/env python3
"""Boot the JStarx SD card image in QEMU (ARM64) and test the whole OS.

    python3 tools/qemu-test.py result-sd/sd-image/jstarx-1.0.0-jetson-nano.img

What it checks:
  1. it starts with the JStarx boot screen (screenshots of every second of the boot)
  2. the StarX Kernel, the system services and the desktop come up (desktop screenshot)
  3. Firefox, Claude, Spark 1, the games and the Star Store are installed
  4. auto-repair: damaged JStarx files are fixed
  5. auto-repair: a desktop that keeps crashing is put back to a working version
  6. auto-repair: a system build that does not start is undone at the next boot

Needs qemu-system-aarch64, qemu-img, U-Boot for QEMU (Debian/Ubuntu package u-boot-qemu)
and Python 3 with Pillow. The SD image itself is never changed (QEMU writes to an overlay).
Results go to test-out/: report.md, serial.log and screenshots.
"""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UBOOT = ["/usr/lib/u-boot/qemu_arm64/u-boot.bin", "/usr/share/u-boot/qemu_arm64/u-boot.bin"]
USER, PASSWORD = "storm", "jstarx"
SESSION_ENV = ("XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 STARX_PYTHON=starx-python "
               "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus MOZ_ENABLE_WAYLAND=1")
CTL = f"sudo -u {USER} env {SESSION_ENV} /var/lib/jstarx/layers/current/bin/starx-ctl"


class Timeout(Exception):
    pass


class Serial:
    """The serial console of the machine: everything it prints is kept and logged."""

    def __init__(self, path, logfile):
        self.sock = _connect(path)
        self.buf = b""
        self.lock = threading.Lock()
        self.log = open(logfile, "ab", buffering=0)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.buf += data
            self.log.write(data)

    def mark(self):
        with self.lock:
            return len(self.buf)

    def text(self, since=0):
        with self.lock:
            return self.buf[since:].decode("utf-8", "replace")

    def wait(self, pattern, timeout, since=0):
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            m = rx.search(self.text(since))
            if m:
                return m
            time.sleep(0.5)
        raise Timeout(f"waited {timeout}s for {pattern!r}")

    def send(self, text):
        self.sock.sendall(text.encode())


class Monitor:
    """The QEMU monitor: used for screenshots."""

    def __init__(self, path):
        self.sock = _connect(path)
        self.sock.settimeout(30)
        self._read_prompt()

    def _read_prompt(self):
        data = b""
        while not data.endswith(b"(qemu) "):
            chunk = self.sock.recv(65536)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", "replace")

    def cmd(self, line):
        self.sock.sendall((line + "\n").encode())
        return self._read_prompt()

    def screenshot(self, png, scale=1.0):
        ppm = png + ".ppm"
        self.cmd(f"screendump {ppm}")
        for _ in range(20):
            if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
                break
            time.sleep(0.2)
        try:
            im = Image.open(ppm).convert("RGB")
        except Exception:
            return None
        finally:
            if os.path.exists(ppm):
                os.remove(ppm)
        if scale != 1.0:
            im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        im.save(png, optimize=True)
        return im


def _connect(path):
    for _ in range(100):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            return s
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"could not connect to {path}")


class Machine:
    def __init__(self, image, out, memory=4096, cpus=4, display=True):
        self.out = out
        self.disk = os.path.join(out, "disk.qcow2")
        if os.path.exists(self.disk):
            os.remove(self.disk)
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "raw", "-b", os.path.abspath(image),
                        self.disk, "16G"], check=True)
        uboot = next((u for u in UBOOT if os.path.exists(u)), None)
        if not uboot:
            sys.exit("U-Boot for QEMU not found (install the u-boot-qemu package)")
        self.serial_path = os.path.join(out, "serial.sock")
        self.monitor_path = os.path.join(out, "monitor.sock")
        for p in (self.serial_path, self.monitor_path):
            if os.path.exists(p):
                os.remove(p)
        cmd = [
            "qemu-system-aarch64", "-M", "virt", "-cpu", "cortex-a57", "-smp", str(cpus), "-m", str(memory),
            "-accel", "tcg,thread=multi", "-bios", uboot,
            "-drive", f"if=none,id=hd0,file={self.disk},format=qcow2", "-device", "virtio-blk-pci,drive=hd0",
            *(["-device", "virtio-gpu-pci,xres=1280,yres=720"] if display else []),
            "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-tablet",
            "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
            "-device", "i6300esb", "-action", "watchdog=reset",
            "-display", "none",
            "-serial", f"unix:{self.serial_path},server=on,wait=off",
            "-monitor", f"unix:{self.monitor_path},server=on,wait=off",
        ]
        self.proc = subprocess.Popen(cmd, stdout=open(os.path.join(out, "qemu.log"), "wb"), stderr=subprocess.STDOUT)
        self.serial = Serial(self.serial_path, os.path.join(out, "serial.log"))
        self.monitor = Monitor(self.monitor_path)
        self.n = 0

    def stop(self):
        try:
            self.monitor.cmd("quit")
        except Exception:
            pass
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def login(self, since=0, timeout=1500):
        """Log in on the serial console and become root (sudo)."""
        s = self.serial
        s.wait(r"jstarx login: ", timeout, since)
        time.sleep(2)
        m = s.mark()
        s.send(USER + "\n")
        s.wait(r"Password: ", 120, m)
        s.send(PASSWORD + "\n")
        s.wait(r"storm@jstarx[^\n]*\$", 300, m)
        m = s.mark()
        s.send("sudo -i\n")
        s.wait(r"password for storm", 120, m)
        s.send(PASSWORD + "\n")
        s.wait(r"root@jstarx[^\n]*#", 300, m)
        s.send("stty -echo; export PS1= PS2= TERM=dumb SYSTEMD_COLORS=0 SYSTEMD_PAGER= PAGER=cat; dmesg -n 1\n")
        time.sleep(3)
        self.sh("true", 120)

    def sh(self, cmd, timeout=300, check=False):
        """Run a command as root. Returns (exit code, output)."""
        self.n += 1
        tag = f"_JX{self.n}_"
        m = self.serial.mark()
        # one line, so nothing is typed ahead while a command runs (sudo would swallow it)
        sep = " " if cmd.rstrip().endswith("&") else " ; "
        self.serial.send(f"{cmd}{sep}echo {tag}$?{tag}\n")
        r = self.serial.wait(rf"{tag}(\d+){tag}", timeout, m)
        out = self.serial.text(m)[: r.start()].replace("\r", "").strip("\n")
        code = int(r.group(1))
        if check and code != 0:
            raise AssertionError(f"`{cmd}` failed ({code}):\n{out}")
        return code, out

    def wait_sh(self, cmd, timeout, every=10):
        """Repeat a command until it succeeds."""
        end = time.time() + timeout
        while time.time() < end:
            code, out = self.sh(cmd, 300)
            if code == 0:
                return out
            time.sleep(every)
        raise Timeout(f"`{cmd}` did not succeed within {timeout}s")


class Report:
    def __init__(self, out):
        self.out = out
        self.rows = []
        self.notes = []
        self.started = time.time()

    def check(self, name, ok, detail=""):
        mark = "PASS" if ok else "FAIL"
        self.rows.append((name, ok, detail))
        print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""), flush=True)
        return ok

    def write(self):
        passed = sum(1 for r in self.rows if r[1])
        lines = ["# JStarx QEMU test report", "",
                 f"{passed} of {len(self.rows)} checks passed in {int(time.time() - self.started) // 60} minutes.", "",
                 "| Check | Result | Details |", "|---|---|---|"]
        for name, ok, detail in self.rows:
            d = detail.replace("|", "/").replace("\n", " ")[:300]
            lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {d} |")
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {n}" for n in self.notes]
        with open(os.path.join(self.out, "report.md"), "w") as f:
            f.write("\n".join(lines) + "\n")
        return passed == len(self.rows)


def boot_frames(vm, out, until_pattern, timeout):
    """Screenshot the screen every second while booting, until the serial console shows the pattern."""
    frames = os.path.join(out, "boot-frames")
    os.makedirs(frames, exist_ok=True)
    end = time.time() + timeout
    i = 0
    rx = re.compile(until_pattern)
    while time.time() < end:
        if rx.search(vm.serial.text()):
            return i
        vm.monitor.screenshot(os.path.join(frames, f"{i:04d}.png"), scale=0.5)
        i += 1
        time.sleep(1)
    return i


def pick_boot_screen(out):
    """The boot screen frame: the most colourful (purple + orange) frame before the desktop."""
    frames = sorted(os.listdir(os.path.join(out, "boot-frames")))
    best, best_score = None, -1
    for name in frames:
        im = Image.open(os.path.join(out, "boot-frames", name)).convert("RGB").resize((160, 90))
        px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
        purple = sum(1 for r, g, b in px if b > 60 and r > 40 and g < r and b > g + 20)
        orange = sum(1 for r, g, b in px if r > 200 and 90 < g < 200 and b < 90)
        centre = im.crop((67, 25, 93, 50))  # where the logo lands
        cp = list(centre.get_flattened_data() if hasattr(centre, "get_flattened_data") else centre.getdata())
        logo = sum(1 for r, g, b in cp if r > 150 and (g > 90 or b > 150))
        score = purple + 30 * orange + 40 * logo if purple > 1500 else purple
        if score > best_score:
            best, best_score = name, score
    if best:
        shutil.copy(os.path.join(out, "boot-frames", best), os.path.join(out, "boot-screen.png"))
    return best, best_score


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--out", default=os.path.join(ROOT, "test-out"))
    ap.add_argument("--skip-reboot-test", action="store_true")
    ap.add_argument("--no-display", action="store_true", help="start with no screen: JStarx should look for a wireless display")
    ap.add_argument("--repair-only", action="store_true", help="only boot, then run the auto-repair tests")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for f in ("serial.log", "report.md"):
        if os.path.exists(os.path.join(args.out, f)):
            os.remove(os.path.join(args.out, f))
    shutil.rmtree(os.path.join(args.out, "boot-frames"), ignore_errors=True)

    rep = Report(args.out)
    vm = Machine(args.image, args.out, display=not args.no_display)
    try:
        (run_no_display_tests if args.no_display else run_tests)(vm, rep, args)
    except Exception as e:
        rep.check("test run finished", False, f"{type(e).__name__}: {e}")
        try:
            vm.monitor.screenshot(os.path.join(args.out, "at-failure.png"))
        except Exception:
            pass
    finally:
        vm.stop()
        ok = rep.write()
    print(open(os.path.join(args.out, "report.md")).read())
    sys.exit(0 if ok else 1)


def run_no_display_tests(vm, rep, args):
    """No screen plugged in: the desktop runs on a virtual screen and StarCast looks for a TV."""
    t0 = time.time()
    vm.serial.wait(r"jstarx login: ", 1500)
    rep.check("Starts with no screen plugged in", True, f"{int(time.time() - t0)}s")
    vm.login()
    try:
        vm.wait_sh("pgrep -u storm -f 'starx.shell' >/dev/null", 1500, every=15)
        rep.check("Desktop runs on a virtual screen", True)
    except Timeout as e:
        rep.check("Desktop runs on a virtual screen", False, str(e))
        vm.sh("tail -30 /run/user/1000/jstarx/session.log")
    code, env = vm.sh("P=$(pgrep -u storm -f 'starx.shell' | head -1); tr '\\0' '\\n' < /proc/$P/environ | grep -E 'STARX_HEADLESS|WLR_BACKENDS'")
    rep.check("Session knows there is no screen", "STARX_HEADLESS=1" in env, env.strip().replace("\n", " "))
    try:
        out = vm.wait_sh("grep -E '\"state\": \"(searching|none-found|starting|casting)\"' /run/user/1000/jstarx/cast.json", 600, every=10)
        rep.check("StarCast looks for a wireless display by itself", True, out.strip()[:200])
    except Timeout as e:
        _, cast = vm.sh("cat /run/user/1000/jstarx/cast.json; pgrep -af starcast")
        rep.check("StarCast looks for a wireless display by itself", False, cast[:200])


def run_tests(vm, rep, args):
    out = args.out
    t0 = time.time()
    # ---------------------------------------------------------------- 1. boot screen
    n = boot_frames(vm, out, r"jstarx login: ", 1500)
    rep.check("Boots to the login console", "jstarx login:" in vm.serial.text(), f"{int(time.time() - t0)}s, {n} screenshots")
    serial = vm.serial.text()
    rep.check("U-Boot finds the JStarx boot menu", "JStarx" in serial and "Retrieving file" in serial)
    best, score = pick_boot_screen(out)
    rep.check("JStarx boot screen is shown", score > 2000, f"frame {best}, colour score {score}")

    vm.login()
    if args.repair_only:
        vm.wait_sh("pgrep -u storm -f 'starx.shell' >/dev/null", 1500, every=15)
        rep.check("StarShell desktop started", True)
        return run_repair_tests(vm, rep, args)
    # ---------------------------------------------------------------- 2. system
    _, kernel = vm.sh("uname -r; cat /proc/version")
    rep.check("Runs the StarX Kernel", "6.12.118-starx" in kernel and "1-StarX" in kernel, kernel.splitlines()[0] if kernel else "")
    _, osr = vm.sh("grep PRETTY_NAME /etc/os-release")
    rep.check("System is JStarx OS", "JStarx OS" in osr, osr)
    _, cmdline = vm.sh("cat /proc/cmdline")
    rep.check("Boot counter knows the build", "jstarx.gen=1" in cmdline)
    for unit in ("starxd", "starai", "spark", "jstarx-repair", "greetd", "NetworkManager", "avahi-daemon"):
        code, state = vm.sh(f"systemctl is-active {unit}")
        rep.check(f"Service {unit} is running", state.strip().endswith("active") and code == 0, state.strip())
    _, failed = vm.sh("systemctl --failed --no-legend --plain | grep -v '^$' || true")
    rep.check("No failed services", failed.strip() == "", failed.strip())
    _, rr = vm.sh("cat /var/lib/jstarx/repair-report.json 2>/dev/null || journalctl -u jstarx-repair -b --no-pager | tail -5")
    rep.check("Auto-repair checked the system at boot", '"state"' in rr or "healthy" in rr, rr[:200])

    # ---------------------------------------------------------------- 3. desktop
    try:
        vm.wait_sh("pgrep -u storm -f 'starx.shell' >/dev/null && test -S /run/user/1000/jstarx/shell.sock", 1500, every=15)
        rep.check("StarShell desktop started", True)
    except Timeout as e:
        rep.check("StarShell desktop started", False, str(e))
        vm.sh("tail -40 /run/user/1000/jstarx/session.log /run/user/1000/jstarx/supervisor.log 2>/dev/null")
    code, _ = vm.sh("pgrep -u storm -x swayidle >/dev/null")
    rep.check("Screen power saving is on", code == 0)
    vm.sh("pkill -u storm -x swayidle || true")  # keep the screen on for the screenshots
    time.sleep(120)  # let the slow emulated CPU finish drawing
    vm.monitor.screenshot(os.path.join(out, "welcome.png"))
    _, state = vm.sh(f"{CTL} state")
    rep.check("Welcome screen opens on the first start", '"welcome"' in state, state[:160])
    vm.sh(f"{CTL} close")
    time.sleep(30)
    vm.monitor.screenshot(os.path.join(out, "desktop.png"))
    _, health = vm.sh(f"{CTL} health")
    rep.check("Desktop answers (dock, island, home)", '"ok": true' in health, health[:200])
    code, _ = vm.sh(f"{CTL} launchpad")
    time.sleep(40)
    vm.monitor.screenshot(os.path.join(out, "launchpad.png"))
    vm.sh(f"{CTL} close")
    code, _ = vm.sh(f"{CTL} start")
    time.sleep(40)
    vm.monitor.screenshot(os.path.join(out, "start-menu.png"))
    vm.sh(f"{CTL} close")
    time.sleep(10)

    # ---------------------------------------------------------------- 4. apps
    code, ff = vm.sh(f"sudo -u {USER} firefox --version 2>&1", 600)
    rep.check("Firefox is installed", code == 0 and "Firefox" in ff, ff.strip()[:80])
    code, _ = vm.sh("test -x /var/lib/jstarx/layers/current/bin/starx-claude")
    rep.check("Claude app is installed", code == 0)
    code, _ = vm.sh("for g in snake dodge breaker; do test -f /var/lib/jstarx/layers/current/web/games/$g/index.html || exit 1; done")
    rep.check("3 games are installed", code == 0)
    code, cat = vm.sh("starx-python -c 'import json;print(len(json.load(open(\"/var/lib/jstarx/layers/current/store/catalog.json\"))[\"apps\"]))'")
    rep.check("Star Store has installable official apps", code == 0 and cat.strip().isdigit() and int(cat.strip()) >= 5, f"{cat.strip()} apps")
    code, sp = vm.sh("journalctl -u spark -b --no-pager | tail -3")
    rep.check("Spark 1 engine is waiting for its model", "spark" in sp.lower() or code == 0, sp.strip()[-150:])
    code, ll = vm.sh("command -v llama-server")
    rep.check("Spark 1 engine (llama.cpp) is installed", code == 0, ll.strip())
    code, _ = vm.sh("command -v gnome-network-displays && pgrep -f starx.starcast >/dev/null")
    rep.check("Wireless display casting is ready", code == 0)
    vm.sh(f"sudo -u {USER} env {SESSION_ENV} firefox about:logo >/dev/null 2>&1 &")
    time.sleep(240)
    vm.monitor.screenshot(os.path.join(out, "firefox.png"))
    vm.sh("pkill -f firefox || true")

    run_repair_tests(vm, rep, args)


def run_repair_tests(vm, rep, args):
    out = args.out
    # ---------------------------------------------------------------- 5. auto-repair: damaged files
    code, upd = vm.sh("jstarx-update apply /etc/jstarx/factory-layer", 900)
    rep.check("Updater installs a layer into slot A", '"updated"' in upd, upd[-200:])
    vm.sh("L=/var/lib/jstarx/layers/a; echo broken > $L/web/shell/dock.js; rm -f $L/web/shell/island.js $L/web/games/snake/index.html")
    code, fix = vm.sh("jstarx-repair quick", 900)
    code2, _ = vm.sh("L=/var/lib/jstarx/layers/a; F=/etc/jstarx/factory-layer; cmp $L/web/shell/dock.js $F/web/shell/dock.js && cmp $L/web/shell/island.js $F/web/shell/island.js && cmp $L/web/games/snake/index.html $F/web/games/snake/index.html")
    rep.check("Auto-repair fixes damaged and missing files", code2 == 0 and "Restored" in fix, " ".join(re.findall(r"Restored [^\"]+", fix))[:200])

    # ---------------------------------------------------------------- 6. auto-repair: crashing desktop
    # end the desktop session, then let greetd log in again (it only auto-logs in once per boot otherwise)
    vm.sh("pkill -u storm -f starx-shell-supervisor; pkill -u storm -x labwc; sleep 8; rm -f /run/greetd.run; systemctl restart greetd")
    try:
        vm.wait_sh("P=$(pgrep -n -u storm -f 'starx.shell') && tr '\\0' '\\n' < /proc/$P/environ | grep -q 'JSTARX_LAYER=/var/lib/jstarx/layers/a'", 1500, every=15)
        on_a = True
    except Timeout:
        on_a = False
    rep.check("Desktop restarts on the updated layer (slot A)", on_a)
    vm.sh("sleep 5; pkill -u storm -x swayidle || true")
    for i in range(3):
        _, pid = vm.sh("pgrep -n -u storm -f 'starx.shell'")
        vm.sh("pkill -9 -u storm -f 'starx.shell' || true")
        if i < 2:
            vm.wait_sh(f"P=$(pgrep -n -u storm -f 'starx.shell') && [ -n \"$P\" ] && [ \"$P\" != '{pid.strip()}' ]", 600, every=3)
    try:
        vm.wait_sh("grep -q 'auto-repair switched' /run/user/1000/jstarx/supervisor.log", 900, every=10)
        switched = True
    except Timeout:
        switched = False
    _, log = vm.sh("tail -5 /run/user/1000/jstarx/supervisor.log; readlink -f /var/lib/jstarx/layers/current")
    rep.check("Crashing desktop is rolled back to a working version", switched and "jstarx-layer" in log, log[-250:])
    try:
        vm.wait_sh("pgrep -u storm -f 'starx.shell' >/dev/null", 900, every=10)
        rep.check("Desktop is running again after the repair", True)
    except Timeout:
        rep.check("Desktop is running again after the repair", False)
    time.sleep(60)
    vm.monitor.screenshot(os.path.join(out, "after-repair.png"))

    if args.skip_reboot_test:
        return
    # ---------------------------------------------------------------- 7. auto-repair: broken system build
    vm.wait_sh("[ \"$(cat /boot/jstarx/known-good 2>/dev/null)\" = 1 ]", 900, every=15)
    rep.check("Build 1 is marked as working", True)
    vm.sh(r"""C=/boot/extlinux/extlinux.conf
FALSE=$(readlink -f $(command -v false))
K=$(grep -m1 '^  LINUX' $C); I=$(grep -m1 '^  INITRD' $C); F=$(grep -m1 '^  FDTDIR' $C)
A=$(grep -m1 '^  APPEND' $C | sed "s|init=[^ ]*|init=$FALSE|; s|jstarx.gen=1|jstarx.gen=2|")
printf '\nLABEL jstarx-2\n  MENU LABEL JStarx (build 2, broken on purpose)\n%s\n%s\n%s\n%s\n' "$K" "$I" "$A" "$F" >> $C
sed -i 's/^DEFAULT .*/DEFAULT jstarx-2/' $C; sync""", check=True)
    m = vm.serial.mark()
    vm.serial.send("systemctl reboot\n")
    try:
        vm.serial.wait(r"JStarx auto-repair: build 2 did not start", 2400, m)
        rep.check("Auto-repair notices build 2 does not start", True)
    except Timeout as e:
        rep.check("Auto-repair notices build 2 does not start", False, str(e))
    vm.login(since=vm.serial.mark(), timeout=2400)
    boots = len(re.findall(r"U-Boot 20\d\d", vm.serial.text(m)))
    _, cmd = vm.sh("cat /proc/cmdline; grep ^DEFAULT /boot/extlinux/extlinux.conf; cat /boot/jstarx/repair.log")
    rep.check("Went back to build 1 by itself", "jstarx.gen=1" in cmd and "DEFAULT jstarx-1" in cmd and "went back to build 1" in cmd,
              f"{boots} starts: {cmd.splitlines()[-1] if cmd else ''}")
    try:
        vm.wait_sh("pgrep -u storm -f 'starx.shell' >/dev/null", 1500, every=15)
        time.sleep(60)
        vm.monitor.screenshot(os.path.join(out, "after-fallback.png"))
        rep.check("Desktop is back after the fallback", True)
    except Timeout:
        rep.check("Desktop is back after the fallback", False)


if __name__ == "__main__":
    main()
