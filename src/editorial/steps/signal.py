"""Step 1: SIGNAL — Head of Intelligence scans trends → TrendReport."""
import logging
from datetime import datetime
from src.database.models import TrendReport, WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)


def run_signal(db, workflow_run, topics: list = None) -> TrendReport:
    """Execute Step 1: Intelligence gathering."""
    step_log = WorkflowStepLog(
        workflow_run_id=workflow_run.id,
        step_name='signal',
        team_member_role='head_intelligence',
        status='running',
        started_at=datetime.utcnow(),
    )
    db.add(step_log)
    db.commit()

    try:
        intel = get_role('head_intelligence', db=db)
        result = intel.execute({'topics': topics or []})

        import json as _json
        def _safe(v):
            if isinstance(v, (dict, list)):
                return _json.dumps(v)
            return v

        report = TrendReport(
            workflow_run_id=workflow_run.id,
            anchor_points=_safe(result.get('anchor_points', [])),
            raw_signals=_safe(result.get('raw_signals', [])),
            market_context=str(result.get('market_context', '')),
        )
        db.add(report)

        ap_count = len(result.get('anchor_points', []))
        step_log.status = 'completed'
        step_log.completed_at = datetime.utcnow()
        step_log.output_summary = f"{ap_count} anchor points generated"
        db.commit()

        log.info(f"[Step1:Signal] ✅ {ap_count} anchor points")
        return report

    except Exception as e:
        step_log.status = 'failed'
        step_log.output_summary = str(e)
        step_log.completed_at = datetime.utcnow()
        db.commit()
        raise
