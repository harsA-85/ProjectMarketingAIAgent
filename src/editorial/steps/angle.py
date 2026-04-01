"""Step 2: ANGLE — EIC picks the angle, CD adds visual direction → ContentBrief."""
import logging
from datetime import datetime
from src.database.models import ContentBrief, WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)


def run_angle(db, workflow_run, trend_report) -> ContentBrief:
    """Execute Step 2: Editorial Board angle selection."""
    # ── EIC chooses angle ──
    eic_log = WorkflowStepLog(
        workflow_run_id=workflow_run.id,
        step_name='angle',
        team_member_role='eic',
        status='running',
        started_at=datetime.utcnow(),
    )
    db.add(eic_log)
    db.commit()

    try:
        eic = get_role('eic', db=db)
        eic_result = eic.execute({
            'trend_report': {
                'anchor_points': trend_report.anchor_points,
                'market_context': trend_report.market_context,
            }
        })

        eic_log.status = 'completed'
        eic_log.completed_at = datetime.utcnow()
        eic_log.output_summary = eic_result.get('headline', '')[:200]
        db.commit()

    except Exception as e:
        eic_log.status = 'failed'
        eic_log.output_summary = str(e)
        eic_log.completed_at = datetime.utcnow()
        db.commit()
        raise

    # ── CD adds visual direction ──
    cd_log = WorkflowStepLog(
        workflow_run_id=workflow_run.id,
        step_name='angle',
        team_member_role='creative_director',
        status='running',
        started_at=datetime.utcnow(),
    )
    db.add(cd_log)
    db.commit()

    try:
        cd = get_role('creative_director', db=db)
        cd_result = cd.execute({'editorial_brief': eic_result})

        cd_log.status = 'completed'
        cd_log.completed_at = datetime.utcnow()
        cd_log.output_summary = cd_result.get('visual_mood', '')[:200]
        db.commit()

    except Exception as e:
        cd_log.status = 'failed'
        cd_log.output_summary = str(e)
        cd_log.completed_at = datetime.utcnow()
        db.commit()
        raise

    # ── Assemble ContentBrief ──
    import json

    # Safely stringify any dict/list values for Text columns
    def _str(v):
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return str(v) if v else ''

    brief = ContentBrief(
        workflow_run_id=workflow_run.id,
        chosen_angle=_str(eic_result.get('angle', eic_result.get('headline', ''))),
        headline=_str(eic_result.get('headline', '')),
        narrative_hook=_str(eic_result.get('narrative_hook', '')),
        visual_direction=_str(cd_result),
        target_platforms=json.dumps(['instagram', 'twitter', 'linkedin', 'tiktok']),
        tone_guidelines=_str(eic_result.get('tone_notes', '')),
    )
    db.add(brief)
    db.commit()

    log.info(f"[Step2:Angle] ✅ '{brief.headline}'")
    return brief
