"""Step 3: CO-CREATION — Copywriters draft + Prompt Engineers generate images → MasterContent."""
import json
import logging
import threading
from datetime import datetime
from src.database.models import MasterContent, WorkflowStepLog
from src.editorial.team_roles import get_role
from src.database.db import get_db

log = logging.getLogger(__name__)


def _safe(v):
    """Serialize dicts/lists to JSON strings for SQLite Text columns."""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def run_co_creation(db, workflow_run, content_brief) -> MasterContent:
    """Execute Step 3: parallel content + image production."""
    brief_data = {
        'headline': content_brief.headline,
        'angle': content_brief.chosen_angle,
        'narrative_hook': content_brief.narrative_hook,
        'visual_direction': content_brief.visual_direction,
        'tone_guidelines': content_brief.tone_guidelines,
    }
    run_id = workflow_run.id

    # Results containers
    copy_result = {}
    social_result = {}
    photo_prompts = {}
    design_prompts = {}
    generated_images = []

    # ── Each parallel thread gets its OWN db session ──
    def run_copywriter_1():
        nonlocal copy_result
        tdb = get_db()
        try:
            _log = WorkflowStepLog(
                workflow_run_id=run_id, step_name='co_creation',
                team_member_role='copywriter_1', status='running', started_at=datetime.utcnow())
            tdb.add(_log); tdb.commit()
            cw = get_role('copywriter_1', db=tdb)
            copy_result = cw.execute({'content_brief': brief_data})
            _log.status = 'completed'
            _log.output_summary = f"{len(copy_result.get('body', ''))} chars"
            _log.completed_at = datetime.utcnow()
            tdb.commit()
        except Exception as e:
            try:
                _log.status = 'failed'; _log.output_summary = str(e)[:200]
                _log.completed_at = datetime.utcnow(); tdb.commit()
            except Exception:
                pass
            log.error(f"[CoCreation] copywriter_1 failed: {e}")
        finally:
            tdb.close()

    def run_copywriter_2():
        nonlocal social_result
        tdb = get_db()
        try:
            _log = WorkflowStepLog(
                workflow_run_id=run_id, step_name='co_creation',
                team_member_role='copywriter_2', status='running', started_at=datetime.utcnow())
            tdb.add(_log); tdb.commit()
            cw2 = get_role('copywriter_2', db=tdb)
            social_result = cw2.execute({'content_brief': brief_data, 'master_body': ''})
            _log.status = 'completed'
            _log.output_summary = f"{len(social_result.get('hooks', []))} hooks"
            _log.completed_at = datetime.utcnow()
            tdb.commit()
        except Exception as e:
            try:
                _log.status = 'failed'; _log.output_summary = str(e)[:200]
                _log.completed_at = datetime.utcnow(); tdb.commit()
            except Exception:
                pass
            log.error(f"[CoCreation] copywriter_2 failed: {e}")
        finally:
            tdb.close()

    def run_prompt_engineers():
        nonlocal photo_prompts, design_prompts
        tdb = get_db()
        try:
            visual_dir = {}
            try:
                visual_dir = json.loads(content_brief.visual_direction or '{}')
            except Exception:
                pass
            topic = content_brief.chosen_angle or 'real estate'

            # Prompt Engineer 1 — Photography
            _log1 = WorkflowStepLog(
                workflow_run_id=run_id, step_name='co_creation',
                team_member_role='prompt_engineer_1', status='running', started_at=datetime.utcnow())
            tdb.add(_log1); tdb.commit()
            try:
                pe1 = get_role('prompt_engineer_1', db=tdb)
                photo_prompts = pe1.execute({'visual_direction': visual_dir, 'topic': topic})
                _log1.status = 'completed'
                _log1.output_summary = f"{len(photo_prompts.get('prompts', []))} photo prompts"
                _log1.completed_at = datetime.utcnow()
                tdb.commit()
            except Exception as e:
                _log1.status = 'failed'; _log1.output_summary = str(e)[:200]
                _log1.completed_at = datetime.utcnow(); tdb.commit()
                log.error(f"[CoCreation] prompt_engineer_1 failed: {e}")

            # Prompt Engineer 2 — Design
            _log2 = WorkflowStepLog(
                workflow_run_id=run_id, step_name='co_creation',
                team_member_role='prompt_engineer_2', status='running', started_at=datetime.utcnow())
            tdb.add(_log2); tdb.commit()
            try:
                pe2 = get_role('prompt_engineer_2', db=tdb)
                design_prompts = pe2.execute({'visual_direction': visual_dir, 'topic': topic})
                _log2.status = 'completed'
                _log2.output_summary = f"{len(design_prompts.get('prompts', []))} design prompts"
                _log2.completed_at = datetime.utcnow()
                tdb.commit()
            except Exception as e:
                _log2.status = 'failed'; _log2.output_summary = str(e)[:200]
                _log2.completed_at = datetime.utcnow(); tdb.commit()
                log.error(f"[CoCreation] prompt_engineer_2 failed: {e}")
        finally:
            tdb.close()

    # Launch parallel threads
    t1 = threading.Thread(target=run_copywriter_1, name='copywriter_1')
    t2 = threading.Thread(target=run_copywriter_2, name='copywriter_2')
    t3 = threading.Thread(target=run_prompt_engineers, name='prompt_engineers')
    t1.start(); t2.start(); t3.start()
    t1.join(timeout=120); t2.join(timeout=120); t3.join(timeout=120)

    # ── Generate actual images from the prompts ──
    all_prompts = (photo_prompts.get('prompts', []) + design_prompts.get('prompts', []))[:4]
    if all_prompts:
        try:
            from src.api.image_generator import GeminiImageGenerator
            img_gen = GeminiImageGenerator()
            generated_images = img_gen.generate_carousel(all_prompts)
            log.info(f"[Step3:CoCreation] Generated {len(generated_images)} images")
        except Exception as e:
            log.error(f"[Step3:CoCreation] Image generation failed: {e}")

    # ── Production Manager assembles (uses the main db session) ──
    pm_log = WorkflowStepLog(
        workflow_run_id=run_id, step_name='co_creation',
        team_member_role='production_manager', status='running', started_at=datetime.utcnow())
    db.add(pm_log); db.commit()

    try:
        pm = get_role('production_manager', db=db)
        assembled = pm.execute({
            'content_brief': brief_data,
            'copywriter_output': copy_result,
        })
        pm_log.status = 'completed'
        pm_log.output_summary = assembled.get('validation_status', 'unknown')
        pm_log.completed_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        pm_log.status = 'failed'; pm_log.output_summary = str(e)[:200]
        pm_log.completed_at = datetime.utcnow(); db.commit()
        assembled = copy_result  # fallback to raw copy

    # ── Save MasterContent ──
    master = MasterContent(
        workflow_run_id=run_id,
        headline=str(assembled.get('headline', content_brief.headline or '')),
        body=str(assembled.get('body', copy_result.get('body', ''))),
        key_points=_safe(assembled.get('key_points', copy_result.get('key_points', []))),
        visual_assets=_safe(generated_images),
        image_prompts=_safe(all_prompts),
        fact_check_notes=_safe([]),
        fact_check_passed=False,
    )
    db.add(master)
    db.commit()

    log.info(f"[Step3:CoCreation] ✅ Master content assembled: '{master.headline}'")
    return master
