"""
Autopilot Engine — automatically generates and optionally publishes posts
on a per-agent schedule. Runs as a background daemon thread.
"""
import threading
import time
import logging
import random
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Peak posting windows per platform (hour, weekday-weighted)
PEAK_HOURS = {
    'instagram': [9, 12, 18],
    'twitter':   [8, 12, 17],
    'tiktok':    [7, 12, 19, 21]
}

BEST_DAYS = {
    'instagram': [1, 2, 4],
    'twitter':   [0, 1, 2, 3, 4],
    'tiktok':    list(range(7))
}


def next_peak_time(platform: str, posts_per_day: int) -> datetime:
    now   = datetime.utcnow()
    hours = PEAK_HOURS.get(platform, [9, 18])
    chosen_hours = sorted(random.sample(hours, min(posts_per_day, len(hours))))
    for h in chosen_hours:
        candidate = now.replace(hour=h, minute=random.randint(0, 15), second=0, microsecond=0)
        if candidate > now + timedelta(minutes=30):
            return candidate
    return (now + timedelta(days=1)).replace(
        hour=chosen_hours[0], minute=random.randint(0, 15), second=0, microsecond=0
    )


class AutopilotEngine:
    def __init__(self, db_factory, orchestrator):
        self.db_factory    = db_factory
        self.orchestrator  = orchestrator
        self._running      = False
        self._thread       = None
        self._lock         = threading.Lock()
        self._active_agents: set = set()   # agent IDs currently generating

    def is_generating(self, agent_id: int) -> bool:
        """True while this agent is actively producing posts."""
        return agent_id in self._active_agents

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name='autopilot')
            self._thread.start()
            log.info('[Autopilot] Engine started.')

    def stop(self):
        with self._lock:
            self._running = False
        log.info('[Autopilot] Engine stopped.')

    def _loop(self):
        while self._running:
            try:
                self._tick(force=False)
            except Exception as e:
                log.error(f'[Autopilot] Tick error: {e}')
            time.sleep(900)

    def _tick(self, force: bool = False):
        """
        Core generation loop.
        force=True  → used by trigger_now(); bypasses cooldown, generates ALL ppd posts.
        force=False → normal background tick; respects 2h cooldown.
        """
        from src.database.models import Agent, Content
        db = self.db_factory()
        try:
            agents = db.query(Agent).filter(
                Agent.autopilot_enabled == True,
                Agent.is_active == True
            ).all()
            now = datetime.utcnow()

            for agent in agents:
                try:
                    ppd       = agent.autopilot_posts_per_day or 1
                    platforms = agent.autopilot_platforms or ['instagram']
                    if isinstance(platforms, str):
                        import json
                        try:
                            platforms = json.loads(platforms)
                        except Exception:
                            platforms = ['instagram']

                    # How many posts created today already
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_count = db.query(Content).filter(
                        Content.agent_id  == agent.id,
                        Content.created_at >= today_start
                    ).count()

                    remaining = ppd - today_count

                    # Normal (non-forced) tick: respect 2h cooldown + done check
                    if not force:
                        if remaining <= 0:
                            log.info(f'[Autopilot] {agent.name}: {today_count}/{ppd} posts today — done.')
                            continue
                        if agent.autopilot_last_run:
                            elapsed = (now - agent.autopilot_last_run).total_seconds()
                            if elapsed < 7200:
                                log.info(f'[Autopilot] {agent.name}: last run {int(elapsed/60)}m ago — waiting.')
                                continue

                    # Forced manual trigger → always generate the full ppd quota
                    posts_to_make = ppd if force else 1

                    ag = self.orchestrator.get_agent(agent.id)
                    if not ag:
                        log.warning(f'[Autopilot] {agent.name}: not found in orchestrator.')
                        continue

                    topic = ', '.join(agent.fields or []) or 'real estate investing'

                    self._active_agents.add(agent.id)
                    for i in range(posts_to_make):
                        platform = random.choice(platforms)
                        log.info(f'[Autopilot] Generating post {i+1}/{posts_to_make} for {agent.name} on {platform}…')

                        # ── KEY FIX ──────────────────────────────────────────
                        # Give the agent its OWN fresh db session so it never
                        # touches the orchestrator's shared request-level session.
                        agent_db = self.db_factory()
                        original_db = ag.db
                        ag.db = agent_db
                        # ─────────────────────────────────────────────────────
                        try:
                            cid = ag.create_draft_post(platform=platform, topic=topic)
                        finally:
                            ag.db = original_db   # always restore
                            agent_db.close()

                        if not cid:
                            log.warning(f'[Autopilot] {agent.name}: post generation returned nothing.')
                            continue

                        # Update status / schedule using the engine's own session
                        post = db.query(Content).filter(Content.id == cid).first()
                        if post:
                            if agent.autopilot_mode == 'publish':
                                post.status      = 'published'
                                post.published_at = now
                            else:
                                post.status      = 'scheduled'
                                post.scheduled_at = next_peak_time(platform, ppd)

                        agent.autopilot_last_run = now
                        db.commit()
                        log.info(f'[Autopilot] ✅ {agent.name}: post {cid} created ({agent.autopilot_mode}).')

                        # Small gap between posts if generating multiple
                        if posts_to_make > 1 and i < posts_to_make - 1:
                            time.sleep(2)

                except Exception as ae:
                    log.error(f'[Autopilot] {agent.name} error: {ae}', exc_info=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                finally:
                    self._active_agents.discard(agent.id)
        finally:
            db.close()

    def trigger_now(self, agent_id: int):
        """
        Manually trigger autopilot for one agent right now.
        Bypasses cooldown and generates ALL posts_per_day posts in one go.
        """
        from src.database.models import Agent
        db = self.db_factory()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.autopilot_last_run = None
                db.commit()
        finally:
            db.close()
        threading.Thread(
            target=self._tick,
            kwargs={'force': True},
            daemon=True,
            name=f'autopilot-force-{agent_id}'
        ).start()
