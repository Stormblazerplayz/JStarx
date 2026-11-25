# ⭐ JStarx OS

**A custom operating system for the NVIDIA Jetson Nano.**
Made by Storm, coded by Claude.

JStarx is a whole OS stacked on its own kernel, the **StarX Kernel** (Linux 6.12 LTS with the
JStarx config and boot logo). It has a purple-and-orange liquid-glass desktop with bouncy
animations, and it is built to run AI 24/7.

<p align="center"><img src="logos/png/01-nova.png" width="160" alt="JStarx logo"></p>

## What's inside

| | |
|---|---|
| **Desktop (StarShell)** | Dock at the bottom, Dynamic Island at the top, Start menu, Launchpad with pages, home screen with app folders, Control Center, notifications, spring/bounce animations everywhere |
| **Boot screen** | JStarx logo that bounces in, glow, progress bar (Plymouth), plus the StarX logo in the kernel |
| **Settings** | 15 pages: Wi-Fi, Display & Casting, Appearance, Dock & Island, Home & Launchpad, Sound, Power, AI & Spark, Apps, Updates, Repair, Storage, Users & Privacy, Date & Time, About |
| **Apps** | Firefox, Claude, Spark 1 (assistant), AI Center, Star Store, Terminal |
| **Games** | Snake, Dodge, Breaker |
| **Star Store** | Official JStarx apps you can install later: Notes, Paint, Calculator, Clock, Claude Code, AI Kit (PyTorch + Jupyter), VSCodium, Files, GIMP, VLC |
| **24/7 AI** | AI Center runs training/serving jobs as system services, keeps them going after a restart, pauses them when the Jetson gets too hot, and has an "AI 24/7" mode that never sleeps |
| **Spark 1** | Your own assistant model, run by llama.cpp on the Jetson (see below) |
| **Auto update** | Checks this GitHub repo every few hours and installs the new JStarx layer into a spare slot (A/B), with a safety check of every file |
| **Auto repair** | Fixes damaged files at every start, undoes an update if the desktop keeps crashing, Safe Mode, and goes back to the last working system if a new one can't start |
| **Wireless display** | Cast the screen to a Miracast TV or a Chromecast; with no screen plugged in, JStarx finds a wireless display by itself |
| **Power saving** | Power modes (Saver / Balanced / Performance), screen dimming and screen off, CPU limits, compressed memory (zram) |

No bloatware: the system only has what JStarx needs. Everything else is in the Star Store.

## Get JStarx on your Jetson Nano

You need: a Jetson Nano Developer Kit, a microSD card (32 GB or bigger is best), and a PC.

1. **Get the image.** Open the **Actions** tab of this repo, pick **Build JStarx OS image**, press
   **Run workflow**, wait for it to finish (about an hour), and download `jstarx-sd-image`.
   (Releases also have it when a version tag is pushed.) You get `jstarx-1.0.0-jetson-nano.img.xz`.
2. **Flash it.** Open [balenaEtcher](https://etcher.balena.io), pick the `.img.xz` file, pick your
   SD card, press **Flash**.
3. **Start it.** Put the card in the Jetson, plug in a screen (or don't, see below), keyboard,
   mouse and power. The JStarx boot screen shows up and then the desktop.

The first start takes a bit longer because JStarx grows to fill your whole SD card.

* User: `storm` · Password: `jstarx` (change it in **Settings → Users & Privacy**).
* No screen? JStarx looks for a Miracast or Chromecast display on your Wi-Fi and casts to it.

> **If the Jetson doesn't start JStarx:** its built-in bootloader may be too old. Flash NVIDIA's
> JetPack 4.6 SD card image once, start it and let it finish setting up (this updates the
> bootloader inside the Jetson), then flash JStarx again.

## Spark 1 (the assistant)

Spark 1's model file is too big for git, so it lives in a GitHub **release**:

1. On GitHub: **Releases → Draft a new release**, tag `spark-1`.
2. Drag the model file (a `.gguf`, or a `.safetensors`/`.bin` with its config files) into the
   box that says **"Attach binaries by dropping them here"**, then **Publish release**.
3. On the Jetson: **Settings → AI & Spark → Download Spark 1**. It downloads, checks and starts it.

You can also copy the file onto the Jetson and use **Import from file**.

## Auto repair: what happens when something breaks

| Problem | What JStarx does |
|---|---|
| A JStarx file is damaged or missing | Every start (and **Settings → Repair**) checks all files against `MANIFEST.json` and copies good ones back |
| An update makes the desktop crash | After 3 crashes in a row, JStarx undoes the update; if it still crashes, Safe Mode |
| A new system build can't start | The boot counter notices after 2 failed tries and goes back to the last build that worked |
| The Jetson freezes | The hardware watchdog restarts it |
| Something worse | Pick **JStarx Recovery** in the boot menu: it checks every system file and repairs it |

All of this is tested in a virtual Jetson (QEMU), see `tools/qemu-test.py`.

## Build it yourself

On any Linux PC with [Nix](https://nixos.org/download):

```bash
nix-build -A sdImage -o result-sd
```

The StarX Kernel is cross-compiled; everything else comes from the NixOS cache. On an x86 PC,
let it run ARM64 programs first (QEMU `binfmt`, e.g. `docker run --privileged --rm tonistiigi/binfmt --install arm64`)
and add `extra-platforms = aarch64-linux` to `/etc/nix/nix.conf`.

Test the image in QEMU (needs `qemu-system-aarch64` and the `u-boot-qemu` package):

```bash
python3 tools/qemu-test.py result-sd/sd-image/jstarx-1.0.0-jetson-nano.img
```

Run the unit tests:

```bash
python3 -m pytest -q tests
```

## How the repo is laid out

| Folder | What's in it |
|---|---|
| `os/kernel/` | StarX Kernel: config fragment, full config, boot logo, build recipe |
| `os/modules/` | The OS itself (`jstarx.nix`), boot menu + boot counter, SD card image |
| `os/pkgs/jstarx-core/` | System services: `starxd`, updater, repair, power, StarAI, Spark server |
| `os/plymouth/` | The boot screen |
| `os/config/` | Window theme, keyboard shortcuts, GTK theme |
| `layer/` | The JStarx layer (updates itself from GitHub): StarShell, apps, games, Star Store, wallpapers |
| `logos/` | 10 logo concepts (Nova is the official one) |
| `tools/` | Scripts that make the logos, icons, wallpapers, boot screen, manifests, and the QEMU test |
| `tests/` | Tests for the updater, repair, power, StarAI and boot counter |

## Keyboard shortcuts

| Keys | Does |
|---|---|
| `Super` | Start menu |
| `Super + A` | Launchpad |
| `Super + Space` | Ask Spark |
| `Super + C` | Control Center |
| `Super + P` | Power menu |
| `Print` | Screenshot |
