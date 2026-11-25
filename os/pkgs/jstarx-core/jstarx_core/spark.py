"""Spark 1: the built-in assistant's model files and engine.

The model lives in /var/lib/spark/models. It comes from a GitHub release (every model and
tokenizer file in the release is fetched), or from a file. Storm's PyTorch checkpoint (.pt) is
converted to GGUF on the Jetson (spark_convert.py); Hugging Face safetensors use llama.cpp's
converter. The engine is llama.cpp's llama-server on 127.0.0.1:8090.
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .common import log, merge_status, read_json, run, status, write_json

ROOT = os.environ.get("SPARK_ROOT", "/var/lib/spark")
MODELS = os.path.join(ROOT, "models")
CONFIG = os.path.join(ROOT, "config.json")
RUN_STATUS = os.path.join(os.environ.get("JSTARX_RUN", "/run/jstarx"), "spark.json")
DEFAULT_RELEASE = "https://github.com/Stormblazerplayz/JStarx/releases/tag/Spark1"
TAG_ALIASES = ("Spark1", "spark-1", "spark1", "Spark-1")
CHECKPOINT_EXT = (".pt", ".pth", ".ckpt")
MODEL_EXT = (".gguf", ".safetensors", ".bin") + CHECKPOINT_EXT
EXTRA_EXT = (".json", ".model", ".txt", ".tiktoken", ".jinja")
UA = {"User-Agent": "JStarx-Spark/1.0", "Accept": "application/vnd.github+json"}
BUSY_STATES = ("downloading", "converting")


def cfg():
    c = read_json(CONFIG)
    c.setdefault("threads", 4)
    c.setdefault("ctx", 2048)
    c.setdefault("port", 8090)
    c.setdefault("auto_download", True)
    c.setdefault("release", DEFAULT_RELEASE)
    c.setdefault("fast", False)
    return c


def set_cfg(threads=None, ctx=None, fast=None):
    c = cfg()
    if threads:
        c["threads"] = max(1, min(16, int(threads)))
    if ctx:
        c["ctx"] = max(256, min(32768, int(ctx)))
    if fast is not None:
        c["fast"] = bool(fast)
    write_json(CONFIG, c)
    return c


def find_model(fast=None):
    """The model to run: the smaller 4-bit copy for "Faster answers", else the best quality one."""
    ggufs = sorted(glob.glob(os.path.join(MODELS, "**", "*.gguf"), recursive=True), key=os.path.getsize, reverse=True)
    ggufs = [g for g in ggufs if not g.endswith(".part")]
    if not ggufs:
        return None
    fast = cfg().get("fast") if fast is None else fast
    if fast:
        small = [g for g in ggufs if "q4" in os.path.basename(g).lower()]
        if small:
            return small[0]
    preferred = [g for g in ggufs if "q8_0" in os.path.basename(g).lower()]
    return preferred[0] if preferred else ggufs[0]


def find_checkpoint():
    cks = [p for ext in CHECKPOINT_EXT for p in glob.glob(os.path.join(MODELS, "**", "*" + ext), recursive=True)]
    return max(cks, key=os.path.getsize) if cks else None


def current_status():
    return read_json(RUN_STATUS)


def info():
    m = find_model()
    st = current_status()
    if m:
        st.update({"model": os.path.basename(m), "size": os.path.getsize(m)})
    elif find_checkpoint() and st.get("state") not in BUSY_STATES:
        st.setdefault("state", "needs-conversion")
    return st


# ---------------------------------------------------------------- one download/convert at a time (across processes)
class _Busy:
    def __init__(self):
        self.fd = None

    def acquire(self):
        os.makedirs(MODELS, exist_ok=True)
        fd = os.open(os.path.join(MODELS, ".busy.lock"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


# ---------------------------------------------------------------- download
def _release_json(owner, repo, tag):
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    with urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=20) as r:
        return json.load(r)


def resolve_assets(url):
    """Turn a release link into a list of (name, download_url, size, sha256 or None)."""
    url = (url or "").strip() or DEFAULT_RELEASE
    if url.lower().split("?")[0].endswith(MODEL_EXT + EXTRA_EXT):
        return [(url.split("?")[0].rsplit("/", 1)[-1], url, 0, None)]
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/(?:download|tag)/([^/?#]+)", url)
    if not m:
        raise ValueError("Use a GitHub release link (…/releases/tag/Spark1) or a direct link to a model file")
    owner, repo, tag = m.groups()
    rel, tried = None, []
    for t in [tag] + [a for a in TAG_ALIASES if a.lower() != tag.lower()]:
        tried.append(t)
        try:
            rel = _release_json(owner, repo, t)
            break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    if rel is None:
        raise ValueError(f"No release called {tried[0]} in {owner}/{repo} yet. Make one and upload the Spark 1 files to it.")
    assets = []
    for a in rel.get("assets", []):
        digest = a.get("digest") or ""
        sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
        assets.append((a["name"], a["browser_download_url"], int(a.get("size") or 0), sha))
    ggufs = [a for a in assets if a[0].lower().endswith(".gguf")]
    if ggufs:
        return ggufs
    files = [a for a in assets if a[0].lower().endswith(MODEL_EXT + EXTRA_EXT)]
    if not any(a[0].lower().endswith(MODEL_EXT) for a in files):
        raise ValueError(f"No model files in the release '{rel.get('tag_name', tag)}' yet. Upload the Spark 1 file to it.")
    return files


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_all(assets):
    os.makedirs(MODELS, exist_ok=True)
    need = sum(a[2] for a in assets)
    free = shutil.disk_usage(MODELS).free
    if need and free < need * 2.2:  # the model, plus room for converting it
        raise RuntimeError(f"Not enough free space: Spark 1 needs about {need * 2.2 / 1e9:.1f} GB, there is {free / 1e9:.1f} GB")
    total = need or 0
    done = 0
    for name, url, size, sha in assets:
        safe = os.path.basename(name)
        dest = os.path.join(MODELS, safe)
        if size and os.path.exists(dest) and os.path.getsize(dest) == size and (not sha or _sha256(dest) == sha):
            done += size  # already here from an earlier download
            continue
        part = dest + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
            size = size or int(r.headers.get("Content-Length") or 0)
            got, last = 0, 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if time.time() - last > 1:
                    last = time.time()
                    pct = round(100 * (done + got) / total) if total else None
                    merge_status("spark", state="downloading", progress=pct, file=safe, message=f"Downloading {safe}")
        if size and os.path.getsize(part) != size:
            os.remove(part)
            raise RuntimeError(f"{safe} did not download completely, try again")
        if sha and _sha256(part) != sha:
            os.remove(part)
            raise RuntimeError(f"{safe} was damaged while downloading (checksum), try again")
        os.replace(part, dest)
        done += size or got


def download(url=None):
    busy = _Busy()
    if not busy.acquire():
        raise RuntimeError("Spark 1 is already downloading or converting")
    try:
        assets = resolve_assets(url)  # fail fast (inside the request) if the link is wrong
    except Exception:
        busy.release()
        raise

    def work():
        try:
            status("spark", state="downloading", progress=0, message="Starting download")
            _download_all(assets)
            after_install()
        except Exception as e:
            status("spark", state="error", message=str(e)[:300])
            log("spark download failed:", e)
        finally:
            busy.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "files": [a[0] for a in assets]}


def import_file(path):
    if not path or not os.path.isfile(path):
        raise ValueError("That file does not exist")
    if not path.lower().endswith(MODEL_EXT + EXTRA_EXT):
        raise ValueError("Spark needs a model file (.gguf, .pt or .safetensors) or its tokenizer file")
    os.makedirs(MODELS, exist_ok=True)
    shutil.copy2(path, os.path.join(MODELS, os.path.basename(path)))
    if not path.lower().endswith(MODEL_EXT) and not (find_model() or find_checkpoint()):
        return status("spark", state="none", message="Tokenizer saved. Now add the Spark 1 model file.")
    return after_install()


def after_install():
    if find_model():
        m = find_model()
        status("spark", state="installed", progress=100, message="Model installed, starting Spark…", model=os.path.basename(m))
        run(["systemctl", "restart", "spark.service"], timeout=30)
        return info()
    if find_checkpoint():
        return convert_checkpoint()
    if glob.glob(os.path.join(MODELS, "*.safetensors")):
        return convert_hf()
    raise RuntimeError("No model file was installed")


def convert_checkpoint():
    """Storm's PyTorch checkpoint -> GGUF (Q8_0), using the tokenizer files next to it."""
    from . import spark_convert
    ck = find_checkpoint()
    free = shutil.disk_usage(MODELS).free
    if free < os.path.getsize(ck) * 0.9:
        return status("spark", state="error", message=f"Not enough free space to convert Spark 1 ({free / 1e9:.1f} GB free)")
    status("spark", state="converting", progress=None, message="Getting Spark 1 ready…")

    def say(msg):
        merge_status("spark", state="converting", message=str(msg)[:200])
        log("spark convert:", msg)

    try:
        res = spark_convert.convert(ck, MODELS, log=say)
    except Exception as e:
        log("spark convert failed:", e)
        return status("spark", state="error", message=f"Could not convert the model: {str(e)[:250]}")
    if res["state"] == "needs-tokenizer":
        return status("spark", state="needs-tokenizer", message=res["message"])
    note = "" if res.get("tokenizer_matches", True) else " (warning: the tokenizer is not the one Spark 1 was trained with)"
    status("spark", state="installed", progress=100, model=os.path.basename(res["gguf"]),
           message="Spark 1 is converted, starting it…" + note, rope=res.get("rope"))
    run(["systemctl", "restart", "spark.service"], timeout=30)
    return info()


def convert_hf():
    """safetensors (Hugging Face format) -> GGUF with llama.cpp's converter, then Q8_0."""
    conv = shutil.which("convert_hf_to_gguf.py")
    if not conv:
        return status("spark", state="needs-conversion", message="The model is in safetensors format. Install 'Python AI Kit' from Star Store to convert it.")
    status("spark", state="converting", message="Converting the model to GGUF (this takes a while)…")
    f16 = os.path.join(MODELS, "spark-1-f16.gguf")
    r = subprocess.run(["python3", conv, MODELS, "--outfile", f16, "--outtype", "f16"], capture_output=True, text=True)
    if r.returncode != 0:
        return status("spark", state="needs-conversion", message="Conversion failed: " + (r.stderr or r.stdout).strip()[-250:])
    q = shutil.which("llama-quantize")
    if q:
        out = os.path.join(MODELS, "spark-1-q8_0.gguf")
        if subprocess.run([q, f16, out, "Q8_0"], capture_output=True).returncode == 0:
            os.remove(f16)
    return after_install()


# ---------------------------------------------------------------- engine
def _online():
    try:
        urllib.request.urlopen(urllib.request.Request("https://api.github.com", headers=UA, method="HEAD"), timeout=8)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _auto_setup(last_try):
    """No model yet: fetch Spark 1 from its GitHub release by itself (once an hour, when online)."""
    c = cfg()
    st = current_status()
    if not c.get("auto_download") or st.get("state") in BUSY_STATES or time.time() - last_try < 3600:
        return last_try
    if find_checkpoint():  # files are here (maybe the tokenizer arrived later): try converting again
        busy = _Busy()
        if busy.acquire():
            try:
                after_install()
            except Exception as e:
                status("spark", state="error", message=str(e)[:300])
            finally:
                busy.release()
        return time.time()
    if not _online():
        return last_try
    try:
        download(c.get("release") or DEFAULT_RELEASE)
    except Exception as e:
        status("spark", state="none", message=f"Spark 1 is not downloaded yet ({str(e)[:160]})")
    return time.time()


def serve():
    """spark.service entry point: get a model (downloading it if needed), then run llama-server."""
    last_try = 0.0
    while True:
        model = find_model()
        if model and current_status().get("state") not in BUSY_STATES:
            break
        st = current_status().get("state")
        if not model and st not in BUSY_STATES + ("needs-tokenizer", "error"):
            status("spark", state="none", message="Waiting for the Spark 1 model")
        last_try = _auto_setup(last_try)
        time.sleep(30)
    c = cfg()
    status("spark", state="starting", model=os.path.basename(model), size=os.path.getsize(model), message="Loading the model…")
    server = shutil.which("llama-server") or "llama-server"
    args = [server, "--model", model, "--host", "127.0.0.1", "--port", str(c["port"]), "--ctx-size", str(c["ctx"]),
            "--threads", str(c["threads"]), "--parallel", "1", "--alias", "spark-1", "--no-ui"]
    proc = subprocess.Popen(args)
    # report "ready" once the health endpoint answers
    for _ in range(600):
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{c['port']}/health", timeout=2) as r:
                if json.load(r).get("status") == "ok":
                    status("spark", state="ready", model=os.path.basename(model), size=os.path.getsize(model), message="Spark 1 is ready")
                    break
        except Exception:
            time.sleep(2)
    code = proc.wait()
    status("spark", state="error", message=f"The engine stopped (code {code})")
    raise SystemExit(code or 1)


def service(action):
    if action not in ("start", "stop", "restart"):
        raise ValueError("unknown action")
    r = run(["systemctl", action, "spark.service"], timeout=60)
    return {"ok": bool(r and r.returncode == 0)}
