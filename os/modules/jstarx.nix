# JStarx OS: the whole system, stacked on the StarX Kernel.
{ config, lib, pkgs, starxKernel, nixpkgsSrc ? null, ... }:

let
  J = pkgs;
  core = J.jstarx-core;
  layer = J.jstarx-layer;
  runtime = J.jstarx-runtime;
  version = (lib.importJSON ../../layer/layer.json).version;
  codename = (lib.importJSON ../../layer/layer.json).codename;
  greetdToml = pkgs.writeShellScript "jstarx-greetd-config" ''
    # Autologin is on unless the user switched it off in Settings.
    mkdir -p /run/jstarx
    {
      echo '[terminal]'
      echo 'vt = 1'
      echo '[default_session]'
      echo 'command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --asterisks --greeting \"Welcome to JStarx\" --cmd ${core}/bin/starx-session"'
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
  nixpkgs.hostPlatform = "aarch64-linux";
  nixpkgs.config.allowUnfree = true;
  system.stateVersion = "26.05";

  # ------------------------------------------------------------------ branding
  system.nixos.distroName = "JStarx OS";
  system.nixos.distroId = "jstarx";
  system.nixos.vendorName = "JStarx";
  system.nixos.vendorId = "jstarx";
  system.nixos.extraOSReleaseArgs = {
    PRETTY_NAME = "JStarx OS ${version} (${codename})";
    VERSION = "${version} (${codename})";
    VERSION_ID = version;
    HOME_URL = "https://github.com/Stormblazerplayz/JStarx";
    LOGO = "jstarx";
  };
  networking.hostName = "jstarx";
  system.nixos.label = "jstarx-${version}";

  # ------------------------------------------------------------------ StarX Kernel + hardware
  boot.kernelPackages = pkgs.linuxPackagesFor starxKernel;
  boot.initrd.includeDefaultModules = false;
  boot.initrd.availableKernelModules = [ ];   # everything needed to start is built into the kernel
  # if anything freezes while starting, the watchdog restarts the Jetson (and auto-repair counts it)
  boot.initrd.systemd.settings.Manager.RuntimeWatchdogSec = "60s";
  boot.initrd.systemd.tpm2.enable = false;   # no TPM chip on the Jetson Nano
  systemd.tpm2.enable = false;
  boot.kernelParams = [
    "console=ttyS0,115200n8" "console=ttyAMA0,115200" "console=tty1"
    "quiet" "splash" "loglevel=3" "udev.log_level=3" "vt.global_cursor_default=0"
    "fbcon=logo-pos:center" "fbcon=logo-count:1" "panic=10" "boot.panic_on_fail"
    # show the boot screen on the display even though serial consoles are listed above
    "plymouth.ignore-serial-consoles"
  ];
  hardware.firmware = [ J.jstarx-firmware ];
  hardware.enableRedistributableFirmware = false;   # we ship only what the Jetson needs
  hardware.firmwareCompression = "none";            # the StarX Kernel loads plain firmware files
  hardware.graphics.enable = true;
  hardware.bluetooth.enable = true;
  hardware.deviceTree.enable = true;
  boot.consoleLogLevel = 3;

  # ------------------------------------------------------------------ boot screen
  boot.plymouth = {
    enable = true;
    theme = "jstarx";
    themePackages = [ J.jstarx-plymouth ];
    font = "${pkgs.inter}/share/fonts/truetype/InterVariable.ttf";
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
  programs.labwc.enable = true;
  services.greetd = {
    enable = true;
    settings.default_session = { command = "${core}/bin/starx-session"; user = "storm"; };
  };
  systemd.services.greetd = {
    after = [ "starxd.service" "jstarx-repair.service" "systemd-user-sessions.service" ];
    serviceConfig.ExecStartPre = [ "${greetdToml}" ];
    serviceConfig.ExecStart = lib.mkForce "${pkgs.greetd}/bin/greetd --config /run/jstarx/greetd.toml";
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
    config.common.default = [ "wlr" "gtk" ];
  };
  fonts.packages = with pkgs; [ inter jetbrains-mono noto-fonts-color-emoji dejavu_fonts ];
  fonts.fontconfig.defaultFonts = { sansSerif = [ "Inter" "DejaVu Sans" ]; monospace = [ "JetBrains Mono" ]; emoji = [ "Noto Color Emoji" ]; };

  environment.systemPackages = with pkgs; [
    core runtime J.jstarx-theme
    labwc swayidle wlopm wlrctl wlr-randr grim foot wf-recorder ffmpeg-headless
    gnome-network-displays networkmanager wireplumber libnotify xdg-utils
    llama-cpp git curl htop
  ];
  environment.sessionVariables = {
    JSTARX_RUN = "/run/jstarx";
    STARX_GPU = "never";
  };

  # ------------------------------------------------------------------ Firefox (Claude also runs in it)
  programs.firefox = {
    enable = true;
    policies = {
      DisableTelemetry = true;
      DisableFirefoxStudies = true;
      DisablePocket = true;
      DontCheckDefaultBrowser = true;
      OverrideFirstRunPage = "";
      OverridePostUpdatePage = "";
      UserMessaging = { WhatsNew = false; ExtensionRecommendations = false; FeatureRecommendations = false; SkipOnboarding = true; };
      Homepage = { URL = "about:home"; StartPage = "homepage"; };
    };
    preferences = {
      "widget.use-xdg-desktop-portal.file-picker" = 1;
      "ui.systemUsesDarkTheme" = 1;
      "browser.theme.toolbar-theme" = 0;
      "browser.tabs.inTitlebar" = 1;   # Firefox draws its own top bar, which curves around the island
      "toolkit.legacyUserProfileCustomizations.stylesheets" = true;   # use the JStarx userChrome.css
      "media.ffmpeg.vaapi.enabled" = false;
    };
  };

  # ------------------------------------------------------------------ no bloat
  documentation.nixos.enable = false;
  documentation.doc.enable = false;
  documentation.info.enable = false;
  programs.command-not-found.enable = false;
  environment.defaultPackages = [ ];
  services.speechd.enable = false;
  networking.modemmanager.enable = false;

  # ------------------------------------------------------------------ network, sound, casting
  networking.networkmanager.enable = true;
  services.avahi = { enable = true; nssmdns4 = true; publish = { enable = true; addresses = true; workstation = true; }; };
  networking.firewall = {
    enable = true;
    allowedTCPPorts = [ 7236 7250 8765 8091 ];   # Miracast, StarCast stream, AI model server
    allowedUDPPorts = [ 5353 7236 ];
  };
  services.pipewire = { enable = true; alsa.enable = true; pulse.enable = true; wireplumber.enable = true; };
  security.rtkit.enable = true;

  # ------------------------------------------------------------------ power + 24/7 reliability
  # Memory: 4 GB RAM + a swap file of up to 8 GB on the SD card / SSD (12 GB usable). Idle app memory
  # is moved out of RAM early: first into compressed RAM (zram, fastest), then into the swap file.
  zramSwap = { enable = true; memoryPercent = 50; algorithm = "zstd"; priority = 100; };
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
    "vm.swappiness" = 150;              # swap idle app memory out aggressively (0-200)
    "vm.watermark_scale_factor" = 125;  # start freeing memory before it runs out
    "vm.page-cluster" = 0;              # zram works best one page at a time
  };
  systemd.settings.Manager = { RuntimeWatchdogSec = "30s"; RebootWatchdogSec = "2min"; };
  # never stop at a rescue prompt: keep starting, then auto-repair takes over
  systemd.enableEmergencyMode = false;
  services.logind.settings.Login = { HandlePowerKey = "poweroff"; IdleAction = "ignore"; };
  services.journald.extraConfig = "SystemMaxUse=200M";

  # ------------------------------------------------------------------ SSH (off until switched on in Settings)
  services.openssh = { enable = true; settings.PermitRootLogin = "no"; };
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
    path = with pkgs; [ systemd nix coreutils util-linux gnutar gzip zstd shadow llama-cpp ];
    environment.JSTARX_UNIX_CHKPWD = "${pkgs.pam}/bin/unix_chkpwd";
    serviceConfig = { ExecStart = "${core}/bin/starxd"; Restart = "always"; RestartSec = 2; };
  };

  systemd.services.starai = {
    description = "StarAI 24/7 job runner";
    wantedBy = [ "multi-user.target" ];
    path = with pkgs; [ systemd coreutils llama-cpp ];
    environment.STARAI_PYTHON = "${core.python}/bin/python3";
    serviceConfig = { ExecStart = "${core}/bin/starai"; Restart = "always"; RestartSec = 5; };
  };

  systemd.services.spark = {
    description = "Spark 1 assistant engine (llama.cpp)";
    wantedBy = [ "multi-user.target" ];
    path = with pkgs; [ llama-cpp core.python ];
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
