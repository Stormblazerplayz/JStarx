# JStarx GTK theme (used by Firefox and GTK apps) and labwc window theme.
{ runCommand }:
runCommand "jstarx-theme" { } ''
  mkdir -p $out/share/themes/JStarx/gtk-3.0 $out/share/themes/JStarx/labwc
  cp ${../config/gtk.css} $out/share/themes/JStarx/gtk-3.0/gtk.css
  cp ${../config/themerc} $out/share/themes/JStarx/labwc/themerc
''
