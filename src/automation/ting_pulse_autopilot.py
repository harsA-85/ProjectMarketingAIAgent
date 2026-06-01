"""Ting Pulse Autopilot — schedules 3-25 fake-social-proof tweets per day for
the "Ting Pulse" ambassador agent (a real-time activity feed account).

Behavior:
  • At first start AND at every UTC midnight rollover, builds a "day plan":
      - rolls a random target between 3 and 25 tweets
      - splits them into bursts (1-5 tweets per burst)
      - scatters the bursts across an 8-hour-to-23-hour active window
      - within each burst, spaces tweets 2-15 seconds apart so SchedPub
        (which polls every 60s) picks them up as a natural-feeling burst
  • Pulls existing 'draft' tweets from the Ting Pulse agent's pool.
  • If the draft pool runs below 30, triggers a regen via the seed script
    (so the autopilot is genuinely self-sustaining).
  • For roughly 1 in 6 tweets, attaches a PIL-rendered "ting notification
    card" image (no Gemini — fast, clean, perfect spelling).
  • Sets each chosen draft's status='scheduled' + scheduled_at=<the planned
    time>. The existing SchedPub thread then publishes them at that time.
  • Idempotent per UTC day: re-planning a day with existing scheduled
    tweets is a no-op.

If the Ting Pulse agent has no connected Twitter account yet, scheduling
still proceeds — SchedPub will simply fail publish until the account is
connected, then catch up.
"""
from __future__ import annotations
import threading, time, random, logging, io, base64, os
from datetime import datetime, timedelta, date, timezone

log = logging.getLogger(__name__)

AGENT_NAME = "Ting Pulse"
IMAGE_RATIO = 0.17           # ~1 in 6 tweets gets a card image
MIN_POOL_AFTER_PLAN = 30     # if drafts left < this, regen
TARGET_MIN = 3
TARGET_MAX = 25
ACTIVE_HOUR_START = 8        # UTC — earliest a tweet can fire
ACTIVE_HOUR_END = 23         # UTC — latest a tweet can fire
BURST_MAX = 5                # cap intra-burst tweet count

_FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
_FONT_REG  = "C:/Windows/Fonts/arial.ttf"


# ─── PIL notification-card images ─────────────────────────────────────────
# Two card styles, picked based on tweet content:
#   • PERSON CARD — for signups & reach-outs. Big Gmail-style colored circle
#     with the first initial; name + city/intent label underneath.
#   • CITY-PULSE CARD — for aggregate tweets ("17 people in Manhattan…").
#     Big tinted background with the number + city name as the focal point.

import re as _re
import hashlib as _hashlib

_AVATAR_PALETTE = [
    ((229,  62,  62), (255, 255, 255)),  # crimson
    ((20,  184, 166), (255, 255, 255)),  # deep teal
    ((59,  130, 246), (255, 255, 255)),  # cobalt
    ((245, 158,  11), (40, 40, 50)),     # amber / dark text
    ((139,  92, 246), (255, 255, 255)),  # violet
    ((16,  185, 129), (255, 255, 255)),  # emerald
    ((249, 115,  22), (255, 255, 255)),  # tangerine
    ((236,  72, 153), (255, 255, 255)),  # pink
    ((217,  70, 239), (255, 255, 255)),  # fuchsia
    ((6,   148, 162), (255, 255, 255)),  # cyan-deep
]

_CITY_KEYWORDS = [
    # NYC
    'Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Williamsburg', 'Park Slope', 'Bed-Stuy',
    'DUMBO', 'Astoria', 'LIC', 'Upper East', 'Upper West', 'Tribeca', 'Chelsea', 'SoHo',
    'Harlem', 'FiDi', 'Murray Hill', "Hell's Kitchen", 'Greenpoint',
    # Paris
    'Paris 1er', 'Paris 4e', 'Paris 6e', 'Paris 7e', 'Paris 9e', 'Paris 11e', 'Paris 14e',
    'Paris 16e', 'Paris 17e', 'Paris 18e', 'Paris 20e', 'Paris', 'Marais', 'Saint-Germain',
    'Bastille', 'Batignolles',
    # Boston
    'Back Bay', 'South End', 'Beacon Hill', 'Cambridge', 'Somerville', 'JP', 'Dorchester',
    'Brookline',
    # London
    'Notting Hill', 'Shoreditch', 'Hackney', 'Islington', 'Camden', 'Clapham', 'Hampstead',
    'London',
    # Generic fallbacks
    'Boston', 'NYC', 'New York',
]
# Pre-sort longer phrases first so "Paris 16e" matches before "Paris"
_CITY_KEYWORDS_SORTED = sorted(set(_CITY_KEYWORDS), key=len, reverse=True)


def _fonts():
    from PIL import ImageFont
    try:
        return {
            'huge':        ImageFont.truetype(_FONT_BOLD, 280),  # avatar letter
            'big':         ImageFont.truetype(_FONT_BOLD, 200),  # city pulse number
            'title':       ImageFont.truetype(_FONT_BOLD, 72),
            'sub':         ImageFont.truetype(_FONT_REG, 38),
            'small':       ImageFont.truetype(_FONT_REG, 28),
            'word':        ImageFont.truetype(_FONT_BOLD, 56),
            'chrome_bold': ImageFont.truetype(_FONT_BOLD, 30),
            'chrome_reg':  ImageFont.truetype(_FONT_REG, 24),
        }
    except OSError:
        return {k: ImageFont.load_default() for k in
                ['huge', 'big', 'title', 'sub', 'small', 'word',
                 'chrome_bold', 'chrome_reg']}


def _color_for_name(name: str):
    """Deterministic palette pick — same name always lands on same color."""
    h = _hashlib.md5(name.encode('utf-8')).digest()[0]
    return _AVATAR_PALETTE[h % len(_AVATAR_PALETTE)]


_FRENCH_CITY_TOKENS = [
    'paris', 'marais', 'saint-germain', 'bastille', 'batignolles', 'montmartre',
    'lyon', 'bordeaux', 'marseille', 'nantes', 'toulouse', 'lille',
]


def _extract_city(text: str) -> str | None:
    for kw in _CITY_KEYWORDS_SORTED:
        if kw.lower() in text.lower():
            return kw
    return None


# French linguistic markers — catches tweets that reference an arrondissement
# ("dans le 14e") or use French verbs without naming "Paris" explicitly.
_FRENCH_MARKERS = [
    'il y a', 'vient de', 'a rejoint', 'cherche à', 'cherche a', "à l'instant",
    'en ce moment', 'agents pour', 'acheteur', 'vendeur', 'appartement', 'appart',
    'pièces', 'pieces', 'son compte', 'personnes', 'maison', 'à vendre', 'à acheter',
]


def _is_french(text: str, city: str | None) -> bool:
    """True if this tweet is French (→ French card labels). Detects both French
    city tokens and French linguistic markers in the body."""
    hay = f'{text} {city or ""}'.lower()
    if any(tok in hay for tok in _FRENCH_CITY_TOKENS):
        return True
    return any(mk in hay for mk in _FRENCH_MARKERS)


# Matches a leading first name (Latin extended), incl. accented chars
_NAME_RX = _re.compile(r'^([A-ZÀ-Ý][a-zà-ÿ\'-]+)\b')
# Matches a leading number (e.g. "17 people…") → aggregate pulse
_NUMERIC_RX = _re.compile(r'^(\d+)\s')


def _classify(text: str) -> tuple[str, dict]:
    """Return ('person', {name, city}) | ('city_pulse', {n, city}) | ('generic', {})."""
    body = text.strip().lstrip('@').strip()

    m = _NUMERIC_RX.match(body)
    if m:
        return 'city_pulse', {'n': int(m.group(1)), 'city': _extract_city(body)}

    m = _NAME_RX.match(body)
    if m:
        return 'person', {'name': m.group(1), 'city': _extract_city(body)}

    return 'generic', {}


def _draw_centered(draw, text, font, y, w, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, y), text, fill=fill, font=font)
    return bbox[3] - bbox[1]


def _draw_chrome(draw, fonts, w):
    """Top-left 'ting · live' chrome with a small pulsing-green dot."""
    x = 60
    y = 60
    # Green live dot (12px circle)
    draw.ellipse([x, y + 10, x + 16, y + 26], fill=(34, 197, 94))
    # 'ting' wordmark
    draw.text((x + 28, y - 4), 'ting', fill=(40, 44, 60), font=fonts['chrome_bold'])
    # subtle 'live' label
    bbox = draw.textbbox((0, 0), 'ting', font=fonts['chrome_bold'])
    after_ting = x + 28 + (bbox[2] - bbox[0]) + 14
    draw.text((after_ting, y + 4), 'live', fill=(120, 128, 145), font=fonts['chrome_reg'])


_TIME_RX = _re.compile(
    r'(il\s+y\s+a\s+\d+\s*(?:s|sec|secondes?|min|minutes?|h|heures?)'   # FR: "il y a 5 min"
    r'|à\s+l\'instant'                                                    # FR: "à l'instant"
    r'|\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\s*ago'
    r'|just\s+now|just\s+signed\s+up|seconds?\s+ago|minutes?\s+ago)',
    _re.IGNORECASE,
)


def _extract_time_phrase(text: str) -> str | None:
    """Pull a human time phrase out of the tweet — 'just now', '3 mins ago',
    'il y a 5 min', 'à l'instant', etc."""
    m = _TIME_RX.search(text)
    if not m:
        return None
    phrase = m.group(1).strip().lower()
    if 'just signed up' in phrase:
        return 'just now'
    return phrase


def _build_person_card(name: str, city: str | None, body_text: str = '') -> str:
    from PIL import Image, ImageDraw
    size = 1080
    img = Image.new('RGB', (size, size), (248, 249, 252))
    draw = ImageDraw.Draw(img)
    fonts = _fonts()

    _draw_chrome(draw, fonts, size)

    # Avatar: deterministic color per name
    circle_color, text_color = _color_for_name(name)
    radius = 220
    cx, cy = size // 2, 440
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=circle_color)

    # Initial (single letter — these tweets don't include last names).
    # Use anchor='mm' (middle/middle) so PIL handles glyph bearing/baseline
    # correctly — manual bbox-based centering is off by the left bearing.
    initial = name[0].upper()
    draw.text((cx, cy), initial, fill=text_color, font=fonts['huge'], anchor='mm')

    fr = _is_french(body_text or '', city)

    # Name below the circle
    _draw_centered(draw, name, fonts['title'], 740, size, (20, 22, 35))

    # City line
    if city:
        _draw_centered(draw, city, fonts['sub'], 835, size, (110, 116, 135))

    # Time phrase if found, else default join line
    time_phrase = _extract_time_phrase(body_text or '')
    if fr:
        if time_phrase:
            footer = time_phrase if time_phrase.startswith(('il y a', 'à l')) else f'inscrit·e {time_phrase}'
        else:
            footer = 'vient de rejoindre ting'
    else:
        if time_phrase:
            footer = f'joined {time_phrase}' if ('now' in time_phrase or 'ago' in time_phrase) else time_phrase
        else:
            footer = 'just joined ting'
    _draw_centered(draw, footer, fonts['small'], 945, size, (160, 165, 180))

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _build_city_pulse_card(n: int, city: str | None, body_text: str) -> str:
    from PIL import Image, ImageDraw
    size = 1080
    # Soft tinted background based on city hash for variety
    seed_str = (city or 'ting') + str(n)
    h = _hashlib.md5(seed_str.encode('utf-8')).digest()
    bg = (
        220 + (h[0] % 30),
        220 + (h[1] % 30),
        225 + (h[2] % 25),
    )
    img = Image.new('RGB', (size, size), bg)
    draw = ImageDraw.Draw(img)
    fonts = _fonts()

    _draw_chrome(draw, fonts, size)

    fr = _is_french(body_text or '', city)

    # Sub-label
    _draw_centered(draw, 'en ce moment sur ting' if fr else 'right now on ting',
                   fonts['small'], 160, size, (110, 116, 135))

    # Big number
    num_str = str(n)
    bbox = draw.textbbox((0, 0), num_str, font=fonts['big'])
    nw = bbox[2] - bbox[0]
    draw.text(((size - nw) // 2, 200), num_str, fill=(20, 22, 35), font=fonts['big'])

    # "people in <City>" / "personnes à <City>"
    if city:
        line2 = f'personnes à {city}' if fr else f'people in {city}'
    else:
        if fr:
            m = _re.search(r'à ([A-ZÀ-Ý][\w \-\']+?)(?:\s(?:pour|sur)|[.,])', body_text)
            line2 = f'personnes à {m.group(1)}' if m else 'personnes actives'
        else:
            m = _re.search(r'in ([A-ZÀ-Ý][\w \-\']+?)(?:\s(?:to|on|currently)|[.,])', body_text)
            line2 = f'people in {m.group(1)}' if m else 'people active'
    _draw_centered(draw, line2, fonts['title'], 480, size, (40, 44, 60))

    # Subline — intent
    low = body_text.lower()
    if fr:
        if 'vendre' in low:
            sub = 'cherchent un agent pour vendre'
        elif 'achet' in low:  # acheter / acheteur
            sub = 'cherchent un agent pour acheter'
        else:
            sub = 'en discussion avec des agents'
    else:
        if 'sell' in low:
            sub = 'looking for an agent to sell'
        elif 'buy' in low:
            sub = 'looking for an agent to buy'
        else:
            sub = 'active in agent conversations'
    _draw_centered(draw, sub, fonts['sub'], 610, size, (110, 116, 135))

    # Footer
    _draw_centered(draw, 'ting.co', fonts['small'], 940, size, (140, 145, 165))

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _build_generic_card(text: str) -> str:
    """Last-resort fallback when classification fails."""
    from PIL import Image, ImageDraw
    size = 1080
    img = Image.new('RGB', (size, size), (245, 247, 252))
    draw = ImageDraw.Draw(img)
    fonts = _fonts()

    _draw_chrome(draw, fonts, size)
    _draw_centered(draw, 'live activity', fonts['small'], 220, size, (130, 134, 150))

    # Word-wrap body
    margin = 90
    max_width = size - 2 * margin
    words = text.split()
    lines = []
    cur = ''
    for w in words:
        test = (cur + ' ' + w).strip()
        bbox = draw.textbbox((0, 0), test, font=fonts['word'])
        if bbox[2] - bbox[0] > max_width and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    line_h = int(56 * 1.22)
    total_h = len(lines) * line_h
    y = (size - total_h) // 2 + 30
    for ln in lines:
        _draw_centered(draw, ln, fonts['word'], y, size, (25, 28, 42))
        y += line_h

    _draw_centered(draw, 'ting.co', fonts['small'], size - 90, size, (160, 165, 180))

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _build_ting_card(text: str) -> str:
    """Pick the right card style based on the tweet content."""
    kind, info = _classify(text)
    if kind == 'person':
        return _build_person_card(info['name'], info.get('city'), body_text=text)
    if kind == 'city_pulse':
        return _build_city_pulse_card(info['n'], info.get('city'), text)
    return _build_generic_card(text)


# ─── Scheduling math ──────────────────────────────────────────────────────
def _plan_bursts(n: int, day_start_utc: datetime, earliest_utc: datetime | None = None) -> list:
    """Distribute n tweets across the day with bursty cluster behavior.
    Returns a sorted list of datetime objects (UTC), all within the active window.
    If earliest_utc is given, no tweet is scheduled before it (so a mid-day restart
    or a fresh connect never backfills past timestamps)."""
    # Choose burst_count — fewer bursts for small days, more for big ones,
    # but ALWAYS at least one burst contains multiple tweets when n >= 2.
    # Aim ~ n / (random 2.0..3.8) so n=3 → 1, n=25 → 7-12
    target_bc = max(1, round(n / random.uniform(2.0, 3.8)))
    burst_count = min(target_bc, n)

    # Active window — clamp the start forward if earliest_utc lands inside the day
    active_start_dt = day_start_utc + timedelta(hours=ACTIVE_HOUR_START)
    if earliest_utc and earliest_utc > active_start_dt:
        active_start_dt = earliest_utc
    active_end_dt = day_start_utc + timedelta(hours=ACTIVE_HOUR_END)
    active_span_s = max(60, int((active_end_dt - active_start_dt).total_seconds()))

    # Burst start offsets within active window (with a 30s tail margin)
    if burst_count == 1:
        offsets = [random.randint(0, max(1, active_span_s - 120))]
    else:
        # Sample with minimum 60s spacing between burst starts to keep them readable
        # Use a stratified sampling: divide the window into burst_count slots, pick a random point in each
        slot = active_span_s / burst_count
        offsets = [int(i * slot + random.uniform(0, slot * 0.7)) for i in range(burst_count)]

    # Decide burst sizes (random partition of n into burst_count parts, cap at BURST_MAX)
    sizes = [1] * burst_count
    remaining = n - burst_count
    # While we have tweets left to assign, randomly bump bursts
    while remaining > 0:
        idx = random.randint(0, burst_count - 1)
        if sizes[idx] < BURST_MAX:
            sizes[idx] += 1
            remaining -= 1
        elif all(s >= BURST_MAX for s in sizes):
            sizes[idx] += 1  # exceed cap when forced
            remaining -= 1

    # Build the final times
    times = []
    for off, sz in zip(offsets, sizes):
        base = active_start_dt + timedelta(seconds=off)
        intra = 0.0
        for k in range(sz):
            if k > 0:
                intra += random.uniform(2.0, 15.0)
            times.append(base + timedelta(seconds=intra))
    times.sort()
    return times


# ─── Pool maintenance ─────────────────────────────────────────────────────
def _maybe_regen_drafts(db, agent_id: int, drafts_left: int):
    """If the draft pool is too low, run the seed script logic to add more."""
    if drafts_left >= MIN_POOL_AFTER_PLAN:
        return
    log.info(f'[TingPulse] Pool low ({drafts_left} drafts). Regenerating…')
    try:
        # Import lazily to avoid circular import on app startup
        from scripts.seed_ting_pulse_agent import generate_batch, insert_drafts
        from src.api.llm_provider import LLMProvider
        from src.database.models import Agent
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            log.error('[TingPulse] Agent vanished during regen?'); return
        llm = LLMProvider(provider=a.llm_provider or 'claude', model=a.llm_model)
        # One batch of 50 — keeps things one LLM call
        posts = generate_batch(llm, 50, 'AUTOPILOT REGEN — pool replenishment, vary names/cities/formats')
        n = insert_drafts(db, agent_id, posts)
        log.info(f'[TingPulse] Regen added {n} fresh drafts.')
    except Exception as e:
        log.error(f'[TingPulse] Regen failed: {e}', exc_info=True)


# ─── Day planner ──────────────────────────────────────────────────────────
def _plan_day(day_utc: date | None = None):
    from src.database.db import get_db
    from src.database.models import Agent, Content
    from sqlalchemy import and_

    day_utc = day_utc or datetime.utcnow().date()
    day_start = datetime.combine(day_utc, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    db = get_db()
    try:
        agent = db.query(Agent).filter(Agent.name == AGENT_NAME).first()
        if not agent:
            log.warning(f'[TingPulse] Agent "{AGENT_NAME}" not found — skipping day plan.')
            return
        agent_id = agent.id

        # Idempotency: skip if anything already scheduled for today
        already = db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.status == 'scheduled',
            Content.scheduled_at >= day_start,
            Content.scheduled_at < day_end,
        ).count()
        if already > 0:
            log.info(f'[TingPulse] Day {day_utc} already has {already} scheduled — skipping plan.')
            return

        # Roll the daily target
        target = random.randint(TARGET_MIN, TARGET_MAX)
        log.info(f'[TingPulse] Planning {day_utc} → {target} tweets')

        # Grab drafts. Newest IDs first so freshly regenerated content gets used first.
        drafts = db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.platform == 'twitter',
            Content.status == 'draft',
        ).order_by(Content.id.desc()).limit(target * 3).all()

        if len(drafts) < target:
            log.warning(f'[TingPulse] Only {len(drafts)} drafts vs target {target}. Trying regen first…')
            _maybe_regen_drafts(db, agent_id, len(drafts))
            drafts = db.query(Content).filter(
                Content.agent_id == agent_id,
                Content.platform == 'twitter',
                Content.status == 'draft',
            ).order_by(Content.id.desc()).limit(target * 3).all()

        chosen = drafts[:target]
        if not chosen:
            log.error('[TingPulse] No drafts available even after regen. Aborting day plan.')
            return

        # Build the bursty schedule. If we're planning the current day, never
        # schedule before "now + 2 min" so a mid-day (re)plan doesn't backfill.
        now_utc = datetime.utcnow()
        earliest = (now_utc + timedelta(minutes=2)) if day_utc == now_utc.date() else None
        times = _plan_bursts(len(chosen), day_start, earliest_utc=earliest)

        # Apply scheduling + maybe attach a PIL card
        n_scheduled = 0
        n_with_img = 0
        for c, t in zip(chosen, times):
            c.status = 'scheduled'
            c.scheduled_at = t
            existing_media = c.media_urls or []
            if isinstance(existing_media, str):
                try:
                    import json as _json
                    existing_media = _json.loads(existing_media)
                except Exception:
                    existing_media = []
            if (not existing_media) and random.random() < IMAGE_RATIO:
                try:
                    card = _build_ting_card(c.body or '')
                    c.media_urls = [card]
                    n_with_img += 1
                except Exception as ie:
                    log.warning(f'[TingPulse] card build failed for draft #{c.id}: {ie}')
            db.add(c)
            n_scheduled += 1
        db.commit()
        log.info(f'[TingPulse] ✅ Scheduled {n_scheduled} tweets for {day_utc} ({n_with_img} with card image).')

        # Top up the pool for tomorrow if we're now below threshold
        remaining = db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.platform == 'twitter',
            Content.status == 'draft',
        ).count()
        _maybe_regen_drafts(db, agent_id, remaining)

    except Exception as e:
        log.error(f'[TingPulse] Day plan crashed: {e}', exc_info=True)
    finally:
        db.close()


# ─── Daemon loop ──────────────────────────────────────────────────────────
def start_ting_pulse_autopilot():
    """Spawn the background daemon. Idempotent — won't start twice."""
    if getattr(start_ting_pulse_autopilot, '_started', False):
        return
    start_ting_pulse_autopilot._started = True

    def _loop():
        log.info('[TingPulse] Autopilot started.')
        last_planned: date | None = None
        # Plan immediately so a fresh server start gets today's schedule too
        try:
            _plan_day()
            last_planned = datetime.utcnow().date()
        except Exception as e:
            log.error(f'[TingPulse] Initial plan crashed: {e}', exc_info=True)
        while True:
            # Check every 15 minutes whether we crossed UTC midnight
            time.sleep(15 * 60)
            today = datetime.utcnow().date()
            if today != last_planned:
                try:
                    _plan_day(today)
                    last_planned = today
                except Exception as e:
                    log.error(f'[TingPulse] Daily replan crashed: {e}', exc_info=True)

    t = threading.Thread(target=_loop, name='ting-pulse-autopilot', daemon=True)
    t.start()


# ─── Manual trigger (for one-shot use / testing) ──────────────────────────
def plan_today_now():
    """Plan today immediately. Idempotent (same as the daemon's first call)."""
    _plan_day(datetime.utcnow().date())
