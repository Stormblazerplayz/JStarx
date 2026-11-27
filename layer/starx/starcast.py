"""StarCast: when no screen is plugged in, find a wireless display and show JStarx on it.

How it works
  1. Every few seconds it checks /sys/class/drm for a connected screen (HDMI, DP...).
  2. If none is connected, the session runs on a virtual screen. StarCast looks for
     Google Cast displays (Chromecast, TVs with Chromecast built in) on the network.
  3. It records the virtual screen (wf-recorder), turns it into a live HLS stream
     (ffmpeg), serves it on port 8765 and asks the display to play it.
  4. When a real screen is plugged in, casting stops.
Run with:  python3 -m starx.starcast
"""
import functools
import glob
import http.server
import json
import os
import shutil
import signal
import socket
import socketserver
import subprocess
import tempfile
import threading
import time

from . import paths
from .settings import Settings, atomic_write_json

PORT = int(os.environ.get("STARCAST_PORT", "8765"))
STATUS_FILE = os.path.join(paths.RUNTIME, "cast.json")


def physical_display_connected(drm_root="/sys/class/drm"):
    """True if any real display connector reports 'connected'."""
    for status in glob.glob(os.path.join(drm_root, "card*-*", "status")):
        name = os.path.basename(os.path.dirname(status))
        if "Writeback" in name:
            continue
        try:
            with open(status) as f:
                if f.read().strip() == "connected":
                    return True
        except OSError:
            continue
    return False


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def write_status(**st):
    st["time"] = time.time()
    try:
        atomic_write_json(STATUS_FILE, st)
    except OSError:
        pass


def pick_device(devices, preferred=""):
    """Prefer the remembered display, otherwise the first one found (sorted by name)."""
    if not devices:
        return None
    for d in devices:
        if preferred and preferred in (d["name"], d["uuid"]):
            return d
    return sorted(devices, key=lambda d: d["name"].lower())[0]


class Streamer:
    """Screen -> H.264 -> HLS files -> tiny web server."""

    def __init__(self, output=None, fps=15, size="1280x720"):
        self.output, self.fps, self.size = output, fps, size
        self.dir = tempfile.mkdtemp(prefix="starcast-")
        self.procs = []
        self.httpd = None

    def start(self):
        rec = ["wf-recorder", "-y", "-c", "libx264", "-p", "preset=ultrafast", "-p", "tune=zerolatency",
               "-x", "yuv420p", "-r", str(self.fps), "-m", "mpegts", "-f", "/dev/stdout"]
        if self.output:
            rec[1:1] = ["-o", self.output]
        w, h = self.size.split("x")
        hls = ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
               "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", str(self.fps * 2), "-b:v", "2500k",
               "-f", "hls", "-hls_time", "2", "-hls_list_size", "5", "-hls_flags", "delete_segments+independent_segments",
               os.path.join(self.dir, "stream.m3u8")]
        r = subprocess.Popen(rec, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        f = subprocess.Popen(hls, stdin=r.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r.stdout.close()
        self.procs = [r, f]
        handler = functools.partial(_QuietHandler, directory=self.dir)
        self.httpd = _ThreadingHTTPServer(("0.0.0.0", PORT), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return f"http://{local_ip()}:{PORT}/stream.m3u8"

    def alive(self):
        return all(p.poll() is None for p in self.procs)

    def wait_ready(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(os.path.join(self.dir, "stream.m3u8")):
                return True
            time.sleep(0.5)
        return False

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if self.httpd:
            self.httpd.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """http.server.ThreadingHTTPServer, which only exists from Python 3.7 (JetPack has 3.6)."""
    daemon_threads = True


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def discover(timeout=8):
    """Find Google Cast displays on the local network."""
    try:
        import pychromecast
    except ImportError:
        return [], None
    casts, browser = pychromecast.get_chromecasts(timeout=timeout)
    devices = [{"name": c.cast_info.friendly_name, "uuid": str(c.cast_info.uuid), "model": c.cast_info.model_name,
                "host": c.cast_info.host, "_obj": c} for c in casts]
    return devices, browser


def headless_output():
    """Name of the virtual output the session renders to (if any)."""
    try:
        r = subprocess.run(["wlr-randr", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=5)
        for o in json.loads(r.stdout or "[]"):
            if o.get("name", "").startswith("HEADLESS"):
                return o["name"]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def run():
    settings = Settings()
    streamer, cast_dev, browser = None, None, None
    write_status(state="idle")
    while True:
        cfg = settings.load().get("cast", {})
        if physical_display_connected() or not cfg.get("auto", True):
            if streamer:
                streamer.stop()
                streamer = None
                try:
                    cast_dev and cast_dev["_obj"].quit_app()
                except Exception:
                    pass
                cast_dev = None
            write_status(state="screen-connected" if physical_display_connected() else "off")
            time.sleep(5)
            continue
        if streamer and streamer.alive():
            time.sleep(5)
            continue
        if streamer:  # it stopped by itself: clean up and try again
            streamer.stop()
            streamer = None
        write_status(state="searching")
        devices, browser = discover(timeout=8)
        dev = pick_device(devices, cfg.get("device", ""))
        if not dev:
            write_status(state="none-found", found=[])
            time.sleep(20)
            continue
        write_status(state="starting", device=dev["name"])
        streamer = Streamer(headless_output(), fps=cfg.get("fps", 15), size=cfg.get("resolution", "1280x720"))
        url = streamer.start()
        if not streamer.wait_ready():
            streamer.stop()
            streamer = None
            write_status(state="error", message="could not record the screen")
            time.sleep(20)
            continue
        try:
            cc = dev["_obj"]
            cc.wait(timeout=10)
            cc.media_controller.play_media(url, "application/x-mpegurl", stream_type="LIVE", title="JStarx")
            cast_dev = dev
            write_status(state="casting", device=dev["name"], url=url,
                         found=[{"name": d["name"], "model": d["model"]} for d in devices])
        except Exception as e:
            write_status(state="error", message=str(e)[:200])
            streamer.stop()
            streamer = None
            time.sleep(20)


if __name__ == "__main__":
    paths.ensure_user_dirs()
    run()
