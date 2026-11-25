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


# ---------------------------------------------------------------- Settings -> change password
def test_password_change_needs_the_current_password(sysroot, monkeypatch, tmp_path):
    import pwd
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    chk = bin_dir / "unix_chkpwd"
    chk.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0 if sys.stdin.buffer.read() == b'jstarx\\0' else 1)\n")
    chp = bin_dir / "chpasswd"
    chp.write_text(f"#!{sys.executable}\nimport sys\nopen({str(tmp_path / 'chpasswd.out')!r}, 'wb').write(sys.stdin.buffer.read())\n")
    for f in (chk, chp):
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("JSTARX_UNIX_CHKPWD", str(chk))
    starxd = fresh("jstarx_core.starxd")
    nobody = pwd.getpwnam("nobody").pw_uid
    with pytest.raises(ValueError):
        starxd.op_password_set("wrong", "newpass1", _uid=nobody)
    assert not (tmp_path / "chpasswd.out").exists()
    with pytest.raises(ValueError):
        starxd.op_password_set("jstarx", "a:b\nroot:x", _uid=nobody)  # can't sneak in another user
    with pytest.raises(PermissionError):
        starxd.op_password_set("jstarx", "newpass1", _uid=0)
    assert starxd.op_password_set("jstarx", "newpass1", _uid=nobody)["changed"]
    assert (tmp_path / "chpasswd.out").read_text() == "nobody:newpass1\n"


# ---------------------------------------------------------------- memory: details + freeing RAM
def test_memory_details_has_ram_and_swap():
    system = fresh("starx.system")
    m = system.memory_details()
    assert m["ram"]["total"] > 0 and m["usable"] >= m["ram"]["total"]
    assert {"zram", "swapfile", "apps", "swap_total"} <= set(m)
    assert all({"name", "ram", "swap"} <= set(a) for a in m["apps"])


def fake_cgroups(tmp_path, monkeypatch, pressure=0.0, current=1 << 30):
    root = tmp_path / "cgroup"
    for name in ("user.slice", "system.slice"):
        cg = root / name
        cg.mkdir(parents=True)
        (cg / "memory.reclaim").write_text("")
        (cg / "memory.current").write_text(f"{current}\n")
        (cg / "memory.pressure").write_text(f"some avg10={pressure:.2f} avg60=0.00 avg300=0.00 total=1\n"
                                            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    monkeypatch.delenv("JSTARX_USER_CGROUP", raising=False)
    monkeypatch.delenv("JSTARX_SYSTEM_CGROUP", raising=False)
    monkeypatch.setenv("JSTARX_CGROUP_ROOT", str(root))
    return root


def asked(root, name):
    text = (root / name / "memory.reclaim").read_text()
    return int(text) if text else 0


def test_free_memory_moves_idle_apps_then_services_to_swap(sysroot, monkeypatch, tmp_path):
    root = fake_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 1 << 30})
    res = starxd.op_memory_free()
    # 60% of 4 GB should be free: ~1.4 GB more, asked from the apps first, then background services
    assert asked(root, "user.slice") == int(4 * 0.6 * (1 << 30)) - (1 << 30)
    assert asked(root, "system.slice") == asked(root, "user.slice")  # the fake RAM did not get freer
    assert "freed" in res and res["total"] == 4 << 30
    assert starxd.op_memory_saver(False) == {"on": False}
    assert starxd.op_memory_saver() == {"on": False}
    assert starxd.op_memory_saver(True) == {"on": True}


def test_free_memory_stops_once_enough_is_free(sysroot, monkeypatch, tmp_path):
    root = fake_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    state = {"avail": 1 << 30}

    def meminfo():
        return {"MemTotal": 4 << 30, "MemAvailable": state["avail"]}

    real = starxd.reclaim

    def reclaim(n, cg=None, minimum=16 << 20):
        state["avail"] += n  # the kernel freed all of it
        return real(n, cg, minimum)

    monkeypatch.setattr(starxd, "_meminfo", meminfo)
    monkeypatch.setattr(starxd, "reclaim", reclaim)
    starxd.free_ram(3 << 30)
    assert asked(root, "user.slice") == 2 << 30 and asked(root, "system.slice") == 0


def test_memory_saver_is_gentle_with_ai_jobs(sysroot, monkeypatch, tmp_path):
    # the automatic saver takes at most 256 MB per pass from background services (Spark, StarAI) ...
    root = fake_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 1 << 30})
    starxd.free_ram(2 << 30, gentle=True)
    assert asked(root, "user.slice") == 1 << 30 and asked(root, "system.slice") == 256 << 20
    # ... and leaves a group alone while its programs are waiting for memory
    root2 = fake_cgroups(tmp_path / "busy", monkeypatch, pressure=5.0)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 1 << 30})
    starxd.free_ram(2 << 30, gentle=True)
    assert asked(root2, "user.slice") == 0 and asked(root2, "system.slice") == 0


def test_sweep_moves_a_little_idle_memory_and_backs_off(sysroot, monkeypatch, tmp_path):
    root = fake_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 3 << 30, "SwapFree": 2 << 30})
    assert starxd.sweep() == 2 * ((1 << 30) // 50)  # 2% of each group (about 20 MB)
    assert asked(root, "user.slice") == (1 << 30) // 50 and asked(root, "system.slice") == (1 << 30) // 50
    # programs waiting for memory: leave that group alone
    root2 = fake_cgroups(tmp_path / "busy", monkeypatch, pressure=3.5)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 3 << 30, "SwapFree": 2 << 30})
    assert starxd.sweep() == 0 and asked(root2, "user.slice") == 0
    # swap is full: nothing to do
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 3 << 30, "SwapFree": 0})
    assert starxd.sweep() == 0
    # a big group: at most 64 MB per sweep
    root3 = fake_cgroups(tmp_path / "big", monkeypatch, current=8 << 30)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"SwapFree": 2 << 30})
    starxd.sweep()
    assert asked(root3, "system.slice") == 64 << 20


def test_newest_system_update_is_the_highest_build_number(monkeypatch):
    sysupdate = fresh("jstarx_core.sysupdate")
    rels = [{"tag_name": "system-12", "published_at": "2026-11-25T22:40:00Z"},
            {"tag_name": "system-13", "published_at": "2026-11-25T22:30:00Z"},  # newer build, finished first
            {"tag_name": "v2.0.0", "published_at": "2026-11-25T23:00:00Z"},
            {"tag_name": "system-14", "draft": True, "published_at": None}]
    monkeypatch.setattr(sysupdate, "_get", lambda url, *a, **k: json.dumps(rels).encode())
    assert sysupdate.latest_release()["tag_name"] == "system-13"


# ---------------------------------------------------------------- Spark: faster answers
def test_spark_picks_fast_or_quality_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_ROOT", str(tmp_path))
    spark = fresh("jstarx_core.spark")
    os.makedirs(spark.MODELS)
    open(os.path.join(spark.MODELS, "spark-1-q8_0.gguf"), "wb").write(b"x" * 300)
    open(os.path.join(spark.MODELS, "spark-1-q4_k_m.gguf"), "wb").write(b"x" * 200)
    assert spark.find_model().endswith("q8_0.gguf")
    spark.set_cfg(fast=True)
    assert spark.find_model().endswith("q4_k_m.gguf")


# ---------------------------------------------------------------- whole-system updates
def test_system_update_check_and_install(sysroot, monkeypatch, tmp_path):
    current = tmp_path / "current-system"
    current.mkdir()
    monkeypatch.setenv("JSTARX_CURRENT_SYSTEM", str(current))
    monkeypatch.setenv("JSTARX_SYSTEM_PROFILE", str(tmp_path / "profiles" / "system"))
    sysupdate = fresh("jstarx_core.sysupdate")
    target = "/nix/store/0123456789abcdefghijklmnopqrstuv-nixos-system-jstarx-jstarx-1.1.0"
    rel = {"tag_name": "system-7", "assets": [
        {"name": "system.json", "browser_download_url": "https://x/system.json", "size": 10},
        {"name": "system-cache.tar.zst", "browser_download_url": "https://x/cache.tar.zst", "size": 4}]}
    monkeypatch.setattr(sysupdate, "latest_release", lambda: rel)
    monkeypatch.setattr(sysupdate, "_get", lambda url, timeout=30: json.dumps({"system": target, "version": "1.1.0"}).encode())
    res = sysupdate.check()
    assert res["state"] == "available" and res["version"] == "1.1.0"

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sysupdate.urllib.request, "urlopen", lambda req, timeout=60: FakeResponse(b"zstd"))
    ran = []

    class Done:
        returncode, stdout = 0, ""

    monkeypatch.setattr(sysupdate.subprocess, "run", lambda cmd, **kw: (ran.append(cmd), Done())[1])
    res = sysupdate.apply()
    assert res["state"] == "ready"
    assert ran[0][0] == "tar"
    realise = ran[1]
    assert realise[:3] == ["nix-store", "--realise", target] and "require-sigs" in realise and "builders" in realise
    assert ran[2][:3] == ["nix-env", "-p", str(tmp_path / "profiles" / "system")] and ran[2][-1] == target
    assert ran[3] == [os.path.join(target, "bin", "switch-to-configuration"), "boot"]


def test_system_update_refuses_bad_description(sysroot, monkeypatch):
    sysupdate = fresh("jstarx_core.sysupdate")
    rel = {"tag_name": "system-1", "assets": [{"name": "system.json", "browser_download_url": "u"},
                                               {"name": "system-cache.tar.zst", "browser_download_url": "u", "size": 1}]}
    monkeypatch.setattr(sysupdate, "latest_release", lambda: rel)
    monkeypatch.setattr(sysupdate, "_get", lambda url, timeout=30: b'{"system": "/nix/store/../../etc/evil"}')
    with pytest.raises(RuntimeError):
        sysupdate.apply()


def test_low_and_extreme_power_and_fan(tmp_path, monkeypatch, sysroot):
    sysfs = tmp_path / "sys"
    for n in range(4):
        cpu = sysfs / f"devices/system/cpu/cpu{n}"
        (cpu / "cpuidle/state1").mkdir(parents=True)
        (cpu / "cpuidle/state1/disable").write_text("0")
        if n:
            (cpu / "online").write_text("1")
    pol = sysfs / "devices/system/cpu/cpufreq/policy0"
    pol.mkdir(parents=True)
    for k, v in {"scaling_available_governors": "powersave conservative schedutil performance", "scaling_governor": "schedutil",
                 "cpuinfo_min_freq": "100000", "cpuinfo_max_freq": "1500000", "scaling_max_freq": "1500000", "scaling_min_freq": "100000"}.items():
        (pol / k).write_text(v)
    fan = sysfs / "class/thermal/cooling_device0"
    fan.mkdir(parents=True)
    for k, v in {"type": "pwm-fan", "max_state": "3", "cur_state": "0"}.items():
        (fan / k).write_text(v)
    monkeypatch.setenv("JSTARX_SYSFS", str(sysfs))
    power = fresh("jstarx_core.power")
    power.apply("low")
    assert (sysfs / "devices/system/cpu/cpu1/online").read_text() == "0"
    assert int((pol / "scaling_max_freq").read_text()) == 100000 + int(1400000 * 0.4)
    power.set_profile("extreme")
    assert all((sysfs / f"devices/system/cpu/cpu{n}/online").read_text() == "1" for n in range(1, 4))
    assert (pol / "scaling_governor").read_text() == "performance"
    assert (pol / "scaling_min_freq").read_text() == "1500000"  # locked at full speed
    assert (sysfs / "devices/system/cpu/cpu2/cpuidle/state1/disable").read_text() == "1"
    assert (fan / "cur_state").read_text() == "3"  # fan at full speed
    (fan / "cur_state").write_text("1")  # the kernel lowers it when cool…
    assert power.keep_fan() and (fan / "cur_state").read_text() == "3"  # …and JStarx puts it back
    power.set_profile("balanced")
    assert power.fan("auto") == "auto" and not power.keep_fan()
    power.fan("max")
    assert power.keep_fan() and power.get()["fan"] == "max"
    power.fan("auto")
    assert (sysfs / "devices/system/cpu/cpu2/cpuidle/state1/disable").read_text() == "0"
