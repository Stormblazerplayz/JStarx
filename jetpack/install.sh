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

# 2b. The desktop: StarShell on the openbox window manager (the "JStarx" session at the login screen)
FACTORY="$ROOT/etc/jstarx/factory-layer"
rm -rf "${FACTORY:?}"
mkdir -p "$(dirname "$FACTORY")"
cp -a "$REPO/layer" "$FACTORY"
find "$FACTORY" -name __pycache__ -type d -prune -exec rm -rf {} +
install -m 0755 "$HERE/files/starx-session-x11" "$OPT/bin/starx-session-x11"
install -m 0755 "$REPO/os/pkgs/jstarx-core/bin/starx-shell-supervisor" "$OPT/bin/starx-shell-supervisor"
install -d "$OPT/config/openbox" "$ROOT/usr/share/xsessions"
install -m 0644 "$HERE/files/openbox/rc.xml" "$OPT/config/openbox/rc.xml"
install -m 0644 "$HERE/files/jstarx.desktop" "$ROOT/usr/share/xsessions/jstarx.desktop"
install -d "$ROOT/usr/share/themes/JStarx/gtk-3.0"
install -m 0644 "$REPO/os/config/gtk.css" "$ROOT/usr/share/themes/JStarx/gtk-3.0/gtk.css"

# 3. Start everything (only on a real Jetson)
if [ -z "$ROOT" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update || warn "could not update the package list (are you online?)"
  apt-get install -y openbox xcompmgr wmctrl xdotool x11-utils x11-xserver-utils scrot xterm \
    python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0 pulseaudio-utils \
    || warn "some desktop packages could not be installed (are you online?): run this script again"
  apt-get install -y firefox || warn "Firefox could not be installed; the Firefox icon will not start"
  getent group jstarx >/dev/null || groupadd --system jstarx
  # the desktop talks to the helper through its socket: the user who runs this must be in the group
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
    usermod -aG jstarx "$SUDO_USER" || warn "could not add $SUDO_USER to the jstarx group"
    echo "Added $SUDO_USER to the jstarx group: log out and back in once."
  fi
  systemd-tmpfiles --create /etc/tmpfiles.d/jstarx.conf
  sysctl -q -p /etc/sysctl.d/90-jstarx.conf || warn "the memory settings take effect at the next start"
  systemctl daemon-reload
  systemctl enable --now jstarx-starxd.service || warn "the helper did not start: see journalctl -u jstarx-starxd"
  systemctl enable --now jstarx-swap.service || warn "no swap file: see journalctl -u jstarx-swap"
  systemctl enable --now jstarx-zram.service || warn "no zram: see journalctl -u jstarx-zram"
  echo "JStarx core $VERSION is installed. Check it with: systemctl status jstarx-starxd"
  echo "For the desktop, log out and choose the JStarx session at the login screen."
else
  echo "Test install of JStarx core $VERSION finished in $ROOT. No services were started."
fi
