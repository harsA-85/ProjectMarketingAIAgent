"""Delete old Cleveland drafts and re-dispatch Instagram carousels to US agents
with the new USA market posture + slide-image generation pipeline.
"""
import os, sys, io, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

from src.database.db import get_db
from src.database.models import Content, Task, Agent
from dashboard.app import _execute_individual_task


# 5 US agents chosen for persona variety
US_AGENT_IDS = [2, 3, 6, 9, 11]  # David Chen, Marcus Hayes, Jessica Lin, Tyler Reed, Maya Rostova

CAROUSEL_BRIEF = """Create a 5-slide Instagram carousel about the Cleveland Airbnb disaster.

THE STORY (US-market facts only):
- US investor bought Cleveland STR for $189,000 — listing promised 'high-demand short-term rental corridor'
- Real numbers: $28,400 gross annual revenue
- Hidden costs the pro forma omitted: STR permit $800/yr, city occupancy tax ~6%, HOA ~$220/mo, insurance premium on STR, property management 20%
- NOI after all real costs: ~$11,400
- $37,800 down payment, losing $7,500–$11,700/year
- Pro forma claimed 75% occupancy; Cleveland STR average is 52%
- Neighborhood: West Park / Ohio City mixed STR saturation
- Market context: 40% of Cleveland STRs now operating at negative cash flow per AirDNA-style data

DELIVERABLE FORMAT (strict):
Produce EXACTLY 5 slides, each clearly marked:

SLIDE 1: [Hook — one punchy line, max 12 words, text that goes ON the image]
SLIDE 2: [The promise vs the reality — one short sentence, max 15 words]
SLIDE 3: [The hidden numbers — short stat or callout, max 12 words]
SLIDE 4: [The real monthly loss — blunt line, max 15 words]
SLIDE 5: [Call to action / lesson — max 12 words]

Then:
CAPTION: [A 150–220 word Instagram caption in YOUR persona voice. Hook in first 2 lines.
Tell the story, use the data, land a lesson. End with: 'Link in bio → buyer-side platform.']
HASHTAGS: [7 relevant US hashtags]

Market: United States. Currency: USD ($). All references US-native. Do NOT mention France, Europe, or €.
Stay in your persona voice throughout.
"""


def main():
    db = get_db()

    # ── Step 1: Delete Cleveland drafts ──
    drafts = db.query(Content).filter(Content.status == 'draft').all()
    cleveland = [d for d in drafts
                 if 'cleveland' in (d.body or '').lower() or 'cleveland' in (d.title or '').lower()]
    print(f'Deleting {len(cleveland)} Cleveland drafts…')
    for d in cleveland:
        db.delete(d)
    db.commit()
    print(f'  ✅ Deleted')

    # ── Step 2: Create + execute one Instagram carousel task per US agent ──
    for agent_id in US_AGENT_IDS:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            print(f'  ⚠️  Agent #{agent_id} not found, skipping')
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
        print(f'\n📝 Task #{task.id} → {agent.name} — executing…')

        try:
            _execute_individual_task(db, task, agent, 'agent', str(agent.id))
            db.commit()
            print(f'  ✅ Task #{task.id} complete')
        except Exception as e:
            import traceback
            print(f'  ❌ Task #{task.id} failed: {e}')
            print(traceback.format_exc())
            db.rollback()

    # ── Step 3: Report ──
    new_drafts = db.query(Content).filter(
        Content.status == 'draft',
        Content.platform == 'Instagram',
    ).all()
    cleveland_new = [d for d in new_drafts if 'cleveland' in (d.body or '').lower()]
    print(f'\n═══ Result ═══')
    print(f'Cleveland Instagram drafts now: {len(cleveland_new)}')
    for d in cleveland_new:
        a = db.query(Agent).filter(Agent.id == d.agent_id).first()
        imgs = len(d.media_urls or [])
        print(f'  #{d.id} {a.name if a else d.agent_id}: {imgs} images | {d.title[:60]}')

    db.close()


if __name__ == '__main__':
    main()
