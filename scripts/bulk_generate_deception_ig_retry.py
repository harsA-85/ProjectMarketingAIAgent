"""IG-only retry: 2 batches of 5 posts per agent, sequential, lower max_tokens to dodge 180s client timeout."""
import os, sys, json, re, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('ig_retry')

from src.database.db import get_db, init_db
from src.database.models import Agent, Content
from src.api.llm_provider import LLMProvider
from scripts.bulk_generate_deception_posts import TOPIC_BANK, parse_json_loose

init_db()

CONNECTED_IDS = [1, 2, 3, 4, 5]


def build_ig_prompt(agent_name, persona, tone, count, batch_label):
    return (
        f"You are writing {count} INSTAGRAM posts for yourself ({agent_name}). "
        f"This is {batch_label} — make sure these {count} posts cover DIFFERENT angles than any previous batch.\n"
        f"Persona: {persona}\nTone: {tone}\n\n"
        f"OVERARCHING THEME: real estate is deceiving — staged photos, virtual staging, choreographed tours, "
        f"brokers who work for the seller and the commission, and how a buyer gets screwed by trusting a "
        f"stranger with the biggest decision of their life. Each post = ONE specific angle.\n\n"
        f"{TOPIC_BANK}\n\n"
        f"PLATFORM RULES: Each Instagram caption must be 1200-1800 characters (long-form, layered, line breaks ok). "
        f"Tell a real story / specific scenario, not abstract slogans. Hook in line 1. "
        f"Each post hashtags array: 20-25 niche hashtags. "
        f"Body must NOT contain hashtags inline.\n\n"
        f"VOICE: stay 100% in character as {agent_name}. Vary openers. No two posts on the same angle. Specific > generic.\n\n"
        f"INFLUENCER CONSTRAINT (HARD): you are an INFLUENCER, not a broker/agent/realtor. NEVER write "
        f"\"my client\", \"my buyer\", \"my listing\", \"I just closed\", \"DM me to buy/sell\". You comment, "
        f"expose, analyze — you do not transact.\n\n"
        f"Respond with ONLY valid JSON, no markdown:\n"
        f'{{"posts": [{{"body": "...", "hashtags": ["tag1","tag2"]}}, ...]}}\n'
        f"Return exactly {count} posts."
    )


def run_one(agent_id: int):
    db = get_db()
    inserted = 0
    try:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return 0
        log.info(f"[{a.name}] IG batched retry starting")
        llm = LLMProvider(provider=a.llm_provider or 'claude', model=a.llm_model)
        system_prompt = (
            f"You are {a.name}.\nBrand: {a.brand}\nPersona: {a.persona}\n"
            f"Tone of Voice: {a.tone_of_voice}\nFields: {', '.join(a.fields or [])}\nBio: {a.bio or ''}\n\n"
            "CRITICAL: You are an INFLUENCER, not a broker/agent. No clients, no listings, no deals. "
            "Never use 'my client', 'my buyer', 'my listing', 'I just closed', 'DM me to buy/sell'."
        )
        for i, label in enumerate(['BATCH 1 of 2', 'BATCH 2 of 2'], 1):
            user_prompt = build_ig_prompt(a.name, a.persona or '', a.tone_of_voice or '', 5, label)
            try:
                raw = llm.generate_content(prompt=user_prompt, system_prompt=system_prompt, max_tokens=4500)
            except Exception as e:
                log.error(f"[{a.name}/ig batch {i}] LLM call failed: {e}")
                continue
            parsed = parse_json_loose(raw)
            if not parsed or 'posts' not in parsed:
                log.error(f"[{a.name}/ig batch {i}] failed to parse JSON; raw len={len(raw)}")
                continue
            posts = (parsed.get('posts') or [])[:5]
            log.info(f"[{a.name}/ig batch {i}] parsed {len(posts)} posts")
            for p in posts:
                body = (p.get('body') or '').strip()
                if not body:
                    continue
                hashtags = p.get('hashtags') or []
                if not isinstance(hashtags, list):
                    hashtags = []
                db.add(Content(
                    agent_id=agent_id, title=body[:100], body=body,
                    hashtags=hashtags, media_urls=[], platform='instagram', status='draft',
                ))
                inserted += 1
            db.commit()
        log.info(f"[{a.name}] committed {inserted} IG drafts total")
        return inserted
    finally:
        db.close()


def main():
    total = 0
    for aid in CONNECTED_IDS:
        total += run_one(aid)
    log.info(f"DONE — inserted {total} IG drafts.")


if __name__ == '__main__':
    main()
