# The JStarx boot screen.
{ runCommand }:
runCommand "jstarx-plymouth" { } ''
  d=$out/share/plymouth/themes/jstarx
  mkdir -p $d
  cp ${../plymouth/jstarx}/* $d/
  chmod -R u+w $d
  substituteInPlace $d/jstarx.plymouth --replace-fail "@out@" "$out"
''
