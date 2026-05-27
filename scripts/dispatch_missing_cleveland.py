"""Dispatch Cleveland Instagram carousels to the 5 US agents that were missed.
Reuses the brief + pipeline from redispatch_cleveland.py.
"""
import os, sys, logging
os.environ['PYTHONIOENCODING'] = 'utf-8'
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

from src.database.db import get_db
from src.database.models import Content, Task, Agent
from dashboard.app import _execute_individual_task
from scripts.redispatch_cleveland import CAROUSEL_BRIEF

# Previously missed US agents
MISSING_AGENT_IDS = [4, 5, 7, 8, 10]  # Chloe, Greg, Mike & Sarah, Tom, Liam


def main():
    db = get_db()
    for agent_id in MISSING_AGENT_IDS:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            print(f'  [skip] Agent #{agent_id} not found')
            continue
        # Skip if this agent already has a recent Cleveland IG draft
        existing = db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.platform.in_(['instagram', 'Instagram']),
        ).first()
        if existing and 'cleveland' in (existing.body or '').lower():
            print(f'  [skip] {agent.name} already has a Cleveland draft (#{existing.id})')
            continue

        task = Task(
            title=f'Instagram carousel — Cleveland Airbnb disaster ({agent.name})',
            description=CAROUSEL_BRIEF,
            status='in_progress',
            priority='high',
            created_by_type='user', created_by_key='supervisor', created_by_name='You',
            assignee_type='agent', assignee_key=str(agent.id), assignee_name=agent.name,
            department='newsroom',
        )
        db.add(task)
        db.commit()
        print(f'\nTask #{task.id} -> {agent.name} ({agent.persona[:60]}...)')

        try:
            _execute_individual_task(db, task, agent, 'agent', str(agent.id))
            db.commit()
            print(f'  OK Task #{task.id} complete')
        except Exception as e:
            import traceback
            print(f'  FAILED Task #{task.id}: {e}')
            print(traceback.format_exc())
            db.rollback()

    # Report
    print('\n=== Result ===')
    for aid in MISSING_AGENT_IDS:
        a = db.query(Agent).filter(Agent.id == aid).first()
        if not a: continue
        drafts = db.query(Content).filter(
            Content.agent_id == aid,
            Content.platform.in_(['instagram', 'Instagram']),
        ).all()
        cleveland = [d for d in drafts if 'cleveland' in (d.body or '').lower()]
        imgs = sum(len(d.media_urls or []) for d in cleveland)
        print(f'  {a.name:<20} cleveland_drafts={len(cleveland)} total_images={imgs}')
    db.close()


if __name__ == '__main__':
    main()
