"""Step 5: ATOMIZATION — Distribution Specialist splits master content per agent/platform."""
import json
import logging
from datetime import datetime
from src.database.models import Agent, AtomizedContent, WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)


def run_atomization(db, workflow_run, master_content):
    """Execute Step 5: atomize master content for each target agent."""
    target_ids = workflow_run.target_agent_ids or []
    if not target_ids:
        # Default: all active agents
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        target_ids = [a.id for a in agents]

    agents = db.query(Agent).filter(Agent.id.in_(target_ids)).all()
    if not agents:
        log.warning("[Step5:Atomization] No target agents found")
        return []

    all_atomized = []
    distro = get_role('distribution_specialist', db=db)

    for agent in agents:
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
            result = distro.execute({
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
            })

            formats = result.get('formats', [])
            for fmt in formats:
                import json as _json
                def _safe(v):
                    if isinstance(v, (dict, list)):
                        return _json.dumps(v)
                    return v
                atom = AtomizedContent(
                    workflow_run_id=workflow_run.id,
                    agent_id=agent.id,
                    format_type=fmt.get('format_type', 'ig_post'),
                    platform=fmt.get('platform', 'instagram'),
                    body=str(fmt.get('body', '')),
                    hashtags=_safe(fmt.get('hashtags', [])),
                    media_urls=_safe(master_content.visual_assets or []),
                    status='draft',
                )
                db.add(atom)
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
            log.error(f"[Step5:Atomization] ❌ {agent.name}: {e}")

    return all_atomized
