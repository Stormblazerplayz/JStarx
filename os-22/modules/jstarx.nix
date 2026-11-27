# JStarx OS: the whole system, stacked on the StarX Kernel.
{ config, lib, pkgs, starxKernel, nixpkgsSrc ? null, ... }:

let
  J = pkgs;
  core = J.jstarx-core;
  layer = J.jstarx-layer;
  runtime = J.jstarx-runtime;
  # The board's display has no Wayland (DRM) device, so the desktop runs on X11 with the framebuffer,
  # the same way as the JetPack desktop (jetpack/files/starx-session-x11).
  x11Session = pkgs.writeShellScript "jstarx-x11-session" ''
    export XDG_CURRENT_DESKTOP=JStarx XDG_SESSION_DESKTOP=JStarx XDG_SESSION_TYPE=x11
    export GDK_BACKEND=x11 MOZ_ENABLE_WAYLAND=0 MOZ_LEGACY_PROFILES=1 STARX_GPU=never LIBGL_ALWAYS_SOFTWARE=1
    export GTK_THEME=JStarx
    export JSTARX_LAYER=${layer} STARX_APP_BIN=${layer}/bin/starx-app STARX_PYTHON=${runtime}/bin/starx-python
    export PATH=${layer}/bin:${core}/bin:${runtime}/bin:$PATH
    xset s off || true
    xset -dpms || true
    xcompmgr >/dev/null 2>&1 &
    exec ${pkgs.openbox}/bin/openbox --config-file ${../config/openbox/rc.xml} --startup "${core}/bin/starx-shell-supervisor"
  '';
  version = (lib.importJSON ../../layer/layer.json).version;
  codename = (lib.importJSON ../../layer/layer.json).codename;
  greetdToml = pkgs.writeShellScript "jstarx-greetd-config" ''
    # Autologin is on unless the user switched it off in Settings.
    mkdir -p /run/jstarx
    {
      echo '[terminal]'
      echo 'vt = 1'
      echo '[default_session]'
      echo 'command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --remember --asterisks --greeting \"Welcome to JStarx\" --cmd ${core}/bin/starx-session"'
      echo 'user = "greeter"'
      if [ ! -e /var/lib/jstarx/flags/no-autologin ]; then
        echo '[initial_session]'
        echo 'command = "${core}/bin/starx-session"'
        echo 'user = "storm"'
      fi
    } > /run/jstarx/greetd.toml
  '';
in
{
  imports = [ ./bootloader.nix ];

  nixpkgs.overlays = [ (import ../pkgs) ];
  nixpkgs.localSystem.system = "aarch64-linux";
  nixpkgs.config.allowUnfree = true;
  system.stateVersion = "26.05";

  # ------------------------------------------------------------------ branding
  system.nixos.label = "jstarx-${version}";

  # ------------------------------------------------------------------ StarX Kernel + hardware
  boot.kernelPackages = pkgs.linuxPackages_5_10;   # the board runs its own NVIDIA 4.9 kernel; this one is for the QEMU check
  boot.initrd.includeDefaultModules = false;
  boot.initrd.availableKernelModules = [ ];   # everything needed to start is built into the kernel
  # if anything freezes while starting, the watchdog restarts the Jetson (and auto-repair counts it)
  boot.kernelParams = [
    "console=ttyS0,115200n8" "console=ttyAMA0,115200" "console=tty1"
    "quiet" "splash" "loglevel=3" "udev.log_level=3" "vt.global_cursor_default=0"
    "fbcon=logo-pos:center" "fbcon=logo-count:1" "panic=10" "boot.panic_on_fail"
    # show the boot screen on the display even though serial consoles are listed above
    "plymouth.ignore-serial-consoles"
  ];
  hardware.firmware = [ J.jstarx-firmware ];
  hardware.enableRedistributableFirmware = lib.mkForce false;   # we ship only what the Jetson needs
  hardware.opengl.enable = true;
  hardware.bluetooth.enable = true;
  hardware.deviceTree.enable = true;
  boot.consoleLogLevel = 3;

  # ------------------------------------------------------------------ boot screen
  boot.plymouth = {
    enable = true;
    theme = "jstarx";
    themePackages = [ J.jstarx-plymouth ];
    font = "${pkgs.inter}/share/fonts/opentype/Inter-Regular.otf";
  };
  # Plymouth only uses a graphics card that udev has finished setting up. Without this wait it
  # can look too early, miss the card and show text instead of the boot screen.
  boot.initrd.systemd.services.plymouth-start.preStart = lib.mkAfter ''
    udevadm settle --timeout=15 || true
  '';

  # ------------------------------------------------------------------ users
  users.groups.jstarx = { };
  users.groups.starai = { };
  users.users.storm = {
    isNormalUser = true;
    description = "Storm";
    extraGroups = [ "wheel" "jstarx" "networkmanager" "video" "audio" "input" "render" ];
    initialPassword = "jstarx";
  };
  users.users.starai = { isSystemUser = true; group = "starai"; home = "/var/lib/starai"; description = "StarAI jobs"; };
  security.sudo.wheelNeedsPassword = true;
  security.polkit.enable = true;

  # ------------------------------------------------------------------ desktop session
  # X11 desktop with log-in as storm (the Wayland greeter cannot run on this board)
  services.xserver = {
    enable = true;
    videoDrivers = [ "fbdev" ];
    windowManager.openbox.enable = true;
    displayManager.lightdm = {
      enable = true;
      greeter.enable = false;
      autoLogin = { enable = true; user = "storm"; };
    };
    displayManager.session = [ { manage = "desktop"; name = "jstarx"; start = "exec ${x11Session}"; } ];
    displayManager.defaultSession = "jstarx";
  };
  services.greetd = {
    enable = false;
    settings.default_session = { command = "${core}/bin/starx-session"; user = "storm"; };
  };
  systemd.services.greetd = {
    unitConfig.After = lib.mkAfter [ "starxd.service" "jstarx-repair.service" ];
    serviceConfig.ExecStartPre = [ "${greetdToml}" ];
    serviceConfig.ExecStart = lib.mkForce "${pkgs.greetd.greetd}/bin/greetd --config /run/jstarx/greetd.toml";
  };
  environment.etc = {
    "xdg/labwc/rc.xml".source = ../config/labwc/rc.xml;
    "xdg/labwc/autostart".source = ../config/labwc/autostart;
    "xdg/labwc/environment".source = ../config/labwc/environment;
    "xdg/labwc/menu.xml".source = ../config/labwc/menu.xml;
    "jstarx/factory-layer".source = layer;
    "jstarx/version".text = "${version}\n";
    "xdg/gtk-3.0/settings.ini".text = ''
      [Settings]
      gtk-theme-name=JStarx
      gtk-application-prefer-dark-theme=true
      gtk-font-name=Inter 11
      gtk-cursor-theme-size=24
    '';
    "xdg/foot/foot.ini".text = ''
      font=JetBrains Mono:size=11
      pad=12x10
      [colors]
      alpha=0.95
      background=160433
      foreground=f6f0ff
      regular1=ff6b81
      regular2=5dffb0
      regular3=ffd166
      regular4=9d4edd
      regular5=ff7ac6
      regular6=4fd1ff
      bright4=c77dff
    '';
  };
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
  };
  fonts.fonts = with pkgs; [ inter jetbrains-mono noto-fonts-emoji dejavu_fonts ];
  fonts.fontconfig.defaultFonts = { sansSerif = [ "Inter" "DejaVu Sans" ]; monospace = [ "JetBrains Mono" ]; emoji = [ "Noto Color Emoji" ]; };

  environment.systemPackages = with pkgs; [ firefox
    core runtime J.jstarx-theme
    xorg.xset xorg.xcompmgr xorg.xprop xorg.xrandr wmctrl xdotool pulseaudio openbox xterm labwc swayidle wlrctl wlr-randr grim foot wf-recorder ffmpeg
    gnome-network-displays networkmanager wireplumber libnotify xdg-utils
    git curl htop
  ];
  environment.sessionVariables = {
    JSTARX_RUN = "/run/jstarx";
    STARX_GPU = "never";
  };

  # ------------------------------------------------------------------ Firefox (Claude also runs in it)
  # NixOS 22.05 has no Firefox module: install Firefox and write its policies file ourselves
  environment.etc."firefox/policies/policies.json".text = builtins.toJSON { policies = {
    DisableTelemetry = true;
    DisableFirefoxStudies = true;
    DisablePocket = true;
    DontCheckDefaultBrowser = true;
    OverrideFirstRunPage = "";
    OverridePostUpdatePage = "";
    UserMessaging = { WhatsNew = false; ExtensionRecommendations = false; FeatureRecommendations = false; SkipOnboarding = true; };
    Homepage = { URL = "about:home"; StartPage = "homepage"; };
    Preferences = lib.mapAttrs (_: v: { Value = v; Status = "default"; }) {
      "widget.use-xdg-desktop-portal.file-picker" = 1;
      "ui.systemUsesDarkTheme" = 1;
      "dom.ipc.processCount" = 2;
      "browser.cache.disk.enable" = false;
      "browser.cache.memory.capacity" = 65536;
      "browser.sessionstore.interval" = 60000;
      "browser.theme.toolbar-theme" = 0;
      "browser.tabs.inTitlebar" = 1;
      "toolkit.legacyUserProfileCustomizations.stylesheets" = true;
      "media.ffmpeg.vaapi.enabled" = false;
    };
  }; };

  # ------------------------------------------------------------------ no bloat
  documentation.nixos.enable = false;
  documentation.doc.enable = false;
  documentation.info.enable = false;
  programs.command-not-found.enable = false;
  documentation.man.enable = false;   # no manual pages: smaller system (every command has --help)

  # ------------------------------------------------------------------ v2 speed + SD card care
  # start faster: don't wait for the network before showing the desktop
  systemd.services.NetworkManager-wait-online.enable = false;
  # fewer writes to the SD card (faster, and the card lasts longer)
  fileSystems."/".options = [ "noatime" "commit=60" ];
  boot.tmpOnTmpfs = true;           # temporary files live in RAM (they can swap out)
  boot.tmpOnTmpfsSize = "30%";
  # updates and app installs run at idle priority, so the desktop and AI stay smooth
  nix.daemonCPUSchedPolicy = "idle";
  nix.daemonIOSchedClass = "idle";
  environment.defaultPackages = [ ];

  # ------------------------------------------------------------------ network, sound, casting
  networking.networkmanager.enable = true;
  services.avahi = { enable = true; nssmdns = true; publish = { enable = true; addresses = true; workstation = true; }; };
  networking.firewall = {
    # off on the 4.9 board kernel: its netfilter modules do not match this firewall (see the boot log)
    enable = false;
    allowedTCPPorts = [ 7236 7250 8765 8091 ];   # Miracast, StarCast stream, AI model server
    allowedUDPPorts = [ 5353 7236 ];
  };
  # Grow the system partition to fill the card. The NixOS grow service picks the partition number from
  # the device's minor number, which is wrong for mmcblk1 (partition 1 is minor 129), so this one uses sysfs.
  systemd.services.jstarx-grow-root = {
    description = "Grow the JStarx system partition to fill the SD card";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    path = with pkgs; [ util-linux e2fsprogs gawk ];
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
    script = ''
      dev=$(findmnt -n -o SOURCE /)
      disk=/dev/$(lsblk -npo PKNAME "$dev" | head -n 1 | xargs basename)
      part=$(cat /sys/class/block/$(basename "$dev")/partition)
      echo ",+" | sfdisk -N "$part" --no-reread "$disk" || true
      resize2fs "$dev" || true
    '';
  };
  services.pipewire = { enable = true; alsa.enable = true; pulse.enable = true; wireplumber.enable = true; };
  security.rtkit.enable = true;

  # ------------------------------------------------------------------ power + 24/7 reliability
  # Memory: 4 GB RAM + a swap file of up to 8 GB on the SD card / SSD (12 GB usable). Idle app memory
  # is moved out of RAM early: first into compressed RAM (zram, fastest), then into the swap file.
  # zram is off on the board kernel (the zram module reload fails there); the swap file still works
  zramSwap.enable = false;
  systemd.services.jstarx-swap = {
    description = "JStarx swap file (up to 8 GB, sized to fit the SD card)";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    path = with pkgs; [ util-linux coreutils ];
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
    script = ''
      f=/var/lib/jstarx-swapfile
      disk=$(df --output=size -B1M / | tail -n 1)
      want=$(( disk / 4 ))                    # a quarter of the card…
      [ "$want" -gt 8192 ] && want=8192       # …and at most 8 GB
      [ "$want" -lt 512 ] && exit 0
      have=0
      [ -f "$f" ] && have=$(( $(stat -c %s "$f") / 1048576 ))
      if [ "$have" -ne "$want" ]; then
        swapoff "$f" 2>/dev/null || true
        free=$(( $(df --output=avail -B1M / | tail -n 1) + have ))
        [ "$free" -gt $(( want + 2048 )) ] || want=$(( free - 2048 ))   # always keep 2 GB free
        [ "$want" -ge 512 ] || exit 0
        truncate -s 0 "$f" 2>/dev/null || true
        fallocate -l "''${want}M" "$f"
        chmod 600 "$f"
        mkswap "$f" > /dev/null
      fi
      swapon -p 10 "$f" 2>/dev/null || true
    '';
  };
  boot.kernel.sysctl = {
    "vm.swappiness" = 200;              # the most the kernel allows: idle memory goes to swap first (0-200)
    "vm.watermark_scale_factor" = 125;  # start freeing memory before it runs out
    "vm.page-cluster" = 0;              # zram works best one page at a time
    "vm.dirty_writeback_centisecs" = 1500;  # write to the SD card in bigger, rarer batches
    "vm.dirty_expire_centisecs" = 3000;
  };
  systemd.extraConfig = "RuntimeWatchdogSec=30s\nRebootWatchdogSec=2min";
  # never stop at a rescue prompt: keep starting, then auto-repair takes over
  systemd.enableEmergencyMode = false;
  services.logind.extraConfig = "HandlePowerKey=poweroff\nIdleAction=ignore";
  services.journald.extraConfig = ''
    SystemMaxUse=100M
    RuntimeMaxUse=32M
  '';

  # ------------------------------------------------------------------ SSH (off until switched on in Settings)
  services.openssh = { enable = true; extraConfig = "PermitRootLogin no"; };
  systemd.services.sshd.wantedBy = lib.mkForce [ ];

  # ------------------------------------------------------------------ Nix (updates + Star Store installs)
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    trusted-users = [ "root" "@wheel" ];
    auto-optimise-store = true;
  };
  nix.registry = lib.mkIf (nixpkgsSrc != null) { nixpkgs.to = { type = "path"; path = nixpkgsSrc; }; };
  nix.nixPath = lib.mkIf (nixpkgsSrc != null) [ "nixpkgs=${nixpkgsSrc}" ];
  nix.gc = { automatic = true; dates = "weekly"; options = "--delete-older-than 30d"; };

  # ------------------------------------------------------------------ JStarx services
  systemd.tmpfiles.rules = [
    "d /run/jstarx 0755 root root -"
    "d /var/lib/jstarx 0755 root root -"
    "d /var/lib/jstarx/flags 0755 root root -"
    "d /var/lib/starai 0750 starai starai -"
    "d /var/lib/starai/jobs 0750 starai starai -"
    "d /var/lib/spark 0755 root root -"
    "d /var/lib/spark/models 0755 root root -"
  ];

  systemd.services.starxd = {
    description = "JStarx system helper";
    wantedBy = [ "multi-user.target" ];
    after = [ "jstarx-repair.service" ];
    path = with pkgs; [ systemd nix coreutils util-linux gnutar gzip zstd shadow ];
    environment.JSTARX_UNIX_CHKPWD = "${pkgs.pam}/bin/unix_chkpwd";
    serviceConfig = { ExecStart = "${core}/bin/starxd"; Restart = "always"; RestartSec = 2; };
  };

  systemd.services.starai = {
    description = "StarAI 24/7 job runner";
    wantedBy = [ "multi-user.target" ];
    path = with pkgs; [ systemd coreutils ];
    environment.STARAI_PYTHON = "${core.python}/bin/python3";
    serviceConfig = { ExecStart = "${core}/bin/starai"; Restart = "always"; RestartSec = 5; };
  };

  systemd.services.spark = {
    description = "Spark 1 assistant engine (llama.cpp)";
    wantedBy = [ "multi-user.target" ];
    path = with pkgs; [ core.python ];
    serviceConfig = {
      ExecStart = "${core}/bin/spark-serve";
      Restart = "on-failure";
      RestartSec = 15;
      Nice = 5;
      CPUQuota = "350%";
      MemoryMax = "80%";
    };
  };

  systemd.services.jstarx-repair = {
    description = "JStarx auto-repair (checks and fixes JStarx files at boot)";
    wantedBy = [ "multi-user.target" ];
    before = [ "display-manager.service" "greetd.service" ];
    path = with pkgs; [ systemd nix coreutils ];
    script = ''
      if grep -q 'jstarx.repair=deep' /proc/cmdline; then
        ${pkgs.plymouth}/bin/plymouth display-message --text="JStarx Recovery: checking every system file…" 2>/dev/null || true
        exec ${core}/bin/jstarx-repair deep
      fi
      exec ${core}/bin/jstarx-repair quick
    '';
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; TimeoutStartSec = "6h"; };
  };

  systemd.services.jstarx-update = {
    description = "JStarx auto-update from GitHub";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = with pkgs; [ systemd coreutils nix gnutar zstd ];
    serviceConfig = { Type = "oneshot"; ExecStart = "${core}/bin/jstarx-update auto"; Nice = 10; TimeoutStartSec = "6h"; };
  };
  systemd.timers.jstarx-update = {
    wantedBy = [ "timers.target" ];
    timerConfig = { OnBootSec = "10min"; OnUnitActiveSec = "6h"; RandomizedDelaySec = "20min"; Persistent = true; };
  };

  systemd.services.jstarx-boot-ok = {
    description = "Mark this JStarx build as working (auto-repair boot counter)";
    wantedBy = [ "multi-user.target" ];
    after = [ "multi-user.target" ];
    serviceConfig = { Type = "oneshot"; ExecStartPre = "${pkgs.coreutils}/bin/sleep 90"; ExecStart = "${core}/bin/jstarx-boot-ok system-running"; };
  };

  systemd.services.jstarx-ssh = {
    description = "Start SSH if it was switched on in Settings";
    wantedBy = [ "multi-user.target" ];
    serviceConfig.Type = "oneshot";
    script = ''[ -e /var/lib/jstarx/flags/ssh ] && ${pkgs.systemd}/bin/systemctl start sshd.service || true'';
  };
}
