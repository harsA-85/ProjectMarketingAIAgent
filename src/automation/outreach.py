"""Ting outreach 'veille' — find people asking for a real estate agent on X,
draft a helpful reply for each, and store as a ReplyCandidate for MANUAL
approval. Nothing is ever auto-posted by this module.

Flow:
  scan_outreach() → search recent tweets for each query → dedupe against
  existing candidates → draft a reply in the right language → save as 'pending'.

The dashboard lists pending candidates; the supervisor sends or dismisses each.
Sending is done by the /api/outreach endpoints in app.py (reuses the existing
Twitter publish/reply path).
"""
from __future__ import annotations
import os, base64, json, logging, urllib.request, urllib.parse, urllib.error
from datetime import datetime

log = logging.getLogger(__name__)

TING_PULSE_AGENT_NAME = "Ting Pulse"

# Search queries — FR + EN. -is:retweet to skip RTs. Each query costs a little
# API credit per scan, so keep the list focused on real buyer/seller intent.
# NOTE: X recent-search only covers the LAST ~7 DAYS, and apostrophes inside
# quoted phrases break matching (X tokenizes on '). So FR queries avoid quoted
# apostrophes and combine an exact noun phrase (AND) with an OR-group of intent
# words. Breadth is tuned to catch real buyer/seller intent without pure noise.
DEFAULT_QUERIES = [
    # ── FRENCH — seeking / recommending an agent ─────────────────
    '("agent immobilier" OR "agent immo") (cherche OR recherche OR recommande OR recommandation OR connait OR "connaît" OR conseille OR "quelqu un") -is:retweet lang:fr',
    '("agence immobilière" OR "agent immobilier") (recommandation OR conseil OR "à conseiller" OR fiable OR sérieux) -is:retweet lang:fr',
    # ── FRENCH — fee / agency frustration ────────────────────────
    '("agent immobilier" OR "agence immobilière" OR "frais d agence") (galère OR arnaque OR nul OR "déçu" OR "trop cher" OR honteux OR abusif) -is:retweet lang:fr',
    # ── FRENCH — buying / selling intent ─────────────────────────
    '("acheter un appartement" OR "acheter une maison" OR "achat immobilier") (conseil OR aide OR agent OR agence OR comment OR "première fois") -is:retweet lang:fr',
    '("vendre mon appartement" OR "vendre ma maison" OR "vendre mon bien") (agent OR agence OR comment OR conseil) -is:retweet lang:fr',
    '("primo-accédant" OR "primo accédant" OR "premier achat") (immobilier OR appartement OR maison OR agent) -is:retweet lang:fr',
    # ── ENGLISH — seeking an agent ───────────────────────────────
    '("looking for a real estate agent" OR "need a good realtor" OR "recommend a realtor") -is:retweet lang:en',
    '("any realtor recommendations" OR "real estate agent recommendations" OR "recommend a real estate agent") -is:retweet lang:en',
    '("buyer\'s agent" (NYC OR Brooklyn OR Manhattan OR Boston OR London) (recommend OR looking)) -is:retweet lang:en',
    # ── ENGLISH — fee / agent frustration ────────────────────────
    '(("realtor fees" OR "agent fees" OR "agent commission") (high OR ridiculous OR "too much" OR scam)) -is:retweet lang:en',
    '("fed up with realtors" OR "realtor was useless" OR "bad real estate agent") -is:retweet lang:en',
    # ── ENGLISH — buying / selling intent ────────────────────────
    '("first time home buyer" (agent OR realtor) (advice OR help OR recommend)) -is:retweet lang:en',
    '("selling my house" ("without an agent" OR "do I need an agent" OR realtor)) -is:retweet lang:en',
]

MAX_PER_QUERY = 10          # tweets pulled per query
MAX_DRAFTS_PER_SCAN = 25    # safety cap on how many drafts we create per run


def _app_bearer() -> str | None:
    """Get an app-only OAuth2 bearer token from the consumer key/secret."""
    key = os.environ.get('TWITTER_API_KEY', '')
    sec = os.environ.get('TWITTER_API_SECRET', '')
    if not key or not sec:
        log.warning('[Outreach] TWITTER_API_KEY/SECRET missing — cannot search.')
        return None
    creds = base64.b64encode(f'{key}:{sec}'.encode()).decode()
    req = urllib.request.Request(
        'https://api.twitter.com/oauth2/token',
        data=b'grant_type=client_credentials', method='POST',
    )
    req.add_header('Authorization', f'Basic {creds}')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())['access_token']
    except Exception as e:
        log.error(f'[Outreach] bearer token failed: {e}')
        return None


def _search_recent(bearer: str, query: str, limit: int) -> list:
    """Return list of {id, text, author_id, lang, username} for a query.
    Forces -is:reply so we only get ORIGINAL tweets — replying to a tweet that
    is itself inside someone else's conversation triggers X's conversation-level
    reply restrictions (403). Original tweets allow replies by default."""
    if '-is:reply' not in query:
        query = query + ' -is:reply'
    params = urllib.parse.urlencode({
        'query': query,
        'max_results': max(10, min(limit, 100)),
        'tweet.fields': 'lang,created_at,author_id',
        'expansions': 'author_id',
        'user.fields': 'username',
    })
    req = urllib.request.Request(f'https://api.twitter.com/2/tweets/search/recent?{params}')
    req.add_header('Authorization', f'Bearer {bearer}')
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        log.warning(f'[Outreach] search HTTP {e.code} for {query[:40]!r}: {body[:200]}')
        return []
    except Exception as e:
        log.warning(f'[Outreach] search error for {query[:40]!r}: {e}')
        return []

    users = {u['id']: u.get('username') for u in data.get('includes', {}).get('users', [])}
    out = []
    for t in data.get('data', [])[:limit]:
        out.append({
            'id': t['id'],
            'text': t.get('text', ''),
            'author_id': t.get('author_id'),
            'username': users.get(t.get('author_id')),
            'lang': t.get('lang'),
        })
    return out


def _draft_reply(llm, tweet_text: str, lang: str, persona: str) -> str:
    """Generate a helpful, human-sounding reply. Mentions Ting only when natural."""
    is_fr = (lang or '').startswith('fr')
    if is_fr:
        instr = (
            "Tu réponds à ce tweet d'une personne qui cherche un agent immobilier ou se plaint "
            "des frais d'agence. Écris une réponse COURTE (1-2 phrases), humaine, utile, jamais "
            "spam. Ton: serviable, pair-à-pair, pas commercial. Tu peux mentionner Ting (par son "
            "nom, comme une plateforme qui aide à trouver des agents vérifiés travaillant VRAIMENT "
            "pour l'acheteur) — seulement si c'est naturel, sans hard-sell, sans emojis à outrance. "
            "IMPORTANT : n'écris JAMAIS d'URL, de lien ou de domaine (pas de ting.co, pas de .com, "
            "pas de http). Mentionne juste le nom 'Ting' ou '@ting'. Pas de hashtags. N'invente pas de promesses."
        )
    else:
        instr = (
            "You're replying to someone looking for a real estate agent (or complaining about "
            "agent fees). Write a SHORT (1-2 sentence), human, genuinely helpful reply — never "
            "spammy. Tone: peer-to-peer, not salesy. You may mention Ting BY NAME (a platform that "
            "helps find vetted agents who actually work for the buyer) — ONLY if it fits naturally, "
            "no hard sell, no emoji spam, no hashtags. "
            "IMPORTANT: NEVER write a URL, link, or domain (no ting.co, no .com, no http). Just say "
            "the name 'Ting' or '@ting'. Don't over-promise."
        )
    prompt = (
        f"{instr}\n\nPersona of the account replying: {persona}\n\n"
        f"Tweet to reply to:\n\"{tweet_text}\"\n\n"
        "Return ONLY the reply text, nothing else."
    )
    try:
        reply = llm.generate_content(prompt=prompt, system_prompt='', max_tokens=200) or ''
        return reply.strip().strip('"').strip()
    except Exception as e:
        log.warning(f'[Outreach] draft failed: {e}')
        return ''


def scan_outreach(queries: list | None = None) -> dict:
    """Run one veille pass. Returns {'found': n, 'drafted': n, 'skipped': n}."""
    from src.database.db import get_db
    from src.database.models import Agent, SocialMediaAccount, ReplyCandidate
    from src.api.llm_provider import LLMProvider

    queries = queries or DEFAULT_QUERIES
    bearer = _app_bearer()
    if not bearer:
        return {'error': 'No Twitter bearer token (check TWITTER_API_KEY/SECRET).'}

    db = get_db()
    found = drafted = skipped = 0
    try:
        agent = db.query(Agent).filter(Agent.name == TING_PULSE_AGENT_NAME).first()
        if not agent:
            return {'error': f'Agent "{TING_PULSE_AGENT_NAME}" not found.'}
        acct = db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == agent.id,
            SocialMediaAccount.platform == 'twitter',
        ).first()
        acct_id = acct.id if acct else None

        # Our own handles — never reply to ourselves
        own_handles = {
            (a.username or '').lower()
            for a in db.query(SocialMediaAccount).all()
        }

        llm = LLMProvider(provider=agent.llm_provider or 'claude', model=agent.llm_model)
        persona = agent.persona or 'helpful real estate platform'

        for q in queries:
            if drafted >= MAX_DRAFTS_PER_SCAN:
                break
            tweets = _search_recent(bearer, q, MAX_PER_QUERY)
            for tw in tweets:
                found += 1
                if drafted >= MAX_DRAFTS_PER_SCAN:
                    break
                # Skip our own tweets
                if (tw.get('username') or '').lower() in own_handles:
                    skipped += 1
                    continue
                # Guard: skip tweets that are replies-in-thread (text starts with @).
                # Replying to these hits conversation-level reply restrictions (403).
                if (tw.get('text') or '').lstrip().startswith('@'):
                    skipped += 1
                    continue
                # Dedupe — already have a candidate for this tweet?
                exists = db.query(ReplyCandidate).filter(
                    ReplyCandidate.source_tweet_id == tw['id']
                ).first()
                if exists:
                    skipped += 1
                    continue
                reply = _draft_reply(llm, tw['text'], tw.get('lang'), persona)
                if not reply:
                    skipped += 1
                    continue
                uname = tw.get('username')
                cand = ReplyCandidate(
                    agent_id=agent.id,
                    account_id=acct_id,
                    platform='twitter',
                    source_tweet_id=tw['id'],
                    source_author=uname,
                    source_author_id=tw.get('author_id'),
                    source_text=tw['text'],
                    source_url=(f'https://x.com/{uname}/status/{tw["id"]}' if uname else f'https://x.com/i/status/{tw["id"]}'),
                    lang=tw.get('lang'),
                    matched_query=q[:255],
                    draft_reply=reply,
                    status='pending',
                )
                db.add(cand)
                drafted += 1
            db.commit()
        log.info(f'[Outreach] scan done — found={found} drafted={drafted} skipped={skipped}')
        return {'found': found, 'drafted': drafted, 'skipped': skipped}
    except Exception as e:
        log.error(f'[Outreach] scan crashed: {e}', exc_info=True)
        return {'error': str(e)}
    finally:
        db.close()
