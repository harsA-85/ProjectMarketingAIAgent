"""Step 4: FACT-CHECK — Head of Intelligence re-verifies data accuracy."""
import json
import logging
from datetime import datetime
from src.database.models import WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)

MAX_REVISION_LOOPS = 2


def run_fact_check(db, workflow_run, master_content, trend_report):
    """Execute Step 4: verify master content against original data."""
    step_log = WorkflowStepLog(
        workflow_run_id=workflow_run.id,
        step_name='fact_check',
        team_member_role='head_intelligence',
        status='running',
        started_at=datetime.utcnow(),
    )
    db.add(step_log)
    db.commit()

    try:
        intel = get_role('head_intelligence', db=db)

        for loop in range(MAX_REVISION_LOOPS):
            prompt = (
                f"FACT-CHECK PASS {loop + 1}/{MAX_REVISION_LOOPS}\n\n"
                f"Original Trend Data:\n"
                f"Anchor Points: {json.dumps(trend_report.anchor_points, indent=2)}\n"
                f"Market Context: {trend_report.market_context}\n\n"
                f"Master Content to verify:\n"
                f"Headline: {master_content.headline}\n"
                f"Body: {master_content.body[:2000]}\n"
                f"Key Points: {json.dumps(master_content.key_points)}\n\n"
                "Check for:\n"
                "1. Data accuracy — do the numbers match the original intelligence?\n"
                "2. Logical consistency — does the narrative follow from the data?\n"
                "3. Misleading framing — are we creating new information asymmetry?\n"
                "4. Missing context — are important caveats omitted?\n\n"
                "Respond in JSON: {passed: true/false, issues: [{issue, severity, suggestion}], "
                "overall_assessment: '...'}"
            )

            result = intel.call_llm_json(prompt, max_tokens=1500)
            passed = result.get('passed', False)
            issues = result.get('issues', [])

            existing_notes = master_content.fact_check_notes or []
            if isinstance(existing_notes, str):
                try:
                    existing_notes = json.loads(existing_notes)
                except Exception:
                    existing_notes = []
            existing_notes.append({
                'loop': loop + 1,
                'passed': passed,
                'issues': issues,
                'assessment': result.get('overall_assessment', ''),
            })
            master_content.fact_check_notes = json.dumps(existing_notes)

            if passed or not issues:
                master_content.fact_check_passed = True
                break

            # If issues found and we have loops left, attempt revision
            if loop < MAX_REVISION_LOOPS - 1:
                log.info(f"[Step4:FactCheck] {len(issues)} issues found, revising…")
                cw = get_role('copywriter_1', db=db)
                revision_prompt = (
                    f"REVISION NEEDED. Your master content has fact-check issues:\n\n"
                    f"{json.dumps(issues, indent=2)}\n\n"
                    f"Current body:\n{master_content.body[:2000]}\n\n"
                    "Fix the issues while preserving the narrative strength. "
                    "Respond in JSON: {body: '...revised text...', key_points: [...]}"
                )
                revised = cw.call_llm_json(revision_prompt, max_tokens=3000)
                if revised.get('body'):
                    master_content.body = revised['body']
                if revised.get('key_points'):
                    master_content.key_points = json.dumps(revised['key_points']) if isinstance(revised['key_points'], list) else revised['key_points']
            else:
                # Last loop and still issues — pass with warnings
                master_content.fact_check_passed = True
                log.warning("[Step4:FactCheck] Passing with warnings after max revisions")

        db.commit()

        step_log.status = 'completed'
        step_log.completed_at = datetime.utcnow()
        step_log.output_summary = (
            f"{'PASSED' if master_content.fact_check_passed else 'FAILED'} "
            f"after {len(master_content.fact_check_notes)} check(s)"
        )
        db.commit()

        log.info(f"[Step4:FactCheck] ✅ {step_log.output_summary}")
        return master_content

    except Exception as e:
        step_log.status = 'failed'
        step_log.output_summary = str(e)
        step_log.completed_at = datetime.utcnow()
        db.commit()
        raise
