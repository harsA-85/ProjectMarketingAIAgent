"""Daily job: for each connected influencer, pick one IG draft that has no images yet,
break the post into 3 slide texts, and generate a 3-image carousel with story text
rendered in the influencer's visual style. Attach the images to the post.

Run from project root:  python scripts/daily_carousel_for_influencers.py

Designed to be safe to run daily — it skips posts that already have media_urls.
"""
import os, sys, json, re, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('carousel')

from src.database.db import get_db, init_db
from src.database.models import Agent, Content
from src.api.llm_provider import LLMProvider
from src.api.image_generator import GeminiImageGenerator
from scripts.bulk_generate_deception_posts import parse_json_loose

init_db()

CONNECTED_IDS = [1, 2, 3, 4, 5]


def pick_draft_for_agent(db, agent_id: int):
    """Pick the oldest IG draft for this agent that has no media yet."""
    candidates = (
        db.query(Content)
          .filter(Content.agent_id == agent_id,
                  Content.platform == 'instagram',
                  Content.status == 'draft')
          .order_by(Content.created_at.asc())
          .all()
    )
    for c in candidates:
        media = c.media_urls or []
        if isinstance(media, str):
            try:
                media = json.loads(media)
            except Exception:
                media = []
        if not media:
            return c
    return None


def break_into_slides(llm: LLMProvider, post_body: str, persona: str, tone: str, name: str) -> list:
    """Ask Claude to turn the IG post into 3 punchy slide texts (8-18 words each)."""
    prompt = (
        f"You are {name}. Persona: {persona}. Tone: {tone}.\n\n"
        f"Here is one of your Instagram posts:\n\n---\n{post_body}\n---\n\n"
        "Turn this into a 3-slide Instagram carousel. Each slide will appear as TEXT ON AN IMAGE, "
        "so the text must be SHORT, punchy, readable, and self-contained.\n\n"
        "RULES:\n"
        "- Slide 1 = HOOK. 6-12 words. Stops the scroll. A bold claim or question.\n"
        "- Slide 2 = REVEAL / PROOF. 10-18 words. The specific scam, trick, or data point.\n"
        "- Slide 3 = PUNCHLINE / TAKEAWAY. 6-14 words. The lesson, the warning, or the mic-drop.\n"
        "- All in your voice. No quotation marks around the slides.\n"
        "- Stay 100% in character. No broker-voice. You are an INFLUENCER, never write 'my client', 'my listing', 'I just sold'.\n\n"
        "Respond with ONLY valid JSON, no markdown:\n"
        '{"slides": ["slide 1 text", "slide 2 text", "slide 3 text"]}'
    )
    raw = llm.generate_content(prompt=prompt, system_prompt="", max_tokens=400)
    parsed = parse_json_loose(raw) or {}
    slides = parsed.get('slides') or []
    if isinstance(slides, list) and len(slides) >= 3:
        return [str(s).strip().strip('"').strip("'") for s in slides[:3]]
    return []


def build_carousel_prompts(slides: list, image_style: str, name: str) -> list:
    """Three Gemini prompts, each rendering one slide's text on a styled background."""
    prompts = []
    for i, slide_text in enumerate(slides, 1):
        # Escape any double quotes in the slide
        clean_text = slide_text.replace('"', "'")
        prompts.append(
            f"Square 1080x1080 Instagram carousel slide {i} of 3. "
            f"Visual style: {image_style}. "
            f"RENDER THIS EXACT TEXT prominently on the image, large bold sans-serif typography, "
            f"high contrast against the background, perfectly legible: \"{clean_text}\". "
            f"The text MUST be spelled exactly as provided — no extra letters, no missing letters. "
            f"Center the text or place it where it dominates the composition. "
            f"Background should match the visual style and reinforce the message thematically. "
            f"Editorial quality, social-media native, scroll-stopping. "
            f"No watermarks, no logos, no extra text other than the requested slide text. "
            f"For an influencer named {name} on the topic of real estate transparency."
        )
    return prompts


def process_agent(db, img_gen: GeminiImageGenerator, agent_id: int) -> bool:
    a = db.query(Agent).filter(Agent.id == agent_id).first()
    if not a:
        log.error(f"agent {agent_id} not found"); return False
    draft = pick_draft_for_agent(db, agent_id)
    if not draft:
        log.info(f"[{a.name}] no IG draft without media — nothing to do today")
        return False
    log.info(f"[{a.name}] picked draft #{draft.id}: {draft.title[:60]}…")

    llm = LLMProvider(provider=a.llm_provider or 'claude', model=a.llm_model)
    try:
        slides = break_into_slides(llm, draft.body or '', a.persona or '', a.tone_of_voice or '', a.name)
    except Exception as e:
        log.error(f"[{a.name}] slide-breakdown failed: {e}"); return False
    if not slides:
        log.error(f"[{a.name}] could not produce 3 slides"); return False
    log.info(f"[{a.name}] slides: " + " | ".join(s[:50] for s in slides))

    image_style = getattr(a, 'image_style', None) or 'ultra realistic photography'
    prompts = build_carousel_prompts(slides, image_style, a.name)
    images = img_gen.generate_carousel(prompts, retries=2)
    if len(images) < 3:
        log.error(f"[{a.name}] only got {len(images)}/3 images — skipping commit")
        return False

    draft.media_urls = images
    db.add(draft)
    db.commit()
    log.info(f"[{a.name}] ✅ attached 3-image carousel to draft #{draft.id}")
    return True


def main():
    db = get_db()
    try:
        img_gen = GeminiImageGenerator()
    except Exception as e:
        log.error(f"could not init Gemini: {e}"); return
    done = 0
    try:
        for aid in CONNECTED_IDS:
            try:
                if process_agent(db, img_gen, aid):
                    done += 1
            except Exception as e:
                log.error(f"agent {aid} crashed: {e}")
    finally:
        db.close()
    log.info(f"DAILY CAROUSEL DONE — {done}/5 influencers carouseled today.")


if __name__ == '__main__':
    main()
