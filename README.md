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
| **Settings** | 16 pages: Wi-Fi, Display & Casting, Appearance, Dock & Island, Home & Launchpad, Sound, Power, AI & Spark, Apps, Updates, Repair, Memory, Storage, Users & Privacy, Date & Time, About |
| **Apps** | Firefox, Claude, Spark 1 (assistant), AI Center, Star Store, Terminal |
| **Games** | Snake, Dodge, Breaker |
| **Star Store** | Official JStarx apps you can install later: Notes, Paint, Calculator, Clock, Claude Code, AI Kit (PyTorch + Jupyter), VSCodium, Files, GIMP, VLC |
| **24/7 AI** | AI Center runs training/serving jobs as system services, keeps them going after a restart, pauses them when the Jetson gets too hot, and has an "AI 24/7" mode that never sleeps |
| **Spark 1** | Your own assistant model, run by llama.cpp on the Jetson (see below) |
| **Auto update** | Checks this GitHub repo every few hours: installs the new JStarx layer into a spare slot (A/B, every file checked), and whole-system updates (StarX Kernel, drivers, apps) that GitHub Actions publishes as `system-N` releases |
| **Auto repair** | Fixes damaged files at every start, undoes an update if the desktop keeps crashing, Safe Mode, and goes back to the last working system if a new one can't start |
| **Wireless display** | Cast the screen to a Miracast TV or a Chromecast; with no screen plugged in, JStarx finds a wireless display by itself |
| **Full-screen apps** | Apps open full screen; the title bars of JStarx apps and Firefox curve around the Dynamic Island, and hovering the island opens it (Today and Memory tabs) |
| **Up to 12 GB memory** | 4 GB RAM + a swap file of up to 8 GB (a quarter of the card: 32 GB cards get the full 8 GB); only what is in use stays in RAM: idle apps and background services move to compressed RAM, then to the swap file, and half of the RAM stays free. Settings → Memory and the island's Memory tab show it |
| **Power modes** | Low power, Power saver, Balanced, Performance and Extreme (everything at full speed, fan at max); screen dimming and screen off; zram |
| **Fan** | The StarX Kernel drives the Nano's fan from the temperature; Settings → Power → Fan: Auto or Max |

No bloatware: the system only has what JStarx needs. Everything else is in the Star Store.

## Get JStarx on your Jetson Nano

You need: a Jetson Nano Developer Kit, a microSD card (32 GB or bigger is best), and a PC.

1. **Get the image.** Download `jstarx-2.0.1-jetson-nano.img.xz` from the
   [latest release](https://github.com/Stormblazerplayz/JStarx/releases/latest). Every push to
   main builds a new release (about an hour); every build also keeps the file in the run's
   **Artifacts** (Actions tab → **Build JStarx OS image**).
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

> **ISO file?** The Jetson Nano starts from an SD card image (`.img`, here `.img.xz`), not an `.iso`.
> An ISO is for PCs and would not start on a Jetson. Flash the `.img.xz` with balenaEtcher.

## Spark 1 (the assistant)

Spark 1 is Storm's own model: a Llama-style transformer with 20 layers, 1024 wide, 16 attention
heads (4 key/value heads), a 33,039-token vocabulary and a 4,096-token context (about 300M
parameters). Its weights are in the **Spark1** release of this repo (`sft_best.pt`).

JStarx gets it ready by itself:

1. When the Jetson is online, it downloads every file in the Spark1 release (it checks each file's
   checksum, and skips files it already has). You can also press **Settings → AI & Spark → Download Spark 1**.
2. It reads the PyTorch checkpoint safely (no code inside the file is ever run), works out how the
   model encodes word positions, and converts it to GGUF (8-bit, about 330 MB).
3. llama.cpp runs it on the Jetson. Ask Spark from the island, the Start menu or `Super + Space`.

**One more file is needed:** the tokenizer Spark 1 was trained with. The checkpoint remembers its
fingerprint (sha256 `88c43f2c…`). Open the Spark1 release → **Edit** → drag `tokenizer.json` into
the **"Attach binaries by dropping them here"** box → **Update release**. If you have
`tokenizer_config.json` (it holds the chat format), upload that too. Then JStarx finishes the setup.

You can also copy the files onto the Jetson and use **Import from file**.

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
python3 tools/qemu-test.py result-sd/sd-image/jstarx-2.0.1-jetson-nano.img
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
