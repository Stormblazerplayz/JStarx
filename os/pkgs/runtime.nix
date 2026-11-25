# Python with GTK 3, WebKitGTK and gtk-layer-shell: runs StarShell and the JStarx apps.
{ stdenv, python3, wrapGAppsHook3, gobject-introspection, makeWrapper, gtk3, webkitgtk_4_1, gtk-layer-shell,
  glib-networking, librsvg, gdk-pixbuf, gsettings-desktop-schemas }:
let
  py = python3.withPackages (ps: with ps; [ pygobject3 pycairo pychromecast zeroconf ]);
in
stdenv.mkDerivation {
  pname = "starx-runtime";
  version = "2.0.0";
  dontUnpack = true;
  nativeBuildInputs = [ wrapGAppsHook3 gobject-introspection makeWrapper ];
  buildInputs = [ gtk3 webkitgtk_4_1 gtk-layer-shell glib-networking librsvg gdk-pixbuf gsettings-desktop-schemas ];
  installPhase = ''
    mkdir -p $out/bin
    makeWrapper ${py}/bin/python3 $out/bin/starx-python
  '';
  meta.description = "Python runtime for StarShell (GTK + WebKitGTK + layer-shell)";
}
