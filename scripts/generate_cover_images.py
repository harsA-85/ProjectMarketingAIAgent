"""Generate 1 cover image per IG draft (IDs 252-256) using Gemini.
Writes to dashboard/static/media/ and updates content.media_urls.
"""
import os, sys, json, uuid, base64, sqlite3, logging

os.environ['PYTHONIOENCODING'] = 'utf-8'
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

from src.api.image_generator import GeminiImageGenerator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'marketing_ai.db')
MEDIA_DIR = os.path.join(ROOT, 'dashboard', 'static', 'media')
os.makedirs(MEDIA_DIR, exist_ok=True)


COVERS = {
    252: (
        "Moody editorial photograph, French Haussmann apartment building exterior at dusk, "
        "cinematic Paris street scene, warm golden light, real estate magazine quality, "
        "rich color grading, shallow depth of field, square 1:1 format. "
        "STRICT: NO text, NO words, NO letters, NO logos, NO watermarks, NO UI elements, "
        "full-bleed edge-to-edge composition, NO borders or frames."
    ),
    253: (
        "Dark minimalist financial data visualization backdrop, abstract terminal charts "
        "and scatter plot glow on deep navy background, cinematic fintech aesthetic, "
        "subtle blue/green data glow, ultra high contrast, editorial quality, square 1:1. "
        "STRICT: NO text, NO words, NO numbers rendered as legible characters, NO letters, "
        "NO logos, NO watermarks, full-bleed edge-to-edge, NO borders."
    ),
    254: (
        "Cinematic view through a car windshield at night, NYC skyline blurred through rain-streaked glass, "
        "yellow cab headlights, gritty urban realism, Bronx/Queens/Manhattan vibe, "
        "moody high-contrast color grade, square 1:1 format. "
        "STRICT: NO text, NO words, NO letters, NO logos, NO watermarks, NO UI, "
        "full-bleed edge-to-edge, NO borders or frames."
    ),
    255: (
        "Split-frame editorial still: left side shows a staged perfect listing photo of a bright empty apartment, "
        "right side shows the same room dim and stripped bare with visible water damage and cracks, "
        "Instagram-vs-reality comparison aesthetic, sharp documentary photography, square 1:1. "
        "STRICT: NO text, NO words, NO letters, NO labels, NO logos, NO watermarks, "
        "full-bleed edge-to-edge composition, NO borders."
    ),
    256: (
        "Top-down editorial still life: an open leather-bound document binder on a dark wooden desk, "
        "pages dense with legal text (illegible, abstract blur), vintage reading lamp glow, "
        "brass magnifying glass resting on the page, moody chiaroscuro lighting, "
        "The Office dry humor aesthetic, square 1:1 format. "
        "STRICT: NO legible text, NO readable words, NO letters that can be read, "
        "NO logos, NO watermarks, full-bleed edge-to-edge, NO borders."
    ),
}


def main():
    gen = GeminiImageGenerator()
    con = sqlite3.connect(DB)
    cur = con.cursor()

    for cid, prompt in COVERS.items():
        row = cur.execute('SELECT agent_id, title FROM content WHERE id=?', (cid,)).fetchone()
        if not row:
            print(f'#{cid}: NOT FOUND')
            continue
        print(f'#{cid} ag{row[0]}: generating cover...')
        b64 = gen.generate_image(prompt)
        if not b64:
            print(f'  FAILED')
            continue
        fname = f'cover_{uuid.uuid4().hex[:12]}.jpg'
        fpath = os.path.join(MEDIA_DIR, fname)
        with open(fpath, 'wb') as f:
            f.write(base64.b64decode(b64))
        url = f'/static/media/{fname}'
        cur.execute('UPDATE content SET media_urls=? WHERE id=?', (json.dumps([url]), cid))
        con.commit()
        print(f'  OK {url} ({os.path.getsize(fpath)//1024}KB)')

    con.close()
    print('\nDone. Refresh Newsroom to see covers.')


if __name__ == '__main__':
    main()
