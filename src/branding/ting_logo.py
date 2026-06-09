"""Render the official Ting logo (gold gradient pill + 'Ting' wordmark) as an
RGBA PIL image, faithful to ting-logo.svg, and composite it onto campaign ads.

The wordmark letters are rasterized from the real SVG (white fill renders fine);
the gold gradient pill is redrawn in PIL because svglib can't handle the SVG's
linear-gradient url() fill. Geometry & gradient stops are taken verbatim from
the SVG so the lockup matches the brand asset exactly.

SVG reference (viewBox 0 0 84.5713 40):
  - Pill 'Rectangle 7041': rounded vertical capsule, x[0..24.1632], y[0..40],
    radius 12.0816; vertical gradient #FFCC00 (bottom, opaque) → transparent
    (~81% up), gradient line y1=39.4199 → y2=3.98487.
  - 'Ting' wordmark: white letter paths spanning x≈28.2 .. 84.57.
"""
from __future__ import annotations
import os, io, re
from typing import Optional
from PIL import Image, ImageDraw

# viewBox + pill geometry (verbatim from the SVG)
VB_W, VB_H = 84.5713, 40.0
PILL_X0, PILL_X1 = 0.0, 24.1632
PILL_R = 12.0816
GRAD_Y1, GRAD_Y2 = 39.4199, 3.98487   # bottom (t=0) → top (t=1)
GRAD_STOP_TRANSPARENT = 0.81           # alpha hits 0 at this t
GOLD = (255, 204, 0)                   # #FFCC00

_DEFAULT_SVG = os.path.join(os.path.dirname(__file__), 'assets', 'ting-logo.svg')


def _wordmark_only_svg(svg_text: str) -> str:
    """Strip the gold pill path so only the white 'Ting' wordmark remains
    (svglib renders solid white fills correctly; the gradient pill it cannot)."""
    # Remove the <path id='Rectangle 7041' .../> element (the pill)
    out = re.sub(r"<path[^>]*id=['\"]Rectangle[^>]*?/>", "", svg_text)
    return out


def _render_wordmark(svg_text: str, height_px: int) -> Image.Image:
    """Rasterize the white wordmark on black, return an RGBA cream image with
    luminance-derived alpha (clean anti-aliased edges, transparent background)."""
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM

    scale = height_px / VB_H
    tmp = _wordmark_only_svg(svg_text)
    drawing = svg2rlg(io.StringIO(tmp))
    drawing.scale(scale, scale)
    drawing.width = int(VB_W * scale)
    drawing.height = int(VB_H * scale)
    pil = renderPM.drawToPIL(drawing, bg=0x000000)  # black bg, white letters
    lum = pil.convert('L')                          # luminance == letter alpha
    cream = Image.new('RGBA', pil.size, (244, 239, 224, 0))
    cream.putalpha(lum)
    return cream


def _render_pill(height_px: int) -> Image.Image:
    """Draw the gold gradient vertical capsule on a transparent canvas sized to
    the full logo viewBox, positioned exactly where the SVG places it."""
    scale = height_px / VB_H
    W = int(VB_W * scale)
    H = int(VB_H * scale)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))

    # Per-row gold with the SVG's vertical alpha gradient
    grad = Image.new('RGBA', (1, H), (0, 0, 0, 0))
    for py in range(H):
        y_vb = (py / scale)
        t = (y_vb - GRAD_Y1) / (GRAD_Y2 - GRAD_Y1)  # 0 at bottom → 1 at top
        if t <= 0:
            a = 255
        elif t >= GRAD_STOP_TRANSPARENT:
            a = 0
        else:
            a = int(round(255 * (1 - t / GRAD_STOP_TRANSPARENT)))
        grad.putpixel((0, py), (GOLD[0], GOLD[1], GOLD[2], a))
    grad = grad.resize((int((PILL_X1 - PILL_X0) * scale), H))

    # Rounded-capsule mask for the pill
    pill_w = int((PILL_X1 - PILL_X0) * scale)
    mask = Image.new('L', (pill_w, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, pill_w - 1, H - 1], radius=int(PILL_R * scale), fill=255)

    pill = Image.new('RGBA', (pill_w, H), (0, 0, 0, 0))
    pill = Image.composite(grad, pill, mask)
    canvas.alpha_composite(pill, (int(PILL_X0 * scale), 0))
    return canvas


def render_logo(height_px: int = 56, svg_path: Optional[str] = None) -> Image.Image:
    """Return the full Ting logo (pill + wordmark) as a transparent RGBA image
    of the given height."""
    svg_path = svg_path or _DEFAULT_SVG
    with open(svg_path, 'r', encoding='utf-8') as f:
        svg_text = f.read()
    wordmark = _render_wordmark(svg_text, height_px)
    pill = _render_pill(height_px)
    logo = Image.alpha_composite(pill, wordmark)
    return logo


def overlay_logo(image: Image.Image, height_px: int = 56,
                 margin_x: int = 72, margin_y: int = 64,
                 anchor: str = 'bottom-left',
                 svg_path: Optional[str] = None) -> Image.Image:
    """Composite the Ting logo onto `image` (RGB). Returns RGB."""
    base = image.convert('RGBA')
    logo = render_logo(height_px, svg_path)
    W, H = base.size
    lw, lh = logo.size
    if anchor == 'bottom-left':
        x, y = margin_x, H - margin_y - lh
    elif anchor == 'bottom-center':
        x, y = (W - lw) // 2, H - margin_y - lh
    else:
        x, y = margin_x, H - margin_y - lh
    base.alpha_composite(logo, (x, y))
    return base.convert('RGB')
