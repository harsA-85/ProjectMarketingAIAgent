"""Backfill Twitter thread drafts from InternalMessage bodies.
Handles JSON (data.threads list or dict) and text (# THREAD N — NAME) formats.
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.db import get_db
from src.database.models import Task, Agent, Content, InternalMessage


TW_LIMIT = 260


def trim_tweet(t: str) -> str:
    t = t.strip()
    t = re.sub(r'^\*?\*?Tweet\s*\d+\s*/?\s*\d*\s*\*?\*?\s*\n+', '', t, flags=re.IGNORECASE)
    t = re.sub(r'^\d+/\s+', '', t)  # "1/ "
    if len(t) > TW_LIMIT:
        t = t[:TW_LIMIT - 1].rstrip() + '…'
    return t


def _name_to_agent_id(name_hint: str, agents: list[Agent]) -> int | None:
    nh = name_hint.lower()
    for a in agents:
        if a.name.lower() in nh:
            return a.id
    # Try first token
    first = nh.split()[0] if nh.split() else ''
    for a in agents:
        if first and first in a.name.lower():
            return a.id
    return None


def extract_tweets(text: str, agents: list[Agent]):
    """Yield (agent_id, [tweet_strings])."""
    results = []

    # ── JSON path ──
    for m in re.finditer(r'```json\s*(.+?)```', text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        threads = data.get('threads')
        if isinstance(threads, list):
            for t in threads:
                _yield_thread(t, agents, results)
        elif isinstance(threads, dict):
            for key, t in threads.items():
                _yield_thread(t, agents, results)
    if results:
        return results

    # ── Text path: "# THREAD N — NAME" or "# AGENT N — NAME" ──
    header_re = re.compile(
        r'(?:^|\n)#{1,4}\s*(?:THREAD|AGENT)\s*(\d+)\s*[—\-–:|]\s*([^\n(@]+?)(?:\s*\([^)]*\))?\s*\n',
        re.IGNORECASE,
    )
    matches = list(header_re.finditer(text))
    for i, m in enumerate(matches):
        num = int(m.group(1))
        name_hint = m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[m.end():end]
        aid = _name_to_agent_id(name_hint, agents) or num if num in {a.id for a in agents} else _name_to_agent_id(name_hint, agents)
        if not aid:
            continue
        # Extract tweets
        tweets = []
        for tm in re.finditer(
            r'\*?\*?Tweet\s*(\d+)(?:\s*/\s*\d+)?\*?\*?\s*\n+(.+?)(?=\n\s*(?:\*?\*?Tweet\s*\d+|---|\n#|\Z))',
            section, re.DOTALL | re.IGNORECASE,
        ):
            tweets.append(tm.group(2).strip())
        if tweets:
            results.append((aid, tweets))
    return results


def _yield_thread(t: dict, agents: list[Agent], results: list):
    aid = t.get('agent_id')
    if not aid and t.get('agent'):
        aid = _name_to_agent_id(t['agent'], agents)
    if not aid:
        return
    tw = t.get('thread') or t.get('tweets') or []
    texts = []
    for x in tw:
        if isinstance(x, dict):
            texts.append(x.get('text') or x.get('tweet') or '')
        elif isinstance(x, str):
            texts.append(x)
    if texts:
        results.append((aid, texts))


def main():
    db = get_db()
    agents = db.query(Agent).all()
    agent_ids = {a.id for a in agents}

    # All done Twitter-writing tasks (Cleveland, Saint-Étienne, etc.)
    tasks = db.query(Task).filter(
        Task.status == 'done',
        Task.title.like('%Twitter threads%'),
    ).all() + db.query(Task).filter(
        Task.status == 'done',
        Task.title.like('%write%thread%'),
    ).all()
    seen = set()
    uniq = []
    for t in tasks:
        if t.id in seen: continue
        seen.add(t.id); uniq.append(t)
    tasks = uniq

    created = 0
    for task in tasks:
        msg = db.query(InternalMessage).filter(
            InternalMessage.subject == f'✅ Deliverable: {task.title[:80]}'
        ).order_by(InternalMessage.id.desc()).first()
        text = (msg.body if msg else None) or (task.deliverable or '')
        if not text:
            continue
        for aid, items in extract_tweets(text, agents):
            if aid not in agent_ids:
                continue
            for raw in items:
                body = trim_tweet(raw)
                if len(body) < 20:
                    continue
                title_key = body[:80]
                dup = db.query(Content).filter(
                    Content.agent_id == aid,
                    Content.platform == 'Twitter/X',
                    Content.title == title_key,
                ).first()
                if dup:
                    continue
                db.add(Content(
                    agent_id=aid, title=title_key, body=body,
                    hashtags=[], media_urls=[],
                    platform='Twitter/X', status='draft',
                ))
                created += 1
        db.commit()
        print(f'  task {task.id}: processed')
    print(f'\nCreated {created} drafts')
    db.close()


if __name__ == '__main__':
    main()
