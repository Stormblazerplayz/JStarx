"""Tests for the JetPack 4.6.1 install, and for the parts of JStarx that change on JetPack's 4.9 kernel.

Run: python3 -m pytest -q tests
"""
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "os", "pkgs", "jstarx-core")
INSTALL = os.path.join(ROOT, "jetpack", "install.sh")
sys.path.insert(0, CORE)

NV_OK = "# R32 (release), REVISION: 7.1, GCID: 1, BOARD: t210ref, EABI: aarch64, DATE: test\n"
OS_OK = 'NAME="Ubuntu"\nVERSION_ID="18.04"\n'


def fresh(modname):
    """(Re)import a module after the environment has changed."""
    top = modname.split(".")[0]
    for name in list(sys.modules):
        if name == top or name.startswith(top + "."):
            del sys.modules[name]
    return importlib.import_module(modname)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Send every JStarx folder to a temp folder, and pretend to be a computer that is neither NixOS nor JetPack."""
    monkeypatch.setenv("JSTARX_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("JSTARX_RUN", str(tmp_path / "run"))
    monkeypatch.setenv("JSTARX_BOOT", str(tmp_path / "boot"))
    monkeypatch.setenv("JSTARX_FACTORY_LAYER", str(tmp_path / "factory"))
    monkeypatch.setenv("JSTARX_SYSFS", str(tmp_path / "sys"))
    monkeypatch.setenv("SPARK_ROOT", str(tmp_path / "spark"))
    monkeypatch.setenv("JSTARX_NIX_DIR", str(tmp_path / "no-nix"))
    monkeypatch.setenv("JSTARX_NV_RELEASE", str(tmp_path / "no-release"))
    monkeypatch.delenv("JSTARX_PLATFORM", raising=False)
    (tmp_path / "drop_caches").write_text("0")
    monkeypatch.setenv("JSTARX_DROP_CACHES", str(tmp_path / "drop_caches"))
    (tmp_path / "cgroup").mkdir()
    monkeypatch.setenv("JSTARX_CGROUP_ROOT", str(tmp_path / "cgroup"))
    monkeypatch.delenv("JSTARX_USER_CGROUP", raising=False)
    monkeypatch.delenv("JSTARX_SYSTEM_CGROUP", raising=False)
    monkeypatch.setattr(os, "sync", lambda: None)
    return tmp_path


# ---------------------------------------------------------------- the JetPack installer
def jetpack_root(tmp_path, release=NV_OK, osrel=OS_OK):
    root = tmp_path / "jetson"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "nv_tegra_release").write_text(release)
    (root / "etc" / "os-release").write_text(osrel)
    return root


def run_install(root):
    return subprocess.run(["bash", INSTALL, "--root", str(root)], capture_output=True, text=True)


def test_installer_puts_everything_in_place(tmp_path):
    root = jetpack_root(tmp_path)
    r = run_install(root)
    assert r.returncode == 0, r.stderr
    opt = root / "opt" / "jstarx"
    assert (opt / "lib" / "jstarx_core" / "starxd.py").is_file()
    assert not list(opt.rglob("__pycache__"))
    assert os.access(opt / "bin" / "jstarx-swapfile", os.X_OK)
    assert os.access(opt / "bin" / "jstarx-zram", os.X_OK)
    units = root / "etc" / "systemd" / "system"
    starxd = (units / "jstarx-starxd.service").read_text()
    assert "Environment=PYTHONPATH=/opt/jstarx/lib" in starxd
    assert "ExecStart=/usr/bin/python3 -m jstarx_core.starxd" in starxd
    assert "ExecStart=/opt/jstarx/bin/jstarx-swapfile start" in (units / "jstarx-swap.service").read_text()
    assert "ExecStart=/opt/jstarx/bin/jstarx-zram start" in (units / "jstarx-zram.service").read_text()
    sysctl = (root / "etc" / "sysctl.d" / "90-jstarx.conf").read_text()
    assert "vm.swappiness = 100" in sysctl
    assert "vm.swappiness = 200" not in sysctl
    assert (root / "etc" / "tmpfiles.d" / "jstarx.conf").is_file()
    version = (opt / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    with open(os.path.join(ROOT, "layer", "layer.json")) as f:
        assert f'"version": "{version}"' in f.read()


def test_installer_can_run_again(tmp_path):
    root = jetpack_root(tmp_path)
    assert run_install(root).returncode == 0
    r = run_install(root)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("break_it", [
    lambda root: (root / "etc" / "nv_tegra_release").unlink(),
    lambda root: (root / "etc" / "nv_tegra_release").write_text("# R35 (release), REVISION: 4.1, BOARD: generic\n"),
    lambda root: (root / "etc" / "os-release").write_text('VERSION_ID="22.04"\n'),
])
def test_installer_refuses_other_systems(tmp_path, break_it):
    root = jetpack_root(tmp_path)
    break_it(root)
    r = run_install(root)
    assert r.returncode != 0
    assert not (root / "opt" / "jstarx").exists()


def test_installer_warns_about_other_jetpack_4_versions(tmp_path):
    root = jetpack_root(tmp_path, release="# R32 (release), REVISION: 6.1, BOARD: t210ref, EABI: aarch64\n")
    r = run_install(root)
    assert r.returncode == 0, r.stderr
    assert "warning" in r.stderr


def test_shell_scripts_are_valid():
    scripts = [INSTALL] + [os.path.join(ROOT, "jetpack", "files", n) for n in ("jstarx-swapfile", "jstarx-zram")]
    for path in scripts:
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", *scripts], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------- Python 3.6 (Ubuntu 18.04)
def test_core_avoids_options_that_python_36_does_not_have():
    # subprocess.run(capture_output=...) and text=... only exist from Python 3.7
    hits = []
    for dirpath, _dirs, files in os.walk(os.path.join(CORE, "jstarx_core")):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                with open(path) as f:
                    for number, line in enumerate(f, 1):
                        if "capture_output=" in line or "text=True" in line:
                            hits.append(f"{path}:{number}")
    assert not hits, hits


# ---------------------------------------------------------------- which system JStarx is on
def test_platform_is_nixos_jetpack_or_other(tmp_path, monkeypatch):
    assert fresh("jstarx_core.common").platform() == "other"
    (tmp_path / "release").write_text(NV_OK)
    monkeypatch.setenv("JSTARX_NV_RELEASE", str(tmp_path / "release"))
    assert fresh("jstarx_core.common").platform() == "jetpack"
    (tmp_path / "nix").mkdir()
    monkeypatch.setenv("JSTARX_NIX_DIR", str(tmp_path / "nix"))
    assert fresh("jstarx_core.common").platform() == "nixos"
    monkeypatch.setenv("JSTARX_PLATFORM", "jetpack")
    assert fresh("jstarx_core.common").platform() == "jetpack"


def test_whole_system_updates_only_on_the_nixos_image(monkeypatch):
    monkeypatch.setenv("JSTARX_PLATFORM", "jetpack")
    starxd = fresh("jstarx_core.starxd")
    assert starxd.OPS["system_update_check"]()["state"] == "unsupported"
    with pytest.raises(RuntimeError):
        starxd.OPS["system_update_apply"]()


def test_ssh_switch_uses_the_ubuntu_service_name(monkeypatch):
    monkeypatch.setenv("JSTARX_PLATFORM", "jetpack")
    starxd = fresh("jstarx_core.starxd")
    calls = []
    monkeypatch.setattr(starxd, "run", lambda args, **kw: calls.append(list(args)))
    assert starxd.OPS["system_set"]("ssh", True) == {"ssh": True}
    assert calls[-1] == ["systemctl", "start", "ssh.service"]


def test_storage_clean_skips_nix_outside_nixos(monkeypatch):
    monkeypatch.setenv("JSTARX_PLATFORM", "jetpack")
    starxd = fresh("jstarx_core.starxd")
    calls = []
    monkeypatch.setattr(starxd, "run", lambda args, **kw: calls.append(list(args)))
    starxd.op_storage_clean()
    assert calls and all(c[0] != "nix-collect-garbage" for c in calls)


# ---------------------------------------------------------------- memory on a kernel without memory.reclaim
def v1_cgroups(tmp_path, monkeypatch):
    """Cgroup folders without memory.reclaim, like JetPack's 4.9 kernel."""
    root = tmp_path / "cgroup"
    for name in ("user.slice", "system.slice"):
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "memory.current").write_text("1073741824\n")
    monkeypatch.setenv("JSTARX_CGROUP_ROOT", str(root))
    return root


def test_without_memory_reclaim_the_saver_drops_the_page_cache(tmp_path, monkeypatch):
    v1_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    assert starxd.can_reclaim() is False
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 1 << 30})
    res = starxd.op_memory_free()
    assert (tmp_path / "drop_caches").read_text() == "1"
    assert res["total"] == 4 << 30


def test_the_automatic_saver_drops_the_page_cache_at_most_once_a_minute(tmp_path, monkeypatch):
    v1_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 1 << 30})
    drop = tmp_path / "drop_caches"
    starxd.free_ram(2 << 30, gentle=True)
    assert drop.read_text() == "1"
    drop.write_text("0")
    starxd.free_ram(2 << 30, gentle=True)  # again right away: nothing
    assert drop.read_text() == "0"
    starxd._last_drop[0] -= 3600  # an hour later
    starxd.free_ram(2 << 30, gentle=True)
    assert drop.read_text() == "1"


def test_nothing_is_dropped_when_enough_is_free(tmp_path, monkeypatch):
    v1_cgroups(tmp_path, monkeypatch)
    starxd = fresh("jstarx_core.starxd")
    monkeypatch.setattr(starxd, "_meminfo", lambda: {"MemTotal": 4 << 30, "MemAvailable": 3 << 30})
    starxd.free_ram(2 << 30)
    assert (tmp_path / "drop_caches").read_text() == "0"


# ---------------------------------------------------------------- the helper really starts on JetPack
@pytest.mark.skipif(os.name != "posix" or os.getuid() != 0, reason="the helper only lets root ask in this test")
def test_the_helper_starts_and_answers_on_jetpack(tmp_path):
    work = tempfile.mkdtemp(prefix="jstarx-", dir="/tmp")  # short folder: Unix socket paths have a length limit
    sock = os.path.join(work, "starxd.sock")
    env = dict(os.environ, PYTHONPATH=CORE, JSTARX_PLATFORM="jetpack", STARXD_SOCKET=sock,
               JSTARX_STATE=os.path.join(work, "state"), JSTARX_RUN=os.path.join(work, "run"),
               JSTARX_BOOT=os.path.join(work, "boot"), JSTARX_SYSFS=os.path.join(work, "sys"),
               JSTARX_CGROUP_ROOT=os.path.join(work, "cgroup"), JSTARX_DROP_CACHES=os.path.join(work, "drop"),
               JSTARX_FACTORY_LAYER=os.path.join(work, "factory"), SPARK_ROOT=os.path.join(work, "spark"))
    log_path = os.path.join(work, "starxd.log")
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, "-m", "jstarx_core.starxd"], env=env, cwd=work,
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 20
        while not os.path.exists(sock):
            if proc.poll() is not None or time.time() > deadline:
                proc.kill()
                proc.wait()
                log.close()
                raise AssertionError("the helper did not start:\n" + open(log_path).read())
            time.sleep(0.1)

        def ask(op, **args):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(sock)
                s.sendall((json.dumps({"op": op, "args": args}) + "\n").encode())
                return json.loads(s.makefile().readline())

        assert ask("ping")["ok"]
        assert ask("system_update_check")["result"]["state"] == "unsupported"
        assert ask("power_get")["result"]["profile"] == "balanced"
        assert ask("memory_saver") == {"ok": True, "result": {"on": True}}
        assert ask("memory_free")["ok"]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
        shutil.rmtree(work, ignore_errors=True)
