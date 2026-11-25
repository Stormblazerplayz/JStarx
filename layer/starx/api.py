"""Methods the web UI can call (StarX.call('group.name', {...}) -> Api.m_group_name)."""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import apps, daemon, paths, system, wm
from .bridge import open_external, threaded
from .settings import Settings, load_home, save_home

REPO = os.environ.get("JSTARX_REPO", "Stormblazerplayz/JStarx")


class Api:
    def __init__(self, role="app", app_id=None):
        paths.ensure_user_dirs()
        self.role = role
        self.app_id = app_id
        self.settings = Settings()
        self.bridge = None
        self._spark_streams = {}

    # ------------------------------------------------------------------ settings
    def m_settings_get(self, view=None):
        return self.settings.get()

    def m_settings_set(self, path, value, view=None):
        return self.settings.set(path, value)

    def m_settings_reset(self, view=None):
        return self.settings.reset()

    def m_settings_fixes(self, view=None):
        return self.settings.fixes

    # ------------------------------------------------------------------ apps
    def m_apps_list(self, view=None):
        return apps.all_apps()

    def m_apps_launch(self, id, view=None):
        rec = apps.find(id)
        if not rec:
            raise ValueError(f"no app called {id}")
        open_ids = {w["app_id"] for w in wm.windows()}
        if rec["app_id"] in open_ids and wm.focus(rec["app_id"]):
            return {"focused": True}
        res = apps.launch(rec)
        if res is not True:
            raise RuntimeError(f"could not start {rec['name']}: {res}")
        return {"started": True}

    def m_home_get(self, view=None):
        return load_home()

    def m_home_set(self, layout, view=None):
        save_home(layout)
        return True

    def m_home_reset(self, view=None):
        from .settings import DEFAULT_HOME
        save_home(DEFAULT_HOME)
        _notify_shell("reload")
        return True

    def m_open_url(self, url, view=None):
        if not str(url).startswith(("http://", "https://")):
            raise ValueError("only web links can be opened")
        return open_external(url)

    # ------------------------------------------------------------------ system
    def m_system_info(self, view=None):
        info = system.static_info()
        info["update"] = daemon.status("update")
        return info

    def m_system_stats(self, view=None):
        return system.stats()

    @threaded
    def m_net_status(self, view=None):
        return system.net_status()

    @threaded
    def m_net_wifi_list(self, rescan=False, view=None):
        return system.wifi_list(rescan)

    @threaded
    def m_net_wifi_connect(self, ssid, password=None, view=None):
        return system.wifi_connect(ssid, password)

    @threaded
    def m_net_wifi_radio(self, on, view=None):
        return system.wifi_radio(bool(on))

    @threaded
    def m_audio_get(self, view=None):
        return system.audio_get()

    @threaded
    def m_audio_set(self, volume=None, muted=None, view=None):
        return system.audio_set(volume, muted)

    @threaded
    def m_display_get(self, view=None):
        return {"outputs": system.outputs(), "backlight": system.backlight_get(), "casting": system.casting_available(),
                "cast_status": daemon.status("cast")}

    @threaded
    def m_display_set(self, name, mode=None, scale=None, view=None):
        return system.set_output(name, mode, scale)

    def m_display_cast(self, view=None):
        """Open the wireless display picker (Miracast and Chromecast)."""
        if not system.casting_available():
            raise RuntimeError("Screen casting is not installed")
        subprocess.Popen(["gnome-network-displays"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # ------------------------------------------------------------------ power + session
    @threaded
    def m_power_get(self, view=None):
        try:
            return daemon.starxd("power_get")
        except daemon.DaemonError:
            gov = system._read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
            return {"profile": "balanced", "governor": gov or "unknown", "ai_247": False, "service": False}

    @threaded
    def m_power_set(self, profile, view=None):
        return daemon.starxd("power_set", profile=profile)

    @threaded
    def m_power_ai247(self, on, view=None):
        return daemon.starxd("ai247_set", on=bool(on))

    def m_session_action(self, action, view=None):
        cmds = {
            "reboot": ["systemctl", "reboot"],
            "poweroff": ["systemctl", "poweroff"],
            "logout": ["labwc", "--exit"],
        }
        if action not in cmds:
            raise ValueError("unknown action")
        subprocess.Popen(cmds[action], start_new_session=True)
        return True

    # ------------------------------------------------------------------ updates + repair (root services)
    def m_update_status(self, view=None):
        st = daemon.status("update")
        st.setdefault("current", {"layer": self._layer_version()})
        return st

    @staticmethod
    def _layer_version():
        try:
            with open(os.path.join(paths.LAYER, "layer.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    @threaded
    def m_update_check(self, view=None):
        return daemon.starxd("update_check", timeout=90)

    @threaded
    def m_update_apply(self, view=None):
        return daemon.starxd("update_apply", timeout=600)

    @threaded
    def m_update_rollback(self, view=None):
        return daemon.starxd("update_rollback", timeout=120)

    @threaded
    def m_update_config(self, auto=None, branch=None, view=None):
        if auto is not None:
            self.settings.set("updates.auto", bool(auto))
        if branch:
            self.settings.set("updates.branch", str(branch))
        return daemon.starxd("update_config", auto=self.settings.get("updates.auto"), branch=self.settings.get("updates.branch"))

    def m_repair_status(self, view=None):
        st = daemon.status("repair")
        st["settings_fixes"] = self.settings.fixes
        return st

    @threaded
    def m_repair_run(self, mode="quick", view=None):
        self.settings.data = self.settings.load()  # re-check (and fix) the user's settings too
        res = daemon.starxd("repair_run", mode=mode, timeout=1800)
        if isinstance(res, dict):
            res["settings_fixes"] = self.settings.fixes
        return res

    @threaded
    @threaded
    def m_update_system_check(self, view=None):
        return daemon.starxd("system_update_check", timeout=60)

    def m_update_system_apply(self, view=None):
        return daemon.starxd("system_update_apply", timeout=30)

    def m_update_system_status(self, view=None):
        return daemon.status("sysupdate")

    def m_memory_info(self, view=None):
        return system.memory_details()

    @threaded
    def m_memory_free(self, view=None):
        return daemon.starxd("memory_free", timeout=120)

    @threaded
    def m_memory_saver(self, on=None, view=None):
        return daemon.starxd("memory_saver", on=on, timeout=20)

    def m_storage_clean(self, view=None):
        return daemon.starxd("storage_clean", timeout=1800)

    @threaded
    def m_system_set(self, key, value, view=None):
        if key not in ("timezone", "hostname", "autologin", "ssh"):
            raise ValueError("unknown system setting")
        return daemon.starxd("system_set", key=key, value=value)

    def m_system_password(self, old, new, view=None):
        return daemon.starxd("password_set", timeout=60, old=old, new=new)

    # ------------------------------------------------------------------ per-app storage (notes, high scores...)
    def _appdata_path(self):
        safe = "".join(c for c in (self.app_id or "shell") if c.isalnum() or c in "-_")
        return os.path.join(paths.DATA, "appdata", f"{safe}.json")

    def m_appdata_get(self, key=None, view=None):
        try:
            with open(self._appdata_path()) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        return data.get(key) if key else data

    def m_appdata_set(self, key, value, view=None):
        from .settings import atomic_write_json
        data = self.m_appdata_get()
        data[str(key)] = value
        blob = json.dumps(data)
        if len(blob) > 5_000_000:
            raise ValueError("this app's saved data is too big (5 MB limit)")
        atomic_write_json(self._appdata_path(), data)
        return True

    def m_files_save_image(self, name, data_url, view=None):
        import base64
        import re
        m = re.match(r"^data:image/png;base64,(.+)$", data_url or "")
        if not m:
            raise ValueError("not a PNG image")
        folder = os.path.join(paths.HOME, "Pictures")
        os.makedirs(folder, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in " -_")[:60].strip() or "drawing"
        path = os.path.join(folder, f"{safe}.png")
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, f"{safe} {n}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(m.group(1)))
        return path

    # ------------------------------------------------------------------ Star Store
    def _catalog_local(self):
        for base in (os.path.join(paths.LAYER, "store"), os.path.join(paths.LAYER, "..", "store")):
            p = os.path.join(base, "catalog.json")
            if os.path.exists(p):
                with open(p) as f:
                    return json.load(f), base
        return {"apps": []}, None

    @threaded
    def m_store_catalog(self, refresh=False, view=None):
        catalog, _ = self._catalog_local()
        if refresh:
            url = f"https://raw.githubusercontent.com/{REPO}/{self.settings.get('updates.branch')}/layer/store/catalog.json"
            try:
                with urllib.request.urlopen(url, timeout=12) as r:
                    catalog = json.load(r)
            except (OSError, ValueError, urllib.error.URLError):
                pass  # offline: keep the bundled catalog
        installed = {a["id"]: a for a in apps.all_apps() if not a.get("builtin")}
        for a in catalog.get("apps", []):
            a["installed"] = a["id"] in installed
            a["icon_url"] = "file://" + os.path.join(paths.WEB, "icons", a.get("icon", "box") + ".svg")
        return catalog

    @threaded
    def m_store_install(self, id, view=None):
        from . import store
        catalog, base = self._catalog_local()
        entry = next((a for a in catalog.get("apps", []) if a["id"] == id), None)
        if not entry:
            raise ValueError("app not in the catalog")
        progress = lambda text, pct=None: self.bridge.emit_threadsafe("store-progress", {"id": id, "text": text, "pct": pct})
        result = store.install(entry, base, self.settings.get("updates.branch"), REPO, progress)
        self.bridge.emit_threadsafe("apps-changed", None)
        _notify_shell("apps-changed")
        return result

    @threaded
    def m_store_uninstall(self, id, view=None):
        from . import store
        result = store.uninstall(id)
        _notify_shell("apps-changed")
        return result

    # ------------------------------------------------------------------ AI (StarAI daemon)
    @threaded
    def m_ai_status(self, view=None):
        try:
            return daemon.starai("status")
        except daemon.DaemonError as e:
            st = daemon.status("ai")
            st.setdefault("jobs", [])
            st["offline"] = str(e)
            return st

    @threaded
    def m_ai_templates(self, view=None):
        return daemon.starai("templates")

    @threaded
    def m_ai_create(self, job, view=None):
        return daemon.starai("create", job=job)

    @threaded
    def m_ai_action(self, id, action, view=None):
        return daemon.starai("action", id=id, action=action)

    @threaded
    def m_ai_log(self, id, lines=200, view=None):
        return daemon.starai("log", id=id, lines=lines)

    # ------------------------------------------------------------------ Spark 1
    @threaded
    def m_spark_status(self, view=None):
        st = daemon.status("spark")
        try:
            with _LOCAL.open(paths.SPARK_URL + "/health", timeout=2) as r:
                st["engine"] = json.load(r).get("status", "ok")
        except Exception:
            st["engine"] = "offline"
        return st

    @threaded
    def m_spark_download(self, url=None, view=None):
        return daemon.starxd("spark_download", url=url or self.settings.get("spark.model_url"), timeout=30)

    @threaded
    def m_spark_import(self, path, view=None):
        return daemon.starxd("spark_import", path=path, timeout=600)

    @threaded
    def m_spark_service(self, action, view=None):
        return daemon.starxd("spark_service", action=action, threads=self.settings.get("spark.threads"),
                             ctx=self.settings.get("spark.ctx"), fast=bool(self.settings.get("spark.fast")))

    def m_spark_chat(self, messages, view=None):
        """Stream an answer from Spark 1. Sends 'spark-token' events, then 'spark-done'."""
        req = f"r{int(time.time() * 1000)}"
        stop = threading.Event()
        self._spark_streams[req] = stop
        system_prompt = self.settings.get("spark.personality")
        body = {"messages": [{"role": "system", "content": system_prompt}] + list(messages)[-20:],
                "stream": True, "temperature": 0.7, "max_tokens": 512}

        def work():
            err = None
            got = False
            try:
                rq = urllib.request.Request(paths.SPARK_URL + "/v1/chat/completions", data=json.dumps(body).encode(),
                                            headers={"Content-Type": "application/json"})
                with _LOCAL.open(rq, timeout=300) as r:
                    for raw in r:
                        if stop.is_set():
                            break
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            continue
                        if isinstance(obj, dict) and obj.get("error"):
                            if not got:  # a problem before any words: say so; after some words, keep what we have
                                e = obj["error"]
                                err = "Spark 1 had a problem: " + str(e.get("message", e) if isinstance(e, dict) else e)[:200]
                            break
                        try:
                            delta = obj["choices"][0].get("delta", {}).get("content")
                        except (KeyError, IndexError, TypeError, AttributeError):
                            delta = None
                        if delta:
                            got = True
                            self.bridge.emit_threadsafe("spark-token", {"req": req, "text": delta}, [view])
            except urllib.error.HTTPError as e:
                err = f"Spark 1 had a problem (error {e.code}). Try again in a moment."
            except (urllib.error.URLError, ConnectionError, OSError):
                err = "Spark 1 isn't running yet. Install the Spark 1 model in Settings → AI & Spark."
            except Exception as e:
                err = str(e)
            self.bridge.emit_threadsafe("spark-done", {"req": req, "error": err}, [view])
            self._spark_streams.pop(req, None)

        threading.Thread(target=work, daemon=True).start()
        return {"req": req}

    def m_spark_stop(self, req, view=None):
        ev = self._spark_streams.get(req)
        if ev:
            ev.set()
        return True


# requests to services on this Jetson never go through a proxy
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _notify_shell(command):
    """Tell the running shell something changed (installed apps, settings...)."""
    import socket
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(paths.SHELL_SOCKET)
        s.sendall((command + "\n").encode())
        s.close()
    except OSError:
        pass


def which(cmd):
    return shutil.which(cmd) is not None
