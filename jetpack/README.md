# JStarx on JetPack 4.6.1 (Jetson Nano)

This runs the JStarx core services on a Jetson Nano that has NVIDIA's JetPack 4.6.1 (Ubuntu 18.04). JetPack's own kernel and system stay. The installer adds:

- **Memory saver:** JetPack's kernel (4.9) can't move idle apps to swap the way the JStarx image does. Instead, when memory runs low, the saver drops the page cache (files kept in RAM for speed). Programs keep their memory.
- **Power modes and fan control:** the same modes as the JStarx image.
- **Swap:** a swap file on the card (up to 8 GB), and zram (compressed RAM, used first).
- **Memory setting:** `vm.swappiness` is 100, the most this kernel allows.

The desktop is included (see below). Not included yet: Spark, StarAI, the Star Store's Nix apps, wireless display casting and whole-system updates. Those need the JStarx SD card image.

## The desktop

The installer adds the JStarx desktop (StarShell) on the openbox window manager. After the install, log out and choose **JStarx** at the login screen.

- The dock, the Dynamic Island, the launchpad and the apps look and work the same as on the SD card image.
- Keys: Super+A launchpad, Super+Space Spark, Super+C control center, Super+P power, Super+E Settings, Super+B Firefox, Super+Return terminal (xterm), Super+Q close the window, Print takes a screenshot.
- Power saving: the screen turns off after the time you set. The desktop does not dim first.

## Install

1. Copy this repo to the Jetson (`git clone`, or download the ZIP from GitHub).
2. In a terminal, go into the `jetpack` folder and run (it installs the desktop packages, so it needs internet):

   ```bash
   sudo ./install.sh
   ```

3. Check it:

   ```bash
   systemctl status jstarx-starxd
   swapon --show
   cat /proc/sys/vm/swappiness
   ```

   The last command should print `100`.

If something fails, read the log, for example `journalctl -u jstarx-starxd -n 40`.

## Test without installing

```bash
./install.sh --root /tmp/jstarx-test
```

This writes the files into `/tmp/jstarx-test` and starts nothing. Delete it with `rm -rf /tmp/jstarx-test` when you are done.
