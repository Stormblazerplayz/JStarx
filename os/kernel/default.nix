# StarX Kernel: Linux 6.12 LTS with the JStarx configuration and boot logo.
# Built with a cross compiler (x86_64 -> aarch64) so it compiles fast on a PC.
# NixOS calls kernel.override { features, randstructSeed, kernelPatches }, so those are passed on.
{ lib, linuxManualConfig, linux_6_12, features ? { }, randstructSeed ? "", kernelPatches ? [ ] }:

let
  base = linux_6_12;
  kernel = linuxManualConfig {
    inherit (base) src version;
    inherit features randstructSeed kernelPatches;
    modDirVersion = "${base.version}-starx";
    configfile = ./starx.config;
    extraMeta = {
      description = "StarX Kernel for JStarx OS (Linux ${base.version} LTS)";
      platforms = [ "aarch64-linux" ];
    };
  };
in
kernel.overrideAttrs (old: {
  pname = "starx-kernel";
  # The JStarx logo replaces the penguin that Linux shows while booting.
  postPatch = (old.postPatch or "") + ''
    cp ${./logo_starx_clut224.ppm} drivers/video/logo/logo_linux_clut224.ppm
  '';
  buildFlags = map (f: if lib.hasPrefix "KBUILD_BUILD_VERSION=" f then "KBUILD_BUILD_VERSION=1-StarX" else f) old.buildFlags;
  # U-Boot on the Jetson Nano looks for the device tree at the top of FDTDIR,
  # while Linux installs it under nvidia/. Keep a copy in both places.
  postInstall = (old.postInstall or "") + ''
    if [ -d "$out/dtbs/nvidia" ]; then
      cp "$out/dtbs/nvidia/tegra210-p3450-0000.dtb" "$out/dtbs/" || true
    fi
  '';
})
