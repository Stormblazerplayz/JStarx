# Only the firmware JStarx needs (Tegra X1 USB + GPU, common Wi-Fi/Bluetooth), not all of linux-firmware.
{ runCommand, linux-firmware, zstd, xz }:
runCommand "jstarx-firmware" { nativeBuildInputs = [ zstd xz ]; } ''
  mkdir -p $out/lib/firmware
  cd ${linux-firmware}/lib/firmware
  for pat in nvidia/tegra210 nvidia/gm20b 'iwlwifi-8265-*' 'iwlwifi-8000C-*' 'iwlwifi-7265D-*' 'iwlwifi-9260-*' \
             rtw88 rtlwifi rtl_bt 'mediatek/mt7601u*' 'mt7601u*' 'mt7610u*' 'mt7662u*' 'intel/ibt-12-16*' 'intel/ibt-11-5*' 'regulatory.db*'; do
    for f in $pat; do
      if [ -e "$f" ]; then cp -rL --parents "$f" $out/lib/firmware/; fi
    done
  done
  find $out/lib/firmware -name '*.zst' -exec zstd -d --rm -q {} \;
  find $out/lib/firmware -name '*.xz' -exec xz -d {} \;
''
