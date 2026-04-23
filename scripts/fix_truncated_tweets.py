"""Rewrite Twitter drafts that were trimmed at 260 chars with a mid-sentence ellipsis
so they fit the 280-char limit cleanly, preserving meaning + persona voice.
"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass

from src.database.db import get_db
from src.database.models import Content, Agent
from src.api.llm_provider import LLMProvider


LIMIT = 270  # leave 10-char buffer under the 280 hard limit


def is_broken(body: str) -> bool:
    b = (body or '').rstrip()
    return len(b) > LIMIT or b.endswith('…') or b.endswith('...')


def rewrite(agent: Agent, body: str) -> str:
    llm = LLMProvider(
        provider=agent.llm_provider or 'claude',
        model=agent.llm_model or 'claude-sonnet-4-6',
    )
    sys_prompt = (
        f"You are {agent.name} ({agent.brand}). Persona: {agent.persona}. "
        f"Tone: {agent.tone_of_voice}.\n\n"
        f"You are rewriting a single tweet. Output MUST be ≤{LIMIT} characters "
        f"including spaces and punctuation. No ellipsis, no truncation. "
        f"Stay in persona voice. Output ONLY the tweet text, nothing else."
    )
    prompt = (
        f"Rewrite this tweet so it fits in ≤{LIMIT} characters without losing the core "
        f"point. Keep the punch. No '…'. Complete sentence. Output just the tweet.\n\n"
        f"---\n{body}\n---"
    )
    for _ in range(3):
        out = (llm.generate_content(prompt, max_tokens=300, temperature=0.5, system_prompt=sys_prompt) or '').strip()
        # strip quotes if the model wrapped the tweet
        if out.startswith('"') and out.endswith('"'):
            out = out[1:-1].strip()
        if out and len(out) <= LIMIT and not out.endswith('…'):
            return out
    # fallback: hard-trim at last sentence boundary
    t = body[:LIMIT]
    for sep in ['. ', '! ', '? ']:
        i = t.rfind(sep)
        if i > 100:
            return t[:i + 1]
    return t.rstrip()


def main():
    db = get_db()
    drafts = db.query(Content).filter(
        Content.platform == 'Twitter/X',
        Content.status == 'draft',
    ).all()
    broken = [d for d in drafts if is_broken(d.body)]
    print(f'Fixing {len(broken)} broken Twitter drafts…\n')

    fixed = 0
    for d in broken:
        agent = db.query(Agent).filter(Agent.id == d.agent_id).first()
        if not agent:
            continue
        try:
            new = rewrite(agent, d.body)
            print(f'#{d.id} {agent.name} | {len(d.body)}→{len(new)} chars')
            print(f'   OLD: {d.body[-70:]!r}')
            print(f'   NEW: {new[-70:]!r}\n')
            d.body = new
            d.title = new[:80]
            fixed += 1
            db.commit()
        except Exception as e:
            import traceback
            print(f'#{d.id} FAILED: {e}')
            print(traceback.format_exc())
            db.rollback()

    print(f'\n═══ Fixed {fixed}/{len(broken)} drafts ═══')
    db.close()


if __name__ == '__main__':
    main()
