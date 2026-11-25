#!/usr/bin/env python3
"""Turn the official JStarx logo into the StarX Kernel boot logo.

The kernel's CLUT224 logo must be an ASCII PPM (P3) with at most 224 colors,
drawn on black (that is what the console shows behind it).
Usage: python3 tools/make_kernel_logo.py [size]
"""
import os
import sys

from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "logos", "png", "jstarx-logo.png")
DST = os.path.join(ROOT, "os", "kernel", "logo_starx_clut224.ppm")
SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 192


def main():
    logo = Image.open(SRC).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    canvas.alpha_composite(logo)
    rgb = canvas.convert("RGB").quantize(colors=223, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = rgb.getcolors(maxcolors=100000)
    assert colors is not None and len(colors) <= 224, f"too many colors: {len(colors) if colors else '?'}"
    px = list(rgb.get_flattened_data()) if hasattr(rgb, "get_flattened_data") else list(rgb.getdata())
    lines = ["P3", "# JStarx StarX Kernel boot logo", f"{SIZE} {SIZE}", "255"]
    row = []
    for i, (r, g, b) in enumerate(px):
        row.append(f"{r} {g} {b}")
        if len(row) == 6:
            lines.append("  ".join(row))
            row = []
    if row:
        lines.append("  ".join(row))
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {DST}: {SIZE}x{SIZE}, {len(colors)} colors")


if __name__ == "__main__":
    main()
