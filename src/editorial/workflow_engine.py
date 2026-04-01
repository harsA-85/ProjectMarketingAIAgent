"""
Workflow Engine — orchestrates the 5-step editorial pipeline.
Runs as background threads (one per workflow run).
"""
import threading
import logging
from datetime import datetime
from src.database.models import WorkflowRun

log = logging.getLogger(__name__)


class WorkflowEngine:
    def __init__(self, db_factory):
        self.db_factory = db_factory
        self._active_runs: dict = {}  # run_id → thread

    def is_running(self, run_id: int = None) -> bool:
        """Check if any (or a specific) workflow is running."""
        if run_id:
            return run_id in self._active_runs
        return len(self._active_runs) > 0

    def active_run_ids(self) -> list:
        return list(self._active_runs.keys())

    def start_workflow(self, target_agent_ids: list, topics: list = None) -> int:
        """Create a WorkflowRun and execute the pipeline in a background thread."""
        db = self.db_factory()
        try:
            run = WorkflowRun(
                status='pending',
                current_step='signal',
                target_agent_ids=target_agent_ids or [],
                topic_seeds=topics or [],
            )
            db.add(run)
            db.commit()
            run_id = run.id
        finally:
            db.close()

        thread = threading.Thread(
            target=self._execute_pipeline,
            args=(run_id, topics),
            daemon=True,
            name=f'workflow-{run_id}'
        )
        self._active_runs[run_id] = thread
        thread.start()

        log.info(f"[Workflow] Started run #{run_id} targeting {len(target_agent_ids)} agents")
        return run_id

    def _execute_pipeline(self, run_id: int, topics: list = None):
        """Run all 5 steps sequentially, updating DB status at each stage."""
        from src.editorial.steps.signal import run_signal
        from src.editorial.steps.angle import run_angle
        from src.editorial.steps.co_creation import run_co_creation
        from src.editorial.steps.fact_check import run_fact_check
        from src.editorial.steps.atomization import run_atomization

        db = self.db_factory()
        try:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if not run:
                log.error(f"[Workflow] Run #{run_id} not found")
                return

            run.status = 'running'
            run.started_at = datetime.utcnow()
            db.commit()

            # ── Step 1: SIGNAL ──
            self._update_step(db, run, 'signal')
            trend_report = run_signal(db, run, topics)

            # ── Step 2: ANGLE ──
            self._update_step(db, run, 'angle')
            content_brief = run_angle(db, run, trend_report)

            # ── Step 3: CO-CREATION ──
            self._update_step(db, run, 'co_creation')
            master_content = run_co_creation(db, run, content_brief)

            # ── Step 4: FACT-CHECK ──
            self._update_step(db, run, 'fact_check')
            master_content = run_fact_check(db, run, master_content, trend_report)

            # ── Step 5: ATOMIZATION ──
            self._update_step(db, run, 'atomization')
            atomized = run_atomization(db, run, master_content)

            # ── Done ──
            run.status = 'completed'
            run.current_step = 'completed'
            run.completed_at = datetime.utcnow()
            db.commit()

            # Create notification
            try:
                from src.database.models import Notification
                notif = Notification(
                    type='workflow_completed',
                    title=f'Workflow #{run_id} completed',
                    body=f'{len(atomized)} content pieces ready for review across {len(run.target_agent_ids or [])} agents',
                    link=f'/newsroom.html',
                    workflow_run_id=run_id,
                )
                db.add(notif)
                db.commit()
            except Exception:
                pass

            # Send internal email from Victoria
            try:
                from src.database.models import InternalMessage
                import uuid
                agents_str = ', '.join(str(a) for a in (run.target_agent_ids or []))
                topics_str = ', '.join(run.topic_seeds or []) or 'auto-selected'
                email = InternalMessage(
                    from_type='team_member',
                    from_key='eic',
                    from_name='Victoria Crane',
                    from_emoji='\U0001f451',
                    subject=f'Workflow #{run_id} Complete — {len(atomized)} pieces ready',
                    body=(
                        f'Workflow #{run_id} has completed successfully.\n\n'
                        f'Topics: {topics_str}\n'
                        f'Target agents: {agents_str}\n'
                        f'Content pieces produced: {len(atomized)}\n\n'
                        f'All atomized content is ready for your review in the Newsroom. '
                        f'Please approve the pieces you want to push to the publishing agents.'
                    ),
                    msg_type='email',
                    thread_id=f'email_eic_wf{run_id}_{uuid.uuid4().hex[:6]}',
                    is_read=False,
                )
                db.add(email)
                db.commit()
            except Exception:
                pass

            log.info(f"[Workflow] ✅ Run #{run_id} completed — {len(atomized)} atomized pieces")

        except Exception as e:
            log.error(f"[Workflow] ❌ Run #{run_id} failed at step '{run.current_step}': {e}",
                      exc_info=True)
            try:
                run.status = 'failed'
                run.error_message = str(e)
                db.commit()
                from src.database.models import Notification
                db.add(Notification(
                    type='workflow_failed',
                    title=f'Workflow #{run_id} failed at {run.current_step}',
                    body=str(e)[:300],
                    link='/newsroom.html',
                    workflow_run_id=run_id,
                ))
                db.commit()
            except Exception:
                pass
        finally:
            db.close()
            self._active_runs.pop(run_id, None)

    def _update_step(self, db, run, step_name):
        """Update current_step on the workflow run."""
        run.current_step = step_name
        db.commit()
        log.info(f"[Workflow] Run #{run.id} → Step: {step_name}")

    def get_run_status(self, run_id: int) -> dict:
        """Get full status of a workflow run (called from API routes)."""
        db = self.db_factory()
        try:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if not run:
                return {'error': 'Not found'}

            step_logs = [
                {
                    'step': s.step_name,
                    'role': s.team_member_role,
                    'status': s.status,
                    'output': s.output_summary,
                    'started': s.started_at.isoformat() if s.started_at else None,
                    'completed': s.completed_at.isoformat() if s.completed_at else None,
                }
                for s in run.step_logs
            ]

            return {
                'id': run.id,
                'status': run.status,
                'current_step': run.current_step,
                'target_agent_ids': run.target_agent_ids,
                'topic_seeds': run.topic_seeds,
                'started_at': run.started_at.isoformat() if run.started_at else None,
                'completed_at': run.completed_at.isoformat() if run.completed_at else None,
                'error_message': run.error_message,
                'step_logs': step_logs,
                'is_active': run.id in self._active_runs,
            }
        finally:
            db.close()
