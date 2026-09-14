"""Render the addon's original vector menu artwork (requires cairosvg)."""
from pathlib import Path
import io
import cairosvg
from PIL import Image

ICON_DIR = Path(__file__).resolve().parents[1] / 'resources/icons/polished'
# Vector sources are kept outside the addon package (dev-only): Kodi ships PNG
# art and kodi-addon-checker does not whitelist .svg inside the addon.
SVG_DIR = Path(__file__).resolve().parents[1] / 'scripts/icons-svg'
GLYPHS = {
    'continue': '<path d="M82 92a53 53 0 1 1-6 62M82 72v25H57"/><path d="m117 105 32 23-32 23z" fill="white" stroke="none"/>',
    'recommended': '<path d="m119 79 13 35 36 13-36 13-13 36-13-36-36-13 36-13zM176 74v26m-13-13h26"/>',
    'preview': '<path d="M69 128s23-38 59-38 59 38 59 38-23 38-59 38-59-38-59-38z"/><path d="m121 112 22 16-22 16z" fill="white" stroke="none"/>',
    'top10': '<path d="M99 78h58v38a29 29 0 0 1-58 0zM99 89H77v15a26 26 0 0 0 25 26m55-41h22v15a26 26 0 0 1-25 26m-26 15v32m-25 0h50"/>',
    'genres': '<rect x="77" y="77" width="42" height="42" rx="8"/><rect x="137" y="77" width="42" height="42" rx="8"/><rect x="77" y="137" width="42" height="42" rx="8"/><rect x="137" y="137" width="42" height="42" rx="8"/>',
    'romance': '<path d="M128 180 82 134c-39-42 19-77 46-38 27-39 85-4 46 38z"/>',
    'crime': '<circle cx="106" cy="138" r="27"/><circle cx="164" cy="107" r="27"/><path d="m128 122 14-8m-64 24h18m68-58v18"/>',
    'action': '<path d="m140 68-58 70h41l-9 51 60-76h-43z"/>',
    'awards': '<circle cx="128" cy="106" r="34"/><path d="m104 133-13 54 37-20 37 20-13-54"/><path d="m128 85 6 13 15 2-11 11 3 15-13-7-13 7 3-15-11-11 15-2z" stroke-width="4"/>',
    'autumn': '<path d="M87 166C58 102 119 86 179 75c-6 64-28 112-79 94M78 184l77-80m-40 41-5-30m20 17 25 2"/>',
    'recent': '<circle cx="128" cy="126" r="51"/><path d="M128 93v35l24 15"/><path d="M174 69v28m-14-14h28" stroke="#ff3547"/>',
    'night': '<path d="M146 77a52 52 0 1 0 33 77 48 48 0 0 1-33-77zM173 88v20m-10-10h20"/>',
    'featured': '<path d="m128 72 17 35 39 6-28 27 7 39-35-18-35 18 7-39-28-27 39-6z"/>',
    'home': '<path d="M72 124 128 76l56 48M86 115v65h30v-40h24v40h30v-65"/>',
    'films': '<rect x="73" y="84" width="110" height="92" rx="10"/><path d="M96 84v92m64-92v92M74 108h22m-22 44h22m64-44h22m-22 44h22"/><path d="m117 112 26 18-26 18z" fill="white" stroke="none"/>',
    'series': '<rect x="75" y="94" width="106" height="80" rx="10"/><path d="M88 80h80m-66-14h52"/><path d="m118 117 27 18-27 18z" fill="white" stroke="none"/>',
    'programmas': '<rect x="72" y="91" width="112" height="79" rx="10"/><path d="m105 70 23 21 23-21m-40 116h34"/>',
    'kids': ('<circle cx="92" cy="80" r="13"/><circle cx="164" cy="80" r="13"/>'
             '<ellipse cx="128" cy="110" rx="46" ry="39"/>'
             '<circle cx="108" cy="101" r="4.5" fill="white" stroke="none"/>'
             '<circle cx="148" cy="101" r="4.5" fill="white" stroke="none"/>'
             '<ellipse cx="128" cy="123" rx="19" ry="13"/>'
             '<circle cx="128" cy="116" r="3.5" fill="white" stroke="none"/>'
             '<path d="M120 128q7 6 16 0"/>'
             '<ellipse cx="106" cy="190" rx="16" ry="10"/><ellipse cx="150" cy="190" rx="16" ry="10"/>'
             '<ellipse cx="82" cy="160" rx="10" ry="18"/><ellipse cx="174" cy="160" rx="10" ry="18"/>'
             '<ellipse cx="128" cy="163" rx="29" ry="21"/>'),
    'trending': '<path d="m77 166 35-36 26 18 42-57m-35 0h35v35"/>',
    'zoeken': '<circle cx="117" cy="115" r="37"/><path d="m145 143 34 34"/>',
    'cache': '<path d="M92 104v73h72v-73M82 90h92m-60-15h28m-29 45v34m30-34v34"/>',
    'aanmelden': '<path d="M139 77h36v102h-36M75 128h69m-23-24 24 24-24 24"/>',
    'afmelden': '<path d="M117 77H81v102h36m-5-51h69m-23-24 24 24-24 24"/>',
    'profiel': '<circle cx="128" cy="100" r="25"/><path d="M81 181v-9a47 38 0 0 1 94 0v9"/>',
    'kijklijst': '<path d="M92 77h72v107l-36-23-36 23z"/>',
}
GLYPHS['collection'] = GLYPHS['series']


def _glyph_bbox(glyph, size=512):
    """Return the stroke bounding box in 0-256 layout coords."""
    probe = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 256 256">
<g fill="none" stroke="white" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">{glyph}</g></svg>'''
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=probe.encode(), write_to=buf)
    alpha = Image.open(buf).convert('RGBA').split()[3]
    scale = 256 / size
    xs, ys = [], []
    for y in range(size):
        for x in range(size):
            if alpha.getpixel((x, y)) > 0:
                xs.append(x)
                ys.append(y)
    return min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale


def _list_viewbox(glyph):
    """Fit the glyph into Estuary's 32px list indicator (default 60 60 136 136).

    The default box suits the compact glyphs; any glyph that overflows it (e.g.
    a taller teddy bear) gets its viewBox widened so nothing is clipped.
    """
    x0, y0, x1, y1 = _glyph_bbox(glyph)
    vx = min(60, x0 - 8)
    vy = min(60, y0 - 8)
    vx1 = max(196, x1 + 8)
    vy1 = max(196, y1 + 8)
    return "{:.1f} {:.1f} {:.1f} {:.1f}".format(vx, vy, vx1 - vx, vy1 - vy)


ICON_DIR.mkdir(parents=True, exist_ok=True)
SVG_DIR.mkdir(parents=True, exist_ok=True)
for name, glyph in GLYPHS.items():
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 256 256">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#29272b"/><stop offset="1" stop-color="#111114"/></linearGradient></defs>
<rect x="8" y="8" width="240" height="240" rx="48" fill="url(#bg)" stroke="#454047" stroke-width="2"/>
<rect x="105" y="31" width="46" height="5" rx="2.5" fill="#ff3547"/>
<g fill="none" stroke="#f6f5f6" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">{glyph}</g>
</svg>'''
    (SVG_DIR / (name + '.svg')).write_text(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(ICON_DIR / (name + '.png')))
    # Compact transparent glyph for Estuary's 32px list-row indicator.
    list_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="{_list_viewbox(glyph)}">
<g fill="none" stroke="white" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">{glyph}</g></svg>'''
    cairosvg.svg2png(bytestring=list_svg.encode(), write_to=str(ICON_DIR / ('list-' + name + '.png')))
