#!/usr/bin/env bash
# Installs the JStarx core services on an NVIDIA Jetson Nano running JetPack 4.6.1
# (Ubuntu 18.04, L4T R32.7.1). On the Jetson, run:
#   sudo ./install.sh
# To test without touching the system (writes only inside DIR, starts nothing):
#   ./install.sh --root DIR
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ROOT=""

fail() { echo "install.sh: $*" >&2; exit 1; }
warn() { echo "install.sh: warning: $*" >&2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      [ $# -ge 2 ] || fail "--root needs a folder"
      ROOT="${2%/}"
      shift 2 ;;
    -h|--help)
      echo "usage: sudo ./install.sh     or     ./install.sh --root DIR"
      exit 0 ;;
    *)
      fail "unknown option: $1" ;;
  esac
done

# 1. Check that this is the right system
RELEASE="$ROOT/etc/nv_tegra_release"
OSREL="$ROOT/etc/os-release"
[ -f "$RELEASE" ] || fail "this is not a JetPack system (no $RELEASE). Install JetPack 4.6.1 first."
grep -q '^# R32 ' "$RELEASE" || fail "this is not JetPack 4.x (L4T R32): $(head -n 1 "$RELEASE")"
grep -q 'REVISION: 7\.1,' "$RELEASE" || warn "tested on JetPack 4.6.1 (L4T R32.7.1), this system says: $(head -n 1 "$RELEASE")"
grep -q 'BOARD: t210' "$RELEASE" || warn "this does not look like a Jetson Nano (T210)"
grep -q 'VERSION_ID="18.04"' "$OSREL" 2>/dev/null || fail "this needs Ubuntu 18.04 (JetPack 4.6.1)"
if [ -z "$ROOT" ]; then
  [ "$(id -u)" -eq 0 ] || fail "run it with sudo: sudo ./install.sh"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' || fail "Python 3.6 or newer is needed"
fi

# 2. Copy the files into place
OPT="$ROOT/opt/jstarx"
VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$REPO/layer/layer.json" | head -n 1)"
echo "Installing JStarx core $VERSION into ${ROOT:-/} ..."
rm -rf "${OPT:?}/lib"
mkdir -p "$OPT/lib" "$OPT/bin"
cp -a "$REPO/os/pkgs/jstarx-core/jstarx_core" "$OPT/lib/"
find "$OPT/lib" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "$VERSION" > "$OPT/VERSION"
install -m 0755 "$HERE/files/jstarx-swapfile" "$HERE/files/jstarx-zram" "$OPT/bin/"
install -d "$ROOT/etc/systemd/system" "$ROOT/etc/sysctl.d" "$ROOT/etc/tmpfiles.d"
install -m 0644 "$HERE/files/jstarx-starxd.service" "$HERE/files/jstarx-swap.service" "$HERE/files/jstarx-zram.service" "$ROOT/etc/systemd/system/"
install -m 0644 "$HERE/files/90-jstarx.conf" "$ROOT/etc/sysctl.d/90-jstarx.conf"
install -m 0644 "$HERE/files/jstarx.tmpfiles.conf" "$ROOT/etc/tmpfiles.d/jstarx.conf"

# 3. Start everything (only on a real Jetson)
if [ -z "$ROOT" ]; then
  getent group jstarx >/dev/null || groupadd --system jstarx
  systemd-tmpfiles --create /etc/tmpfiles.d/jstarx.conf
  sysctl -q -p /etc/sysctl.d/90-jstarx.conf || warn "the memory settings take effect at the next start"
  systemctl daemon-reload
  systemctl enable --now jstarx-starxd.service || warn "the helper did not start: see journalctl -u jstarx-starxd"
  systemctl enable --now jstarx-swap.service || warn "no swap file: see journalctl -u jstarx-swap"
  systemctl enable --now jstarx-zram.service || warn "no zram: see journalctl -u jstarx-zram"
  echo "JStarx core $VERSION is installed. Check it with: systemctl status jstarx-starxd"
else
  echo "Test install of JStarx core $VERSION finished in $ROOT. No services were started."
fi
