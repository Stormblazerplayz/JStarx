# JStarx system services: starxd, updater, auto-repair, power, StarAI, Spark, session scripts.
{ stdenv, python3, bash, jstarx-runtime }:
let
  py = python3.withPackages (ps: [ ps.numpy ]);
in
stdenv.mkDerivation {
  pname = "jstarx-core";
  version = "2.0.0";
  src = ./.;
  dontBuild = true;
  installPhase = ''
    site=$out/lib/jstarx
    mkdir -p $site $out/bin
    cp -r jstarx_core $site/
    for e in jstarx-update:update jstarx-repair:repair jstarx-boot-ok:boot_ok jstarx-power:power \
             starxd:starxd starai:starai spark-serve:spark_serve; do
      name=''${e%%:*}; fn=''${e##*:}
      printf '#!%s\nimport sys\nsys.path.insert(0, "%s")\nfrom jstarx_core.cli import %s\n%s()\n' \
        "${py}/bin/python3" "$site" "$fn" "$fn" > $out/bin/$name
      chmod +x $out/bin/$name
    done
    for s in starx-session starx-shell-supervisor; do
      { echo "#!${bash}/bin/bash"; echo "export STARX_PYTHON=${jstarx-runtime}/bin/starx-python"; tail -n +2 bin/$s; } > $out/bin/$s
      chmod +x $out/bin/$s
    done
  '';
  passthru.python = py;
  meta.description = "JStarx core system services";
}
