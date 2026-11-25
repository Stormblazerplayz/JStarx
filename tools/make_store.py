#!/usr/bin/env python3
"""Build layer/store/catalog.json: official JStarx apps you can install later.

Web apps live in layer/store/apps/<id>/ (each file gets a SHA-256 so installs are verified).
Nix apps install prebuilt packages from the same nixpkgs the system uses.
Usage: python3 tools/make_store.py
"""
import hashlib
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STORE = os.path.join(ROOT, "layer", "store")

NIX_APPS = [
    {"id": "claude-code", "name": "Claude Code", "type": "nix", "nix": "claude-code", "unfree": True,
     "exec": ["foot", "-e", "claude"], "app_id": "foot", "icon": "claude", "category": "AI & Code", "size": "≈ 150 MB",
     "description": "Anthropic's coding assistant in the terminal. Build and fix code by chatting."},
    {"id": "ai-kit", "name": "Python AI Kit", "type": "nix", "nix": "python3-ai-kit",
     "nix_expr": "with import <nixpkgs> {}; python3.withPackages (ps: [ ps.torch ps.numpy ps.pandas ps.matplotlib ps.jupyterlab ])",
     "exec": ["foot", "-e", "jupyter", "lab"], "app_id": "foot", "icon": "torch", "category": "AI & Code", "size": "≈ 1.5 GB",
     "description": "PyTorch, NumPy, pandas and JupyterLab for training your own AI models."},
    {"id": "vscodium", "name": "VSCodium", "type": "nix", "nix": "vscodium", "exec": ["codium"], "app_id": "codium",
     "icon": "code", "category": "AI & Code", "size": "≈ 450 MB", "description": "A full code editor for big projects."},
    {"id": "files", "name": "Files", "type": "nix", "nix": "xfce.thunar", "exec": ["thunar"], "app_id": "thunar",
     "icon": "files", "category": "Productivity", "size": "≈ 30 MB", "description": "Browse folders, USB sticks and SD cards."},
    {"id": "gimp", "name": "GIMP", "type": "nix", "nix": "gimp", "exec": ["gimp"], "app_id": "gimp",
     "icon": "image", "category": "Creative", "size": "≈ 400 MB", "description": "Edit photos and make artwork like a pro."},
    {"id": "vlc", "name": "VLC", "type": "nix", "nix": "vlc", "exec": ["vlc"], "app_id": "vlc",
     "icon": "video", "category": "Fun", "size": "≈ 200 MB", "description": "Play any video or music file."},
]

FEATURED = "notes"


def web_apps():
    out = []
    apps_dir = os.path.join(STORE, "apps")
    for app_id in sorted(os.listdir(apps_dir)):
        folder = os.path.join(apps_dir, app_id)
        with open(os.path.join(folder, "app.json")) as f:
            meta = json.load(f)
        files, total = {}, 0
        for base, _dirs, names in os.walk(folder):
            for name in sorted(names):
                full = os.path.join(base, name)
                rel = os.path.relpath(full, folder)
                data = open(full, "rb").read()
                files[rel] = hashlib.sha256(data).hexdigest()
                total += len(data)
        out.append({"id": meta["id"], "name": meta["name"], "type": "web", "version": meta["version"],
                    "icon": meta["id"], "category": meta.get("category", "Apps"),
                    "description": meta["description"], "size": f"{max(1, total // 1024)} KB", "files": files})
    return out


def main():
    catalog = {"name": "Star Store", "featured": FEATURED, "apps": web_apps() + NIX_APPS,
               "categories": ["Productivity", "Creative", "AI & Code", "Fun"]}
    with open(os.path.join(STORE, "catalog.json"), "w") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print("catalog:", len(catalog["apps"]), "apps")


if __name__ == "__main__":
    main()
