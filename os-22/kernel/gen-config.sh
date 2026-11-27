#!/usr/bin/env bash
# Generate os/kernel/starx.config (the full StarX Kernel .config).
# Run inside the cross build environment, e.g.:
#   nix-shell '<nixpkgs>' -A pkgsCross.aarch64-multiplatform.linux_6_12 --run 'bash os/kernel/gen-config.sh /path/to/linux-6.12.x.tar.xz'
set -euo pipefail

SRC_TARBALL="$1"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

tar -xf "$SRC_TARBALL" -C "$WORK"
cd "$WORK"/linux-*

MAKE=(make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- -s)
"${MAKE[@]}" defconfig

# Turn off every SoC family except Tegra (Jetson Nano). QEMU virt needs none.
mapfile -t platforms < <(grep -oE '^config ARCH_[A-Z0-9_]+' arch/arm64/Kconfig.platforms | awk '{print $2}')
for p in "${platforms[@]}"; do
  case "$p" in
    ARCH_TEGRA|ARCH_TEGRA_210_SOC) ;;
    *) scripts/config --disable "$p" ;;
  esac
done
for soc in ARCH_TEGRA_132_SOC ARCH_TEGRA_186_SOC ARCH_TEGRA_194_SOC ARCH_TEGRA_234_SOC ARCH_TEGRA_241_SOC; do
  scripts/config --disable "$soc"
done

scripts/kconfig/merge_config.sh -m .config "$HERE/starx.fragment" >/dev/null
"${MAKE[@]}" olddefconfig

# Report fragment options that did not survive (missing dependencies).
missing=0
while IFS= read -r line; do
  case "$line" in
    CONFIG_*=*)
      key="${line%%=*}"
      if ! grep -qxF "$line" .config; then
        echo "note: $line -> $(grep -E "^(# )?$key[= ]" .config || echo 'not available')"
        missing=$((missing + 1))
      fi ;;
  esac
done < "$HERE/starx.fragment"
echo "fragment options not applied as written: $missing"

cp .config "$HERE/starx.config"
echo "kernel release: $("${MAKE[@]}" kernelrelease)"
echo "modules: $(grep -c '=m$' .config)  built-in: $(grep -c '=y$' .config)"
