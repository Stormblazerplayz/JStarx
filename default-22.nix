# Build JStarx OS (no flakes needed):
#
#   nix-build -A sdImage      the SD card image for the Jetson Nano  -> result/sd-image/*.img
#   nix-build -A kernel       just the StarX Kernel
#
# tools/qemu-test.sh boots the same SD card image in QEMU to test it.
#
# Works on an x86_64 Linux PC (the kernel is cross-compiled, everything else comes from the
# NixOS cache; small JStarx packages build through QEMU, see README) or on an ARM64 machine.
{ nixpkgs ? import ./os-22/nixpkgs.nix
, buildSystem ? builtins.currentSystem
}:

let
  pkgsBuild = import nixpkgs { system = buildSystem; };
  starxKernel =
    if buildSystem == "aarch64-linux"
    then pkgsBuild.callPackage ./os-22/kernel { kernelPatches = [ ]; }
    else pkgsBuild.pkgsCross.aarch64-multiplatform.callPackage ./os-22/kernel { kernelPatches = [ ]; };

  mkSystem = extraModules: import "${nixpkgs}/nixos/lib/eval-config.nix" {
    system = "aarch64-linux";
    specialArgs = { inherit starxKernel; nixpkgsSrc = nixpkgs; };
    modules = [ ./os-22/modules/jstarx.nix ./os-22/modules/image.nix ] ++ extraModules;
  };

  jstarx = mkSystem [ ];
in
{
  inherit jstarx;
  kernel = starxKernel;
  toplevel = jstarx.config.system.build.toplevel;
  sdImage = jstarx.config.system.build.sdImage;
}
