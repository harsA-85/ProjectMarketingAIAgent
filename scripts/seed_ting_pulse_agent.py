"""Create the Ting Pulse ambassador agent (Twitter-only social-proof feed)
and seed 50 tweet drafts.

Tweets are 'real-time activity feed' style — single-user signups, multi-agent
reach-outs, and live city-pulse counts. NO marketing fluff, NO 10k milestones,
NO slogans. Just terse, plausible status updates that read like a system feed.

Run from project root:  python scripts/seed_ting_pulse_agent.py
Safe to re-run — won't double-insert the agent; will only add more tweets.
"""
import os, sys, json, re, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('ting_pulse')

from src.database.db import get_db, init_db
from src.database.models import Agent, Content
from src.api.llm_provider import LLMProvider
from scripts.bulk_generate_deception_posts import parse_json_loose

init_db()

AGENT_NAME = "Ting Pulse"

AGENT_DEFAULTS = {
    'name': AGENT_NAME,
    'brand': 'Ting',
    'persona': (
        "Real-time activity feed for Ting — the platform where buyers and sellers find vetted real estate "
        "agents that actually work for them. Posts plausible-sounding live status updates: who just signed "
        "up, who just reached out to agents, how many people are currently active in each city. Reads like "
        "a Stripe / Vercel status feed, not like marketing."
    ),
    'tone_of_voice': (
        "Terse, factual, status-feed flat tone. No emoji unless functional. No slogans, no hype, no growth "
        "metrics, no exclamation points, no '10k users' announcements. Just one short concrete activity per "
        "tweet. Sometimes adds the platform handle 'ting.co' or '@ting' at the end, but not always."
    ),
    'bio': (
        "Live signup & agent-request feed from Ting. Buyers, sellers, neighborhoods, minutes ago."
    ),
    'fields': ["Real Estate", "Social Proof", "Marketplace Activity", "Buyer & Seller Matching"],
    'image_style': "minimalist status-feed card aesthetic, soft pastel background, monospace typography (text-only, no images needed for this agent)",
    'llm_provider': 'claude',
    'llm_model': 'claude-sonnet-4-6',
    'is_active': True,
}


def get_or_create_agent(db) -> Agent:
    a = db.query(Agent).filter(Agent.name == AGENT_NAME).first()
    if a:
        log.info(f"agent already exists: id={a.id} '{a.name}'")
        return a
    a = Agent(**AGENT_DEFAULTS)
    db.add(a); db.commit(); db.refresh(a)
    log.info(f"created agent: id={a.id} '{a.name}'")
    return a


GEN_PROMPT_TEMPLATE = """You are writing tweets for @ting — Ting Pulse, a live activity feed account.

Each tweet is ONE short status update about a real-looking event happening RIGHT NOW on the Ting platform.

THREE accepted formats, mix them roughly 50% / 30% / 20%:

FORMAT A — SINGLE-USER SIGNUP / INTENT (50% of tweets)
  Pattern: [First name] [created an account / just signed up / joined Ting] [X mins/seconds ago] [to buy/sell] [property type] [in city/neighborhood].
  Examples (do NOT copy verbatim — write fresh ones):
    "Léa just created an account on Ting 4 minutes ago. Looking to buy a 2-bed in Brooklyn."
    "Martin signed up 2 mins ago — wants to sell his apartment in Paris 7e."
    "Pierre joined Ting 8 minutes ago. Buyer, Manhattan budget $1.4M."
    "Sofia, 11 mins ago. Sell. Williamsburg loft."
    "James — account created 30 seconds ago. Looking for a buyer's agent in Boston Back Bay."

FORMAT B — MULTI-AGENT REACH-OUT (30% of tweets)
  Pattern: [First name] [reached out to / contacted / messaged] [N] agents [X mins ago] [to buy/sell] [in city/neighborhood].
  Examples:
    "Sandra just reached out to 3 agents in Boston, 7 mins ago. Buyer, Beacon Hill."
    "John contacted 2 agents 1 min ago to sell his place in Paris 1er."
    "Camille, 4 mins ago: messaged 5 agents about selling a 3-bed in the 16e."
    "Daniel just pinged 4 buyer's agents in NYC for a co-op in Murray Hill. 6 minutes ago."

FORMAT C — AGGREGATE CITY PULSE (20% of tweets)
  Pattern: [N] people are currently [searching for / talking to / reaching out to] agents in [city/neighborhood] to [buy/sell].
  Examples:
    "17 people are currently looking for an agent to sell in Manhattan."
    "Right now: 23 buyers active in Paris 16e on Ting."
    "9 sellers in Boston South End currently in active conversations with agents."
    "5 people in Notting Hill have reached out to agents in the last 10 minutes."

LANGUAGE RULE (IMPORTANT)
- If the city/neighborhood is in FRANCE (Paris, any "Paris 1er/4e/6e/7e/9e/11e/14e/16e/17e/18e/20e",
  Marais, Saint-Germain, Bastille, Batignolles, Montmartre, Lyon, Bordeaux, Marseille, etc.),
  WRITE THE ENTIRE TWEET IN FRENCH. Natural, native French — not translated-sounding.
    FR examples (write fresh ones, don't copy):
      "Martin vient de créer son compte sur Ting il y a 2 min. Cherche à vendre son appart dans le 7e."
      "Léa, il y a 4 minutes : a contacté 3 agents pour acheter un 2-pièces dans le Marais."
      "Pierre a rejoint Ting il y a 8 min. Acheteur, budget 850 000 € à Saint-Germain."
      "En ce moment : 23 personnes cherchent un agent pour vendre dans le 16e."
      "9 acheteurs actifs à Paris 11e sur Ting, à l'instant."
    FR vocabulary: "vient de créer son compte", "a rejoint Ting", "il y a X min", "cherche à acheter/vendre",
      "a contacté X agents", "acheteur/vendeur", "appartement/appart", "studio", "2-pièces", "3-pièces",
      "maison", "loft", budgets in euros (€). Time: "à l'instant", "il y a 1 min", "il y a 5 minutes".
- For all NON-French cities (NYC, Boston, London, etc.), write in ENGLISH as before.
- Aim for roughly 30-40% of tweets being French (France/Paris), the rest English.

HARD RULES
- Each tweet MUST be a SINGLE standalone tweet, ≤ 250 characters total (emojis = 2 chars each, count carefully).
- No threads. No 1/, 2/ numbering. No marketing tagline. No "join us", no "the future of real estate", no "10k users".
- No exclamation points. No emoji overload (max 1, and only if it adds information — a 📍 for location is OK occasionally).
- Names: international mix. Use first names from: French (Léa, Martin, Camille, Pierre, Sophie, Hugo, Manon, Antoine, Élise, Théo, Inès, Lucas), Anglo (James, Emma, Daniel, Olivia, Ryan, Sarah, Ethan, Maya, Noah, Hannah, Jake, Chloe), Hispanic (Sofia, Mateo, Lucia, Diego, Carmen), other (Yuki, Aanya, Omar, Priya, Kenji, Anya, Reza, Linh, Adaeze, Niall).
- Cities/neighborhoods: heavy mix of NYC (Manhattan, Brooklyn — Williamsburg/Park Slope/Bed-Stuy/DUMBO, Queens — Astoria/LIC, Upper East/West Side, Tribeca, Chelsea, SoHo, Harlem, FiDi, Murray Hill, Hell's Kitchen, Greenpoint), Paris (1er, 4e, 6e, 7e, 9e, 11e, 14e, 16e, 17e, 18e, 20e, Marais, Saint-Germain, Bastille, Batignolles), Boston (Back Bay, South End, Beacon Hill, Cambridge, Somerville, JP, Dorchester, Brookline), London (Notting Hill, Shoreditch, Hackney, Islington, Camden, Clapham, Hampstead). Vary actively.
- Property types when used: studio, 1-bed, 2-bed, 3-bed, loft, townhouse, brownstone, co-op, condo, duplex, garden apartment, pied-à-terre, family apartment.
- Vary the time phrasing: "just now", "30 seconds ago", "1 min ago", "2 mins ago", "4 minutes ago", "7 mins ago", "11 mins ago", "23 minutes ago", "an hour ago".
- Vary the verb pattern. Do NOT start every tweet the same way.
- Optional final tag at end (use on roughly 1 in 4 tweets, not more): "via @ting" or "ting.co" — never both. Most tweets should NOT have it.
- NO hashtags inside the body. The hashtags array stays empty or has at most 1 functional tag like "RealEstate" — use sparingly.

Respond with ONLY a valid JSON object, no markdown, no code fences:
{{"posts": [{{"body": "...", "hashtags": []}}, ... {count} items]}}
You MUST return exactly {count} posts. Vary names, cities, formats, time phrasings — no repetition.
"""


def generate_batch(llm: LLMProvider, count: int, batch_label: str) -> list:
    prompt = GEN_PROMPT_TEMPLATE.format(count=count) + f"\n\nBATCH CONTEXT: {batch_label}. Make these {count} feel distinct from any prior batch."
    raw = llm.generate_content(
        prompt=prompt,
        system_prompt=(
            "You are Ting Pulse, an automated real-time activity feed for the Ting real estate platform. "
            "Status-feed voice. Terse, factual, plausible. No marketing language. "
            "INFLUENCER NOTE: this account is not a broker/agent itself — never say 'my client', 'my listing', "
            "or 'I just closed'. It only reports activity happening on the Ting platform."
        ),
        max_tokens=6000,
        temperature=0.85,
    )
    parsed = parse_json_loose(raw)
    if not parsed or 'posts' not in parsed:
        log.error(f"[{batch_label}] failed to parse JSON; raw len={len(raw)}, head={raw[:200]}")
        return []
    posts = parsed.get('posts') or []
    log.info(f"[{batch_label}] parsed {len(posts)} posts")
    return posts[:count]


def insert_drafts(db, agent_id: int, posts: list) -> int:
    n = 0
    for p in posts:
        body = (p.get('body') or '').strip().strip('"').strip()
        if not body:
            continue
        if len(body) > 280:
            body = body[:277].rstrip() + '...'
        hashtags = p.get('hashtags') or []
        if not isinstance(hashtags, list):
            hashtags = []
        db.add(Content(
            agent_id=agent_id, title=body[:100], body=body,
            hashtags=hashtags, media_urls=[], platform='twitter', status='draft',
        ))
        n += 1
    db.commit()
    return n


def main():
    db = get_db()
    try:
        a = get_or_create_agent(db)
        llm = LLMProvider(provider=a.llm_provider or 'claude', model=a.llm_model)

        # Two batches of 25 to keep each LLM call well under timeout & with format diversity.
        total = 0
        for i, label in enumerate(['BATCH 1/2 — mostly Format A signups + a few B and C',
                                   'BATCH 2/2 — flip the mix: more reach-outs + city pulses, plus a few signups'], 1):
            posts = generate_batch(llm, 25, label)
            n = insert_drafts(db, a.id, posts)
            log.info(f"[batch {i}] inserted {n} drafts (running total {total + n})")
            total += n
        log.info(f"DONE — {total} Ting Pulse tweet drafts inserted for agent #{a.id} ({a.name}).")
    finally:
        db.close()


if __name__ == '__main__':
    main()
