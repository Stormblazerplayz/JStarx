#!/usr/bin/env python3
"""Generate the 10 JStarx logo concepts as SVG files.

Usage: python3 tools/make_logos.py [output_dir]
Every logo uses the JStarx palette: deep purple, violet and orange,
with "liquid glass" highlights (soft specular light on top, glow below).
"""
import math
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "logos")

# Palette
P_LIGHT, P_MID, P_DEEP, P_INK = "#E0AAFF", "#9D4EDD", "#5A189A", "#10002B"
O_LIGHT, O_MID, O_DEEP = "#FFD166", "#FF8A00", "#F25C05"


def sparkle(cx, cy, r, pinch=0.13):
    """4-point sparkle star with curved (concave) edges."""
    c = r * pinch
    return (f"M{cx:.1f} {cy - r:.1f} Q{cx + c:.1f} {cy - c:.1f} {cx + r:.1f} {cy:.1f} "
            f"Q{cx + c:.1f} {cy + c:.1f} {cx:.1f} {cy + r:.1f} "
            f"Q{cx - c:.1f} {cy + c:.1f} {cx - r:.1f} {cy:.1f} "
            f"Q{cx - c:.1f} {cy - c:.1f} {cx:.1f} {cy - r:.1f}Z")


def star5(cx, cy, r_out, r_in, rot=-90):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 36)
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def rotate_point(x, y, cx, cy, deg):
    a = math.radians(deg)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


COMMON_DEFS = f"""
  <linearGradient id="gStar" x1=".15" y1=".05" x2=".85" y2=".95">
    <stop offset="0" stop-color="{P_LIGHT}"/><stop offset=".42" stop-color="#B15CFF"/>
    <stop offset=".74" stop-color="#FF8A3D"/><stop offset="1" stop-color="{O_LIGHT}"/>
  </linearGradient>
  <linearGradient id="gPurple" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#C77DFF"/><stop offset=".5" stop-color="{P_MID}"/><stop offset="1" stop-color="{P_DEEP}"/>
  </linearGradient>
  <linearGradient id="gOrange" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{O_LIGHT}"/><stop offset=".55" stop-color="{O_MID}"/><stop offset="1" stop-color="{O_DEEP}"/>
  </linearGradient>
  <linearGradient id="gSpec" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff" stop-opacity=".6"/><stop offset=".48" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="gBg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#3C096C"/><stop offset=".55" stop-color="#240046"/><stop offset="1" stop-color="{P_INK}"/>
  </linearGradient>
  <radialGradient id="gGlowP" cx=".2" cy=".15" r=".75">
    <stop offset="0" stop-color="#C77DFF" stop-opacity=".55"/><stop offset="1" stop-color="#C77DFF" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="gGlowO" cx=".82" cy=".88" r=".65">
    <stop offset="0" stop-color="{O_MID}" stop-opacity=".55"/><stop offset="1" stop-color="{O_MID}" stop-opacity="0"/>
  </radialGradient>
  <filter id="fShadow" x="-30%" y="-30%" width="160%" height="160%">
    <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#0B0018" flood-opacity=".55"/>
  </filter>
  <filter id="fSoft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="18"/></filter>
  <filter id="fBlur6" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
"""


def svg(body, defs=""):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">\n'
            f"<defs>{COMMON_DEFS}{defs}</defs>\n{body}\n</svg>\n")


def badge_bg(shape="squircle"):
    if shape == "circle":
        clip = '<clipPath id="cBadge"><circle cx="256" cy="256" r="240"/></clipPath>'
        edge = '<circle cx="256" cy="256" r="239.5" fill="none" stroke="#fff" stroke-opacity=".2"/>'
    else:
        clip = '<clipPath id="cBadge"><rect x="16" y="16" width="480" height="480" rx="120"/></clipPath>'
        edge = '<rect x="16.5" y="16.5" width="479" height="479" rx="119.5" fill="none" stroke="#fff" stroke-opacity=".2"/>'
    fill = ('<g clip-path="url(#cBadge)"><rect width="512" height="512" fill="url(#gBg)"/>'
            '<rect width="512" height="512" fill="url(#gGlowP)"/><rect width="512" height="512" fill="url(#gGlowO)"/>'
            '<path d="M44 170 C60 82 116 40 200 32" stroke="#fff" stroke-opacity=".32" stroke-width="7" fill="none" stroke-linecap="round"/></g>')
    return clip, fill, edge


def nova():
    clip, fill, edge = badge_bg()
    s = sparkle(256, 268, 172)
    body = f"""{fill}
<rect x="66" y="66" width="380" height="380" rx="98" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".2" stroke-width="2"/>
<path d="{s}" fill="#B15CFF" opacity=".75" filter="url(#fSoft)"/>
<path d="{s}" fill="url(#gStar)" filter="url(#fShadow)"/>
<path d="{s}" fill="url(#gSpec)"/>
<path d="{sparkle(378, 132, 34, .16)}" fill="{O_LIGHT}"/>
<circle cx="378" cy="132" r="10" fill="#fff" opacity=".8"/>
{edge}"""
    return svg(body, clip)


def orbit():
    clip, fill, edge = badge_bg("circle")
    ang = 28
    px, py = rotate_point(256 + 214 * math.cos(math.radians(32)), 256 + 76 * math.sin(math.radians(32)), 256, 256, -ang)
    body = f"""{fill}
<g transform="rotate(-{ang} 256 256)"><ellipse cx="256" cy="256" rx="214" ry="76" fill="none" stroke="url(#gOrange)" stroke-width="14" opacity=".4"/></g>
<path d="M304 112 L304 296 C304 372 254 404 206 404 C166 404 140 384 124 352" fill="none" stroke="#7B2CBF" stroke-width="64" stroke-linecap="round" opacity=".55" filter="url(#fBlur6)"/>
<path d="M304 112 L304 296 C304 372 254 404 206 404 C166 404 140 384 124 352" fill="none" stroke="url(#gPurple)" stroke-width="58" stroke-linecap="round"/>
<path d="M292 128 L292 290" stroke="#fff" stroke-opacity=".45" stroke-width="10" stroke-linecap="round"/>
<g transform="rotate(-{ang} 256 256)"><path d="M42 256 A214 76 0 0 0 470 256" fill="none" stroke="url(#gOrange)" stroke-width="14" stroke-linecap="round"/></g>
<circle cx="{px:.1f}" cy="{py:.1f}" r="30" fill="{O_MID}" filter="url(#fSoft)" opacity=".9"/>
<path d="{sparkle(px, py, 34, .16)}" fill="{O_LIGHT}"/>
{edge}"""
    return svg(body, clip)


def prism_x():
    body = f"""
<g filter="url(#fShadow)">
  <rect x="204" y="46" width="104" height="420" rx="52" fill="url(#gOrange)" transform="rotate(-45 256 256)"/>
  <rect x="204" y="46" width="104" height="420" rx="52" fill="url(#gPurple)" opacity=".88" transform="rotate(45 256 256)" style="mix-blend-mode:screen"/>
</g>
<rect x="222" y="74" width="16" height="364" rx="8" fill="#fff" opacity=".35" transform="rotate(45 256 256)"/>
<rect x="222" y="74" width="16" height="364" rx="8" fill="#fff" opacity=".28" transform="rotate(-45 256 256)"/>
<circle cx="256" cy="256" r="46" fill="#fff" opacity=".35" filter="url(#fSoft)"/>
<path d="{sparkle(256, 256, 40, .14)}" fill="#fff"/>"""
    return svg(body)


def constellation():
    clip, fill, edge = badge_bg("circle")
    nodes = [(170, 130, 16), (262, 120, 26), (352, 134, 16), (294, 214, 18), (310, 306, 22), (270, 376, 16), (196, 384, 20), (150, 336, 14)]
    lines = "M170 130 L262 120 L352 134 M262 120 L294 214 L310 306 L270 376 L196 384 L150 336"
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity=".{o}"/>' for x, y, r, o in
                   [(96, 210, 2, 6), (410, 230, 2, 5), (380, 400, 1.6, 6), (120, 420, 1.8, 5), (210, 70, 1.6, 6), (430, 320, 2, 4), (90, 300, 1.4, 6)])
    stars = ""
    for i, (x, y, r) in enumerate(nodes):
        col = "url(#gStar)" if i != 4 else f"{O_LIGHT}"
        stars += f'<circle cx="{x}" cy="{y}" r="{r * .9:.1f}" fill="{P_LIGHT if i != 4 else O_MID}" opacity=".55" filter="url(#fBlur6)"/>'
        stars += f'<path d="{sparkle(x, y, r * 1.3, .15)}" fill="{col}"/>'
    body = f"""{fill}{dots}
<circle cx="256" cy="256" r="212" fill="none" stroke="url(#gStar)" stroke-width="6" opacity=".9"/>
<path d="{lines}" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
{stars}
{edge}"""
    return svg(body, clip)


def drop():
    d = "M256 52 C330 154 412 236 412 320 C412 406 342 462 256 462 C170 462 100 406 100 320 C100 236 182 154 256 52Z"
    body = f"""
<defs><linearGradient id="gDrop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C77DFF"/><stop offset=".55" stop-color="#7B2CBF"/><stop offset="1" stop-color="{O_MID}"/></linearGradient>
<clipPath id="cDrop"><path d="{d}"/></clipPath></defs>
<path d="{d}" fill="url(#gDrop)" filter="url(#fShadow)"/>
<g clip-path="url(#cDrop)">
  <ellipse cx="256" cy="470" rx="190" ry="90" fill="{O_LIGHT}" opacity=".75" filter="url(#fSoft)"/>
  <path d="M150 300 C150 230 196 170 236 120" stroke="#fff" stroke-opacity=".55" stroke-width="18" fill="none" stroke-linecap="round" filter="url(#fBlur6)"/>
  <path d="M156 300 C156 236 198 178 232 134" stroke="#fff" stroke-opacity=".7" stroke-width="7" fill="none" stroke-linecap="round"/>
</g>
<circle cx="268" cy="322" r="60" fill="#fff" opacity=".45" filter="url(#fSoft)"/>
<path d="{sparkle(268, 322, 74, .14)}" fill="#fff"/>
<path d="{d}" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="2"/>"""
    return svg(body)


def hex_gate():
    R, r = 222, 150
    segs = ""
    for i in range(6):
        a0, a1 = math.radians(-90 + 60 * i), math.radians(-90 + 60 * (i + 1))
        pts = [(256 + R * math.cos(a0), 256 + R * math.sin(a0)), (256 + R * math.cos(a1), 256 + R * math.sin(a1)),
               (256 + r * math.cos(a1), 256 + r * math.sin(a1)), (256 + r * math.cos(a0), 256 + r * math.sin(a0))]
        mx = sum(p[0] for p in pts) / 4
        my = sum(p[1] for p in pts) / 4
        pts = [(mx + (x - mx) * .9, my + (y - my) * .9) for x, y in pts]
        grad = "url(#gPurple)" if i % 2 == 0 else "url(#gOrange)"
        segs += f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{grad}" stroke="#fff" stroke-opacity=".25" stroke-width="2" stroke-linejoin="round"/>'
    body = f"""
<g filter="url(#fShadow)">{segs}</g>
<path d="{sparkle(256, 256, 112, .14)}" fill="#B15CFF" opacity=".6" filter="url(#fSoft)"/>
<path d="{sparkle(256, 256, 112, .14)}" fill="url(#gStar)"/>
<path d="{sparkle(256, 256, 112, .14)}" fill="url(#gSpec)"/>"""
    return svg(body)


def planet():
    ang = 20
    body = f"""
<defs><radialGradient id="gPlanet" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="{P_LIGHT}"/><stop offset=".45" stop-color="#8E3BEA"/><stop offset="1" stop-color="#240046"/></radialGradient></defs>
<g transform="rotate(-{ang} 256 256)"><ellipse cx="256" cy="256" rx="232" ry="64" fill="none" stroke="url(#gOrange)" stroke-width="22" opacity=".45"/></g>
<circle cx="256" cy="256" r="134" fill="url(#gPlanet)" filter="url(#fShadow)"/>
<ellipse cx="214" cy="196" rx="70" ry="42" fill="#fff" opacity=".28" filter="url(#fBlur6)" transform="rotate(-30 214 196)"/>
<g transform="rotate(-{ang} 256 256)"><path d="M24 256 A232 64 0 0 0 488 256" fill="none" stroke="url(#gOrange)" stroke-width="22" stroke-linecap="round"/>
<path d="M60 268 A200 50 0 0 0 300 316" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="5" stroke-linecap="round"/></g>
<path d="{sparkle(408, 96, 40, .15)}" fill="{O_LIGHT}"/>
<path d="{sparkle(96, 420, 22, .15)}" fill="{P_LIGHT}"/>"""
    return svg(body)


def comet():
    clip, fill, edge = badge_bg()
    tail = "M334 128 C334 250 334 324 292 378 C254 428 176 424 150 368"
    body = f"""{fill}
<defs><linearGradient id="gTail" gradientUnits="userSpaceOnUse" x1="334" y1="120" x2="150" y2="400"><stop offset="0" stop-color="{O_MID}"/><stop offset=".55" stop-color="#B15CFF"/><stop offset="1" stop-color="#7B2CBF" stop-opacity=".2"/></linearGradient></defs>
<path d="{tail}" fill="none" stroke="url(#gTail)" stroke-width="78" stroke-linecap="round" opacity=".25"/>
<path d="{tail}" fill="none" stroke="url(#gTail)" stroke-width="50" stroke-linecap="round" opacity=".55"/>
<path d="{tail}" fill="none" stroke="url(#gTail)" stroke-width="26" stroke-linecap="round"/>
<circle cx="334" cy="128" r="64" fill="{O_MID}" opacity=".7" filter="url(#fSoft)"/>
<circle cx="334" cy="128" r="40" fill="url(#gOrange)"/>
<circle cx="322" cy="114" r="14" fill="#fff" opacity=".85"/>
<path d="{sparkle(190, 150, 26, .15)}" fill="{P_LIGHT}"/>
<path d="{sparkle(400, 300, 16, .15)}" fill="#fff" opacity=".8"/>
{edge}"""
    return svg(body, clip)


def shield():
    sh = "M256 46 L422 100 C426 270 364 392 256 466 C148 392 86 270 90 100 Z"
    st = star5(256, 262, 112, 46)
    body = f"""
<polygon points="{st}" fill="{O_MID}" opacity=".8" filter="url(#fSoft)"/>
<polygon points="{st}" fill="url(#gOrange)" stroke="#fff" stroke-opacity=".4" stroke-width="2" stroke-linejoin="round"/>
<path d="{sh} M{star5(256, 262, 132, 56).replace(' ', ' L')} Z" fill="url(#gPurple)" fill-rule="evenodd" stroke="#fff" stroke-opacity=".3" stroke-width="2" stroke-linejoin="round" filter="url(#fShadow)"/>
<path d="M118 118 L250 74" stroke="#fff" stroke-opacity=".5" stroke-width="10" stroke-linecap="round"/>
<path d="M112 150 C112 250 150 330 210 392" stroke="#fff" stroke-opacity=".22" stroke-width="8" fill="none" stroke-linecap="round"/>"""
    return svg(body)


def bloom():
    petals = ""
    for i in range(8):
        long = i % 2 == 0
        ry = 176 if long else 120
        grad = "url(#gPurple)" if long else "url(#gOrange)"
        petals += (f'<ellipse cx="256" cy="{256 - ry * .55:.1f}" rx="{40 if long else 32}" ry="{ry * .55:.1f}" fill="{grad}" '
                   f'opacity=".88" transform="rotate({i * 45} 256 256)" style="mix-blend-mode:screen"/>')
    body = f"""
<defs><radialGradient id="gCore" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff"/><stop offset=".5" stop-color="{O_LIGHT}"/><stop offset="1" stop-color="{O_MID}"/></radialGradient></defs>
<g filter="url(#fShadow)">{petals}</g>
<circle cx="256" cy="256" r="70" fill="{O_MID}" opacity=".6" filter="url(#fSoft)"/>
<circle cx="256" cy="256" r="50" fill="url(#gCore)"/>
<circle cx="242" cy="240" r="14" fill="#fff" opacity=".9"/>"""
    return svg(body)


LOGOS = [
    ("01-nova", "Nova", nova),
    ("02-orbit", "Orbit J", orbit),
    ("03-prism-x", "Prism X", prism_x),
    ("04-constellation", "Constellation", constellation),
    ("05-liquid-drop", "Liquid Drop", drop),
    ("06-hex-gate", "Hex Gate", hex_gate),
    ("07-ring-planet", "Ring Planet", planet),
    ("08-comet", "Comet", comet),
    ("09-shield-star", "Shield Star", shield),
    ("10-spark-bloom", "Spark Bloom", bloom),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    for slug, _name, fn in LOGOS:
        with open(os.path.join(OUT, slug + ".svg"), "w") as f:
            f.write(fn())
    # Official mark = Nova, plus a background-free star mark for UI use.
    with open(os.path.join(OUT, "jstarx-logo.svg"), "w") as f:
        f.write(nova())
    s = sparkle(256, 256, 236)
    with open(os.path.join(OUT, "jstarx-mark.svg"), "w") as f:
        f.write(svg(f'<path d="{s}" fill="url(#gStar)"/><path d="{s}" fill="url(#gSpec)"/>'))
    print("wrote", len(LOGOS) + 2, "SVG files to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
