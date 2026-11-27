#! @bash@/bin/sh -e
# JStarx boot menu builder (extlinux.conf for U-Boot, used by the Jetson Nano and QEMU).
# Based on NixOS's generic-extlinux builder, with:
#   * "JStarx (build N)" entries and DEFAULT set to the newest build
#   * jstarx.gen=N on every kernel command line (auto-repair uses it to count failed boots)
#   * a "JStarx Recovery" entry that boots the last build that worked and runs deep repair
shopt -s nullglob
export PATH=/empty:@path@

timeout=20; default=; target=/boot; numGenerations=0
while getopts "t:c:d:g:" opt; do
    case "$opt" in
        t) timeout=$((OPTARG * 10)) ;;
        c) default="$OPTARG" ;;
        d) target="$OPTARG" ;;
        g) numGenerations="$OPTARG" ;;
        \?) echo "usage: $0 -t <sec> -c <config> [-d <boot>] [-g <n>]" >&2; exit 1 ;;
    esac
done
[ -n "$default" ] || { echo "missing -c" >&2; exit 1; }

mkdir -p "$target/nixos" "$target/extlinux" "$target/jstarx"

cleanName() { echo "$1" | sed 's|^/nix/store/||' | sed 's|/|-|g'; }
declare -A filesCopied
copyToKernelsDir() {
    local src dst
    src=$(readlink -f "$1"); dst="$target/nixos/$(cleanName "$src")"
    if ! test -e "$dst"; then cp -r "$src" "$dst.tmp.$$"; mv "$dst.tmp.$$" "$dst"; fi
    filesCopied[$dst]=1
    result=$dst
}

# Which generation number is the configuration we are installing?
genOf() {
    local want link
    want=$(readlink -f "$1")
    for link in /nix/var/nix/profiles/system-*-link; do
        if [ "$(readlink -f "$link")" = "$want" ]; then
            echo "$link" | sed 's|.*/system-\([0-9]*\)-link|\1|'; return
        fi
    done
    echo ""
}
defaultGen=$(genOf "$default")
[ -n "$defaultGen" ] || defaultGen=1   # building an SD card image: this will be build 1

addEntry() {
    local path tag label extra
    path=$(readlink -f "$1"); tag="$2"; label="$3"; extra="$4"
    test -e "$path/kernel" -a -e "$path/initrd" || return 0
    copyToKernelsDir "$path/kernel"; kernel=$result
    copyToKernelsDir "$path/initrd"; initrd=$result
    dtbDir=$(readlink -m "$path/dtbs")
    [ -e "$dtbDir" ] && { copyToKernelsDir "$dtbDir"; dtbs=$result; }
    timestamp=$(date "+%Y-%m-%d %H:%M" -d @"$(stat -L -c '%Z' "$path")")
    echo
    echo "LABEL $tag"
    echo "  MENU LABEL $label ($timestamp)"
    echo "  LINUX ../nixos/$(basename "$kernel")"
    echo "  INITRD ../nixos/$(basename "$initrd")"
    echo "  APPEND init=$path/init $(cat "$path/kernel-params") $extra"
    [ -d "$dtbDir" ] && echo "  FDTDIR ../nixos/$(basename "$dtbs")"
    return 0
}

tmpFile="$target/extlinux/extlinux.conf.tmp.$$"
{
    echo "# JStarx OS boot menu (generated; auto-repair may change DEFAULT)"
    echo "DEFAULT jstarx-$defaultGen"
    echo "TIMEOUT $timeout"
    echo "MENU TITLE JStarx OS"
    addEntry "$default" "jstarx-$defaultGen" "JStarx (build $defaultGen)" "jstarx.gen=$defaultGen"
    if [ "$numGenerations" -gt 0 ]; then
        for generation in $( (cd /nix/var/nix/profiles 2>/dev/null && ls -d system-*-link) | sed 's/system-\([0-9]\+\)-link/\1/' | sort -n -r | head -n "$numGenerations"); do
            [ "$generation" = "$defaultGen" ] && continue
            addEntry "/nix/var/nix/profiles/system-$generation-link" "jstarx-$generation" "JStarx (build $generation)" "jstarx.gen=$generation"
        done
    fi
    # Recovery: the last build that started fine, plus a deep repair
    good=$(cat "$target/jstarx/known-good" 2>/dev/null || true)
    goodPath="$default"; goodGen=$defaultGen
    if [ -n "$good" ] && [ -e "/nix/var/nix/profiles/system-$good-link" ]; then
        goodPath="/nix/var/nix/profiles/system-$good-link"; goodGen=$good
    fi
    addEntry "$goodPath" "jstarx-recovery" "JStarx Recovery: repair this Jetson" "jstarx.gen=$goodGen jstarx.repair=deep"
} > "$tmpFile"
mv -f "$tmpFile" "$target/extlinux/extlinux.conf"
# a fresh install gets a fresh try counter
echo 0 > "$target/jstarx/tries"

for fn in "$target"/nixos/*; do
    if ! test "${filesCopied[$fn]}" = 1; then
        chmod +w -- "$fn"; rm -rf -- "$fn"
    fi
done
