"""Generate Ting Pub 2 (buyer facing 5 agents in a video grid): one base scene,
then 5 outputs — a no-text version (yesterday's style) + 4 headline variants.
Text rendered in PIL (cream bold sans + one gold serif-italic word) for clean,
controllable, consistent typography across all variants. Real Ting logo overlaid."""
import os, sys, io, base64, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from PIL import Image, ImageDraw, ImageFont
from src.api.image_generator import OpenAIImageGenerator
from src.branding.ting_logo import overlay_logo

MEDIA = os.path.join('dashboard', 'static', 'media')
os.makedirs(MEDIA, exist_ok=True)
SANS = 'C:/Windows/Fonts/arialbd.ttf'
SERIF_IT = 'C:/Windows/Fonts/georgiai.ttf'
CREAM = (244, 239, 224)
GOLD = (255, 204, 0)

BRAND = ('TING BRAND SYSTEM: background pure black #000000 dominant, deep-space void feel. Gold #FFCC00 only on '
 'tiny UI details, used SPARINGLY. Light tones warm cream, never pure white. Premium, editorial, restrained, '
 'cinematic, Mad-Men-era confidence, lots of negative space.')
PUB2 = (BRAND + ' Vertical 4:5 photograph, NO TEXT anywhere. Cinematic shot from behind: a confident buyer at a '
 'minimalist dark desk facing a screen showing five real estate agents in a video-call grid. The buyer is relaxed '
 'and in control, backlit by warm window light against a near-black interior. 35mm film grain, shallow depth of '
 'field, premium editorial aesthetic. Gold accents only on small UI details. Keep the LOWER THIRD darker and '
 'calmer (near-black, low detail) so text can be overlaid later. Absolutely no text, no words, no letters, no '
 'captions, no logos anywhere.')

# (full headline, the single emphasized word -> gold serif italic)
HEADLINES = [
    ('Five agents. One that works for you.', 'you'),
    ('Interview your agent before you trust them.', 'trust'),
    ("Don't pick the first agent. Compare five.", 'five'),
    ('Meet your agents before they meet your money.', 'money'),
]


def _split_punct(tok):
    core = tok
    trail = ''
    while core and core[-1] in '.,;:!?':
        trail = core[-1] + trail
        core = core[:-1]
    return core, trail


def draw_punchline(im, headline, italic_word, size=58, margin=70, bottom_pad=210):
    """Left-aligned wrapped punchline: cream bold sans, the emphasized word in
    gold serif italic. Sits just above the logo."""
    d = ImageDraw.Draw(im)
    W, H = im.size
    f_sans = ImageFont.truetype(SANS, size)
    f_ital = ImageFont.truetype(SERIF_IT, int(size * 1.06))
    space_w = d.textlength(' ', font=f_sans)
    max_w = W - 2 * margin

    # Build tokens with per-word font/color/glue (glue=True -> no space before)
    tokens = []
    for tok in headline.split(' '):
        core, trail = _split_punct(tok)
        if core.lower() == italic_word.lower():
            tokens.append((core, f_ital, GOLD, False))
            if trail:
                tokens.append((trail, f_sans, CREAM, True))  # glue punctuation
        else:
            tokens.append((core + trail, f_sans, CREAM, False))

    # Greedy wrap
    lines, cur, cur_w = [], [], 0
    for word, font, color, glue in tokens:
        ww = d.textlength(word, font=font)
        add = ww + (space_w if (cur and not glue) else 0)
        if cur and cur_w + add > max_w:
            lines.append(cur); cur, cur_w = [], 0
            add = ww
        cur.append((word, font, color, glue)); cur_w += add
    if cur:
        lines.append(cur)

    line_h = int(size * 1.2)
    block_h = len(lines) * line_h
    y = H - bottom_pad - block_h
    for line in lines:
        x = margin
        for i, (word, font, color, glue) in enumerate(line):
            if i and not glue:
                x += space_w
            d.text((x, y), word, font=font, fill=color)
            x += d.textlength(word, font=font)
        y += line_h
    return im


def gen_base():
    gen = OpenAIImageGenerator(quality='high')
    for attempt in range(3):
        print('base attempt', attempt + 1)
        b64 = gen.generate_image(PUB2, size='1024x1536')
        if b64:
            full = Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGB')
            w, h = full.size
            th = int(w * 5 / 4)
            return full.crop((0, h - th, w, h)) if h > th else full
        time.sleep(5)
    raise RuntimeError('base generation failed')


def main():
    base_path = os.path.join(MEDIA, 'tingad_pub2_base.jpg')
    if os.environ.get('REUSE_BASE') == '1' and os.path.exists(base_path):
        print('reusing existing base scene (no image gen)')
        base = Image.open(base_path).convert('RGB')
    else:
        base = gen_base()
        base.save(base_path, 'JPEG', quality=94)

    # no-text (yesterday's style) — logo only
    notext = overlay_logo(base.copy(), height_px=60, margin_x=70, margin_y=64)
    notext.save(os.path.join(MEDIA, 'tingad_pub2_notext.jpg'), 'JPEG', quality=94)
    print('saved tingad_pub2_notext.jpg')

    # 4 headline variants
    for i, (headline, word) in enumerate(HEADLINES, 1):
        im = base.copy()
        im = draw_punchline(im, headline, word)
        im = overlay_logo(im, height_px=60, margin_x=70, margin_y=64)
        fn = f'tingad_pub2_v{i}.jpg'
        im.save(os.path.join(MEDIA, fn), 'JPEG', quality=94)
        print('saved', fn, '->', headline)


if __name__ == '__main__':
    main()
