# The JStarx SD card image for the Jetson Nano.
# Partition 1: a tiny FAT partition (not used by the Jetson, kept so the card shows up on any PC).
# Partition 2: the JStarx system (ext4, label JSTARX) with /boot/extlinux/extlinux.conf for U-Boot.
# The system grows to fill the whole SD card on the first start.
{ config, lib, pkgs, modulesPath, ... }:

let
  version = (lib.importJSON ../../layer/layer.json).version;
in
{
  imports = [ "${modulesPath}/installer/sd-card/sd-image.nix" ];

  # The SD image module turns on drivers for every computer. The StarX Kernel only has what the
  # Jetson Nano (and the QEMU test machine) need, so keep that off.
  hardware.enableAllHardware = lib.mkForce false;

  image.baseName = lib.mkDefault "jstarx-${version}-jetson-nano";

  sdImage = {
    rootVolumeLabel = "JSTARX";
    firmwarePartitionName = "JSTARX-INFO";
    firmwareSize = 16;
    compressImage = lib.mkDefault false;
    populateFirmwareCommands = ''
      printf '%s\n' \
        "JStarx OS ${version}" \
        "This small partition is not used to start JStarx." \
        "The system lives on the second partition (label JSTARX)." \
        "Help: https://github.com/Stormblazerplayz/JStarx" > firmware/README.txt
    '';
    populateRootCommands = ''
      mkdir -p ./files/boot
      ${config.system.build.jstarxBootBuilder} -g 0 -t 2 -c ${config.system.build.toplevel} -d ./files/boot
    '';
  };
}
