#!/usr/bin/env bash
# Run StarShell on a headless Wayland screen (labwc) and screenshot every panel.
# Usage: tools/test-shell.sh OUTDIR [WIDTHxHEIGHT]
# Needs: labwc, grim, wlr-randr, dbus, python3 with PyGObject + WebKit2GTK 4.1 + gtk-layer-shell.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-/tmp/starx-test}"
RES="${2:-1920x1080}"
mkdir -p "$OUT"
export XDG_RUNTIME_DIR="$(mktemp -d)"; chmod 700 "$XDG_RUNTIME_DIR"
export HOME="${TEST_HOME:-$(mktemp -d)}"
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1 WLR_LIBINPUT_NO_DEVICES=1
export JSTARX_LAYER="$ROOT/layer" STARX_APP_BIN="$ROOT/layer/bin/starx-app" STARX_TEST=1
export STARX_NO_WELCOME="${STARX_NO_WELCOME:-1}" STARX_CONSOLE=1
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export JSTARX_RUN="${JSTARX_RUN:-$XDG_RUNTIME_DIR/system}" JSTARX_STATE="${JSTARX_STATE:-$XDG_RUNTIME_DIR/state}"
mkdir -p "$JSTARX_RUN"
export PATH="$ROOT/layer/bin:$PATH"
[ -n "${LABWC_CONFIG:-}" ] && LABWC_ARGS="-C $LABWC_CONFIG" || LABWC_ARGS=""

snap() { sleep "${2:-3}"; grim "$OUT/$1.png" && echo "shot $1"; }
ctl() { starx-ctl "$@" >/dev/null 2>&1; }

run() {
  labwc $LABWC_ARGS > "$OUT/labwc.log" 2>&1 &
  for _ in $(seq 1 40); do sleep 0.25; W=$(ls "$XDG_RUNTIME_DIR" | grep -E '^wayland-[0-9]+$' | head -1); [ -n "$W" ] && break; done
  export WAYLAND_DISPLAY="$W"
  wlr-randr --output HEADLESS-1 --custom-mode "$RES" >/dev/null 2>&1
  starx-shell > "$OUT/shell.log" 2>&1 &
  for _ in $(seq 1 120); do sleep 0.5; starx-ctl health 2>/dev/null | grep -q '"healthy": true' && break; done
  echo "health: $(starx-ctl health 2>&1)"
  snap 01-desktop 4
  ctl launchpad;  snap 02-launchpad 4; ctl close; sleep 1.5
  ctl start;      snap 03-start 3;     ctl close; sleep 1.5
  ctl control;    snap 04-control 4;   ctl close; sleep 1.5
  ctl notify '{"summary":"Training finished","body":"tiny-gpt reached epoch 50 with loss 1.21","app":"AI Center","icon":"chip"}'
  snap 05-notification 1.5; sleep 6
  ctl osd volume; snap 06-osd 1.2; sleep 2
  ctl spark;      snap 07-spark 3;     ctl close; sleep 1.5
  ctl power;      snap 08-power 2.5;   ctl close; sleep 1.5
  ctl welcome;    snap 09-welcome 3;   ctl close; sleep 1.5
  ctl js desktop "document.querySelector('[data-folder=games]').click()"; snap 10-folder 3
  ctl js desktop "document.querySelector('.fcenter').click()"; sleep 1.5
  ${EXTRA_STEPS:-true}
  kill %2 2>/dev/null; sleep 0.5; kill %1 2>/dev/null; sleep 0.5
}
export OUT RES LABWC_ARGS
export -f snap ctl run
DBUS_CONF="$(dirname "$(dirname "$(readlink -f "$(command -v dbus-daemon)")")")/share/dbus-1/session.conf"
[ -f "$DBUS_CONF" ] && dbus-run-session --config-file="$DBUS_CONF" -- bash -c run || dbus-run-session -- bash -c run
