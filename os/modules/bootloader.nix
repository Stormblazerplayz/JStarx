# JStarx boot: U-Boot reads /boot/extlinux/extlinux.conf (Jetson Nano QSPI U-Boot and QEMU).
# Auto-repair at the system level: the initrd counts boot tries. If the selected build has
# not reached a working system after 2 tries, the 3rd start switches the boot menu back to the
# last build that worked (/boot/jstarx/known-good) and reboots into it.
# The counter is reset by jstarx-boot-ok (jstarx_core/boot.py: mark_ok) once the system is up.
{ config, lib, pkgs, ... }:

let
  mkBuilder = p: p.replaceVarsWith {
    src = ./jstarx-extlinux.sh;
    isExecutable = true;
    replacements = {
      path = lib.makeBinPath [ p.coreutils p.gnused p.gnugrep ];
      inherit (p) bash;
    };
  };
  builder = mkBuilder pkgs;
in
{
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = false;
  system.boot.loader.id = "jstarx-extlinux";
  system.build.installBootLoader = pkgs.writeScript "install-jstarx-boot.sh" ''
    #!${pkgs.runtimeShell}
    set -e
    ${builder} -g 10 -t 2 -d /boot -c "$@"
  '';
  # the same builder, runnable on the build machine (used to make the SD card image)
  system.build.jstarxBootBuilder = mkBuilder pkgs.buildPackages;

  boot.initrd.systemd.services.jstarx-bootcount = {
    description = "JStarx auto-repair: count boot tries";
    unitConfig = {
      RequiresMountsFor = "/sysroot/boot";
      DefaultDependencies = false;
    };
    before = [ "initrd.target" "shutdown.target" ];
    conflicts = [ "shutdown.target" ];
    wantedBy = [ "initrd.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      J=/sysroot/boot/jstarx
      conf=/sysroot/boot/extlinux/extlinux.conf
      mkdir -p "$J"
      gen=
      for o in $(< /proc/cmdline); do
        case "$o" in
          jstarx.gen=*) gen="''${o#jstarx.gen=}" ;;
        esac
      done
      tries="$(cat "$J/tries" 2>/dev/null | tr -cd 0-9)"
      [ -n "$tries" ] || tries=0
      tries=$((tries + 1))
      echo "$tries" > "$J/tries"
      good="$(cat "$J/known-good" 2>/dev/null | tr -cd 0-9)"
      echo "JStarx: starting build ''${gen:-?} (try $tries, last working build: ''${good:-none})"
      if [ -n "$gen" ] && [ -n "$good" ] && [ "$gen" != "$good" ] && [ "$tries" -ge 3 ] && [ -f "$conf" ]; then
        echo "JStarx auto-repair: build $gen did not start $((tries - 1)) times, going back to build $good"
        if command -v plymouth >/dev/null; then
          plymouth display-message --text="Auto-repair: going back to build $good" || true
        fi
        while IFS= read -r line || [ -n "$line" ]; do
          case "$line" in
            "DEFAULT "*) echo "DEFAULT jstarx-$good" ;;
            *) printf '%s\n' "$line" ;;
          esac
        done < "$conf" > "$conf.tmp"
        mv -f "$conf.tmp" "$conf"
        echo 0 > "$J/tries"
        echo "$(date +%s) build $gen did not start $((tries - 1)) times, went back to build $good" >> "$J/repair.log"
        sync
        sleep 3
        systemctl --force reboot
      fi
    '';
  };
}
