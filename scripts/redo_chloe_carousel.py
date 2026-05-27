"""Redo draft #337 carousel for Chloe Martinez. Gemini draws clean text-free
'before/after Instagram-vs-Reality' backgrounds; we overlay the captions
ourselves with PIL — perfect spelling, no Gemini gibberish.

Captions are HAND-WRITTEN below in Chloe's voice:
  Persona: The Fake Staging Victim. Sarcastic. Mocking brokers who use
  Photoshop to hide garbage. Sharp wit, zero patience for deceptive listings.
"""
import os, sys, base64, io, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('redo337')

from src.database.db import get_db, init_db
from src.database.models import Content
from src.api.image_generator import GeminiImageGenerator
from scripts.redo_frenchimmoagent_carousel import overlay_text  # reuse PIL helper

init_db()

DRAFT_ID = 337

# ─── Hand-written captions (mine, not LLM) — Chloe's sarcastic voice ──
SLIDES = [
    "I ran the AI destager.\nI almost fell off my chair.",
    "The sofa hid buckled floors.\nThe fig tree hid a crack\nrunning floor-to-ceiling.",
    "Run the destager\nBEFORE you fall in love.\nThe furniture is lying.",
]

# ─── Background prompts — text-free, Instagram-vs-Reality split aesthetic ──
BACKGROUND_PROMPTS = [
    (
        "Square 1080x1080 Instagram-vs-Reality split screen photograph. "
        "LEFT half: a beautifully staged living room with a linen sofa, fiddle-leaf fig plant, "
        "warm Edison bulbs, polished hardwood — looks like a Pinterest magazine shot. "
        "RIGHT half: the SAME ROOM completely empty and revealed — concrete floor, water-stained "
        "ceiling, peeling baseboards, raw exposed walls. Cinematic real-estate documentary look. "
        "Leave a calm horizontal CENTRAL strip free of clutter for text overlay. "
        "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY, NO CAPTIONS, NO LABELS anywhere. "
        "Photojournalism quality. Sharp contrast between the two halves. No watermarks."
    ),
    (
        "Square 1080x1080 photograph. A gorgeous linen sofa positioned in a staged living room — "
        "but the sofa is slightly translucent / ghosted, revealing what is hidden BENEATH it: "
        "deeply buckled, warped wooden floorboards. Behind it, a fiddle-leaf fig plant ALSO "
        "translucent, revealing a long crack running from floor to ceiling in the drywall behind. "
        "Editorial photography, dramatic mood, a thin red laser-pointer beam pointing toward the "
        "concealed damage. Soft daylight from a window. "
        "Leave the upper-center area as a calm wall surface for text overlay. "
        "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY, NO CAPTIONS anywhere. "
        "Cinematic real-estate exposé aesthetic. No watermarks."
    ),
    (
        "Square 1080x1080 photograph. A pair of hands holding a smartphone above a glossy "
        "real-estate listing photo of a beautiful staged apartment — but on the smartphone screen, "
        "the AI-destaged version is shown: same room but EMPTY, revealing structural damage, "
        "water stains, cracked floors. The contrast between the magazine-quality print and the raw "
        "phone-screen reality is the focus. Moody studio lighting, journalistic tone. "
        "Leave the LOWER half as a calm dark/neutral surface for text overlay. "
        "ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO TYPOGRAPHY, NO CAPTIONS, NO LABELS anywhere "
        "(neither on the print nor on the phone screen). "
        "Cinematic, editorial, sharp wit. No watermarks."
    ),
]


def main():
    db = get_db()
    try:
        draft = db.query(Content).filter(Content.id == DRAFT_ID).first()
        if not draft:
            log.error(f"draft {DRAFT_ID} not found"); return
        log.info(f"redoing carousel for draft #{draft.id} ({draft.title[:60]})")

        img_gen = GeminiImageGenerator()
        finals = []
        for i, (prompt, slide_text) in enumerate(zip(BACKGROUND_PROMPTS, SLIDES), 1):
            log.info(f"slide {i}: generating background…")
            bg = None
            for attempt in range(3):
                bg = img_gen.generate_image(prompt)
                if bg:
                    break
                log.warning(f"slide {i} bg attempt {attempt+1} failed")
            if not bg:
                log.error(f"slide {i} bg failed all retries — aborting"); return
            log.info(f"slide {i}: overlaying text → {slide_text!r}")
            finals.append(overlay_text(bg, slide_text))

        if len(finals) != 3:
            log.error(f"only {len(finals)}/3 final images — aborting"); return

        draft.media_urls = finals
        db.add(draft); db.commit()
        log.info(f"DONE — replaced 3 carousel images on draft #{DRAFT_ID}")
    finally:
        db.close()


if __name__ == '__main__':
    main()
