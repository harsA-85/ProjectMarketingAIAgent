"""One-shot: generate 10 IG + 10 Twitter draft posts per connected agent on
the 'real estate is deceiving / brokers don't work for you' theme.

Run from project root:  python scripts/bulk_generate_deception_posts.py
"""
import os, sys, json, re, logging, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('bulk_gen')

from src.database.db import get_db, init_db
from src.database.models import Agent, Content
from src.api.llm_provider import LLMProvider

init_db()

CONNECTED_IDS = [1, 2, 3, 4, 5]   # only fully-connected agents

TOPIC_BANK = """
Topic pool — pick from these, vary across the 10 posts, and add your own angles in your authentic voice:

DECEPTION / FAKE PRESENTATION
- Listing photos are virtually staged — the actual room is empty, smaller, darker
- Wide-angle lens fisheye trick that turns a 9 m² bedroom into "spacious"
- Twilight HDR exterior shots taken once, used for years even after the building decayed
- "Newly renovated" = paint job over rotten subfloors / crumbling pipes
- Floor plans drawn loosely — closets and pillars deleted from the rendering
- The single curated angle of the kitchen, never the wall behind the camera
- Magic-hour photo of the street; in reality there is a bus depot 50m away

STAGED TOURS / TIMING TRICKS
- Tours scheduled at the only hour the apartment gets sun
- Visits routed to avoid the rush-hour traffic jam, the school gate at 3pm, the bar crowd at 9pm
- Garbage collection day = avoided. Construction next door = not mentioned.
- Heating turned on full blast in winter / AC blasting in summer to mask broken systems
- Air freshener / coffee on the stove to hide mold or sewage smells
- Furniture placed to hide cracked tiles, water stains, sloped floors
- Music playing during showings to mask the noise from the neighbor / the highway

INCENTIVE MISALIGNMENT
- The agent works for the SELLER, not for you — by law in most states
- Dual agency: same broker, both sides, "neutral" — yes, neutrally screwing you twice
- 3% commission on a 25-year decision means the agent earns more by closing fast than closing right
- The buyer's agent who pushes you to bid higher: their cut grows with the price
- "Off-market exclusive" often means the agent is shopping it to their commission-friendlier network first
- Pocket listings and steering — you only see what their split allows

INFORMATION ASYMMETRY / HIDING DEFECTS
- Special assessment in the co-op minutes — never disclosed unless you read the docs yourself
- Pending lawsuit against the HOA — mysteriously missing from the brochure
- Last 3 sale prices in the building, all lower than ask — somehow not in the comp sheet
- Days-on-market reset trick: relist to look "fresh"
- Square footage measured generously, including chimney shafts and unfinished basements
- Flood zone reclassification, lead paint, asbestos, knob-and-tube wiring — "minor"
- Noisy neighbors / pending eviction upstairs — the broker knows, you don't

TRUST / EMOTIONAL EXPLOITATION
- You're handing the most critical decision of your life — 25 years of payments — to a stranger you met 3 weeks ago
- If the broker betrays you, no one ever finds out. No public review. No accountability.
- "We have 3 other offers" — half the time, fabricated urgency
- The fake "I just got off the phone with another buyer" line at the showing
- Pressure tactics aimed at first-time buyers: "this is a unicorn, you'll regret it"
- The ones most likely to be screwed: solo buyers, immigrants, out-of-towners, anyone the broker reads as "polite"

PROCESS / FINANCIAL TRAPS
- The "preferred lender" who quietly kicks back to the broker
- The "preferred inspector" who never finds anything serious
- Closing cost surprises — title fees, transfer taxes, attorney "review" fees that magically appear at signing
- Mortgage broker pushing the longest, most expensive product because the rebate is bigger
- Earnest money you can lose because the contingency clause was "standard" — and weak
""".strip()


PLATFORM_RULES = {
    'instagram': {
        'count': 10,
        'rules': (
            "Each Instagram caption must be 1500-2100 characters (long-form, layered, line breaks ok). "
            "Tell a real story / specific scenario, not abstract slogans. Hook in line 1. "
            "Each post hashtags array: 20-25 niche hashtags (mix broad + targeted). "
            "Body must NOT contain hashtags inline; put them only in the hashtags array. "
            "Use line breaks generously for IG readability."
        )
    },
    'twitter': {
        'count': 10,
        'rules': (
            "Each tweet body MUST be a SINGLE standalone tweet under 260 characters TOTAL "
            "(emojis count as 2 chars each). Aim for 220-250 chars. "
            "No threads. No 1/, 2/ numbering. Punchy, opinionated, viral-bait energy. "
            "hashtags array: 0-2 hashtags max (Twitter culture). "
            "Body should NOT contain hashtags inline."
        )
    },
}


def build_user_prompt(platform: str, agent_name: str, persona: str, tone: str) -> str:
    rules = PLATFORM_RULES[platform]
    return (
        f"You are writing 10 {platform.upper()} posts for yourself ({agent_name}). "
        f"Your persona: {persona}\n"
        f"Your tone: {tone}\n\n"
        f"OVERARCHING THEME: real estate is deceiving — staged photos, virtually staged rooms, "
        f"choreographed tours timed for perfect sun and zero traffic, brokers who work for the seller "
        f"and the commission (not for you), and the dozens of ways a buyer gets screwed by trusting a "
        f"stranger with the biggest decision of their life. Each post should pick ONE specific angle "
        f"and drive it home in your voice.\n\n"
        f"{TOPIC_BANK}\n\n"
        f"PLATFORM RULES: {rules['rules']}\n\n"
        f"VOICE REMINDER: stay 100% in character as {agent_name}. Vary the openers across the 10 posts. "
        f"No two posts should attack the same angle. Be specific, not generic. Real scenarios > abstract rant.\n\n"
        f"INFLUENCER CONSTRAINT (HARD): you are an INFLUENCER, not a broker/agent/realtor. NEVER write "
        f"\"my client\", \"my buyer\", \"my listing\", \"I just closed\", \"DM me to buy/sell\", or any "
        f"first-person broker language. You comment, expose, analyze — you do not transact.\n\n"
        f"Respond with ONLY a valid JSON object, no markdown, no code fences. Format:\n"
        f'{{"posts": [{{"body": "...", "hashtags": ["tag1","tag2"]}}, ...]}}\n'
        f"You MUST return exactly {rules['count']} posts."
    )


def parse_json_loose(raw: str):
    cleaned = re.sub(r'```(?:json)?', '', raw).strip().strip('`').strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[\s\S]*\}', cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def generate_for_agent(agent_id: int, results: dict):
    db = get_db()
    try:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            log.error(f"Agent {agent_id} not found")
            return
        log.info(f"[{a.name}] starting generation")
        llm = LLMProvider(provider=a.llm_provider or 'claude', model=a.llm_model)

        system_prompt = (
            f"You are {a.name}.\n"
            f"Brand: {a.brand}\n"
            f"Persona: {a.persona}\n"
            f"Tone of Voice: {a.tone_of_voice}\n"
            f"Fields: {', '.join(a.fields or [])}\n"
            f"Bio: {a.bio or ''}\n\n"
            "CRITICAL ROLE CONSTRAINT: You are an INFLUENCER and commentator on real estate — "
            "NOT a real estate agent, broker, or realtor. You do NOT have clients, buyers, sellers, "
            "listings, deals, transactions, or commissions. NEVER write from a broker/agent point of "
            "view. NEVER use phrases like 'my client', 'my buyer', 'my seller', 'I just closed', "
            "'I just sold', 'my listing', 'DM me to buy/sell', 'let me help you find a home'. You "
            "comment, observe, analyze, and tell stories about real estate because you love it — you "
            "don't transact in it."
        )

        agent_posts = {'instagram': [], 'twitter': []}
        for platform in ('instagram', 'twitter'):
            user_prompt = build_user_prompt(platform, a.name, a.persona or '', a.tone_of_voice or '')
            try:
                raw = llm.generate_content(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=8000,
                )
            except Exception as e:
                log.error(f"[{a.name}/{platform}] LLM call failed: {e}")
                continue

            parsed = parse_json_loose(raw)
            if not parsed or 'posts' not in parsed:
                log.error(f"[{a.name}/{platform}] failed to parse JSON; raw len={len(raw)}")
                continue
            posts = parsed.get('posts') or []
            log.info(f"[{a.name}/{platform}] parsed {len(posts)} posts")
            agent_posts[platform] = posts[:10]

        results[agent_id] = (a.name, agent_posts)
    finally:
        db.close()


def insert_drafts(results: dict):
    db = get_db()
    inserted = 0
    try:
        for agent_id, (agent_name, by_platform) in results.items():
            for platform, posts in by_platform.items():
                for p in posts:
                    body = (p.get('body') or '').strip()
                    if not body:
                        continue
                    if platform == 'twitter' and len(body) > 280:
                        body = body[:257].rstrip() + '...'
                    hashtags = p.get('hashtags') or []
                    if not isinstance(hashtags, list):
                        hashtags = []
                    title = body[:100]
                    c = Content(
                        agent_id=agent_id,
                        title=title,
                        body=body,
                        hashtags=hashtags,
                        media_urls=[],
                        platform=platform,
                        status='draft',
                    )
                    db.add(c)
                    inserted += 1
            db.commit()
            log.info(f"[{agent_name}] committed drafts (running total inserted={inserted})")
    finally:
        db.close()
    return inserted


def main():
    results = {}
    threads = []
    for aid in CONNECTED_IDS:
        t = threading.Thread(target=generate_for_agent, args=(aid, results), name=f'gen-{aid}')
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=600)

    log.info(f"All generators returned. Inserting drafts for {len(results)} agents...")
    n = insert_drafts(results)
    log.info(f"DONE — inserted {n} drafts.")


if __name__ == '__main__':
    main()
