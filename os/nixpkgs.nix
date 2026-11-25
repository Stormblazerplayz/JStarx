# The exact NixOS 26.05 package set JStarx is built from (pinned so every build is the same).
builtins.fetchTarball {
  name = "nixpkgs-26.05-0dc498bfe49b";
  url = "https://releases.nixos.org/nixos/26.05/nixos-26.05.15079.0dc498bfe49b/nixexprs.tar.xz";
  sha256 = "11bidflcplzwprk6wzpgg1ypx3qsb990l8mybcrmg1ggypmmjf25";
}
