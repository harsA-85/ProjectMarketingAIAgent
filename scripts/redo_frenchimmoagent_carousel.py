"""Redo draft #312 carousel for Frenchimmoagent: Gemini draws a clean text-free
cartoon background (his actual image_style), then we overlay the slide text
ourselves with PIL — perfect spelling, proper typography.

Captions are HAND-WRITTEN below (not LLM-generated) in Frenchimmoagent's voice:
  Persona: Enthusiastic community builder, funny, satiric, ironic.
  The post is about virtual staging — beautiful $30 lies that sell feelings.
"""
import os, sys, base64, io, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('redo312')

from PIL import Image, ImageDraw, ImageFont
from src.database.db import get_db, init_db
from src.database.models import Content
from src.api.image_generator import GeminiImageGenerator

init_db()

DRAFT_ID = 312

# ─── Hand-written slides (mine, not LLM) ──────────────────────────
# Frenchimmoagent voice: enthusiastic, funny, satiric, ironic — talks about
# virtual staging as a beautiful $30 lie that sells feelings, not apartments.
SLIDES = [
    "That dreamy bedroom?\nIt's a $30 lie.",
    "Empty beige box\n+ virtual staging\n= your Pinterest fantasy.",
    "They don't sell apartments.\nThey sell feelings.\n(And feelings close deals.)",
]

# ─── Background image prompts — text-free cartoon backgrounds ────
# His image_style: "cartoon illustration, colorful and fun"
BACKGROUND_PROMPTS = [
    (
        "Square 1080x1080 cartoon illustration, colorful and fun flat-vector style. "
        "A cozy bedroom scene that looks too perfect to be real — staged Scandinavian sofa, "
        "soft pastel sunlight through a window, a houseplant, a stack of design magazines. "
        "Slight surreal sparkle effect to hint that something is fake / dreamy. "
        "Leave the CENTER of the image visually CALM and uncluttered — a soft pastel area "
        "where text will be added later. ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY "
        "anywhere in the image. Vibrant color palette: peach, sage green, cream, soft blue. "
        "Cute satirical mood. No watermarks."
    ),
    (
        "Square 1080x1080 cartoon illustration, colorful and fun flat-vector style. "
        "Split visual: left half shows a sad empty beige bedroom with cracked baseboards "
        "and a single bare bulb. Right half shows the same room transformed — full of "
        "trendy Scandinavian furniture, plants, golden-hour light. A small floating "
        "30-dollar bill sticker between the two halves. "
        "Leave a calm CENTRAL band horizontally for text overlay. "
        "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY anywhere. "
        "Vibrant colors: beige and grey on the left, peach and green and cream on the right. "
        "Satirical, ironic, fun. No watermarks."
    ),
    (
        "Square 1080x1080 cartoon illustration, colorful and fun flat-vector style. "
        "A smiling cartoon character holding a giant cartoon HEART balloon with a tiny "
        "apartment building floating inside it. The character is being gently pulled "
        "off the ground by the balloon, dreamy expression. Confetti and sparkles. "
        "Leave the LOWER HALF of the image as a calm soft sky-blue area for text overlay. "
        "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY anywhere. "
        "Bright cheerful palette: peach, sage, cream, sky blue. "
        "Mood: ironic warmth — feelings close deals. No watermarks."
    ),
]

# ─── PIL overlay ──────────────────────────────────────────────────
FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"


def wrap_lines(draw, words, font, max_width):
    lines = []
    cur = ''
    for w in words:
        test = (cur + ' ' + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def overlay_text(image_b64: str, text: str) -> str:
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw)).convert('RGBA')
    if img.size != (1080, 1080):
        img = img.resize((1080, 1080))

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    margin = 70
    max_width = 1080 - 2 * margin

    # Each "\n" in the input is a hard line break — render block-by-block, then word-wrap each block.
    blocks = text.split('\n')
    # Choose a font size that makes the longest single block fit, capped at 110, floor 56
    best_size = 56
    for size in range(110, 55, -4):
        font = ImageFont.truetype(FONT_BOLD, size)
        ok = True
        for blk in blocks:
            if not blk.strip():
                continue
            wrapped = wrap_lines(draw, blk.split(), font, max_width)
            for ln in wrapped:
                bbox = draw.textbbox((0, 0), ln, font=font)
                if bbox[2] - bbox[0] > max_width:
                    ok = False; break
            if not ok:
                break
        if ok:
            best_size = size
            break

    font = ImageFont.truetype(FONT_BOLD, best_size)

    # Build final lines
    final_lines = []
    for blk in blocks:
        if not blk.strip():
            final_lines.append('')
            continue
        wrapped = wrap_lines(draw, blk.split(), font, max_width)
        final_lines.extend(wrapped)

    line_height = int(best_size * 1.18)
    total_h = len(final_lines) * line_height
    y0 = (1080 - total_h) // 2

    # Semi-transparent dark rectangle for legibility
    pad_x, pad_y = 36, 28
    rect = [margin - pad_x, y0 - pad_y, 1080 - margin + pad_x, y0 + total_h + pad_y]
    draw.rounded_rectangle(rect, radius=24, fill=(0, 0, 0, 175))

    # Draw text lines centered, white with subtle shadow
    y = y0
    for ln in final_lines:
        if ln == '':
            y += line_height
            continue
        bbox = draw.textbbox((0, 0), ln, font=font)
        line_w = bbox[2] - bbox[0]
        x = (1080 - line_w) // 2
        # shadow
        draw.text((x + 3, y + 3), ln, fill=(0, 0, 0, 220), font=font)
        # main
        draw.text((x, y), ln, fill=(255, 255, 255, 255), font=font)
        y += line_height

    out = Image.alpha_composite(img, overlay).convert('RGB')
    buf = io.BytesIO()
    out.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def main():
    db = get_db()
    try:
        draft = db.query(Content).filter(Content.id == DRAFT_ID).first()
        if not draft:
            log.error(f"draft {DRAFT_ID} not found"); return
        log.info(f"redoing carousel for draft #{draft.id} ({draft.title[:50]})")

        img_gen = GeminiImageGenerator()
        final_images = []
        for i, (bg_prompt, slide_text) in enumerate(zip(BACKGROUND_PROMPTS, SLIDES), 1):
            log.info(f"slide {i}: generating background…")
            bg = None
            for attempt in range(3):
                bg = img_gen.generate_image(bg_prompt)
                if bg:
                    break
                log.warning(f"slide {i} bg attempt {attempt+1} failed; retrying")
            if not bg:
                log.error(f"slide {i} bg failed all retries — skipping"); return
            log.info(f"slide {i}: overlaying text → {slide_text!r}")
            final = overlay_text(bg, slide_text)
            final_images.append(final)

        if len(final_images) != 3:
            log.error(f"only {len(final_images)}/3 final images — aborting"); return

        draft.media_urls = final_images
        db.add(draft); db.commit()
        log.info(f"DONE — replaced 3 carousel images on draft #{DRAFT_ID}")
    finally:
        db.close()


if __name__ == '__main__':
    main()
