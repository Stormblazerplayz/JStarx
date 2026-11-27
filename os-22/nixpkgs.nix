# NixOS 22.05 package set for the JStarx variant that runs on the Jetson's built-in NVIDIA 4.9 kernel
# (systemd 250 supports that kernel; systemd 260 in NixOS 26.05 needs Linux 5.10 or newer).
builtins.fetchTarball {
  name = "nixpkgs-22.05-380be19fbd2d";
  url = "https://releases.nixos.org/nixos/22.05/nixos-22.05.4694.380be19fbd2d/nixexprs.tar.xz";
  sha256 = "1nsy2zrg38f292ipng160k5m2grigc3a9rjqyz8pdiqkzdd1i2w2";
}
