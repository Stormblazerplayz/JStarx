"""Tests for JStarx: settings self-repair, A/B updates, rollback, auto-repair, power, StarCast, store.

Run: python3 -m pytest -q tests
"""
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = os.path.join(ROOT, "layer")
CORE = os.path.join(ROOT, "os", "pkgs", "jstarx-core")
sys.path.insert(0, CORE)
sys.path.insert(0, LAYER)


def fresh(modname):
    """(Re)import a module after the environment has been pointed at temp folders."""
    top = modname.split(".")[0]
    for name in list(sys.modules):
        if name == top or name.startswith(top + "."):
            del sys.modules[name]
    return importlib.import_module(modname)


@pytest.fixture
def sysroot(tmp_path, monkeypatch):
    """A fake system: state, run, boot folders and a factory layer copied from the repo."""
    factory = tmp_path / "factory-layer"
    shutil.copytree(LAYER, factory, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_manifest.py"), str(factory)], check=True, capture_output=True)
    for d in ("state", "run", "boot"):
        (tmp_path / d).mkdir()
    monkeypatch.setenv("JSTARX_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("JSTARX_RUN", str(tmp_path / "run"))
    monkeypatch.setenv("JSTARX_BOOT", str(tmp_path / "boot"))
    monkeypatch.setenv("JSTARX_FACTORY_LAYER", str(factory))
    return tmp_path


# ---------------------------------------------------------------- user settings
def test_settings_repairs_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings = fresh("starx.settings")
    s = settings.Settings()
    s.set("appearance.wallpaper", "aurora")
    path = tmp_path / "jstarx" / "settings.json"
    path.write_text("{ this is not json")  # damage the file
    s2 = settings.Settings()
    assert s2.get("appearance.wallpaper") == "aurora"  # restored from the backup
    assert any("backup" in f for f in s2.fixes)


def test_settings_fixes_bad_values(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings = fresh("starx.settings")
    (tmp_path / "jstarx").mkdir()
    (tmp_path / "jstarx" / "settings.json").write_text(json.dumps(
        {"appearance": {"wallpaper": "does-not-exist", "bounce": 7}, "dock": {"size": "huge", "pinned": "x"}, "junk": 1}))
    s = settings.Settings()
    assert s.get("appearance.wallpaper") == "nebula"
    assert s.get("appearance.bounce") == 1.0
    assert s.get("dock.size") == 54
    assert s.get("dock.pinned") == settings.DEFAULTS["dock"]["pinned"]
    assert "junk" not in s.get()
    with pytest.raises(ValueError):
        s.set("appearance.glass", "sparkly")


def test_home_layout_repair(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings = fresh("starx.settings")
    p = tmp_path / "home.json"
    p.write_text("[broken")
    home = settings.load_home(str(p))
    assert [i["name"] for i in home["items"]] == ["Internet", "AI", "Games", "System"]


# ---------------------------------------------------------------- updates (A/B) + rollback
def make_update(src_layer, dest, version):
    shutil.copytree(src_layer, dest, ignore=shutil.ignore_patterns("__pycache__", "MANIFEST.json"))
    info = json.load(open(os.path.join(dest, "layer.json")))
    info["version"] = version
    json.dump(info, open(os.path.join(dest, "layer.json"), "w"))
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_manifest.py"), str(dest)], check=True, capture_output=True)
    return dest


def test_update_installs_into_spare_slot_and_rolls_back(sysroot):
    updater = fresh("jstarx_core.updater")
    layers = sys.modules["jstarx_core.layers"]
    assert layers.ensure_initialized() == "factory"
    new = make_update(os.environ["JSTARX_FACTORY_LAYER"], sysroot / "new", "1.0.1")
    res = updater.apply(source_dir=str(new))
    assert res["state"] == "updated" and res["version"] == "1.0.1"
    assert layers.current_slot() == "a"
    assert layers.state()["pending"] is True
    new2 = make_update(os.environ["JSTARX_FACTORY_LAYER"], sysroot / "new2", "1.0.2")
    assert updater.apply(source_dir=str(new2))["state"] == "updated"
    assert layers.current_slot() == "b"
    res = updater.rollback()
    assert res["state"] == "rolled-back"
    assert layers.current_slot() == "a"
    assert updater.current_info()["version"] == "1.0.1"


def test_update_refuses_tampered_files(sysroot):
    updater = fresh("jstarx_core.updater")
    layers = sys.modules["jstarx_core.layers"]
    layers.ensure_initialized()
    bad = make_update(os.environ["JSTARX_FACTORY_LAYER"], sysroot / "bad", "9.9.9")
    with open(os.path.join(bad, "starx", "shell.py"), "a") as f:
        f.write("\n# tampered\n")
    res = updater.apply(source_dir=str(bad))
    assert res["state"] == "error" and "safety check" in res["message"]
    assert layers.current_slot() == "factory"


def test_tarball_extract_only_takes_layer_and_blocks_escapes(tmp_path):
    updater = fresh("jstarx_core.updater")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("JStarx-main/layer/layer.json", b'{"version": "2.0.0"}'),
                           ("JStarx-main/layer/../../evil.txt", b"x"),
                           ("JStarx-main/README.md", b"readme")):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    buf.seek(0)
    out = tmp_path / "out"
    out.mkdir()
    updater.extract_layer(buf, str(out))
    assert (out / "layer.json").exists()
    assert not (tmp_path / "evil.txt").exists()
    assert not (out / "README.md").exists()


# ---------------------------------------------------------------- auto-repair
def test_repair_restores_damaged_and_missing_files(sysroot):
    updater = fresh("jstarx_core.updater")
    layers = sys.modules["jstarx_core.layers"]
    repair = fresh("jstarx_core.repair")
    layers = sys.modules["jstarx_core.layers"]
    updater = sys.modules["jstarx_core.updater"]
    layers.ensure_initialized()
    # install the same version into slot A so the factory copy can donate good files
    same = make_update(os.environ["JSTARX_FACTORY_LAYER"], sysroot / "same", json.load(open(os.path.join(LAYER, "layer.json")))["version"])
    updater.apply(source_dir=str(same))
    slot = layers.slot_path("a")
    os.remove(os.path.join(slot, "web", "shell", "dock.js"))                      # missing
    with open(os.path.join(slot, "web", "common", "theme.css"), "w") as f:        # damaged
        f.write("broken")
    rep = repair.quick()
    assert rep["state"] == "healthy"
    assert any("dock.js" in x for x in rep["fixed"]) and any("theme.css" in x for x in rep["fixed"])
    assert layers.verify(slot)[0]
    assert json.load(open(sysroot / "run" / "repair.json"))["fixed"]


def test_desktop_crash_loop_undoes_update(sysroot):
    updater = fresh("jstarx_core.updater")
    repair = fresh("jstarx_core.repair")
    layers = sys.modules["jstarx_core.layers"]
    updater = sys.modules["jstarx_core.updater"]
    layers.ensure_initialized()
    new = make_update(os.environ["JSTARX_FACTORY_LAYER"], sysroot / "crashy", "1.0.5")
    updater.apply(source_dir=str(new))
    assert layers.current_slot() == "a"
    rep = repair.shell_failed()
    assert layers.current_slot() == "factory"
    assert "Undid" in rep["fixed"][0]


def test_broken_current_link_falls_back_to_factory(sysroot):
    layers = fresh("jstarx_core.layers")
    os.makedirs(os.path.dirname(layers.CURRENT), exist_ok=True)
    os.symlink("/nonexistent/place", layers.CURRENT)
    assert layers.ensure_initialized() == "factory"
    assert os.path.realpath(layers.CURRENT) == os.path.realpath(os.environ["JSTARX_FACTORY_LAYER"])


def test_boot_ok_marks_generation(sysroot, monkeypatch, tmp_path):
    boot = fresh("jstarx_core.boot")
    cmd = tmp_path / "cmdline"
    cmd.write_text("root=/dev/vda2 jstarx.gen=7 quiet")
    monkeypatch.setattr(boot, "booted_generation", lambda p=str(cmd): "7")
    boot.mark_ok("test")
    assert (sysroot / "boot" / "known-good").read_text().strip() == "7"
    assert (sysroot / "boot" / "tries").read_text().strip() == "0"


# ---------------------------------------------------------------- power profiles
def test_power_profiles_write_sysfs(tmp_path, monkeypatch, sysroot):
    sysfs = tmp_path / "sys"
    for n in range(4):
        d = sysfs / "devices" / "system" / "cpu" / f"cpu{n}"
        d.mkdir(parents=True)
        if n:
            (d / "online").write_text("1")
    pol = sysfs / "devices" / "system" / "cpu" / "cpufreq" / "policy0"
    pol.mkdir(parents=True)
    (pol / "scaling_available_governors").write_text("powersave schedutil performance")
    (pol / "scaling_governor").write_text("schedutil")
    (pol / "cpuinfo_min_freq").write_text("100000")
    (pol / "cpuinfo_max_freq").write_text("1500000")
    (pol / "scaling_max_freq").write_text("1500000")
    monkeypatch.setenv("JSTARX_SYSFS", str(sysfs))
    power = fresh("jstarx_core.power")
    power.apply("saver")
    cpu = sysfs / "devices" / "system" / "cpu"
    assert [(cpu / f"cpu{n}" / "online").read_text() for n in (1, 2, 3)] == ["1", "0", "0"]
    assert (pol / "scaling_governor").read_text() == "powersave"
    assert int((pol / "scaling_max_freq").read_text()) == 940000
    power.apply("performance")
    assert (pol / "scaling_governor").read_text() == "performance"
    assert (cpu / "cpu3" / "online").read_text() == "1"


# ---------------------------------------------------------------- StarCast (auto-cast)
def test_starcast_detects_screens(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    starcast = fresh("starx.starcast")
    drm = tmp_path / "drm"
    (drm / "card0-HDMI-A-1").mkdir(parents=True)
    (drm / "card0-HDMI-A-1" / "status").write_text("disconnected\n")
    assert starcast.physical_display_connected(str(drm)) is False
    (drm / "card0-HDMI-A-1" / "status").write_text("connected\n")
    assert starcast.physical_display_connected(str(drm)) is True
    devs = [{"name": "Kitchen", "uuid": "1"}, {"name": "Living Room TV", "uuid": "2"}]
    assert starcast.pick_device(devs, "Living Room TV")["uuid"] == "2"
    assert starcast.pick_device(devs, "")["name"] == "Kitchen"
    assert starcast.pick_device([], "") is None


# ---------------------------------------------------------------- Star Store
def test_store_installs_verified_web_app_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = fresh("starx.store")
    paths = sys.modules["starx.paths"]
    os.makedirs(paths.USER_APPS, exist_ok=True)
    catalog = json.load(open(os.path.join(LAYER, "store", "catalog.json")))
    entry = next(a for a in catalog["apps"] if a["id"] == "notes")
    monkeypatch.setattr(store, "_fetch", lambda url, timeout=30: (_ for _ in ()).throw(OSError("offline")))
    res = store.install(entry, os.path.join(LAYER, "store"), "main", "x/y", lambda *a, **k: None)
    assert res["ok"] and os.path.exists(os.path.join(paths.USER_APPS, "notes", "index.html"))
    bad = dict(entry, files=dict(entry["files"], **{"index.html": "0" * 64}))
    with pytest.raises(RuntimeError):
        store.install(bad, os.path.join(LAYER, "store"), "main", "x/y", lambda *a, **k: None)
    store.uninstall("notes")
    assert not os.path.exists(os.path.join(paths.USER_APPS, "notes"))


def test_spark_direct_link_and_bad_link():
    spark = fresh("jstarx_core.spark")
    assert spark.resolve_assets("https://example.com/models/spark-1.Q4_K_M.gguf")[0][0] == "spark-1.Q4_K_M.gguf"
    with pytest.raises(ValueError):
        spark.resolve_assets("https://example.com/not-a-model")


def test_layer_manifest_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_manifest.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
