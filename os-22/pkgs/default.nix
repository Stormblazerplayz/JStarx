# JStarx packages, as a nixpkgs overlay.
final: prev: {
  jstarx-runtime = final.callPackage ./runtime.nix { };
  jstarx-core = final.callPackage ./jstarx-core/package.nix { };
  jstarx-layer = final.callPackage ./layer.nix { };
  jstarx-plymouth = final.callPackage ./plymouth.nix { };
  jstarx-theme = final.callPackage ./theme.nix { };
  jstarx-firmware = final.callPackage ./firmware.nix { };
}
