#!/usr/bin/env python3
"""Make layer/assets/firefox/userChrome.css: Firefox's top bar curves around the Dynamic Island,
with the same shape and colours JStarx apps draw (see layer/starx/app.py _draw_header)."""
import os
import urllib.parse

B, D, RO, RB = 40, 57, 12, 20      # bar height, bay bottom, fillet radius, bay corner radius
ISLAND_W = 132                      # the compact island (clock + one status icon)
HW = ISLAND_W / 2 + 16
W = 2 * (HW + RO)
CX = W / 2
path = (f"M0 0H{W}V{B}"
        f"A{RO} {RO} 0 0 0 {CX + HW} {B + RO}V{D - RB}A{RB} {RB} 0 0 1 {CX + HW - RB} {D}"
        f"H{CX - HW + RB}A{RB} {RB} 0 0 1 {CX - HW} {D - RB}V{B + RO}A{RO} {RO} 0 0 0 0 {B}Z")
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:g}" height="58"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="58" '
       f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2E0D5C"/><stop offset="1" stop-color="#1A053D"/></linearGradient></defs>'
       f'<path d="{path}" fill="url(#g)"/></svg>')
uri = "data:image/svg+xml," + urllib.parse.quote(svg)
css = f"""/* JStarx: Firefox's top bar curves around the Dynamic Island (made by tools/make_firefox_chrome.py). */
#navigator-toolbox {{
  background:
    url("{uri}") top center / {W:g}px 58px no-repeat,
    linear-gradient(180deg, #2E0D5C 0, #200747 {B}px) top left / 100% {B}px no-repeat,
    #1C0642 !important;
  border-bottom: none !important;
  color: #F6F0FF !important;
}}
/* tabs stay on the left of the island, the window buttons on the right */
#TabsToolbar {{ min-height: {B}px !important; max-height: {B}px !important; background: transparent !important; }}
#TabsToolbar .toolbar-items {{ max-width: calc(50vw - {HW + RO + 14:g}px) !important; }}
/* the toolbar with the address bar sits below the curve */
#nav-bar {{ margin-top: {D - B + 1}px !important; background: transparent !important; box-shadow: none !important; }}
#PersonalToolbar {{ background: transparent !important; }}
"""
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "layer", "assets", "firefox", "userChrome.css")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    f.write(css)
print("wrote", os.path.relpath(out))
