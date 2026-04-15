"""Step 5: ATOMIZATION — Distribution Specialist splits master content per agent/platform."""
import json
import logging
import re
import time
from datetime import datetime
from src.database.models import Agent, AtomizedContent, Content, WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY  = 4   # seconds between retries (doubles each attempt)
AGENT_DELAY = 2   # seconds between agents to avoid rate limits


def _atomize_one(distro, master_content, agent):
    """Call the distribution specialist for one agent, with retry + backoff."""
    payload = {
        'master_content': {
            'headline': master_content.headline,
            'body': master_content.body,
            'key_points': master_content.key_points,
        },
        'agent_info': {
            'name': agent.name,
            'persona': agent.persona,
            'tone': agent.tone_of_voice,
            'fields': agent.fields or [],
            'brand': agent.brand,
        },
    }

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return distro.execute(payload)
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                delay = BASE_DELAY * (2 ** (attempt - 1))   # 4s, 8s, 16s
                log.warning(
                    f"[Step5:Atomization] ⚠️  {agent.name} attempt {attempt}/{MAX_RETRIES} "
                    f"failed ({e}), retrying in {delay}s…"
                )
                time.sleep(delay)
            else:
                log.error(
                    f"[Step5:Atomization] ❌ {agent.name}: all {MAX_RETRIES} attempts "
                    f"failed — {e}"
                )
    raise last_exc


def run_atomization(db, workflow_run, master_content):
    """Execute Step 5: atomize master content for each target agent."""
    target_ids = workflow_run.target_agent_ids or []
    if not target_ids:
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        target_ids = [a.id for a in agents]

    agents = db.query(Agent).filter(Agent.id.in_(target_ids)).all()
    if not agents:
        log.warning("[Step5:Atomization] No target agents found")
        return []

    all_atomized = []
    distro = get_role('distribution_specialist', db=db)

    for idx, agent in enumerate(agents):
        # Pace requests — small gap between agents to avoid rate-limit bursts
        if idx > 0:
            time.sleep(AGENT_DELAY)

        step_log = WorkflowStepLog(
            workflow_run_id=workflow_run.id,
            step_name='atomization',
            team_member_role='distribution_specialist',
            status='running',
            started_at=datetime.utcnow(),
            input_summary=f"Agent: {agent.name}",
        )
        db.add(step_log)
        db.commit()

        try:
            result = _atomize_one(distro, master_content, agent)

            formats = result.get('formats', [])
            for fmt in formats:
                def _safe(v):
                    if isinstance(v, (dict, list)):
                        return json.dumps(v)
                    return v

                platform = fmt.get('platform', 'instagram')
                body_text = str(fmt.get('body', ''))
                hashtags_val = _safe(fmt.get('hashtags', []))
                media_val = _safe(master_content.visual_assets or [])

                # ── Twitter/X: extract first tweet from thread, enforce 280 char limit ──
                if platform.lower() in ('twitter', 'x', 'twitter/x'):
                    # Split thread markers like "1/ ...\n\n2/ ..."
                    parts = re.split(r'\n+\s*\d+[/\.]\s+', body_text)
                    if len(parts) > 1:
                        first = re.sub(r'^\d+[/\.]\s+', '', parts[0] if parts[0].strip() else parts[1])
                        body_text = first.strip()
                    # Weighted char count (emojis > 0xFFFF count as 2)
                    def _tw_len(s):
                        return sum(2 if ord(c) > 0xFFFF else 1 for c in s)
                    if _tw_len(body_text) > 260:
                        while _tw_len(body_text) > 257:
                            body_text = body_text[:-1]
                        body_text = body_text.rstrip() + '...'

                atom = AtomizedContent(
                    workflow_run_id=workflow_run.id,
                    agent_id=agent.id,
                    format_type=fmt.get('format_type', 'ig_post'),
                    platform=platform,
                    body=body_text,
                    hashtags=hashtags_val,
                    media_urls=media_val,
                    status='draft',
                )
                db.add(atom)
                db.flush()  # get atom.id

                # ── Auto-create Content draft so it appears in agent Posts tab ──
                headline = master_content.headline or ''
                title = headline[:100] if headline else body_text[:100]

                # Content.hashtags/media_urls are JSON columns — need real lists
                def _to_list(v):
                    if isinstance(v, list):
                        return v
                    if isinstance(v, str):
                        try:
                            parsed = json.loads(v)
                            return parsed if isinstance(parsed, list) else []
                        except (json.JSONDecodeError, ValueError):
                            return []
                    return []

                post = Content(
                    agent_id=agent.id,
                    title=title,
                    body=body_text,
                    hashtags=_to_list(hashtags_val),
                    media_urls=_to_list(media_val),
                    platform=platform,
                    status='draft',
                )
                db.add(post)
                db.flush()
                atom.content_id = post.id

                all_atomized.append(atom)

            step_log.status = 'completed'
            step_log.completed_at = datetime.utcnow()
            step_log.output_summary = f"{len(formats)} formats for {agent.name}"
            db.commit()

            log.info(f"[Step5:Atomization] ✅ {len(formats)} formats for {agent.name}")

        except Exception as e:
            step_log.status = 'failed'
            step_log.output_summary = str(e)
            step_log.completed_at = datetime.utcnow()
            db.commit()
            log.error(f"[Step5:Atomization] ❌ {agent.name}: Connection error.")

    return all_atomized
