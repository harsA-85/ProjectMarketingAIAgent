"""
AI-Auto Scheduler
Runs 2-3 random engagement sessions per day per agent, at random times,
spreading activity naturally across the day.
"""

import threading
import time
import random
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Sessions run between these hours (local time, 24h)
ACTIVE_WINDOW = (8, 22)   # 8am – 10pm


def _random_session_times(n: int = None) -> list:
    """
    Pick n random times in today's active window.
    n is itself random: 2 or 3 (sometimes 1 on slower days).
    """
    if n is None:
        n = random.choices([1, 2, 3], weights=[15, 50, 35])[0]

    now  = datetime.now()
    day_start = now.replace(hour=ACTIVE_WINDOW[0], minute=0, second=0, microsecond=0)
    day_end   = now.replace(hour=ACTIVE_WINDOW[1], minute=0, second=0, microsecond=0)

    total_seconds = int((day_end - day_start).total_seconds())
    times = sorted([
        day_start + timedelta(seconds=random.randint(0, total_seconds))
        for _ in range(n)
    ])
    # Only keep future times
    return [t for t in times if t > now + timedelta(minutes=5)]


class AIAutoScheduler:
    def __init__(self, db_factory, orchestrator):
        self.db_factory   = db_factory
        self.orchestrator = orchestrator
        self._running     = False
        self._thread      = None
        self._lock        = threading.Lock()
        self._next_runs   = {}   # agent_id → list of scheduled datetimes

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread  = threading.Thread(target=self._loop, daemon=True, name='ai-auto-sched')
            self._thread.start()
            log.info('[AI-Auto] Scheduler started.')

    def stop(self):
        self._running = False

    def schedule_agent(self, agent_id: int):
        """Pick random session times for this agent today."""
        times = _random_session_times()
        self._next_runs[agent_id] = times
        log.info(f'[AI-Auto] Agent {agent_id} sessions today: {[t.strftime("%H:%M") for t in times]}')

    def trigger_now(self, agent_id: int):
        """Immediately run one session for this agent (for testing)."""
        threading.Thread(
            target=self._run_agent_session,
            args=(agent_id,),
            daemon=True
        ).start()

    def _loop(self):
        while self._running:
            try:
                self._check_and_fire()
            except Exception as e:
                log.error(f'[AI-Auto] Scheduler loop error: {e}')
            time.sleep(60)   # check every minute

    def _check_and_fire(self):
        from src.database.models import Agent
        db = self.db_factory()
        try:
            agents = db.query(Agent).filter(
                Agent.ai_auto_enabled == True,
                Agent.is_active == True
            ).all()

            now = datetime.now()

            for agent in agents:
                aid = agent.id

                # Schedule this agent if not yet scheduled today
                if aid not in self._next_runs or not self._next_runs[aid]:
                    self.schedule_agent(aid)

                runs = self._next_runs.get(aid, [])
                due  = [t for t in runs if t <= now]

                if due:
                    # Remove due times
                    self._next_runs[aid] = [t for t in runs if t > now]
                    # Fire in background thread
                    threading.Thread(
                        target=self._run_agent_session,
                        args=(aid,),
                        daemon=True
                    ).start()
        finally:
            db.close()

    def _run_agent_session(self, agent_id: int):
        from src.database.models import Agent
        from src.automation.instagram_agent import InstagramAgent

        db = self.db_factory()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent or not agent.ai_auto_ig_user or not agent.ai_auto_ig_pass:
                log.warning(f'[AI-Auto] Agent {agent_id}: no IG credentials configured.')
                return

            proxy = getattr(agent, 'ai_auto_proxy', None) or None

            # Update status
            agent.ai_auto_status = 'running'
            db.commit()

            # Parse target hashtags
            import json as _json
            try:
                targets = _json.loads(agent.ai_auto_targets or '[]')
            except Exception:
                targets = []
            if not targets:
                # Derive from agent fields
                targets = [f.lower().replace(' ', '') for f in (agent.fields or [])][:5]
                targets = targets or ['realestate', 'investing', 'propertymarket']

            # AI comment function using Claude
            def ai_comment(caption: str) -> str:
                try:
                    from src.api.llm_provider import LLMProvider
                    llm = LLMProvider()
                    prompt = (
                        f"You are {agent.name} — {agent.persona}. "
                        f"Tone: {agent.tone_of_voice}. "
                        f"Write a SHORT (max 12 words), genuine Instagram comment on this post caption: \"{caption}\". "
                        f"No hashtags. No emojis overload. Sound human, curious, or insightful. "
                        f"Return ONLY the comment text."
                    )
                    return llm.generate_text(prompt).strip().strip('"')
                except Exception:
                    return ''

            ig = InstagramAgent(
                agent_id        = agent_id,
                username        = agent.ai_auto_ig_user,
                password        = agent.ai_auto_ig_pass,
                target_hashtags = targets,
                ai_comment_fn   = ai_comment,
                proxy           = proxy,
            )

            summary = ig.run_session(
                status_cb=lambda msg: log.info(f'[AI-Auto] [{agent.name}] {msg}')
            )

            # Update status back
            agent.ai_auto_status = f'idle — last: {datetime.now().strftime("%H:%M")} | L:{summary["likes"]} F:{summary["follows"]} C:{summary["comments"]}'
            db.commit()

        except Exception as e:
            log.error(f'[AI-Auto] Session error agent {agent_id}: {e}')
            try:
                agent = db.query(Agent).filter(Agent.id == agent_id).first()
                if agent:
                    agent.ai_auto_status = f'error: {str(e)[:80]}'
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()
