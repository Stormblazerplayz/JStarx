#!/usr/bin/env python3
"""Generate JStarx app icons: liquid-glass squircles with a white glyph.

Usage: python3 tools/make_icons.py   ->  layer/web/icons/*.svg
"""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "layer", "web", "icons")

# name: (gradient top-left, gradient bottom-right, glyph svg (128x128 space), glyph uses stroke?)
def ws(width=7, color="#fff"):
    return f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"'


W = ws()
F = 'fill="#fff"'

ICONS = {
    "settings": ("#8E5CF7", "#3C096C", f'''<g {W}><circle cx="64" cy="64" r="15"/>
      <path d="M64 30v-8M64 106v-8M98 64h8M22 64h8M88 40l6-6M34 94l6-6M88 88l6 6M34 34l6 6"/>
      <circle cx="64" cy="64" r="30"/></g>'''),
    "store": ("#FFB347", "#F25C05", f'''<path d="M38 50h52l-5 44a8 8 0 0 1-8 7H51a8 8 0 0 1-8-7z" {W}/>
      <path d="M50 50v-6a14 14 0 0 1 28 0v6" {W}/>
      <path d="M64 63l4 9 10 1-7.5 6.5 2.3 9.8L64 84l-8.8 5.3 2.3-9.8L50 73l10-1z" {F}/>'''),
    "ai": ("#7B2CBF", "#240046", f'''<rect x="38" y="38" width="52" height="52" rx="12" {W}/>
      <path d="M52 30v8M64 30v8M76 30v8M52 90v8M64 90v8M76 90v8M30 52h8M30 64h8M30 76h8M90 52h8M90 64h8M90 76h8" {W}/>
      <path d="M64 50q2.5 11.5 14 14q-11.5 2.5-14 14q-2.5-11.5-14-14q11.5-2.5 14-14z" fill="#FFD166"/>'''),
    "spark": ("#2A0657", "#7B2CBF", '''<g style="mix-blend-mode:screen">
      <ellipse cx="64" cy="38" rx="11" ry="26" fill="#C77DFF"/><ellipse cx="64" cy="90" rx="11" ry="26" fill="#C77DFF"/>
      <ellipse cx="38" cy="64" rx="26" ry="11" fill="#C77DFF"/><ellipse cx="90" cy="64" rx="26" ry="11" fill="#C77DFF"/>
      <ellipse cx="64" cy="64" rx="8" ry="30" fill="#FF9F43" transform="rotate(45 64 64)"/>
      <ellipse cx="64" cy="64" rx="8" ry="30" fill="#FF9F43" transform="rotate(-45 64 64)"/></g>
      <circle cx="64" cy="64" r="12" fill="#FFE2B0"/><circle cx="61" cy="61" r="4" fill="#fff"/>'''),
    "claude": ("#E8875F", "#B5502F", f'''<path d="M34 46a14 14 0 0 1 14-14h32a14 14 0 0 1 14 14v22a14 14 0 0 1-14 14H58l-16 13v-13h0a14 14 0 0 1-8-12z" {W}/>
      <path d="M72 50a12 12 0 1 0 0 14" {W}/>'''),
    "terminal": ("#3A2466", "#120626", f'''<rect x="28" y="34" width="72" height="60" rx="12" {ws(6)}/>
      <path d="M44 56l12 9-12 9" {W}/><path d="M62 76h20" {ws(7, "#FF9F43")}/>'''),
    "snake": ("#2BD48A", "#0B6B4A", f'''<path d="M30 88q18-46 36-14t34-14" {ws(11)}/>
      <circle cx="100" cy="60" r="8" {F}/><path d="M42 38q3 9 12 12q-9 3-12 12q-3-9-12-12q9-3 12-12z" fill="#FFD166"/>'''),
    "dodge": ("#6A4CFF", "#1E0B6B", f'''<path d="M64 24c16 12 22 32 18 52H46c-4-20 2-40 18-52z" {F}/>
      <circle cx="64" cy="52" r="7" fill="#3A1A8F"/><path d="M50 78l-10 14h14zM78 78l10 14H74z" {F}/>
      <path d="M58 84h12l-6 18z" fill="#FF9F43"/><circle cx="30" cy="40" r="6" fill="#fff" opacity=".5"/><circle cx="100" cy="92" r="8" fill="#fff" opacity=".5"/>'''),
    "breaker": ("#FF6B6B", "#8A1E4A", f'''<g {F}><rect x="28" y="30" width="22" height="12" rx="3"/><rect x="53" y="30" width="22" height="12" rx="3" opacity=".75"/>
      <rect x="78" y="30" width="22" height="12" rx="3"/><rect x="40" y="46" width="22" height="12" rx="3" opacity=".75"/><rect x="66" y="46" width="22" height="12" rx="3"/></g>
      <circle cx="70" cy="76" r="7" fill="#FFD166"/><rect x="40" y="94" width="48" height="9" rx="4.5" {F}/>'''),
    "files": ("#4FA3FF", "#3C2BB0", f'''<path d="M30 46a8 8 0 0 1 8-8h16l8 8h28a8 8 0 0 1 8 8v28a8 8 0 0 1-8 8H38a8 8 0 0 1-8-8z" {F} opacity=".95"/>
      <path d="M30 56h68" stroke="#3C2BB0" stroke-width="4" opacity=".35"/>'''),
    "notes": ("#FFD166", "#FF8A00", f'''<rect x="36" y="28" width="56" height="72" rx="10" {F}/>
      <path d="M48 48h32M48 60h32M48 72h20" stroke="#E07000" stroke-width="6" stroke-linecap="round"/>'''),
    "paint": ("#FF7AC6", "#7B2CBF", f'''<path d="M64 28a36 36 0 1 0 0 72c6 0 8-5 6-9s0-9 6-9h8a16 16 0 0 0 16-16c0-21-16-38-36-38z" {F}/>
      <circle cx="46" cy="58" r="6" fill="#FF8A00"/><circle cx="58" cy="42" r="6" fill="#7B2CBF"/><circle cx="76" cy="44" r="6" fill="#2BD48A"/><circle cx="46" cy="78" r="6" fill="#4FA3FF"/>'''),
    "calc": ("#5A6378", "#1C2030", f'''<rect x="36" y="26" width="56" height="76" rx="12" {ws(6)}/>
      <rect x="46" y="36" width="36" height="14" rx="4" fill="#FF9F43"/>
      <g {F}><circle cx="51" cy="64" r="5"/><circle cx="64" cy="64" r="5"/><circle cx="77" cy="64" r="5"/><circle cx="51" cy="79" r="5"/><circle cx="64" cy="79" r="5"/><circle cx="77" cy="79" r="5"/><circle cx="51" cy="92" r="4"/><circle cx="64" cy="92" r="4"/></g>
      <circle cx="77" cy="92" r="4" fill="#FF9F43"/>'''),
    "clock": ("#9D4EDD", "#3C096C", f'''<circle cx="64" cy="64" r="34" {W}/><path d="M64 44v22l14 8" {ws(7, "#FFD166")}/>'''),
    "music": ("#FF5E8A", "#7B2CBF", f'''<path d="M54 86V40l36-8v46" {W}/><circle cx="46" cy="88" r="10" {F}/><circle cx="82" cy="80" r="10" {F}/>'''),
    "code": ("#2F7BD9", "#1B2C6B", f'''<path d="M50 44L32 64l18 20M78 44l18 20-18 20" {W}/><path d="M70 36l-12 56" {ws(7, "#FF9F43")}/>'''),
    "torch": ("#FF7A3D", "#7B1E1E", f'''<path d="M64 26l22 22a31 31 0 1 1-44 0z" {W}/><circle cx="76" cy="44" r="5" {F}/>'''),
    "image": ("#2BD48A", "#1E5BB0", f'''<rect x="28" y="36" width="72" height="56" rx="10" {ws(6)}/>
      <circle cx="50" cy="56" r="7" fill="#FFD166"/><path d="M34 86l22-20 14 12 10-8 18 16" {W}/>'''),
    "video": ("#FF9F43", "#C0392B", f'''<path d="M50 38l42 26-42 26z" {F}/>'''),
    "globe": ("#5B8CFF", "#3C096C", f'''<circle cx="64" cy="64" r="34" {W}/><path d="M30 64h68M64 30c-16 18-16 50 0 68M64 30c16 18 16 50 0 68" {W}/>'''),
    "repair": ("#5DFFB0", "#0F7B6C", f'''<path d="M84 30a22 22 0 0 0-26 30L32 86a8 8 0 0 0 11 11l26-26a22 22 0 0 0 30-26L86 58l-14-2-2-14z" {F}/>'''),
}


def icon_svg(c1, c2, glyph):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>
  <linearGradient id="hi" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".42"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <radialGradient id="rim" cx=".5" cy="1" r=".7"><stop offset="0" stop-color="#FF9F43" stop-opacity=".35"/><stop offset="1" stop-color="#FF9F43" stop-opacity="0"/></radialGradient>
  <filter id="gs" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#10002B" flood-opacity=".35"/></filter>
</defs>
<rect x="4" y="4" width="120" height="120" rx="30" fill="url(#bg)"/>
<rect x="4" y="4" width="120" height="120" rx="30" fill="url(#rim)"/>
<g filter="url(#gs)">{glyph}</g>
<path d="M10 52 C12 24 26 10 54 9 L74 9 C100 10 116 22 118 48 C100 36 30 34 10 52Z" fill="url(#hi)"/>
<rect x="4.75" y="4.75" width="118.5" height="118.5" rx="29.25" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.5"/>
</svg>
'''


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (c1, c2, glyph) in ICONS.items():
        with open(os.path.join(OUT, f"{name}.svg"), "w") as f:
            f.write(icon_svg(c1, c2, glyph))
    # JStarx logo for the shell (start button, about page, boot screen)
    src = os.path.join(ROOT, "logos", "jstarx-logo.svg")
    mark = os.path.join(ROOT, "logos", "jstarx-mark.svg")
    for s, d in ((src, "jstarx.svg"), (mark, "jstarx-mark.svg")):
        with open(s) as fi, open(os.path.join(OUT, d), "w") as fo:
            fo.write(fi.read())
    print("wrote", len(ICONS) + 2, "icons to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
