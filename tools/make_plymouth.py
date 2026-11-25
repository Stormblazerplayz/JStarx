#!/usr/bin/env python3
"""Make the images for the JStarx boot screen (Plymouth theme in os/plymouth/jstarx)."""
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "os", "plymouth", "jstarx")


def rounded(w, h, fill_fn):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=255)
    body = fill_fn(w, h)
    im.paste(body, (0, 0), mask)
    return im


def main():
    os.makedirs(OUT, exist_ok=True)
    bg = Image.open(os.path.join(ROOT, "layer", "assets", "wallpapers", "nebula-blur.jpg")).convert("RGB").resize((1280, 720), Image.LANCZOS)
    bg = Image.blend(bg, Image.new("RGB", bg.size, (16, 3, 38)), 0.35)
    bg.save(os.path.join(OUT, "background.png"), optimize=True)

    logo = Image.open(os.path.join(ROOT, "logos", "png", "jstarx-logo.png")).convert("RGBA").resize((256, 256), Image.LANCZOS)
    logo.save(os.path.join(OUT, "logo.png"), optimize=True)

    glow = Image.new("RGBA", (560, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((120, 120, 440, 440), fill=(157, 78, 221, 150))
    d.ellipse((230, 250, 470, 470), fill=(255, 138, 0, 110))
    glow.filter(ImageFilter.GaussianBlur(70)).save(os.path.join(OUT, "glow.png"), optimize=True)

    def track_fill(w, h):
        return Image.new("RGBA", (w, h), (255, 255, 255, 46))

    def grad_fill(w, h):
        g = Image.new("RGBA", (w, h))
        for x in range(w):
            t = x / max(1, w - 1)
            c = (int(157 + (255 - 157) * t), int(78 + (138 - 78) * t), int(221 + (0 - 221) * t), 255)
            ImageDraw.Draw(g).line([(x, 0), (x, h)], fill=c)
        return g

    rounded(360, 8, track_fill).save(os.path.join(OUT, "track.png"))
    rounded(360, 8, grad_fill).save(os.path.join(OUT, "fill.png"))
    dot = Image.new("RGBA", (14, 14), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse((0, 0, 13, 13), fill=(255, 209, 102, 255))
    dot.save(os.path.join(OUT, "dot.png"))
    print("boot screen images written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
