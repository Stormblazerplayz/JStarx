#!/usr/bin/env python3
"""Generate the JStarx wallpapers (and pre-blurred copies used for liquid glass).

The shell's glass panels use the blurred copy as their background, so the
blur is computed once here instead of live on the GPU (saves power).
Usage: python3 tools/make_wallpapers.py
"""
import math
import os

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "layer", "assets", "wallpapers")
W, H = 2560, 1440
rng = np.random.default_rng(7)

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
nx, ny = xx / W, yy / H


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def blob(img, cx, cy, r, color, strength=1.0, aspect=1.0):
    d = np.sqrt(((nx - cx) * aspect) ** 2 + (ny - cy) ** 2) / r
    a = np.clip(np.exp(-d * d * 2.2) * strength, 0, 1)[..., None]
    img[:] = img * (1 - a) + hexrgb(color) * a


def gradient(c0, c1, angle_deg):
    a = math.radians(angle_deg)
    t = np.clip((nx * math.cos(a) + ny * math.sin(a)) / (abs(math.cos(a)) + abs(math.sin(a))), 0, 1)[..., None]
    return hexrgb(c0) * (1 - t) + hexrgb(c1) * t


def ribbon(img, y0, amp, freq, phase, width, color, strength):
    center = y0 + amp * np.sin(nx * freq * 2 * math.pi + phase)
    d = np.abs(ny - center) / width
    a = np.clip(np.exp(-d * d * 3) * strength, 0, 1)[..., None]
    img[:] = img + (hexrgb(color) - img) * a


def stars(img, count, max_alpha=0.9, region=None):
    for _ in range(count):
        x, y = rng.integers(0, W), rng.integers(0, H)
        if region is not None and not region(x / W, y / H):
            continue
        r = rng.choice([1, 1, 1, 2, 2, 3])
        a = rng.uniform(0.25, max_alpha)
        y0, y1, x0, x1 = max(0, y - r), min(H, y + r + 1), max(0, x - r), min(W, x + r + 1)
        sub = img[y0:y1, x0:x1]
        gy, gx = np.mgrid[y0:y1, x0:x1]
        fall = np.clip(1 - np.sqrt((gx - x) ** 2 + (gy - y) ** 2) / (r + 0.5), 0, 1)[..., None] * a
        sub[:] = sub * (1 - fall) + 255 * fall


def sparkle(img, cx, cy, r, color, alpha=0.9):
    x0, x1, y0, y1 = int(cx - r), int(cx + r), int(cy - r), int(cy + r)
    gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = np.abs(gx - cx) / r, np.abs(gy - cy) / r
    shape = np.clip(1 - (np.sqrt(dx) + np.sqrt(dy)), 0, 1) ** 1.5
    glow = np.exp(-((dx * dx + dy * dy) * 18)) * 0.6
    a = np.clip((shape + glow) * alpha, 0, 1)[..., None]
    sub = img[y0:y1, x0:x1]
    sub[:] = sub * (1 - a) + hexrgb(color) * a


def finish(img, name):
    noise = rng.normal(0, 2.2, img.shape[:2])[..., None]
    out = np.clip(img + noise, 0, 255).astype(np.uint8)
    im = Image.fromarray(out, "RGB")
    os.makedirs(OUT, exist_ok=True)
    im.save(os.path.join(OUT, f"{name}.jpg"), quality=88, optimize=True, progressive=True)
    small = im.resize((W // 4, H // 4), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    dark = Image.blend(small, Image.new("RGB", small.size, (20, 6, 40)), 0.18)
    dark.resize((W // 2, H // 2), Image.BICUBIC).save(os.path.join(OUT, f"{name}-blur.jpg"), quality=86)
    im.resize((480, 270), Image.LANCZOS).save(os.path.join(OUT, f"{name}-thumb.jpg"), quality=86)
    print("wrote", name)


def nebula():
    img = gradient("#14002E", "#3A0A73", 35)
    blob(img, 0.18, 0.2, 0.55, "#5B1CB0", 0.85, 0.75)
    blob(img, 0.55, 0.55, 0.45, "#8E3BEA", 0.55, 0.7)
    blob(img, 0.92, 0.95, 0.42, "#FF7A00", 0.85, 0.8)
    blob(img, 0.78, 0.78, 0.25, "#FFB347", 0.35, 0.8)
    blob(img, 0.05, 0.95, 0.35, "#240046", 0.8, 0.8)
    ribbon(img, 0.62, 0.08, 0.8, 0.6, 0.05, "#C77DFF", 0.28)
    ribbon(img, 0.68, 0.07, 0.8, 1.1, 0.035, "#FF9F43", 0.22)
    stars(img, 900, 0.85)
    for cx, cy, r, c in [(0.83, 0.18, 46, "#FFD166"), (0.12, 0.72, 30, "#E0AAFF"), (0.42, 0.12, 22, "#ffffff")]:
        sparkle(img, cx * W, cy * H, r, c)
    finish(img, "nebula")


def aurora():
    img = gradient("#0B0420", "#2B0957", 80)
    for i, (y0, col, s) in enumerate([(0.35, "#9D4EDD", 0.5), (0.42, "#FF8A00", 0.4), (0.5, "#C77DFF", 0.35), (0.58, "#FF5E3A", 0.25)]):
        ribbon(img, y0, 0.09, 0.6 + i * 0.15, i * 1.3, 0.06, col, s)
    blob(img, 0.5, 1.05, 0.5, "#3C096C", 0.9, 0.6)
    stars(img, 700, 0.8, region=lambda x, y: y < 0.55)
    finish(img, "aurora")


def midnight():
    img = gradient("#07020F", "#1A0638", 120)
    blob(img, 0.5, 0.45, 0.6, "#2E0C5C", 0.7, 0.6)
    blob(img, 0.85, 0.1, 0.2, "#FF8A00", 0.18, 0.9)
    stars(img, 500, 0.6)
    sparkle(img, 0.5 * W, 0.42 * H, 70, "#B15CFF", 0.75)
    finish(img, "midnight")


def sunset():
    img = gradient("#FF9F43", "#2A0657", 95)
    blob(img, 0.5, 0.38, 0.3, "#FFD166", 0.7, 0.55)
    blob(img, 0.5, 0.42, 0.18, "#FFF1D6", 0.5, 0.55)
    blob(img, 0.2, 0.85, 0.5, "#3C096C", 0.75, 0.7)
    blob(img, 0.85, 0.9, 0.45, "#5A189A", 0.7, 0.7)
    ribbon(img, 0.7, 0.05, 0.7, 0.3, 0.05, "#9D4EDD", 0.45)
    stars(img, 300, 0.7, region=lambda x, y: y > 0.62)
    finish(img, "sunset")


if __name__ == "__main__":
    nebula()
    aurora()
    midnight()
    sunset()
