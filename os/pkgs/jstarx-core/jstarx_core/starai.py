"""StarAI: run AI jobs 24/7.

Each job is a supervised systemd unit (starai-<id>) running as the 'starai' user with CPU and
memory limits. The daemon:
  * restarts jobs after crashes, reboots and power cuts (jobs resume from their checkpoints)
  * freezes jobs when the Jetson is too hot and thaws them when it cools down
  * starts 'night' jobs only between 22:00 and 07:00
  * publishes /run/jstarx/ai.json for the dynamic island and AI Center
Socket: /run/starai.sock (group jstarx).
"""
import glob
import grp
import json
import os
import re
import shlex
import socket
import socketserver
import struct
import sys
import threading
import time
import uuid

from .common import RUN, log, read_json, run, write_json

ROOT = os.environ.get("STARAI_ROOT", "/var/lib/starai")
JOBS_FILE = os.path.join(ROOT, "jobs.json")
SOCKET = os.environ.get("STARAI_SOCKET", "/run/starai.sock")
PYTHON = os.environ.get("STARAI_PYTHON", sys.executable)
TRAINER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trainer.py")
USER = os.environ.get("STARAI_USER", "starai")

TEMPLATES = [
    {"id": "train-tinystar", "name": "Train TinyStar", "kind": "train", "icon": "chip", "fields": ["steps"],
     "description": "A small language model that learns to write like the stars. Saves progress, resumes after power cuts.",
     "defaults": {"name": "TinyStar training", "steps": 3000}},
    {"id": "serve-model", "name": "Serve a model 24/7", "kind": "serve", "icon": "sparkle", "fields": ["script"],
     "description": "Keep a .gguf model answering on your network (port 8091). Leave the path empty for Spark 1.",
     "defaults": {"name": "Model server", "command": ""}},
    {"id": "custom", "name": "Your own script", "kind": "script", "icon": "terminal", "fields": ["script"],
     "description": "Run a Python script or command. Write progress to $STARAI_PROGRESS to see it in the island.",
     "defaults": {"name": "My AI job", "command": ""}},
]


class Jobs:
    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = read_json(os.path.join(ROOT, "config.json"))
        self.cfg.setdefault("thermal_limit", 75)
        self.jobs = read_json(JOBS_FILE, default={"jobs": []}).get("jobs", [])
        self.temp = None
        self.cpu_prev = None
        self.last_pub = None

    # ---------------------------------------------------------------- persistence
    def save(self):
        write_json(JOBS_FILE, {"jobs": self.jobs})

    def get(self, jid):
        for j in self.jobs:
            if j["id"] == jid:
                return j
        raise KeyError("no such job")

    # ---------------------------------------------------------------- creating
    def create(self, spec):
        tpl = next((t for t in TEMPLATES if t["id"] == spec.get("template")), None)
        if not tpl:
            raise ValueError("unknown template")
        jid = uuid.uuid4().hex[:8]
        workdir = os.path.join(ROOT, "jobs", jid)
        os.makedirs(workdir, exist_ok=True)
        if tpl["id"] == "train-tinystar":
            steps = max(100, min(200000, int(spec.get("steps") or 3000)))
            cmd = [PYTHON, TRAINER, "--steps", str(steps), "--out", workdir]
        elif tpl["id"] == "serve-model":
            model = (spec.get("command") or "").strip() or self._spark_model()
            if not model:
                raise ValueError("No model found. Install Spark 1 first or type the path to a .gguf file.")
            cmd = ["llama-server", "--model", model, "--host", "0.0.0.0", "--port", "8091", "--threads", "3", "--no-webui"]
        else:
            text = (spec.get("command") or "").strip()
            if not text:
                raise ValueError("Type the script or command to run")
            cmd = [PYTHON, text] if text.endswith(".py") and " " not in text else shlex.split(text)
        job = {"id": jid, "name": str(spec.get("name") or tpl["name"])[:60], "kind": tpl["kind"], "template": tpl["id"],
               "cmd": cmd, "dir": workdir, "schedule": spec.get("schedule", "now") if spec.get("schedule") in ("now", "night") else "now",
               "restart": spec.get("restart") if spec.get("restart") in ("always", "on-failure", "never") else "on-failure",
               "cpu_quota": max(25, min(400, int(spec.get("cpu_quota") or 300))), "mem_max": spec.get("mem_max", "75%"),
               "state": "queued", "created": time.time(), "runtime": 0, "restarts": 0, "progress": 0, "message": ""}
        with self.lock:
            self.jobs.append(job)
            self.save()
        self.tick()
        return job

    @staticmethod
    def _spark_model():
        ggufs = sorted(glob.glob("/var/lib/spark/models/**/*.gguf", recursive=True), key=os.path.getsize, reverse=True)
        return ggufs[0] if ggufs else None

    # ---------------------------------------------------------------- systemd control
    def unit(self, job):
        return f"starai-{job['id']}.service"

    def launch(self, job, resume=False):
        props = [f"CPUQuota={job['cpu_quota']}%", f"MemoryMax={job['mem_max']}", "Nice=10", "IOSchedulingClass=idle",
                 f"Restart={'on-failure' if job['restart'] == 'on-failure' else ('always' if job['restart'] == 'always' else 'no')}",
                 "RestartSec=10", "KillSignal=SIGINT", "TimeoutStopSec=30"]
        args = ["systemd-run", f"--unit={self.unit(job)}", "--collect", f"--uid={USER}", f"--gid={USER}",
                f"--working-directory={job['dir']}", f"--setenv=STARAI_PROGRESS={job['dir']}/progress.json",
                f"--setenv=STARAI_CHECKPOINT_DIR={job['dir']}", f"--setenv=STARAI_RESUME={'1' if resume else '0'}",
                "--setenv=PYTHONUNBUFFERED=1", f"--description=StarAI job {job['name']}"]
        for p in props:
            args += ["-p", p]
        run(["chown", "-R", f"{USER}:{USER}", job["dir"]], timeout=30)
        r = run(args + ["--"] + job["cmd"], timeout=30)
        if r is None or r.returncode != 0:
            job["state"], job["message"] = "failed", (r.stderr.strip()[:200] if r else "could not start")
            return False
        job["state"], job["started"], job["message"] = "running", time.time(), ""
        return True

    def unit_state(self, job):
        r = run(["systemctl", "show", self.unit(job), "-p", "ActiveState,SubState,Result,NRestarts,FreezerState"], timeout=10)
        out = {}
        for line in (r.stdout if r else "").splitlines():
            k, _, v = line.partition("=")
            out[k] = v
        return out

    def action(self, jid, action, value=None):
        if jid == "*" and action == "thermal":
            self.cfg["thermal_limit"] = max(50, min(95, int(value)))
            write_json(os.path.join(ROOT, "config.json"), self.cfg)
            self.tick()
            return self.cfg
        with self.lock:
            job = self.get(jid)
            unit = self.unit(job)
            if action == "pause":
                run(["systemctl", "freeze", unit])
                job["state"], job["message"], job["user_paused"] = "paused", "Paused by you", True
            elif action == "resume":
                if job["state"] == "paused":
                    run(["systemctl", "thaw", unit])
                    job["state"], job["message"], job["user_paused"] = "running", "", False
                else:
                    job["state"], job["user_paused"] = "queued", False
            elif action == "stop":
                run(["systemctl", "thaw", unit])
                run(["systemctl", "stop", unit], timeout=60)
                job["state"], job["message"] = "stopped", ""
            elif action == "delete":
                run(["systemctl", "thaw", unit])
                run(["systemctl", "stop", unit], timeout=60)
                self.jobs = [j for j in self.jobs if j["id"] != jid]
            else:
                raise ValueError("unknown action")
            self.save()
        self.tick()
        return True

    def log(self, jid, lines=200):
        job = self.get(jid)
        r = run(["journalctl", "-u", self.unit(job), "-n", str(max(10, min(2000, int(lines)))), "--no-pager", "-o", "cat"], timeout=20)
        return {"text": r.stdout if r else ""}

    # ---------------------------------------------------------------- the loop
    @staticmethod
    def night():
        h = time.localtime().tm_hour
        return h >= 22 or h < 7

    def read_temp(self):
        temps = []
        for z in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
            try:
                v = int(open(z).read().strip()) / 1000
                if 0 < v < 150:
                    temps.append(v)
            except (OSError, ValueError):
                pass
        return max(temps) if temps else None

    def read_cpu(self):
        try:
            nums = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        except OSError:
            return None
        total, idle = sum(nums), nums[3] + (nums[4] if len(nums) > 4 else 0)
        prev, self.cpu_prev = self.cpu_prev, (total, idle)
        if not prev or total == prev[0]:
            return None
        return round(100 * (1 - (idle - prev[1]) / (total - prev[0])), 1)

    def tick(self, boot=False):
        with self.lock:
            self.temp = self.read_temp()
            limit = self.cfg["thermal_limit"]
            hot = self.temp is not None and self.temp >= limit
            cool = self.temp is None or self.temp <= limit - 8
            for job in self.jobs:
                st = job["state"]
                if st in ("running", "paused"):
                    u = self.unit_state(job)
                    active = u.get("ActiveState", "inactive")
                    if active in ("inactive", "failed") and st == "running":
                        if boot and job["restart"] != "never":
                            self.launch(job, resume=True)  # power cut / reboot: resume from checkpoint
                            job["restarts"] += 1
                        else:
                            job["state"] = "finished" if u.get("Result") == "success" else "failed"
                            if job["state"] == "finished":
                                job["progress"] = 100
                    else:
                        job["restarts"] = int(u.get("NRestarts") or 0) or job["restarts"]
                        if st == "running" and hot:
                            run(["systemctl", "freeze", self.unit(job)])
                            job["state"], job["message"] = "paused", f"Cooling down ({round(self.temp)}°C)"
                        elif st == "paused" and cool and not job.get("user_paused"):
                            run(["systemctl", "thaw", self.unit(job)])
                            job["state"], job["message"] = "running", ""
                        if job["schedule"] == "night" and not self.night() and job["state"] == "running":
                            run(["systemctl", "freeze", self.unit(job)])
                            job["state"], job["message"] = "paused", "Waiting for night"
                        elif job["schedule"] == "night" and self.night() and job["state"] == "paused" and job["message"] == "Waiting for night":
                            run(["systemctl", "thaw", self.unit(job)])
                            job["state"], job["message"] = "running", ""
                if job["state"] in ("queued", "waiting"):
                    if job["schedule"] == "night" and not self.night():
                        job["state"] = "waiting"
                    elif not hot:
                        self.launch(job, resume=boot)
                if job["state"] == "running" and job.get("started"):
                    job["runtime"] = job.get("runtime_base", 0) + (time.time() - job["started"])
                prog = read_json(os.path.join(job["dir"], "progress.json"))
                if isinstance(prog.get("progress"), (int, float)):
                    job["progress"] = max(0, min(100, prog["progress"]))
                    if prog.get("message") and job["state"] == "running":
                        job["message"] = str(prog["message"])[:80]
            self.save()
            self.publish()

    def summary(self):
        mem = {}
        for line in open("/proc/meminfo"):
            k, _, v = line.partition(":")
            mem[k] = int(v.split()[0]) * 1024
        return {"jobs": [{k: j.get(k) for k in ("id", "name", "kind", "state", "progress", "runtime", "restarts", "schedule", "message")} for j in self.jobs],
                "temp": self.temp, "thermal_limit": self.cfg["thermal_limit"], "cpu": self.read_cpu(),
                "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)}

    def publish(self):
        data = self.summary()
        key = json.dumps({k: data[k] for k in ("jobs", "thermal_limit")}, sort_keys=True) + str(round(data["temp"] or 0))
        if key != self.last_pub:  # only write when something changed (no needless wakeups)
            self.last_pub = key
            data["time"] = time.time()
            write_json(os.path.join(RUN, "ai.json"), data)


# ---------------------------------------------------------------- socket API
class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        if not allowed(self.request):
            self.wfile.write(b'{"ok": false, "error": "not allowed"}\n')
            return
        try:
            req = json.loads(self.rfile.readline(1 << 20) or b"{}")
            op, args = req.get("op"), req.get("args") or {}
            J = self.server.jobs
            if op == "status":
                res = J.summary()
            elif op == "templates":
                res = TEMPLATES
            elif op == "create":
                res = J.create(args.get("job") or {})
            elif op == "action":
                res = J.action(args.get("id"), args.get("action"), args.get("value"))
            elif op == "log":
                res = J.log(args.get("id"), args.get("lines", 200))
            else:
                raise ValueError("unknown operation")
            self.wfile.write((json.dumps({"ok": True, "result": res}) + "\n").encode())
        except Exception as e:
            self.wfile.write((json.dumps({"ok": False, "error": str(e)}) + "\n").encode())


def allowed(sock):
    """Only root and members of the 'jstarx' group may talk to the AI service."""
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, gid = struct.unpack("3i", creds)
    except OSError:
        return False
    if uid == 0:
        return True
    try:
        g = grp.getgrnam("jstarx")
        import pwd
        name = pwd.getpwuid(uid).pw_name
        return gid == g.gr_gid or name in g.gr_mem
    except KeyError:
        return False


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    os.makedirs(ROOT, exist_ok=True)
    jobs = Jobs()
    try:
        os.unlink(SOCKET)
    except OSError:
        pass
    srv = Server(SOCKET, Handler)
    srv.jobs = jobs
    try:
        os.chown(SOCKET, 0, grp.getgrnam("jstarx").gr_gid)
    except (KeyError, PermissionError):
        pass
    os.chmod(SOCKET, 0o660)
    jobs.tick(boot=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log("StarAI ready with", len(jobs.jobs), "job(s)")
    while True:
        busy = any(j["state"] in ("running", "paused", "queued", "waiting") for j in jobs.jobs)
        time.sleep(10 if busy else 60)  # sleep longer when there is nothing to watch
        try:
            jobs.tick()
        except Exception as e:
            log("tick error:", e)


if __name__ == "__main__":
    main()
