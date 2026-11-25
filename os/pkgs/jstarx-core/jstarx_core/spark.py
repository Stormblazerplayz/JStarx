"""Spark 1: the built-in assistant's model files and engine.

The model lives in /var/lib/spark/models. It can be downloaded from a GitHub release
(every model file in the release is fetched), imported from a file, or converted from
safetensors to GGUF. The engine is llama.cpp's llama-server on 127.0.0.1:8090.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request

from .common import log, merge_status, read_json, run, status, write_json

ROOT = os.environ.get("SPARK_ROOT", "/var/lib/spark")
MODELS = os.path.join(ROOT, "models")
CONFIG = os.path.join(ROOT, "config.json")
MODEL_EXT = (".gguf", ".safetensors", ".bin")
EXTRA_EXT = (".json", ".model", ".txt", ".tiktoken", ".jinja")
UA = {"User-Agent": "JStarx-Spark/1.0", "Accept": "application/vnd.github+json"}
_lock = threading.Lock()


def cfg():
    c = read_json(CONFIG)
    c.setdefault("threads", 4)
    c.setdefault("ctx", 2048)
    c.setdefault("port", 8090)
    return c


def set_cfg(threads=None, ctx=None):
    c = cfg()
    if threads:
        c["threads"] = max(1, min(16, int(threads)))
    if ctx:
        c["ctx"] = max(256, min(32768, int(ctx)))
    write_json(CONFIG, c)
    return c


def find_model():
    ggufs = sorted(glob.glob(os.path.join(MODELS, "**", "*.gguf"), recursive=True), key=os.path.getsize, reverse=True)
    return ggufs[0] if ggufs else None


def info():
    m = find_model()
    st = read_json("/run/jstarx/spark.json")
    if m:
        st.update({"model": os.path.basename(m), "size": os.path.getsize(m)})
    elif glob.glob(os.path.join(MODELS, "**", "*.safetensors"), recursive=True):
        st.setdefault("state", "needs-conversion")
    return st


# ---------------------------------------------------------------- download
def resolve_assets(url):
    """Turn a release URL into a list of (name, download_url, size)."""
    url = url.strip()
    if url.lower().endswith(MODEL_EXT):
        return [(url.rsplit("/", 1)[-1], url, 0)]
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/(?:download|tag)/([^/?#]+)", url)
    if not m:
        raise ValueError("Use a GitHub release link (…/releases/tag/spark-1) or a direct link to a .gguf file")
    owner, repo, tag = m.groups()
    api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    with urllib.request.urlopen(urllib.request.Request(api, headers=UA), timeout=20) as r:
        rel = json.load(r)
    assets = [(a["name"], a["browser_download_url"], a.get("size", 0)) for a in rel.get("assets", [])]
    ggufs = [a for a in assets if a[0].lower().endswith(".gguf")]
    if ggufs:
        return ggufs
    models = [a for a in assets if a[0].lower().endswith(MODEL_EXT + EXTRA_EXT)]
    if not any(a[0].lower().endswith(MODEL_EXT) for a in models):
        raise ValueError(f"No model files found in release '{tag}' yet. Upload the Spark 1 file to that release.")
    return models


def _download_all(assets):
    os.makedirs(MODELS, exist_ok=True)
    total = sum(a[2] for a in assets) or 0
    done = 0
    for name, url, size in assets:
        safe = os.path.basename(name)
        dest = os.path.join(MODELS, safe)
        part = dest + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
            size = size or int(r.headers.get("Content-Length") or 0)
            got = 0
            last = 0
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
            raise RuntimeError(f"{safe} did not download completely")
        os.replace(part, dest)
        done += size or got


def download(url):
    if not _lock.acquire(blocking=False):
        raise RuntimeError("Spark 1 is already downloading")
    assets = resolve_assets(url)  # fail fast (inside the request) if the link is wrong

    def work():
        try:
            status("spark", state="downloading", progress=0, message="Starting download")
            _download_all(assets)
            after_install()
        except Exception as e:
            status("spark", state="error", message=str(e)[:300])
            log("spark download failed:", e)
        finally:
            _lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "files": [a[0] for a in assets]}


def import_file(path):
    if not path or not os.path.isfile(path):
        raise ValueError("That file does not exist")
    if not path.lower().endswith(MODEL_EXT):
        raise ValueError("Spark needs a .gguf (or .safetensors) model file")
    os.makedirs(MODELS, exist_ok=True)
    shutil.copy2(path, os.path.join(MODELS, os.path.basename(path)))
    return after_install()


def after_install():
    if find_model():
        status("spark", state="installed", progress=100, message="Model installed, starting Spark…", model=os.path.basename(find_model()))
        run(["systemctl", "restart", "spark.service"], timeout=30)
        return info()
    if glob.glob(os.path.join(MODELS, "*.safetensors")):
        return convert()
    raise RuntimeError("No model file was installed")


def convert():
    """safetensors (Hugging Face format) -> GGUF, then quantize to Q4_K_M for the Jetson."""
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
        out = os.path.join(MODELS, "spark-1-q4_k_m.gguf")
        if subprocess.run([q, f16, out, "Q4_K_M"], capture_output=True).returncode == 0:
            os.remove(f16)
    return after_install()


# ---------------------------------------------------------------- engine
def serve():
    """spark.service entry point: wait for a model, then run llama-server."""
    while True:
        model = find_model()
        if model:
            break
        if not read_json("/run/jstarx/spark.json").get("state") == "downloading":
            status("spark", state="none", message="Waiting for the Spark 1 model")
        time.sleep(30)
    c = cfg()
    status("spark", state="starting", model=os.path.basename(model), size=os.path.getsize(model), message="Loading the model…")
    server = shutil.which("llama-server") or "llama-server"
    args = [server, "--model", model, "--host", "127.0.0.1", "--port", str(c["port"]), "--ctx-size", str(c["ctx"]),
            "--threads", str(c["threads"]), "--alias", "spark-1", "--no-webui"]
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
