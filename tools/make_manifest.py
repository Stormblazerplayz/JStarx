#!/usr/bin/env python3
"""Write layer/MANIFEST.json: the SHA-256 of every file in the JStarx layer.

Auto-update refuses an update whose files don't match, and auto-repair uses it to find and
restore damaged files. Run before every commit that changes layer/ (CI checks it).
Usage: python3 tools/make_manifest.py [layer_dir]   |   --check to only verify
"""
import hashlib
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def build(layer):
    files = {}
    for base, dirs, names in os.walk(layer):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name == "MANIFEST.json" and base == layer:
                continue
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, layer)
            with open(full, "rb") as f:
                files[rel] = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(layer, "layer.json")) as f:
        version = json.load(f)["version"]
    return {"version": version, "files": files}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    layer = os.path.abspath(args[0] if args else os.path.join(ROOT, "layer"))
    manifest = build(layer)
    path = os.path.join(layer, "MANIFEST.json")
    if "--check" in sys.argv:
        try:
            with open(path) as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = {}
        if old != manifest:
            print("MANIFEST.json is out of date: run python3 tools/make_manifest.py")
            sys.exit(1)
        print("MANIFEST.json is up to date")
        return
    with open(path, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"MANIFEST.json: {len(manifest['files'])} files, version {manifest['version']}")


if __name__ == "__main__":
    main()
