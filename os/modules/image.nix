# The JStarx SD card image for the Jetson Nano.
# The partition table lists the JStarx system first (partition 1, ext4, label JSTARX, with
# /boot/extlinux/extlinux.conf for U-Boot). The Jetson's own start-up reads its system from partition 1.
# Partition 2: a tiny FAT partition with a README (label JSTARX-INFO), so the card shows up on any PC.
# It sits in front of the system on the disk, but the table lists the system first.
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
        "The system lives on the first partition (label JSTARX)." \
        "Help: https://github.com/Stormblazerplayz/JStarx" > firmware/README.txt
    '';
    populateRootCommands = ''
      mkdir -p ./files/boot
      ${config.system.build.jstarxBootBuilder} -g 0 -t 2 -c ${config.system.build.toplevel} -d ./files/boot
      # The Jetson's own start-up runs /sbin/init from this partition and needs these folders to exist
      mkdir -p ./files/sbin ./files/etc ./files/proc ./files/sys ./files/dev ./files/run
      ln -s ${config.system.build.toplevel}/init ./files/sbin/init
    '';
    # The Jetson reads the system from the FIRST partition (root=/dev/mmcblk1p1). The partition table
    # lists the info partition first, so swap the two table entries (16 bytes each, at bytes 446 and 462).
    # The data does not move. The checks stop the build if the layout is not the one expected here.
    postBuildCommands = ''
      test "$(od -An -tu1 -j 450 -N1 $img | tr -d ' ')" = 11
      test "$(od -An -tu4 -j 454 -N4 $img | tr -d ' ')" = 16384
      test "$(od -An -tu1 -j 466 -N1 $img | tr -d ' ')" = 131
      test "$(od -An -tu4 -j 470 -N4 $img | tr -d ' ')" = 49152
      dd if=$img of=entry1.bin bs=1 skip=446 count=16 status=none
      dd if=$img of=entry2.bin bs=1 skip=462 count=16 status=none
      dd if=entry2.bin of=$img bs=1 seek=446 conv=notrunc status=none
      dd if=entry1.bin of=$img bs=1 seek=462 conv=notrunc status=none
      test "$(od -An -tu1 -j 450 -N1 $img | tr -d ' ')" = 131
      test "$(od -An -tu1 -j 466 -N1 $img | tr -d ' ')" = 11
    '';
  };
}
