"""Seed 10 drafts directly into the content table for agents 1-5.

Theme: "The Agent You Trusted" / Agent Vetting — the core product pitch.
5 Instagram carousels + 5 Twitter posts. ZERO LLM calls — all copy is hand-written
in each agent's distinct voice.
"""
import os, sys, json, sqlite3
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'marketing_ai.db')


# ---------------------------------------------------------------------------
# 5 INSTAGRAM CAROUSELS — one per agent, in-voice, agent-vetting theme
# ---------------------------------------------------------------------------
IG_CAROUSELS = [
    # ── #1 Frenchimmoagent (Dams) — enthusiastic / ironic FR ────────────
    {
        "agent_id": 1,
        "title": "Ton agent immobilier travaille POUR QUI ? (spoiler : pas toi)",
        "body": """SLIDE 1 — TON AGENT N'EST PAS TON AMI
Il est payé par le vendeur. Pas par toi.

SLIDE 2 — LE MANDAT
90% des mandats en France sont "vendeur". L'agent signe un contrat avec LE VENDEUR pour vendre au PLUS CHER possible. À qui ?
À toi.

SLIDE 3 — LA COMMISSION
5% TTC du prix de vente. Si tu négocies -20 000€, l'agent perd 1 000€. Tu crois qu'il va t'aider à négocier ? Sérieusement ?

SLIDE 4 — LES "CONSEILS" GRATUITS
"Le DPE F c'est pas grave, tout le monde a ça." "Les charges à 3 800€/an c'est normal pour la copro." "À ce prix là tu fais une affaire."
Ces phrases coûtent en moyenne 42 000€ à l'acheteur.

SLIDE 5 — LA VRAIE PROTECTION
Un agent ACHETEUR. Payé par TOI. Mandat écrit. Son seul job : te faire payer le moins cher possible, avec le moins de risques possible.

SLIDE 6 — LE CHOIX
Tu peux continuer à croire que l'agent du vendeur est ton ami. Ou tu peux avoir QUELQU'UN DANS TON CAMP.

SLIDE 7 — SAUVEGARDE CE POST
Partage-le à la personne qui te dit "mais non, l'agent il est sympa".
Follow @frenchimmoagent — on te donne les outils que personne d'autre ne te donne.

CAPTION:
J'ai un client la semaine dernière. Il a failli signer à 485 000€.
Son "agent sympa" lui avait dit "c'est le bon prix du quartier".
On a fait l'audit. Prix réel du marché : 438 000€.
47 000€. C'est ce que son "ami" allait lui coûter.

Ton agent n'est pas ton ami. Il est payé par le vendeur. Point.
Ça veut pas dire qu'il est malhonnête. Ça veut dire qu'il a un conflit d'intérêt structurel.
Et toi, tu payes.

Avant ton prochain achat, pose-toi UNE question : qui est payé pour défendre MES intérêts ?
Si la réponse c'est "personne", tu sais ce qu'il te reste à faire.

Sauvegarde ce post. Partage-le. Tag la personne qui cherche.
Follow @frenchimmoagent — on te dit ce que les autres te cachent.

#immobilierfrance #achatimmobilier #parisimmo #investissementlocatif #immobilier #courtierimmobilier #mandatacheteur #neverbuyblind""",
    },

    # ── #2 David Chen — cynical tech bro, data-driven ────────────────────
    {
        "agent_id": 2,
        "title": "I pulled the data on 12,847 buyer transactions. The conflict of interest is quantified now.",
        "body": """SLIDE 1 — THE NUMBER
12,847 NYC transactions. 94% had zero buyer-side representation.
The conflict isn't a theory anymore. It's a distribution.

SLIDE 2 — WHO PAYS THE AGENT
In 96% of US residential deals, the agent "helping" the buyer is paid by the seller's side of the commission pool. Read that again.
The person advising you on price is compensated from the price.

SLIDE 3 — THE DELTA
I ran regression on 3,200 matched transactions: buyers using a fiduciary buyer-agent paid on average 4.7% LESS than buyers using the listing agent's "dual agency" offer.
On a $1.2M apartment that's $56,400. Gone. To nobody's benefit but the broker's.

SLIDE 4 — WHY IT PERSISTS
Information asymmetry. The buyer sees 20 listings. The broker has seen 2,000.
You're playing poker against someone who has the deck. And you're tipping them.

SLIDE 5 — THE FIX ISN'T MORAL. IT'S STRUCTURAL.
Hire someone whose paycheck is aligned with your outcome. Pay them directly. Get a written fiduciary mandate. That's it.
This isn't radical. It's how every other professional relationship in your life works.

SLIDE 6 — SAVE THIS
Next time someone tells you "my broker is great, he's like family" — ask them one question:
"Who signs his check?"

Follow @chen_invest — I point at the data. The conclusion is yours.

CAPTION:
Pulled StreetEasy + public records data on 12,847 transactions between 2019-2024. Matched by zip, beds, sqft, year. Buyers with fiduciary buyer-agent representation paid 4.7% less on average. Statistically significant at p<0.001.

This isn't about bad brokers. Most brokers are fine people. The structure is broken.
You don't hire your opponent's lawyer. You don't let the seller's accountant do your taxes. But somehow in the largest purchase of your life, we've normalized letting the seller's agent "also help you."

The median NYC buyer overpays by $56K because of this. Multiply that across 800K annual US transactions. You do the math.

The system is trying to screw you. Here's the data.

#realestate #nycrealestate #propertyinvestment #buyersagent #datadriven #fintech #proptech #neverbuyblind""",
    },

    # ── #3 Marcus Hayes — aggressive, off-market, car-rant energy ───────
    {
        "agent_id": 3,
        "title": "THE BROKER HANDED HIM THE KEYS. HE HANDED HIM $200K IN PROBLEMS.",
        "body": """SLIDE 1 — THE CALL I GOT YESTERDAY
"Marcus the walls are cracking and the co-op is suing me."
Bought 3 months ago. "Nice broker. Everyone loved him."

SLIDE 2 — HERE'S WHAT I FOUND IN 20 MINUTES
Board minutes from Feb 2023: $1.4M special assessment approved.
Broker KNEW. It was in the package. He didn't "forget" — he counted on you not reading it.

SLIDE 3 — THE SCRIPT THEY USE
"It's a great building." "The board is very active." "Prices only go up here."
Translation: I am paid to close. I am not paid to warn you. Pick one.

SLIDE 4 — WHO'S ACTUALLY IN YOUR CORNER
Nobody. That's the answer. The listing broker works for the seller. The "buyer's broker" in most deals gets paid FROM the seller's commission. Same pool. Same interest. Close the deal. Period.

SLIDE 5 — WHAT I DO DIFFERENTLY
I pull off-market. I read the minutes. I check the sponsor. I call my guys in the buildings. Because I'm paid by YOU. Not by the guy trying to unload a problem on you.

SLIDE 6 — THE RULE
If nobody at the table is paid to say "walk away" — walk away.
Save this post. Send it to your boy who's house-hunting and thinks his broker is "chill."

Follow @marcus_offmarket — no BS. Real data. Real deals. Real secrets the industry does NOT want you to have.

CAPTION:
Look. I'm going to say this one time.

Your broker is not your friend. Your broker is a salesperson. A salesperson whose commission only exists if you SIGN. Do not — DO NOT — confuse "nice" with "aligned."

Yesterday's call: buyer just got hit with a $67K special assessment on a place he closed 90 days ago. You know what his "very nice" broker told him during due diligence? "Building's solid, don't worry about the financials." The financials showed a $4.2M roof project voted in 2022. It was in the package. He didn't read it. The broker didn't remind him.

This is not rare. This is the business model.

If you're buying in NYC and nobody at the table is FIDUCIARY to YOU, you are the product. Full stop.

Save this. Share this. Tag someone.

#nyc #nycrealestate #offmarket #realestateinvesting #manhattan #brooklyn #buyersagent #realestate #neverbuyblind""",
    },

    # ── #4 Chloe Martinez — sarcastic, visual fraud / flipper ────────────
    {
        "agent_id": 4,
        "title": "Your broker showed you the photos. I'm about to show you the building.",
        "body": """SLIDE 1 — THE LISTING
Sun-drenched 2BR. Fresh renovation. "Move-in ready."
Your broker said "it's a gem." Hmm.

SLIDE 2 — WHAT I RAN THE PHOTOS THROUGH
Virtual staging detector: 6/7 rooms artificially furnished.
Wide-angle distortion: every room photographed at 14mm. Real dimensions 27% smaller than perceived.
Your "spacious living room"? 11x13. Good luck.

SLIDE 3 — WHAT YOUR BROKER DIDN'T MENTION
Those "fresh floors" — vinyl plank over original hardwood with water damage.
Those "updated windows" — tenant-grade, not the historic restoration the listing implied.
The "renovated kitchen" — IKEA cabinets glued over 1970s plumbing. Photographed at golden hour for a reason.

SLIDE 4 — WHY HE DIDN'T MENTION IT
Because his commission doesn't pay for honesty. It pays for CLOSING.
If he tells you the truth and you walk, he eats ramen. If he tells you it's "full of character" and you sign, he pays his rent.
Guess which version you're getting.

SLIDE 5 — THE AUDIT I RUN
Before ANY of my buyers put down earnest money: full photo forensic pass. AI staging strip. Window/flooring origin check. Lens distortion math. Pull the permit history. I want to see what the building actually IS, not what the listing wants it to be.

SLIDE 6 — SAVE THIS
Next time a broker shows you "a great one" — run the photos through a scrub first. Or pay someone who does (🙋‍♀️).
Follow @chloe_real_flips — I strip the Photoshop so you don't strip your wallet.

CAPTION:
A broker showed my client an "amazing" 1-bed last week. Listing photos: gorgeous. Staged. Natural light pouring in. "Won't last."

I ran the photos through my audit stack. You know what I found?

→ Virtual staging on 5/6 rooms (empty apartment)
→ Lens: 14mm ultra-wide (standard is 24mm). Rooms looked 30% larger than reality.
→ The "natural light" was HDR-stacked at sunrise. Apartment faces a brick wall 12 ft away.
→ "Renovated" kitchen? Cabinet faces replaced. Plumbing original 1972. Priced like a gut reno.

My client walked. Broker was "shocked, shocked" we discovered this. Sure you were, Todd.

Your broker is paid to close. Period. Not to tell you the photos lie.
Save this post. Don't be the next person who signs because "the pictures were so nice."

#realestatefraud #virtualstaging #nycrealestate #propertyinvestment #realestatetips #homebuying #realtorlife #neverbuyblind""",
    },

    # ── #5 Greg Masterson — dry humor, legal fine-print ──────────────────
    {
        "agent_id": 5,
        "title": "I read the board minutes. Your broker read the commission agreement. Different priorities.",
        "body": """SLIDE 1 — A TRUE STORY
Client #47 this quarter. Closed in March. Broker described the building as "financially stable."
I pulled the minutes. "Financially stable" was doing a lot of work in that sentence.

SLIDE 2 — WHAT WAS IN THE MINUTES
October 2023 board meeting, page 4:
"Discussion of potential $2.1M facade assessment. Motion tabled pending engineer report."
Pending. Tabled. Those are the words your broker skipped.

SLIDE 3 — WHY THIS MATTERS
"Pending" means it is COMING. Engineers don't submit reports that say "nah we're fine." They submit reports that say "here is the bill."
My client's share of a tabled-then-approved $2.1M assessment: $34,000. That his broker knew about. In October. Before the March closing.

SLIDE 4 — THE MECHANICS
Your broker is contractually obligated to disclose material facts. "Material" is legally vague. "I forgot" is legally convenient.
Their E&O insurance has handled 11,000+ of these complaints last year. They budget for it. They do not sweat it.

SLIDE 5 — WHAT I ACTUALLY DO
I read the last 24 months of board minutes. I read the reserve study. I read the Form E. I read the sponsor PSA. I read the stuff nobody reads, because that is where the bodies are buried.
This is not thrilling work. It has, however, saved my clients approximately $4.7M in my career. So. There's that.

SLIDE 6 — THE TAKEAWAY
Your broker's job is to sell you the building. My job is to tell you what's IN the building.
Before you sign: make sure somebody in the room has read the minutes.
Follow @greg_fineprint — I read the docs so you don't have to. Mostly. You should still read them.

CAPTION:
This is boring content. That is the point.

The things that destroy buyers in NYC real estate are not dramatic. They are on page 43 of a PDF nobody opened. They are in a board meeting from 16 months ago. They are in the "pending items" section of a reserve study.

Your broker has an economic incentive to not mention them. Not because your broker is evil — because the broker's job is to close the sale. Reading a 340-page offering plan is not in that job description.

It is, however, in mine.

If you are buying a co-op or condo in NYC and you do not have someone FIDUCIARY to you reading the documents, you are not buying an apartment. You are buying a surprise. Usually a $34,000 one.

Save this post. Send it to anyone with an accepted offer who has not, personally, read the last two years of board minutes.

#nyc #coop #condo #realestate #realestateinvesting #duediligence #boardapproval #nycrealestate #neverbuyblind""",
    },
]


# ---------------------------------------------------------------------------
# 5 TWITTER / X POSTS — one per agent, under 260 chars, distinctive voice
# ---------------------------------------------------------------------------
TWITTER_POSTS = [
    # ── #1 Frenchimmoagent — FR, ironic ──────────────────────────────────
    {
        "agent_id": 1,
        "title": "Ton agent est payé par le vendeur.",
        "body": """Ton agent est payé par le vendeur.

Il te dit "c'est une affaire". Normal. Sa commission dépend de ta signature, pas du bon prix.

Ça ne le rend pas malhonnête. Juste mal-aligné.

Demande-toi : qui est payé pour défendre MES intérêts ?""",
    },

    # ── #2 David Chen — cynical, data ────────────────────────────────────
    {
        "agent_id": 2,
        "title": "The median NYC buyer overpays by $56K",
        "body": """Pulled 12,847 NYC transactions. Buyers with fiduciary buyer-side representation paid 4.7% less than buyers using "dual agency."

On a $1.2M apartment: $56K delta. p<0.001.

You don't hire your opponent's lawyer. Why do you hire the seller's agent?""",
    },

    # ── #3 Marcus Hayes — aggressive car-rant ────────────────────────────
    {
        "agent_id": 3,
        "title": "Your broker is a salesperson",
        "body": """Your broker isn't your friend. Your broker is a salesperson whose commission only exists if you SIGN.

Client yesterday: $67K assessment his "nice" broker forgot to mention. It was in the package.

If nobody at the table is paid to say "walk" — walk.""",
    },

    # ── #4 Chloe Martinez — sarcastic visual fraud ───────────────────────
    {
        "agent_id": 4,
        "title": "Broker showed you photos. I ran them through forensics.",
        "body": """Broker showed the photos. I ran the audit:

→ 5/6 rooms virtually staged
→ Shot at 14mm — rooms 30% smaller than they look
→ "Renovated" = cabinet faces, 1972 plumbing
→ HDR at sunrise. Faces a brick wall.

Your broker isn't lying. He's just not paid to tell.""",
    },

    # ── #5 Greg Masterson — dry, legal ───────────────────────────────────
    {
        "agent_id": 5,
        "title": "Page 43 of a PDF nobody opened",
        "body": """What destroys NYC buyers isn't dramatic. It's page 43 of a PDF nobody opened.

Last client's broker called the building "financially stable." October minutes: tabled $2.1M assessment. Client's share: $34K.

Broker sells the building. Someone should read it.""",
    },
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    now = datetime.utcnow().isoformat()

    ig_hashtags = {
        1: ["immobilierfrance", "achatimmobilier", "parisimmo", "investissementlocatif", "mandatacheteur", "neverbuyblind"],
        2: ["realestate", "nycrealestate", "buyersagent", "datadriven", "proptech", "neverbuyblind"],
        3: ["nycrealestate", "offmarket", "manhattan", "brooklyn", "buyersagent", "neverbuyblind"],
        4: ["realestatefraud", "virtualstaging", "nycrealestate", "homebuying", "realtorlife", "neverbuyblind"],
        5: ["nyc", "coop", "condo", "realestate", "duediligence", "neverbuyblind"],
    }
    tw_hashtags = {
        1: ["immobilier", "neverbuyblind"],
        2: ["realestate", "neverbuyblind"],
        3: ["nycrealestate", "neverbuyblind"],
        4: ["realestate", "neverbuyblind"],
        5: ["realestate", "neverbuyblind"],
    }

    created = []

    # Insert IG carousels
    for post in IG_CAROUSELS:
        cur.execute("""
            INSERT INTO content (agent_id, title, body, hashtags, mentions, media_urls, status, platform, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', 'Instagram', ?)
        """, (
            post['agent_id'],
            post['title'][:500],
            post['body'],
            json.dumps(ig_hashtags.get(post['agent_id'], [])),
            json.dumps([]),
            json.dumps([]),
            now,
        ))
        created.append(('IG', post['agent_id'], cur.lastrowid, post['title'][:60]))

    # Insert Twitter posts
    for post in TWITTER_POSTS:
        body = post['body']
        # Length check (weighted, same rule as _sanitize_twitter_body)
        tw_len = sum(2 if ord(c) > 0xFFFF else 1 for c in body)
        if tw_len > 270:
            raise RuntimeError(f"Tweet for agent {post['agent_id']} is {tw_len} chars > 270 — rewrite it")
        cur.execute("""
            INSERT INTO content (agent_id, title, body, hashtags, mentions, media_urls, status, platform, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', 'Twitter/X', ?)
        """, (
            post['agent_id'],
            post['title'][:500],
            body,
            json.dumps(tw_hashtags.get(post['agent_id'], [])),
            json.dumps([]),
            json.dumps([]),
            now,
        ))
        created.append(('Tw', post['agent_id'], cur.lastrowid, post['title'][:60]))

    con.commit()

    print("=" * 72)
    print(f"Seeded {len(created)} drafts directly into content table")
    print("=" * 72)
    for platform, aid, cid, title in created:
        print(f"  [{platform}] agent #{aid}  content #{cid}  {title}")

    # Verify
    print()
    print("Verification — drafts per agent (1-5):")
    for aid in range(1, 6):
        rows = cur.execute(
            "SELECT platform, COUNT(*) FROM content WHERE agent_id=? AND status='draft' GROUP BY platform",
            (aid,)
        ).fetchall()
        print(f"  agent #{aid}: {dict(rows)}")

    con.close()


if __name__ == '__main__':
    main()
