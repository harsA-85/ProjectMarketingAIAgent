"""Step 4: FACT-CHECK — Head of Intelligence verifies claims against live web sources."""
import json
import logging
from datetime import datetime
from src.database.models import WorkflowStepLog
from src.editorial.team_roles import get_role

log = logging.getLogger(__name__)

MAX_REVISION_LOOPS = 2


def run_fact_check(db, workflow_run, master_content, trend_report):
    """Execute Step 4: verify master content against live web sources."""
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

        # ── Step A: Extract key claims to verify ────────────────────────
        claims_prompt = (
            f"Extract the top 3-5 specific factual claims (numbers, statistics, named sources) "
            f"from this article that need web verification:\n\n"
            f"Headline: {master_content.headline}\n"
            f"Body excerpt: {master_content.body[:1500]}\n"
            f"Key Points: {json.dumps(master_content.key_points)}\n\n"
            "List each claim as a short search query (one per line), nothing else."
        )
        claims_raw = intel.call_llm(claims_prompt, max_tokens=400)
        claims = [c.strip() for c in claims_raw.strip().split('\n') if c.strip()][:5]

        # ── Step B: Search the web for each claim ───────────────────────
        web_evidence = []
        for claim in claims:
            search_prompt = (
                f"Search for current news, data, and expert sources that confirm or contradict this claim:\n"
                f"\"{claim}\"\n\n"
                "Report what you find: source names, dates, and specific counter-evidence or confirmation. "
                "Be brief and factual."
            )
            evidence = intel.call_llm_with_search(search_prompt, max_tokens=600)
            web_evidence.append(f"Claim: {claim}\nEvidence: {evidence}")
            log.info(f"[Step4:FactCheck] Searched: {claim[:60]}")

        web_evidence_str = '\n\n---\n\n'.join(web_evidence)

        # ── Step C: Verdict based on real evidence ──────────────────────
        for loop in range(MAX_REVISION_LOOPS):
            prompt = (
                f"FACT-CHECK PASS {loop + 1}/{MAX_REVISION_LOOPS}\n\n"
                f"Web Evidence Gathered:\n{web_evidence_str}\n\n"
                f"Original Trend Data:\n"
                f"Market Context: {trend_report.market_context}\n\n"
                f"Master Content to verify:\n"
                f"Headline: {master_content.headline}\n"
                f"Body: {master_content.body[:2000]}\n"
                f"Key Points: {json.dumps(master_content.key_points)}\n\n"
                "Cross-reference the article claims against the web evidence. Check:\n"
                "1. Data accuracy — do numbers match real sources?\n"
                "2. Source attribution — are named sources real and correctly quoted?\n"
                "3. Logical consistency — does the narrative follow from real data?\n"
                "4. Missing context — are important caveats omitted?\n\n"
                "Respond in JSON: {passed: true/false, issues: [{issue, severity, suggestion}], "
                "overall_assessment: '...', sources_verified: ['...']}"
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
                'sources_verified': result.get('sources_verified', []),
            })
            master_content.fact_check_notes = json.dumps(existing_notes)

            if passed or not issues:
                master_content.fact_check_passed = True
                break

            if loop < MAX_REVISION_LOOPS - 1:
                log.info(f"[Step4:FactCheck] {len(issues)} issues found, revising…")
                cw = get_role('copywriter_1', db=db)
                revision_prompt = (
                    f"REVISION NEEDED. Fact-check found issues:\n\n"
                    f"{json.dumps(issues, indent=2)}\n\n"
                    f"Web evidence for context:\n{web_evidence_str[:1500]}\n\n"
                    f"Current body:\n{master_content.body[:2000]}\n\n"
                    "Fix the issues while preserving narrative strength. "
                    "Respond in JSON: {body: '...revised text...', key_points: [...]}"
                )
                revised = cw.call_llm_json(revision_prompt, max_tokens=3000)
                if revised.get('body'):
                    master_content.body = revised['body']
                if revised.get('key_points'):
                    master_content.key_points = json.dumps(revised['key_points']) if isinstance(revised['key_points'], list) else revised['key_points']
            else:
                master_content.fact_check_passed = True
                log.warning("[Step4:FactCheck] Passing with warnings after max revisions")

        db.commit()

        checks_count = len(claims)
        step_log.status = 'completed'
        step_log.completed_at = datetime.utcnow()
        step_log.output_summary = (
            f"{'PASSED' if master_content.fact_check_passed else 'FAILED'} "
            f"after {checks_count} web check(s)"
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
