"""Builds the Banana Theft Auto mascot art.

- Adds the crying cat (pink bob wig) and the crying fit girl to docs/banana/banner.svg
- Writes docs/banana/watermark.svg (banana pointer + crying cat + crying fit girl)
- Stamps that watermark on the screenshots (docs/menu/*.svg and ../_preview-screenshot.png)

Safe to re-run: originals are copied to J:/GTAVI/_screenshot-originals once and every
run stamps from those, so the watermark is never applied twice.
"""
import io
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent            # leonida/docs/banana
LEONIDA = HERE.parent.parent                      # leonida
ROOT = LEONIDA.parent                             # J:/GTAVI
BACKUP = ROOT / "_screenshot-originals"

# ---------------------------------------------------------------- characters
# Each character is drawn in a 200 x 240 box, origin top-left.

CAT = """
<g class="cat">
  <path d="M150,212 C205,212 205,140 172,128" fill="none" stroke="#3a3a44" stroke-width="20" stroke-linecap="round"/>
  <path d="M150,212 C205,212 205,140 172,128" fill="none" stroke="#9aa0a8" stroke-width="10" stroke-linecap="round"/>
  <ellipse cx="100" cy="186" rx="58" ry="50" fill="#9aa0a8" stroke="#3a3a44" stroke-width="5"/>
  <ellipse cx="100" cy="196" rx="32" ry="34" fill="#cdd0d6"/>
  <ellipse cx="76" cy="231" rx="17" ry="9" fill="#b4b9c0" stroke="#3a3a44" stroke-width="4"/>
  <ellipse cx="124" cy="231" rx="17" ry="9" fill="#b4b9c0" stroke="#3a3a44" stroke-width="4"/>
  <path d="M44,72 L52,12 L94,46 Z" fill="#9aa0a8" stroke="#3a3a44" stroke-width="5" stroke-linejoin="round"/>
  <path d="M156,72 L148,12 L106,46 Z" fill="#9aa0a8" stroke="#3a3a44" stroke-width="5" stroke-linejoin="round"/>
  <path d="M55,52 L58,26 L78,44 Z" fill="#ffb3c7"/>
  <path d="M145,52 L142,26 L122,44 Z" fill="#ffb3c7"/>
  <ellipse cx="100" cy="94" rx="64" ry="54" fill="#9aa0a8" stroke="#3a3a44" stroke-width="5"/>
  <!-- pink bob wig -->
  <path d="M30,124 C20,62 50,30 100,30 C150,30 180,62 170,124 C164,132 150,132 146,122 L146,80 C122,70 78,70 54,80 L54,122 C50,132 36,132 30,124 Z"
        fill="#ff8cc6" stroke="#b83a78" stroke-width="5" stroke-linejoin="round"/>
  <path d="M62,52 C80,40 112,38 134,46" fill="none" stroke="#ffd1e8" stroke-width="7" stroke-linecap="round"/>
  <path d="M60,79 L60,70 M80,74 L80,64 M100,72 L100,62 M120,74 L120,64 M140,79 L140,70" stroke="#b83a78" stroke-width="3" stroke-linecap="round"/>
  <!-- crying face -->
  <path d="M62,98 Q74,88 86,98" fill="none" stroke="#2a2a33" stroke-width="5" stroke-linecap="round"/>
  <path d="M114,98 Q126,88 138,98" fill="none" stroke="#2a2a33" stroke-width="5" stroke-linecap="round"/>
  <path d="M66,88 L84,82 M134,88 L116,82" stroke="#2a2a33" stroke-width="4" stroke-linecap="round"/>
  <path d="M72,101 C70,120 76,138 70,158" fill="none" stroke="#5ec8ff" stroke-width="8" stroke-linecap="round" opacity=".9"/>
  <path d="M128,101 C130,120 124,138 130,158" fill="none" stroke="#5ec8ff" stroke-width="8" stroke-linecap="round" opacity=".9"/>
  <path d="M46,104 q-6,10 0,14 q6,-4 0,-14 Z M154,104 q-6,10 0,14 q6,-4 0,-14 Z" fill="#5ec8ff"/>
  <path d="M95,106 L105,106 L100,112 Z" fill="#ff8fab"/>
  <path d="M86,126 Q100,112 114,126 Q100,136 86,126 Z" fill="#3b1d2a" stroke="#2a2a33" stroke-width="3" stroke-linejoin="round"/>
  <path d="M93,128 Q100,123 107,128" fill="none" stroke="#ff6f91" stroke-width="4" stroke-linecap="round"/>
  <ellipse cx="56" cy="116" rx="8" ry="4.5" fill="#ff6f91" opacity=".6"/>
  <ellipse cx="144" cy="116" rx="8" ry="4.5" fill="#ff6f91" opacity=".6"/>
  <path d="M40,112 L14,108 M40,120 L16,124 M160,112 L186,108 M160,120 L184,124" stroke="#2a2a33" stroke-width="2.5" stroke-linecap="round"/>
</g>"""

GIRL = """
<g class="fitgirl">
  <path d="M38,196 C14,128 26,36 100,30 C174,36 186,128 162,196 Z" fill="#2b1a2e" stroke="#140a16" stroke-width="5" stroke-linejoin="round"/>
  <path d="M56,240 C56,194 74,172 100,172 C126,172 144,194 144,240 Z" fill="#ff4fa3" stroke="#140a16" stroke-width="5" stroke-linejoin="round"/>
  <path d="M84,174 L100,196 L116,174" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>
  <rect x="89" y="146" width="22" height="30" fill="#ffd9c4" stroke="#140a16" stroke-width="4"/>
  <ellipse cx="100" cy="106" rx="52" ry="55" fill="#ffe3d3" stroke="#140a16" stroke-width="5"/>
  <!-- bangs + sweatband -->
  <path d="M46,104 C42,52 68,36 100,36 C132,36 158,52 154,104 C144,84 132,76 124,72 C118,88 106,90 98,74 C90,88 70,94 46,104 Z" fill="#2b1a2e"/>
  <path d="M50,70 C80,56 120,56 150,70" fill="none" stroke="#29c4b0" stroke-width="11" stroke-linecap="round"/>
  <path d="M150,62 C172,54 182,70 176,88" fill="none" stroke="#2b1a2e" stroke-width="18" stroke-linecap="round"/>
  <!-- crying face -->
  <path d="M62,100 Q72,94 84,99 M138,100 Q128,94 116,99" fill="none" stroke="#2b1a2e" stroke-width="4" stroke-linecap="round"/>
  <path d="M64,110 L82,117 L64,124" fill="none" stroke="#2b1a2e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M136,110 L118,117 L136,124" fill="none" stroke="#2b1a2e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M74,124 C70,142 78,156 72,178" fill="none" stroke="#5ec8ff" stroke-width="9" stroke-linecap="round" opacity=".9"/>
  <path d="M126,124 C130,142 122,156 128,178" fill="none" stroke="#5ec8ff" stroke-width="9" stroke-linecap="round" opacity=".9"/>
  <path d="M40,116 q-7,11 0,16 q7,-5 0,-16 Z M160,116 q-7,11 0,16 q7,-5 0,-16 Z" fill="#5ec8ff"/>
  <ellipse cx="100" cy="142" rx="11" ry="9" fill="#5a1a2a" stroke="#140a16" stroke-width="3"/>
  <ellipse cx="100" cy="146" rx="6" ry="3.5" fill="#ff6f91"/>
  <ellipse cx="62" cy="132" rx="9" ry="5" fill="#ff6f91" opacity=".55"/>
  <ellipse cx="138" cy="132" rx="9" ry="5" fill="#ff6f91" opacity=".55"/>
</g>"""

# The banana pointer from banana-cursor-avatar.svg, without its square background.
BANANA = """
<g class="banana" transform="translate(-28,-14) scale(.5)">
  <path transform="translate(14 18)" d="M150 70Q105 210 150 342L214 278 262 390Q286 396 310 374L262 262 342 262Q220 200 150 70Z" fill="#000" opacity=".25"/>
  <g transform="rotate(-8 256 256)">
    <path d="M150 70Q105 210 150 342L214 278 262 390Q286 396 310 374L262 262 342 262Q220 200 150 70Z" fill="url(#bta-ban)" stroke="#3b2200" stroke-width="14" stroke-linejoin="round"/>
    <path d="M160 110Q135 210 160 300" fill="none" stroke="#c98a00" stroke-width="7" stroke-linecap="round" opacity=".6"/>
    <path d="M172 120Q158 190 168 235" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".7"/>
    <path d="M150 70Q140 52 130 38" stroke="#3b2200" stroke-width="30" stroke-linecap="round" fill="none"/>
    <path d="M150 70Q140 52 130 38" stroke="#7a4a12" stroke-width="14" stroke-linecap="round" fill="none"/>
    <path d="M290 391Q300 386 310 374" stroke="#7a4a12" stroke-width="10" stroke-linecap="round" fill="none"/>
    <ellipse cx="170" cy="215" rx="13" ry="17" fill="#fff" stroke="#3b2200" stroke-width="5"/>
    <ellipse cx="208" cy="223" rx="13" ry="17" fill="#fff" stroke="#3b2200" stroke-width="5"/>
    <circle cx="173" cy="219" r="7" fill="#3b2200"/><circle cx="211" cy="227" r="7" fill="#3b2200"/>
    <path d="M172 252Q192 274 214 256" fill="none" stroke="#3b2200" stroke-width="6" stroke-linecap="round"/>
    <ellipse cx="150" cy="248" rx="9" ry="5" fill="#ff6f91" opacity=".7"/>
    <ellipse cx="232" cy="262" rx="9" ry="5" fill="#ff6f91" opacity=".7"/>
  </g>
</g>"""

BAN_GRADIENT = ('<linearGradient id="bta-ban" x1="0" y1="0" x2="1" y2="1">'
                '<stop offset="0" stop-color="#fff176"/><stop offset=".6" stop-color="#ffd600"/>'
                '<stop offset="1" stop-color="#f9a825"/></linearGradient>')

WM_W, WM_H = 640, 290  # watermark canvas


def watermark_group():
    """Three characters in a row plus a small name tag, in a WM_W x WM_H box."""
    return f"""<g class="bta-watermark">
  <defs>{BAN_GRADIENT}</defs>
  <ellipse cx="320" cy="252" rx="300" ry="14" fill="#000" opacity=".18"/>
  <g transform="translate(10,10)">{BANANA}</g>
  <g transform="translate(220,14)">{CAT}</g>
  <g transform="translate(430,14)">{GIRL}</g>
  <g text-anchor="middle" font-family="Arial Black, Impact, Segoe UI, sans-serif" font-weight="900" font-size="26" letter-spacing="5">
    <text x="320" y="284" fill="#12042a" stroke="#12042a" stroke-width="7" stroke-linejoin="round">BANANA THEFT AUTO</text>
    <text x="320" y="284" fill="#ffe14d">BANANA THEFT AUTO</text>
  </g>
</g>"""


def write_watermark_svg():
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WM_W}" height="{WM_H}" viewBox="0 0 {WM_W} {WM_H}" '
           f'role="img" aria-label="Banana Theft Auto watermark">\n{watermark_group()}\n</svg>\n')
    (HERE / "watermark.svg").write_text(svg, encoding="utf-8")
    return svg


# ---------------------------------------------------------------- banner

BANNER_START, BANNER_END = "<!-- bta-crying-friends -->", "<!-- /bta-crying-friends -->"


def update_banner():
    path = HERE / "banner.svg"
    text = path.read_text(encoding="utf-8")
    text = re.sub(re.escape(BANNER_START) + r".*?" + re.escape(BANNER_END) + r"\n?", "", text, flags=re.S)
    friends = f"""{BANNER_START}
  <g transform="translate(288,116) scale(.76)">
    <ellipse cx="100" cy="240" rx="80" ry="10" fill="#000" opacity=".3"/>{CAT}
  </g>
  <g transform="translate(760,116) scale(.76)">
    <ellipse cx="100" cy="240" rx="80" ry="10" fill="#000" opacity=".3"/>{GIRL}
  </g>
  {BANNER_END}
"""
    anchor = '  <g font-family="Arial Black'
    assert anchor in text, "banner title group not found"
    text = text.replace(anchor, friends + anchor, 1)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- screenshots

SVG_SHOTS = sorted((LEONIDA / "docs" / "menu").glob("*.svg"))
PNG_SHOTS = [ROOT / "_preview-screenshot.png"]
WM_FRACTION = 0.30   # watermark width as a share of the screenshot width
WM_OPACITY = 0.5


def backup(path: Path) -> Path:
    dest = BACKUP / path.relative_to(ROOT)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return dest


def stamp_svg(path: Path):
    original = backup(path).read_text(encoding="utf-8")
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', original)
    w, h = float(m.group(1)), float(m.group(2))
    scale = w * WM_FRACTION / WM_W
    x = w - WM_W * scale - 12
    y = h - WM_H * scale - 10
    group = (f'<g id="bta-watermark" opacity="{WM_OPACITY}" transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})">'
             f'{watermark_group()}</g>')
    idx = original.rstrip().rfind("</svg>")
    path.write_text(original[:idx] + group + "\n</svg>\n", encoding="utf-8")


def stamp_png(path: Path, wm_svg: str):
    import cairosvg
    from PIL import Image
    base = Image.open(backup(path)).convert("RGBA")
    target_w = int(base.width * WM_FRACTION)
    png = cairosvg.svg2png(bytestring=wm_svg.encode(), output_width=target_w)
    wm = Image.open(io.BytesIO(png)).convert("RGBA")
    alpha = wm.getchannel("A").point(lambda a: int(a * WM_OPACITY))
    wm.putalpha(alpha)
    base.alpha_composite(wm, (base.width - wm.width - 16, base.height - wm.height - 12))
    base.convert("RGB").save(path)


def main():
    wm_svg = write_watermark_svg()
    update_banner()
    for p in SVG_SHOTS:
        stamp_svg(p)
    for p in PNG_SHOTS:
        if p.exists():
            stamp_png(p, wm_svg)
    print("banner, watermark.svg and", len(SVG_SHOTS) + len(PNG_SHOTS), "screenshots done")


if __name__ == "__main__":
    main()
