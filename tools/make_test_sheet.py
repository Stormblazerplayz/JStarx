#!/usr/bin/env python3
"""Put the QEMU test screenshots on one labelled sheet: python3 tools/make_test_sheet.py test-out/run3"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SHOTS = [("boot-screen.png", "Boot screen"), ("welcome.png", "First start: Welcome"), ("desktop.png", "Desktop: island, folders, dock"),
         ("launchpad.png", "Launchpad"), ("start-menu.png", "Start menu"), ("firefox.png", "Firefox"),
         ("after-repair.png", "After auto-repair (desktop crashed 3x)"), ("after-fallback.png", "After auto-repair (broken build)")]


def main(folder):
    shots = [(os.path.join(folder, f), t) for f, t in SHOTS if os.path.exists(os.path.join(folder, f))]
    if not shots:
        sys.exit("no screenshots found")
    w, h, pad, label = 640, 360, 24, 34
    cols = 2
    rows = (len(shots) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w + (cols + 1) * pad, rows * (h + label) + (rows + 1) * pad + 60), (16, 4, 38))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
    except OSError:
        font = big = ImageFont.load_default()
    d.text((pad, 18), "JStarx OS running in QEMU (virtual Jetson, ARM64)", fill=(255, 209, 102), font=big)
    for i, (path, title) in enumerate(shots):
        x = pad + (i % cols) * (w + pad)
        y = 60 + pad + (i // cols) * (h + label + pad)
        im = Image.open(path).convert("RGB").resize((w, h), Image.LANCZOS)
        sheet.paste(im, (x, y + label))
        d.text((x, y + 4), title, fill=(246, 240, 255), font=font)
    out = os.path.join(folder, "jstarx-screens.png")
    sheet.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test-out/run3")
