"""
Instagram Browser Automation Agent
Uses Playwright with a persistent browser context (real cookies, real session).
Simulates human behaviour: random delays, variable daily budgets, random rest days,
proxy support (one IP per agent), and deep anti-detection fingerprinting.
"""

import random
import time
import logging
import json
import os
from datetime import datetime, date
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

log = logging.getLogger(__name__)

# ── Safety limits — conservative hard caps ─────────────────────────────────
# Instagram's unofficial thresholds are ~60 likes/hr for old accounts;
# new / small accounts get flagged much sooner. These are intentionally low.
HARD_LIMITS = {
    'likes':     20,   # per day absolute max
    'follows':   8,    # per day absolute max
    'comments':  4,    # per day absolute max
    'unfollows': 6,    # per day absolute max
}

SESSIONS_DIR = Path(__file__).parent.parent.parent / 'sessions'
SESSIONS_DIR.mkdir(exist_ok=True)

# Rotate user agents — one chosen per session start (not per request)
_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
]

# Deep stealth init script injected into every page before any JS runs
_STEALTH_SCRIPT = """
// 1. Hide webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. Realistic plugin list (Chrome has these by default)
Object.defineProperty(navigator, 'plugins', { get: () => [
    { name: 'Chrome PDF Plugin',   filename: 'internal-pdf-viewer',             description: 'Portable Document Format' },
    { name: 'Chrome PDF Viewer',   filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
    { name: 'Native Client',       filename: 'internal-nacl-plugin',            description: '' },
]});

// 3. Languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// 4. Full chrome runtime object (missing in headless)
window.chrome = {
    runtime: { id: undefined, connect: () => {}, sendMessage: () => {} },
    loadTimes: function() { return {}; },
    csi:       function() { return {}; },
    app:       { isInstalled: false, getDetails: () => {}, getIsInstalled: () => false, runningState: () => 'cannot_run' },
};

// 5. Permissions API — headless returns 'denied' for notifications, real Chrome returns 'default'
const _origPermsQuery = window.navigator.permissions.query.bind(navigator.permissions);
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission || 'default', onchange: null })
        : _origPermsQuery(params);

// 6. WebGL vendor / renderer — real GPU strings instead of 'Google SwiftShader'
try {
    const _getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
        if (p === 37446) return 'Intel Iris Pro OpenGL'; // UNMASKED_RENDERER_WEBGL
        return _getParam.call(this, p);
    };
} catch(e) {}

// 7. Hide automation-related properties
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

// 8. Realistic screen / window dimensions
Object.defineProperty(screen, 'availWidth',  { get: () => window.outerWidth  });
Object.defineProperty(screen, 'availHeight', { get: () => window.outerHeight });

// 9. Spoof hardware concurrency & device memory (low values look bot-like)
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8 });

// 10. Connection info
Object.defineProperty(navigator, 'connection', { get: () => ({
    effectiveType: '4g', rtt: 50, downlink: 10.0, saveData: false
})});
"""


def _human_delay(min_s: float = 2.5, max_s: float = 9.0):
    """Pause like a real person — occasionally much longer (distraction simulation)."""
    t = random.uniform(min_s, max_s)
    r = random.random()
    if r < 0.06:
        t += random.uniform(15, 45)   # got distracted
    elif r < 0.15:
        t += random.uniform(5, 12)    # reading carefully
    time.sleep(t)


def _micro_delay():
    """Tiny pause between micro-actions (moving mouse, clicking)."""
    time.sleep(random.uniform(0.08, 0.4))


def _daily_budget() -> dict:
    """
    Today's randomised action budget.
    ~25% chance of full rest day — natural variation that avoids weekly patterns.
    On active days, budgets are intentionally low and varied.
    """
    if random.random() < 0.25:
        log.info('[AI-Auto] Rest day — no actions today.')
        return {'likes': 0, 'follows': 0, 'comments': 0}

    return {
        'likes':    random.randint(5,  HARD_LIMITS['likes']),
        'follows':  random.randint(0,  HARD_LIMITS['follows']),
        'comments': random.randint(0,  HARD_LIMITS['comments']),
    }


def _load_daily_state(agent_id: int) -> dict:
    path  = SESSIONS_DIR / f'agent_{agent_id}_daily.json'
    today = str(date.today())
    if path.exists():
        data = json.loads(path.read_text())
        if data.get('date') == today:
            return data
    budget = _daily_budget()
    state  = {
        'date':   today,
        'budget': budget,
        'done':   {'likes': 0, 'follows': 0, 'comments': 0},
    }
    path.write_text(json.dumps(state))
    return state


def _save_daily_state(agent_id: int, state: dict):
    (SESSIONS_DIR / f'agent_{agent_id}_daily.json').write_text(json.dumps(state))


def _remaining(state: dict) -> dict:
    return {
        k: max(0, state['budget'][k] - state['done'].get(k, 0))
        for k in state['budget']
    }


def _move_mouse_naturally(page, target_x: int, target_y: int):
    """
    Move mouse in a slightly curved path rather than teleporting.
    Uses 4–8 intermediate steps with small random jitter.
    """
    try:
        steps = random.randint(4, 8)
        curr  = page.evaluate("() => ({ x: window.innerWidth/2, y: window.innerHeight/2 })")
        cx, cy = curr.get('x', 640), curr.get('y', 400)
        for i in range(1, steps + 1):
            ratio = i / steps
            nx = cx + (target_x - cx) * ratio + random.uniform(-8, 8)
            ny = cy + (target_y - cy) * ratio + random.uniform(-8, 8)
            page.mouse.move(nx, ny)
            time.sleep(random.uniform(0.02, 0.08))
    except Exception:
        pass  # mouse movement is best-effort


def _natural_scroll(page):
    """Scroll down in 2–4 bursts, occasionally scroll back up a little."""
    total = random.randint(2, 4)
    for _ in range(total):
        dist = random.randint(200, 600)
        page.mouse.wheel(0, dist)
        time.sleep(random.uniform(0.4, 1.4))
    # 30% chance to scroll back up a bit — like re-reading
    if random.random() < 0.30:
        time.sleep(random.uniform(0.5, 1.5))
        page.mouse.wheel(0, -random.randint(100, 350))
        time.sleep(random.uniform(0.3, 0.8))


class InstagramAgent:
    """
    Handles one Instagram account for one agent.
    Persistent context = stays logged in across sessions.
    Each agent can have its own proxy (residential IP recommended).
    """

    def __init__(self, agent_id: int, username: str, password: str,
                 target_hashtags: list = None, ai_comment_fn=None,
                 proxy: str = None):
        self.agent_id        = agent_id
        self.username        = username
        self.password        = password
        self.target_hashtags = target_hashtags or ['realestate', 'investing', 'propertymarket']
        self.ai_comment_fn   = ai_comment_fn   # callable(post_caption) → str
        self.proxy           = proxy            # e.g. "http://user:pass@host:port"
        self.profile_dir     = str(SESSIONS_DIR / f'agent_{agent_id}_profile')
        os.makedirs(self.profile_dir, exist_ok=True)

    # ── Public entry point ──────────────────────────────────────────────────

    def run_session(self, status_cb=None) -> dict:
        """
        Run one engagement session (a few minutes of organic activity).
        Returns summary dict: {'likes': n, 'follows': n, 'comments': n, 'errors': [...]}.
        """
        state   = _load_daily_state(self.agent_id)
        remain  = _remaining(state)
        summary = {'likes': 0, 'follows': 0, 'comments': 0, 'errors': []}

        if all(v == 0 for v in remain.values()):
            log.info(f'[AI-Auto] Agent {self.agent_id}: daily budget exhausted or rest day.')
            return summary

        def cb(msg):
            log.info(f'[AI-Auto] {self.username}: {msg}')
            if status_cb:
                status_cb(msg)

        # Pick today's user agent (consistent per session, not per page)
        ua = random.choice(_USER_AGENTS)

        # Proxy config for Playwright
        proxy_cfg = None
        if self.proxy:
            proxy_cfg = {'server': self.proxy}
            cb(f'Using proxy: {self.proxy.split("@")[-1] if "@" in self.proxy else self.proxy}')

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                self.profile_dir,
                headless=True,
                proxy=proxy_cfg,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-infobars',
                    '--disable-extensions',
                    '--disable-default-apps',
                    '--no-first-run',
                    '--disable-background-networking',
                    '--disable-sync',
                    '--metrics-recording-only',
                    '--disable-features=TranslateUI',
                ],
                user_agent=ua,
                viewport={
                    'width':  random.choice([1280, 1366, 1440, 1536]),
                    'height': random.choice([768, 800, 900, 864]),
                },
                locale='en-US',
                timezone_id=random.choice([
                    'America/New_York', 'America/Chicago',
                    'America/Los_Angeles', 'America/Denver',
                ]),
                color_scheme=random.choice(['light', 'no-preference']),
                device_scale_factor=random.choice([1, 1.25, 1.5]),
            )

            try:
                page = browser.pages[0] if browser.pages else browser.new_page()

                # Inject stealth overrides before any page script runs
                page.add_init_script(_STEALTH_SCRIPT)

                if not self._is_logged_in(page):
                    cb('Logging in…')
                    if not self._login(page):
                        summary['errors'].append('Login failed')
                        return summary
                    cb('Logged in ✓')
                else:
                    cb('Session active ✓')

                # ── Warm-up: browse home feed briefly (looks natural) ──
                if random.random() < 0.70:
                    cb('Browsing home feed…')
                    self._browse_home_feed(page)

                # ── Main engagement loop ──
                hashtag = random.choice(self.target_hashtags)
                cb(f'Exploring #{hashtag}…')
                posts = self._get_hashtag_posts(page, hashtag)
                random.shuffle(posts)

                # Skip 1–3 posts at the start — real users don't click the first thing
                skip = random.randint(1, 3)
                posts = posts[skip:]

                for post_url in posts:
                    remain = _remaining(state)
                    if all(v == 0 for v in remain.values()):
                        break

                    try:
                        self._engage_post(page, post_url, state, summary, cb)
                    except Exception as e:
                        log.warning(f'[AI-Auto] Post error: {e}')
                        summary['errors'].append(str(e)[:80])

                    # Human pause between posts — longer than you'd expect
                    _human_delay(6, 25)

            finally:
                _save_daily_state(self.agent_id, state)
                browser.close()

        cb(f'Session done — likes:{summary["likes"]} follows:{summary["follows"]} comments:{summary["comments"]}')
        return summary

    # ── Internal helpers ────────────────────────────────────────────────────

    def _is_logged_in(self, page) -> bool:
        try:
            page.goto('https://www.instagram.com/', timeout=20000)
            _human_delay(2, 5)
            return (
                'instagram.com/accounts/login' not in page.url and
                page.locator('svg[aria-label="Home"]').count() > 0
            )
        except Exception:
            return False

    def _login(self, page) -> bool:
        try:
            page.goto('https://www.instagram.com/accounts/login/', timeout=25000)
            _human_delay(2, 5)

            # Type username char-by-char with human-speed variation
            ufield = page.locator('input[name="username"]')
            ufield.click()
            _human_delay(0.5, 1.5)
            for ch in self.username:
                page.keyboard.type(ch, delay=random.randint(70, 200))
                # Tiny random hesitation (fat-finger moment)
                if random.random() < 0.04:
                    time.sleep(random.uniform(0.4, 1.2))

            _human_delay(0.8, 2.5)
            page.locator('input[name="password"]').click()
            _human_delay(0.3, 0.8)
            for ch in self.password:
                page.keyboard.type(ch, delay=random.randint(70, 200))

            _human_delay(1.0, 3.0)
            page.locator('button[type="submit"]').click()
            page.wait_for_url('https://www.instagram.com/', timeout=25000)
            _human_delay(2, 5)

            for txt in ['Save Info', 'Not Now']:
                try:
                    page.locator(f'button:has-text("{txt}")').click(timeout=4000)
                    _human_delay(1, 2)
                except Exception:
                    pass

            return True
        except Exception as e:
            log.error(f'[AI-Auto] Login error: {e}')
            return False

    def _browse_home_feed(self, page):
        """Spend 20–60 seconds on the home feed to warm up the session."""
        try:
            page.goto('https://www.instagram.com/', timeout=20000)
            _human_delay(3, 7)
            for _ in range(random.randint(2, 4)):
                _natural_scroll(page)
                _human_delay(3, 10)
        except Exception:
            pass

    def _get_hashtag_posts(self, page, hashtag: str) -> list:
        """Browse a hashtag explore page and collect post URLs."""
        try:
            page.goto(f'https://www.instagram.com/explore/tags/{hashtag}/', timeout=25000)
            _human_delay(3, 7)
            _natural_scroll(page)
            _human_delay(1, 3)
            _natural_scroll(page)

            links = page.locator('a[href*="/p/"]').all()
            urls  = list({l.get_attribute('href') for l in links if l.get_attribute('href')})
            full  = [f'https://www.instagram.com{u}' if u.startswith('/') else u for u in urls]
            return full[:25]
        except Exception as e:
            log.warning(f'[AI-Auto] Hashtag fetch error: {e}')
            return []

    def _engage_post(self, page, post_url: str, state: dict, summary: dict, cb):
        """Visit one post and organically decide whether to like, comment, follow."""
        page.goto(post_url, timeout=25000)
        _human_delay(2, 6)

        # Move mouse around randomly — simulates reading
        _move_mouse_naturally(page,
            random.randint(300, 900),
            random.randint(200, 600))
        _micro_delay()

        # Scroll to simulate reading captions / comments
        _natural_scroll(page)

        # "Reading time" — proportional to post length
        _human_delay(random.uniform(4, 18))

        remain = _remaining(state)

        # ── Like (75% chance if budget allows) ──
        if remain['likes'] > 0 and random.random() < 0.75:
            try:
                like_btn = page.locator('svg[aria-label="Like"]').first
                if like_btn.count() > 0:
                    bbox = like_btn.bounding_box()
                    if bbox:
                        _move_mouse_naturally(page,
                            int(bbox['x'] + bbox['width'] / 2),
                            int(bbox['y'] + bbox['height'] / 2))
                        _micro_delay()
                        like_btn.click()
                        state['done']['likes'] = state['done'].get('likes', 0) + 1
                        summary['likes'] += 1
                        cb('Liked post')
                        _human_delay(1.5, 5)
            except Exception:
                pass

        # ── Comment (20% chance if budget allows) ──
        if _remaining(state)['comments'] > 0 and random.random() < 0.20 and self.ai_comment_fn:
            try:
                caption_el   = page.locator('h1, ._a9zs').first
                caption      = caption_el.inner_text(timeout=3000) if caption_el.count() > 0 else ''
                comment_text = self.ai_comment_fn(caption[:300])
                if comment_text:
                    cbox = page.locator(
                        'textarea[placeholder*="comment"], textarea[aria-label*="comment"]'
                    ).first
                    if cbox.count() > 0:
                        _move_mouse_naturally(page, *[
                            int(v) for v in [
                                cbox.bounding_box()['x'] + 10,
                                cbox.bounding_box()['y'] + 10,
                            ]
                        ]) if cbox.bounding_box() else None
                        cbox.click()
                        _human_delay(0.5, 1.5)
                        for ch in comment_text:
                            page.keyboard.type(ch, delay=random.randint(55, 170))
                            if random.random() < 0.03:  # occasional pause while typing
                                time.sleep(random.uniform(0.5, 2.0))
                        _human_delay(1.5, 4)
                        page.keyboard.press('Enter')
                        state['done']['comments'] = state['done'].get('comments', 0) + 1
                        summary['comments'] += 1
                        cb(f'Commented: {comment_text[:40]}…')
                        _human_delay(3, 8)
            except Exception:
                pass

        # ── Follow (25% chance if budget allows) ──
        if _remaining(state)['follows'] > 0 and random.random() < 0.25:
            try:
                follow_btn = page.locator('button:has-text("Follow")').first
                if follow_btn.count() > 0:
                    bbox = follow_btn.bounding_box()
                    if bbox:
                        _move_mouse_naturally(page,
                            int(bbox['x'] + bbox['width'] / 2),
                            int(bbox['y'] + bbox['height'] / 2))
                        _micro_delay()
                        follow_btn.click()
                        state['done']['follows'] = state['done'].get('follows', 0) + 1
                        summary['follows'] += 1
                        cb('Followed user')
                        _human_delay(3, 8)
            except Exception:
                pass
