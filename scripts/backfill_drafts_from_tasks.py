"""Backfill Content drafts from completed aggregate tasks.

Parses deliverables of 'done' tasks that cover multiple agents (e.g.
"Write 5 threads (1 per agent)") and splits them into per-agent Content rows.
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.db import get_db
from src.database.models import Task, Agent, Content


AGENT_HEADER_RE = re.compile(
    r'^(?:#{1,4}\s*)?(?:\*\*)?\s*AGENT\s*(\d+)(?:\s*[—\-–:|]\s*([^\n*]+?))?(?:\*\*)?\s*$',
    re.IGNORECASE | re.MULTILINE,
)


def detect_platform(task: Task) -> str | None:
    t = f"{task.title or ''} {task.description or ''}".lower()
    if any(k in t for k in ['carousel', 'caption', 'instagram']):
        return 'Instagram'
    if any(k in t for k in ['tweet', 'thread', 'twitter', ' x ', 'x/', '/x']):
        return 'Twitter/X'
    if 'linkedin' in t:
        return 'LinkedIn'
    if 'tiktok' in t:
        return 'TikTok'
    return None


def split_by_agent(deliverable: str, agents_by_id: dict, agents_by_name: dict) -> list[tuple[int, str]]:
    """Return [(agent_id, section_text), ...]."""
    if not deliverable:
        return []
    matches = list(AGENT_HEADER_RE.finditer(deliverable))
    if not matches:
        return []
    sections = []
    for i, m in enumerate(matches):
        agent_num = int(m.group(1))
        name_hint = (m.group(2) or '').strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(deliverable)
        body = deliverable[m.end():end].strip()

        agent_id = None
        if agent_num in agents_by_id:
            agent_id = agents_by_id[agent_num]
        if not agent_id and name_hint:
            for name_lower, aid in agents_by_name.items():
                if name_lower in name_hint.lower():
                    agent_id = aid
                    break
        if agent_id and len(body) > 40:
            sections.append((agent_id, body))
    return sections


def extract_post_body(section: str, platform: str) -> str | None:
    """Pull the actual post copy out of a per-agent section."""
    # Strategy 1: MAIN CAPTION / CAPTION / POST / TWEET markers
    for label in ['MAIN CAPTION', 'FINAL CAPTION', 'CAPTION', 'POST COPY',
                  'FINAL COPY', 'TWEET', 'THREAD', 'FINAL THREAD']:
        m = re.search(
            rf'\*?\*?{label}[^:\n]*:?\*?\*?\s*(?:\(\d+\s*words\))?\s*\n+(.+?)(?=\n\s*\n\s*(?:\*?\*?(?:HASHTAG|CTA|CLUSTER|NOTES|VARIANT|TWEET|---))|\n---|\Z)',
            section, re.IGNORECASE | re.DOTALL,
        )
        if m:
            body = m.group(1).strip()
            body = re.sub(r'^\*\*|\*\*$', '', body).strip()
            if len(body) > 40:
                return body

    # Strategy 2: First substantial blockquote
    bqs = re.findall(r'(?:^|\n)((?:>\s*[^\n]+\n?)+)', section)
    for bq in bqs:
        clean = re.sub(r'^>\s?', '', bq, flags=re.MULTILINE).strip()
        if len(clean) > 60:
            return clean

    # Strategy 3: For Twitter threads, concatenate "Tweet 1/N" blocks
    if platform == 'Twitter/X':
        tweets = re.findall(
            r'(?:^|\n)(?:\*?\*?(?:TWEET|Tweet)\s*\d+(?:\s*(?:of|/)\s*\d+)?:?\*?\*?)\s*\n+(.+?)(?=\n\s*(?:\*?\*?(?:TWEET|Tweet)\s*\d+|HASHTAG|---|\Z))',
            section, re.DOTALL,
        )
        if tweets:
            return '\n\n'.join(t.strip() for t in tweets if len(t.strip()) > 20)

    # Strategy 4: first big paragraph
    paras = [p.strip() for p in section.split('\n\n') if len(p.strip()) > 80]
    for p in paras:
        if not p.startswith(('#', '*', '-', '>', '```', '|', 'HASHTAG', 'CTA', 'NOTES')):
            return p
    return None


_TW_LIMIT = 260


def sanitize(body: str, platform: str) -> str:
    body = re.sub(r'\*\*(.+?)\*\*', r'\1', body)
    body = re.sub(r'\*(.+?)\*', r'\1', body)
    body = body.strip()
    if platform == 'Twitter/X' and len(body) > _TW_LIMIT:
        body = body[:_TW_LIMIT - 1].rstrip() + '…'
    return body


def main():
    db = get_db()
    agents = db.query(Agent).filter(Agent.is_active == True).order_by(Agent.id).all()
    agents_by_id = {a.id: a.id for a in agents}  # AGENT N → assumes N == id
    agents_by_name = {a.name.lower(): a.id for a in agents}

    # Also support "AGENT 1..5" mapping to first 5 agents if IDs don't align
    first_five = [a.id for a in agents[:5]]
    for i, aid in enumerate(first_five, start=1):
        agents_by_id.setdefault(i, aid)

    candidates = db.query(Task).filter(
        Task.status == 'done',
        Task.deliverable.isnot(None),
    ).order_by(Task.id).all()

    created = 0
    skipped = 0
    per_task = []
    for task in candidates:
        platform = detect_platform(task)
        if not platform:
            continue
        sections = split_by_agent(task.deliverable or '', agents_by_id, agents_by_name)
        if not sections:
            continue
        task_created = 0
        for agent_id, sec in sections:
            body = extract_post_body(sec, platform)
            if not body or len(body.strip()) < 60:
                continue
            body = sanitize(body, platform)

            # Dedupe: skip if a draft with same agent+platform+first 80 chars already exists
            title_key = body[:80]
            dup = db.query(Content).filter(
                Content.agent_id == agent_id,
                Content.platform == platform,
                Content.title == title_key,
            ).first()
            if dup:
                skipped += 1
                continue
            post = Content(
                agent_id=agent_id,
                title=title_key,
                body=body,
                hashtags=[],
                media_urls=[],
                platform=platform,
                status='draft',
            )
            db.add(post)
            task_created += 1
        if task_created:
            db.commit()
            per_task.append((task.id, task.title[:70], task_created))
            created += task_created

    print(f'\n✅ Created {created} drafts across {len(per_task)} tasks (skipped {skipped} duplicates)\n')
    for tid, title, n in per_task:
        print(f'  #{tid:3d}  +{n}  {title}')
    db.close()


if __name__ == '__main__':
    main()
