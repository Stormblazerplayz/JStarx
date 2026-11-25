# The factory copy of the JStarx layer (shell, apps, games, store). Read-only; auto-repair
# restores files from here, and Settings -> Repair can reset to it.
{ runCommand, python3 }:
runCommand "jstarx-layer" { nativeBuildInputs = [ python3 ]; src = ../../layer; } ''
  cp -r $src $out
  chmod -R u+w $out
  find $out -name __pycache__ -prune -exec rm -rf {} +
  python3 ${../../tools/make_manifest.py} $out
''
