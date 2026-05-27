"""Dispatch 3 punchy, growth-oriented Instagram carousels for Frenchimmoagent (Dams).
Goal: community growth, follower gain, engagement. French market, bilingual FR/EN possible.
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
from src.database.models import Task, Agent
from dashboard.app import _execute_individual_task


FRENCHIMMOAGENT_ID = 1


# Three DISTINCT angles — each optimized for follower growth + saves + shares.
BRIEFS = [
    {
        "title": "Instagram carousel — 7 choses que ton agent immobilier ne te dira jamais",
        "brief": """Create a 7-slide Instagram carousel in your enthusiastic / satirical / ironic voice.

ANGLE: "7 choses que ton agent immobilier ne te dira JAMAIS" — the insider list no French buyer ever gets told. Punchy, funny, slightly provocative. The kind of post people SAVE and SEND to friends who are about to buy.

DELIVERABLE FORMAT (strict):
Produce EXACTLY 7 slides, each marked clearly:

SLIDE 1: [Hook — clickbait-grade headline, max 10 words, text that goes ON the image. Must stop the scroll.]
SLIDE 2: [Secret #1 — one specific, concrete, insider-only fact about French RE buyers don't know. Max 18 words.]
SLIDE 3: [Secret #2 — same format, different angle: pricing / negotiation / frais de notaire]
SLIDE 4: [Secret #3 — diagnostic / DPE / hidden defects]
SLIDE 5: [Secret #4 — copropriété / charges / travaux votés mais pas encore facturés]
SLIDE 6: [Secret #5 — commission structure / agent incentives]
SLIDE 7: [Final: the mic-drop + a "save this post" CTA + "follow for the next 7"]

Then:
CAPTION: [140–200 word caption in YOUR voice — enthusiastic community builder, funny, ironic. Hook in first 2 lines. French (bilingual allowed but keep it French-first). End with a question to drive comments, then: "Follow @frenchimmoagent — on te dit ce que les autres te cachent."]
HASHTAGS: [8 growth-optimized French RE hashtags mixing broad + niche]

Market: France. Currency: EUR (€). Tone: punchy, community-building, ironic, save-worthy. NOT fear-mongering — empowering.""",
    },
    {
        "title": "Instagram carousel — Les 5 red flags d'une annonce immobilière (qui devraient te faire FUIR)",
        "brief": """Create a 6-slide Instagram carousel — educational + entertaining, designed to be SAVED and SHARED.

ANGLE: "5 red flags d'une annonce immobilière qui devraient te faire fuir" — the visible warning signs in a listing that 90% of buyers miss. Punchy, funny, with the satirical edge that makes people send it to their friends.

DELIVERABLE FORMAT (strict):
Produce EXACTLY 6 slides, each marked:

SLIDE 1: [Hook — 8 words max, dramatic, curiosity gap. Text ON the image.]
SLIDE 2: [Red flag #1 — photo/staging tell (e.g. wide-angle tricks, no exterior shot, one bathroom photo). Max 20 words.]
SLIDE 3: [Red flag #2 — wording tell ("coup de cœur", "rare sur le marché", "à rafraîchir") + what it actually means]
SLIDE 4: [Red flag #3 — price vs quartier anomaly / too good to be true]
SLIDE 5: [Red flag #4 — missing info (DPE, année de construction, charges annuelles)]
SLIDE 6: [Final red flag #5 + CTA: "Sauvegarde ce post avant ta prochaine visite" + follow prompt]

Then:
CAPTION: [130–190 word caption. Enthusiastic, ironic tone. Hook: "J'ai vu une annonce hier qui cochait les 5. Je te raconte." Story-driven. End with: "Tag quelqu'un qui cherche un appart 👇" + "Follow @frenchimmoagent."]
HASHTAGS: [8 French RE hashtags: #immobilierfrance #achatimmobilier #parisimmo + niche ones]

Market: France. Voice: community-builder, funny, slightly satirical, NEVER condescending — you're on the buyer's side.""",
    },
    {
        "title": "Instagram carousel — Le calcul que 97% des acheteurs français ne font PAS (et qui change tout)",
        "brief": """Create a 5-slide Instagram carousel — value-bomb post designed to make people follow immediately.

ANGLE: "Le calcul que 97% des acheteurs français ne font pas" — show the ONE financial calculation (rendement net réel, NOT rendement brut) that separates smart buyers from future regretters. Concrete, data-rich, massively shareable.

DELIVERABLE FORMAT (strict):
Produce EXACTLY 5 slides, each marked:

SLIDE 1: [Hook — stat-driven headline, 10 words max. Something like "97% des acheteurs oublient CE calcul" or similar. Text ON the image.]
SLIDE 2: [The wrong math everyone does — "Loyer × 12 ÷ prix = rendement" — show why this is a trap. Real numbers (example: 200k€ appart, 800€/mois = 4,8% brut).]
SLIDE 3: [The missing costs nobody mentions — taxe foncière, charges copro, vacance locative, assurance PNO, frais de gestion, travaux. Show total €/year drain.]
SLIDE 4: [The real math — same 200k€ appart, rendement NET réel ≈ 2,3%. Side-by-side with Livret A / LEP to contextualize.]
SLIDE 5: [The lesson + CTA: "Avant ton prochain achat, fais CE calcul." + "Follow @frenchimmoagent — on te donne les outils que ton agent ne te donnera pas."]

Then:
CAPTION: [150–210 word caption. Hook: "J'ai fait le calcul pour un client la semaine dernière. Il a failli acheter. Il n'a pas acheté." Story + numbers + lesson. End: "Sauvegarde ce post. Partage-le à la personne qui te dit que l'immobilier 'c'est toujours rentable'." + follow CTA.]
HASHTAGS: [8: mix of #immobilier #investissementlocatif #financespersonnelles + niche FR RE]

Market: France. Currency: EUR. Tone: enthusiastic educator, ironic about market myths, community-first. Make people feel SMARTER after reading.""",
    },
]


def main():
    db = get_db()
    agent = db.query(Agent).filter(Agent.id == FRENCHIMMOAGENT_ID).first()
    if not agent:
        print(f'Agent #{FRENCHIMMOAGENT_ID} not found.')
        return
    print(f'Dispatching 3 growth carousels for {agent.name} ({agent.brand})\n')

    for i, b in enumerate(BRIEFS, 1):
        task = Task(
            title=b['title'],
            description=b['brief'],
            status='in_progress',
            priority='high',
            created_by_type='user', created_by_key='supervisor', created_by_name='You',
            assignee_type='agent', assignee_key=str(agent.id), assignee_name=agent.name,
            department='newsroom',
        )
        db.add(task)
        db.commit()
        print(f'[{i}/3] Task #{task.id}: {b["title"][:70]}')
        try:
            _execute_individual_task(db, task, agent, 'agent', str(agent.id))
            db.commit()
            print(f'      OK complete\n')
        except Exception as e:
            import traceback
            print(f'      FAILED: {e}')
            print(traceback.format_exc())
            db.rollback()

    from src.database.models import Content
    print('=== Result ===')
    drafts = db.query(Content).filter(
        Content.agent_id == FRENCHIMMOAGENT_ID,
        Content.platform.in_(['instagram', 'Instagram']),
        Content.status == 'draft',
    ).order_by(Content.id.desc()).limit(5).all()
    for d in drafts:
        imgs = len(d.media_urls or [])
        print(f'  #{d.id} | {imgs} images | {(d.title or "")[:70]}')
    db.close()


if __name__ == '__main__':
    main()
