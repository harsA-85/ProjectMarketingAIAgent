from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
import os
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass
import sys
import logging
import threading
import traceback

# Ensure image-gen errors are visible in the terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

# Catch ANY unhandled exception (main thread + background threads)
def _global_except(exc_type, exc_val, exc_tb):
    logging.error(f"UNHANDLED EXCEPTION: {exc_val}\n{''.join(traceback.format_exception(exc_type, exc_val, exc_tb))}")
sys.excepthook = _global_except

def _thread_except(args):
    logging.error(f"THREAD CRASH [{args.thread.name}]: {args.exc_value}\n{''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))}")
threading.excepthook = _thread_except

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator.orchestrator import Orchestrator
from src.database.db import init_db
from src.api.llm_provider import LLMProvider

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app = Flask(__name__, static_folder=_STATIC_DIR)
CORS(app)

@app.route('/js/<path:filename>')
def serve_js_file(filename):
    filepath = os.path.join(_STATIC_DIR, filename)
    if not os.path.isfile(filepath):
        return f"NOT FOUND: {filepath}", 404
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    from flask import Response
    return Response(content, mimetype='application/javascript')

# Serve saved media files (used as public URLs for Instagram publishing)
@app.route('/static/media/<path:filename>')
def serve_media(filename):
    import mimetypes
    media_dir = os.path.join(os.path.dirname(__file__), 'static', 'media')
    filepath = os.path.join(media_dir, filename)
    mime = mimetypes.guess_type(filepath)[0] or 'image/jpeg'
    response = send_file(filepath, mimetype=mime)
    # ngrok browser warning bypass — required so Instagram fetches raw image
    response.headers['ngrok-skip-browser-warning'] = '1'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# ── Department mapping: role_key → department ──
_ROLE_DEPT = {
    'eic': 'newsroom', 'head_intelligence': 'newsroom', 'creative_director': 'newsroom',
    'prompt_engineer_1': 'newsroom', 'prompt_engineer_2': 'newsroom',
    'production_manager': 'newsroom', 'copywriter_1': 'newsroom', 'copywriter_2': 'newsroom',
    'distribution_specialist': 'newsroom',
    'cto': 'tech', 'lead_engineer': 'tech', 'data_engineer': 'tech',
    'vp_sales': 'sales', 'biz_dev': 'sales', 'account_exec': 'sales',
    'general_manager': 'leadership', 'cofounder': 'leadership',
}

def _dept_from_assignee(assignee_key):
    """Return department string for a given role_key."""
    return _ROLE_DEPT.get(assignee_key, 'newsroom')

orchestrator = None

autopilot      = None
ai_auto_sched  = None
workflow_engine = None

def _bootstrap():
    """Initialize orchestrator, autopilot, scheduler, workflow engine at startup."""
    global orchestrator, autopilot, ai_auto_sched, workflow_engine
    init_db()
    from src.database.db import seed_editorial_team, seed_departments, get_db
    seed_editorial_team()
    seed_departments()

    orchestrator = Orchestrator()
    from src.autopilot.engine import AutopilotEngine
    autopilot = AutopilotEngine(db_factory=get_db, orchestrator=orchestrator)
    autopilot.start()
    from src.automation.scheduler import AIAutoScheduler
    ai_auto_sched = AIAutoScheduler(db_factory=get_db, orchestrator=orchestrator)
    ai_auto_sched.start()
    from src.editorial.workflow_engine import WorkflowEngine
    workflow_engine = WorkflowEngine(db_factory=get_db)

try:
    _bootstrap()
except Exception as e:
    logging.error(f"BOOTSTRAP FAILED: {e}\n{traceback.format_exc()}")

# ── One-time backfill: create Content drafts for orphaned AtomizedContent ──
def _backfill_atomized_drafts():
    """Convert existing AtomizedContent records without Content links into drafts."""
    try:
        from src.database.db import get_db
        from src.database.models import AtomizedContent, Content, MasterContent
        import json as _j
        db = get_db()
        # Fix stale references (content_id pointing to deleted Content rows)
        for a in db.query(AtomizedContent).filter(AtomizedContent.content_id != None).all():
            if not db.query(Content).filter(Content.id == a.content_id).first():
                a.content_id = None
        db.commit()
        orphans = db.query(AtomizedContent).filter(
            AtomizedContent.content_id == None,
            AtomizedContent.status != 'deleted',
        ).all()
        if not orphans:
            return
        for a in orphans:
            mc = db.query(MasterContent).filter(
                MasterContent.workflow_run_id == a.workflow_run_id
            ).first()
            headline = mc.headline if mc else ''
            title = headline[:100] if headline else (a.body or '')[:100]
            # Parse hashtags/media from JSON strings
            def _pl(v):
                if isinstance(v, list): return v
                if isinstance(v, str):
                    try:
                        p = _j.loads(v)
                        return p if isinstance(p, list) else []
                    except Exception:
                        return []
                return []
            post = Content(
                agent_id=a.agent_id,
                title=title,
                body=a.body or '',
                hashtags=_pl(a.hashtags),
                media_urls=_pl(a.media_urls),
                platform=a.platform,
                status='draft',
            )
            db.add(post)
            db.flush()
            a.content_id = post.id
        db.commit()
        logging.info(f"[Backfill] Created {len(orphans)} Content drafts from orphaned AtomizedContent")
    except Exception as e:
        logging.warning(f"[Backfill] Failed: {e}")

_backfill_atomized_drafts()

@app.before_request
def open_db_session():
    """Open a fresh DB session scoped to this request (thread-safe via flask.g)."""
    from flask import g
    from src.database.db import get_db
    g.db = get_db()  # orchestrator.db property reads from g.db automatically

@app.teardown_appcontext
def shutdown_session(exception=None):
    """Close the per-request DB session stored in flask.g."""
    from flask import g
    db = g.pop('db', None)
    if db:
        try:
            if exception:
                db.rollback()
            db.close()
        except Exception:
            pass


@app.after_request
def no_cache(response):
    """Prevent all browser caching during development (HTML + API responses)."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


@app.route('/', methods=['GET'])
def index():
    """Serve the dashboard HTML"""
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))


@app.route('/agent-detail.html', methods=['GET'])
def agent_detail():
    """Serve the agent detail page"""
    return send_file(os.path.join(os.path.dirname(__file__), 'agent-detail.html'))


@app.route('/newsroom.html', methods=['GET'])
def newsroom():
    """Serve the newsroom page"""
    resp = send_file(os.path.join(os.path.dirname(__file__), 'newsroom.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Marketing AI Agent System is running'}), 200


@app.route('/debug', methods=['GET'])
def debug():
    """Debug endpoint - shows DB path and agents"""
    from src.database.db import DATABASE_URL, DB_PATH
    from src.database.models import Agent
    import os
    agents = orchestrator.db.query(Agent).all()
    return jsonify({
        'db_path': DB_PATH,
        'db_url': DATABASE_URL,
        'db_exists': os.path.exists(DB_PATH),
        'agents_count': len(agents),
        'agents': [{'id': a.id, 'name': a.name, 'active': a.is_active} for a in agents]
    })


# ==================== AGENTS ====================

@app.route('/api/agents', methods=['GET'])
def get_agents():
    """Get all agents"""
    dashboard = orchestrator.get_all_agents_dashboard()
    # Stamp each agent with live generating flag
    if autopilot:
        for a in dashboard.get('agents', []):
            a['generating'] = autopilot.is_generating(a.get('agent_id', -1))
    return jsonify(dashboard), 200


@app.route('/api/agents/<int:agent_id>', methods=['GET'])
def get_agent(agent_id):
    """Get specific agent dashboard"""
    try:
        dashboard = orchestrator.get_agent_dashboard(agent_id)
        return jsonify(dashboard), 200
    except ValueError:
        return jsonify({'error': 'Agent not found'}), 404


@app.route('/api/agents/<int:agent_id>/posts', methods=['GET'])
def get_agent_posts(agent_id):
    """Get all posts for a specific agent"""
    try:
        from src.database.models import Content
        posts = orchestrator.db.query(Content).filter(Content.agent_id == agent_id).order_by(Content.created_at.desc()).all()
        posts_data = [
            {
                'id': p.id,
                'title': p.title,
                'body': p.body,
                'platform': p.platform,
                'status': p.status,
                'hashtags': p.hashtags,
                'mentions': p.mentions,
                'media_urls': p.media_urls or [],
                'post_id': p.post_id,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'scheduled_at': p.scheduled_at.isoformat() if p.scheduled_at else None,
                'published_at': p.published_at.isoformat() if p.published_at else None,
            }
            for p in posts
        ]
        return jsonify({'agent_id': agent_id, 'posts': posts_data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents/<int:agent_id>/accounts', methods=['GET'])
def get_agent_accounts(agent_id):
    """Get all social media accounts connected to an agent"""
    try:
        from src.database.models import SocialMediaAccount
        accounts = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == agent_id
        ).all()

        accounts_data = [
            {
                'id': a.id,
                'platform': a.platform,
                'username': a.username,
                'followers': a.followers,
                'is_verified': a.is_verified,
                'last_sync': a.last_sync.isoformat() if a.last_sync else None,
                'is_connected': a.access_token is not None,
                'created_at': a.created_at.isoformat() if a.created_at else None,
            }
            for a in accounts
        ]
        return jsonify({'agent_id': agent_id, 'accounts': accounts_data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents/<int:agent_id>/accounts', methods=['POST'])
def connect_account(agent_id):
    """Connect a social media account to an agent"""
    data = request.json
    if not data.get('platform') or not data.get('username'):
        return jsonify({'error': 'Missing platform or username'}), 400

    try:
        from src.database.models import SocialMediaAccount
        account = SocialMediaAccount(
            agent_id=agent_id,
            platform=data['platform'],
            username=data['username'],
            account_id=data.get('account_id'),
            access_token=data.get('access_token'),
            refresh_token=data.get('refresh_token')
        )
        orchestrator.db.add(account)
        orchestrator.db.commit()
        return jsonify({
            'account_id': account.id,
            'message': f"Account @{data['username']} connected on {data['platform']}"
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
def update_account(account_id):
    """Update a social media account (e.g. refresh token)"""
    data = request.json
    try:
        from src.database.models import SocialMediaAccount
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.id == account_id
        ).first()
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        if data.get('username'):
            account.username = data['username']
        if data.get('access_token') is not None:
            account.access_token = data['access_token']
        if data.get('refresh_token') is not None:
            account.refresh_token = data['refresh_token']
        if data.get('followers') is not None:
            account.followers = data['followers']
        orchestrator.db.commit()
        return jsonify({'account_id': account_id, 'message': 'Account updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/accounts/<int:account_id>/test', methods=['POST'])
def test_account_connection(account_id):
    """Test if the stored access token is valid by calling the platform API"""
    import urllib.request, json as jsonlib
    try:
        from src.database.models import SocialMediaAccount
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.id == account_id
        ).first()
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        if not account.access_token:
            return jsonify({'valid': False, 'error': 'No access token stored. Edit the account to add one.'}), 200

        result = {'valid': False, 'platform': account.platform, 'username': account.username}

        if account.platform == 'instagram':
            url = f"https://graph.instagram.com/me?fields=id,username,followers_count,media_count&access_token={account.access_token}"
            try:
                with urllib.request.urlopen(url, timeout=8) as resp:
                    data = jsonlib.loads(resp.read())
                if data.get('id'):
                    result['valid'] = True
                    result['ig_id'] = data.get('id')
                    result['ig_username'] = data.get('username')
                    result['followers'] = data.get('followers_count', 0)
                    result['media_count'] = data.get('media_count', 0)
                    # Update followers in DB
                    account.followers = data.get('followers_count', 0)
                    orchestrator.db.commit()
                else:
                    result['error'] = data.get('error', {}).get('message', 'Unknown error')
            except Exception as e:
                result['error'] = str(e)

        elif account.platform == 'twitter':
            import base64
            url = "https://api.twitter.com/2/users/me"
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {account.access_token}')
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = jsonlib.loads(resp.read())
                if data.get('data'):
                    result['valid'] = True
                    result['tw_id'] = data['data'].get('id')
                    result['tw_username'] = data['data'].get('username')
                else:
                    result['error'] = str(data.get('errors', 'Unknown error'))
            except Exception as e:
                result['error'] = str(e)

        elif account.platform == 'tiktok':
            url = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,follower_count"
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {account.access_token}')
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = jsonlib.loads(resp.read())
                if data.get('data', {}).get('user'):
                    result['valid'] = True
                    user = data['data']['user']
                    result['tt_id'] = user.get('open_id')
                    result['display_name'] = user.get('display_name')
                    result['followers'] = user.get('follower_count', 0)
                else:
                    result['error'] = str(data.get('error', {}).get('message', 'Unknown error'))
            except Exception as e:
                result['error'] = str(e)
        else:
            result['error'] = f"Platform '{account.platform}' test not implemented yet"

        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    """Remove a connected social media account"""
    try:
        from src.database.models import SocialMediaAccount
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.id == account_id
        ).first()
        if not account:
            return jsonify({'error': 'Account not found'}), 404
        orchestrator.db.delete(account)
        orchestrator.db.commit()
        return jsonify({'account_id': account_id, 'message': 'Account removed'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/accounts/<int:account_id>/engage', methods=['POST'])
def ai_engage(account_id):
    """
    AI auto-engagement: reply to comments on own posts with AI-generated responses.
    Uses official Instagram Graph API only — safe, within ToS.
    Randomised delays make activity look organic.
    """
    import urllib.request, urllib.parse, json as jsonlib, time, random
    from src.database.models import SocialMediaAccount, Agent
    from src.api.llm_provider import LLMProvider

    try:
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.id == account_id
        ).first()
        if not account or not account.access_token:
            return jsonify({'error': 'Account not found or no token'}), 404

        # Auto-engage (reply to comments) is implemented for Instagram only.
        # Twitter/X comment-reading requires a paid API tier and isn't wired up,
        # so return a clear message instead of failing with a cryptic 400.
        _plat = (account.platform or '').lower()
        if _plat not in ('instagram', 'ig'):
            return jsonify({
                'account_id': account_id,
                'replied': 0,
                'actions': [],
                'message': f'Auto-engage (comment replies) is only available for Instagram right now — not {account.platform}.'
            }), 200

        agent = orchestrator.db.query(Agent).filter(Agent.id == account.agent_id).first()
        token = account.access_token

        def ig_get(url):
            with urllib.request.urlopen(url, timeout=10) as r:
                return jsonlib.loads(r.read())

        def ig_post(url, data):
            import urllib.error
            encoded = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(url, data=encoded, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return jsonlib.loads(r.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                raise RuntimeError(f"IG API {e.code}: {body[:200]}")

        # Get IG user ID
        me = ig_get(f"https://graph.instagram.com/v19.0/me?fields=id,username&access_token={token}")
        ig_id = me['id']

        # Get recent media
        media = ig_get(f"https://graph.instagram.com/v19.0/{ig_id}/media?fields=id,caption,timestamp&limit=10&access_token={token}")
        posts = media.get('data', [])

        llm = LLMProvider()
        persona = agent.persona if agent else 'casual and friendly'
        tone = agent.tone_of_voice if agent else 'conversational'

        replied_count = 0
        results = []

        for post in posts[:5]:  # Max 5 posts per run
            post_id = post['id']
            # Get unanswered comments
            comments = ig_get(
                f"https://graph.instagram.com/v19.0/{post_id}/comments?fields=id,text,username,timestamp&access_token={token}"
            )
            for comment in comments.get('data', [])[:3]:  # Max 3 replies per post
                cid   = comment['id']
                ctext = comment.get('text', '')
                cuser = comment.get('username', 'user')

                # Generate AI reply matching agent persona
                prompt = (
                    f"You are {agent.agent_name if agent else 'a social media manager'} with this persona: {persona}. "
                    f"Tone: {tone}. "
                    f"Reply to this Instagram comment from @{cuser}: \"{ctext}\". "
                    f"Keep it short (1-2 sentences max), natural, no hashtags, no emojis overload. "
                    f"Sound like a real person, not a bot."
                )
                reply_text = llm.generate_text(prompt)
                if not reply_text:
                    continue

                # Human-like random delay (3–12 seconds between actions)
                time.sleep(random.uniform(3, 12))

                # Post reply
                ig_post(
                    f"https://graph.instagram.com/v19.0/{cid}/replies",
                    {'message': reply_text, 'access_token': token}
                )
                replied_count += 1
                results.append({'comment': ctext[:60], 'reply': reply_text[:80]})

        return jsonify({
            'account_id': account_id,
            'replied': replied_count,
            'actions': results,
            'message': f'Engaged with {replied_count} comments'
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ═══════════════════════════════════════════
# A — AUTOPILOT
# ═══════════════════════════════════════════

@app.route('/api/agents/<int:agent_id>/autopilot', methods=['GET'])
def get_autopilot(agent_id):
    from src.database.models import Agent
    agent = orchestrator.db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    return jsonify({
        'enabled':        bool(agent.autopilot_enabled),
        'posts_per_day':  agent.autopilot_posts_per_day or 1,
        'mode':           agent.autopilot_mode or 'draft',
        'platforms':      agent.autopilot_platforms or ['instagram'],
        'last_run':       agent.autopilot_last_run.isoformat() if agent.autopilot_last_run else None,
    }), 200


@app.route('/api/agents/<int:agent_id>/autopilot', methods=['POST'])
def set_autopilot(agent_id):
    from src.database.models import Agent
    data = request.json or {}
    try:
        agent = orchestrator.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404
        if 'enabled'        in data: agent.autopilot_enabled       = bool(data['enabled'])
        if 'posts_per_day'  in data: agent.autopilot_posts_per_day = int(data['posts_per_day'])
        if 'mode'           in data: agent.autopilot_mode          = data['mode']
        if 'platforms'      in data: agent.autopilot_platforms      = data['platforms']
        orchestrator.db.commit()
        # Immediately trigger if enabling
        if data.get('enabled') and autopilot:
            autopilot.trigger_now(agent_id)
        return jsonify({'message': 'Autopilot updated', 'enabled': agent.autopilot_enabled}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents/<int:agent_id>/autopilot/run', methods=['POST'])
def run_autopilot_now(agent_id):
    """Manually trigger one autopilot cycle for this agent right now."""
    if autopilot:
        autopilot.trigger_now(agent_id)
        return jsonify({'message': 'Autopilot triggered — generating posts now.'}), 200
    return jsonify({'error': 'Autopilot engine not running'}), 500


@app.route('/api/agents/<int:agent_id>/post_count', methods=['GET'])
def get_post_count(agent_id):
    """Lightweight endpoint — returns current post count for polling."""
    from src.database.models import Content
    total   = orchestrator.db.query(Content).filter(Content.agent_id == agent_id).count()
    drafts  = orchestrator.db.query(Content).filter(Content.agent_id == agent_id, Content.status == 'draft').count()
    sched   = orchestrator.db.query(Content).filter(Content.agent_id == agent_id, Content.status == 'scheduled').count()
    pub     = orchestrator.db.query(Content).filter(Content.agent_id == agent_id, Content.status == 'published').count()
    generating = autopilot.is_generating(agent_id) if autopilot else False
    return jsonify({'total': total, 'drafts': drafts, 'scheduled': sched, 'published': pub,
                    'generating': generating}), 200


@app.route('/api/autopilot/active', methods=['GET'])
def get_active_autopilot():
    """Returns list of agent IDs currently running autopilot generation."""
    active = list(autopilot._active_agents) if autopilot else []
    return jsonify({'active': active}), 200


# ═══════════════════════════════════════════
# AI AUTO — BROWSER ENGAGEMENT
# ═══════════════════════════════════════════

@app.route('/api/agents/<int:agent_id>/ai_auto', methods=['GET'])
def get_ai_auto(agent_id):
    """Get AI Auto (browser engagement) settings for this agent."""
    from src.database.models import Agent
    agent = orchestrator.db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    import json as _j
    try:
        targets = _j.loads(agent.ai_auto_targets or '[]')
    except Exception:
        targets = []
    proxy_raw = getattr(agent, 'ai_auto_proxy', None) or ''
    return jsonify({
        'enabled':  bool(agent.ai_auto_enabled),
        'status':   agent.ai_auto_status or 'idle',
        'ig_user':  agent.ai_auto_ig_user or '',
        'ig_pass':  '●●●●●●' if agent.ai_auto_ig_pass else '',
        'targets':  targets,
        'proxy':    proxy_raw,   # returned as-is (not masked — format is obvious anyway)
    }), 200


@app.route('/api/agents/<int:agent_id>/ai_auto', methods=['POST'])
def set_ai_auto(agent_id):
    """Save AI Auto settings and start/stop the scheduler for this agent."""
    from src.database.models import Agent
    import json as _j
    data = request.json or {}
    try:
        agent = orchestrator.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404

        if 'enabled' in data:
            agent.ai_auto_enabled = bool(data['enabled'])
        if 'ig_user' in data:
            agent.ai_auto_ig_user = data['ig_user'].strip()
        # Only overwrite password if a real value (not the masked placeholder) is sent
        if 'ig_pass' in data and data['ig_pass'] and '●' not in data['ig_pass']:
            agent.ai_auto_ig_pass = data['ig_pass']
        if 'targets' in data:
            targets = data['targets']
            if isinstance(targets, list):
                agent.ai_auto_targets = _j.dumps(targets)
            elif isinstance(targets, str):
                agent.ai_auto_targets = _j.dumps(
                    [t.strip().lstrip('#') for t in targets.split(',') if t.strip()]
                )
        if 'proxy' in data:
            # Store empty string as None
            raw = (data['proxy'] or '').strip()
            agent.ai_auto_proxy = raw if raw else None

        # Update status badge
        if agent.ai_auto_enabled:
            agent.ai_auto_status = 'activated — waiting for next session'
            if ai_auto_sched:
                ai_auto_sched.schedule_agent(agent_id)
        else:
            agent.ai_auto_status = 'deactivated'
            if ai_auto_sched and agent_id in ai_auto_sched._next_runs:
                ai_auto_sched._next_runs[agent_id] = []

        orchestrator.db.commit()
        return jsonify({
            'message': 'AI Auto settings saved',
            'enabled': agent.ai_auto_enabled,
            'status':  agent.ai_auto_status,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents/<int:agent_id>/ai_auto/run', methods=['POST'])
def run_ai_auto_now(agent_id):
    """Immediately fire one AI Auto engagement session (for testing)."""
    if not ai_auto_sched:
        return jsonify({'error': 'AI Auto scheduler not running'}), 500
    ai_auto_sched.trigger_now(agent_id)
    return jsonify({'message': 'AI Auto session started — check status in a minute.'}), 200


# ═══════════════════════════════════════════
# B — CROSS-PLATFORM PUBLISH
# ═══════════════════════════════════════════

@app.route('/api/content/<int:content_id>/publish_all', methods=['POST'])
def publish_to_all_platforms(content_id):
    """Publish this post to ALL connected accounts for the agent (all platforms)."""
    import json as jsonlib
    from src.database.models import Content, SocialMediaAccount
    from datetime import datetime

    try:
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        accounts = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == post.agent_id,
            SocialMediaAccount.access_token.isnot(None)
        ).all()

        if not accounts:
            return jsonify({'error': 'No connected accounts with tokens found'}), 400

        results = []
        for acc in accounts:
            # Create a temporary copy of the post for the other platform if needed
            if acc.platform != post.platform:
                adapted_body = _adapt_caption_for_platform(
                    _clean_body_for_publish(post.body), acc.platform
                )
                # Create a sibling post in DB for the other platform
                sibling = Content(
                    agent_id   = post.agent_id,
                    account_id = acc.id,
                    title      = adapted_body[:100],
                    body       = adapted_body,
                    hashtags   = _adapt_hashtags_for_platform(post.hashtags or [], acc.platform),
                    media_urls = post.media_urls,
                    platform   = acc.platform,
                    status     = 'draft'
                )
                orchestrator.db.add(sibling)
                orchestrator.db.commit()
                target_id = sibling.id
            else:
                target_id = content_id

            results.append({'platform': acc.platform, 'username': acc.username, 'post_id': target_id})

        return jsonify({
            'message': f'Queued for {len(results)} platform(s)',
            'platforms': results
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


def _adapt_caption_for_platform(text: str, platform: str) -> str:
    """Trim/adapt caption for platform character limits."""
    limits = {'twitter': 260, 'instagram': 2200, 'tiktok': 2200}
    limit = limits.get(platform, 2200)
    if len(text) > limit:
        text = text[:limit - 3] + '…'
    return text


def _adapt_hashtags_for_platform(hashtags: list, platform: str) -> list:
    """Platform-appropriate hashtag counts."""
    counts = {'instagram': 30, 'twitter': 3, 'tiktok': 8}
    limit = counts.get(platform, 10)
    return hashtags[:limit]


# ═══════════════════════════════════════════
# C — SMART HASHTAGS + BEST TIME
# ═══════════════════════════════════════════

@app.route('/api/content/<int:content_id>/hashtags', methods=['POST'])
def generate_smart_hashtags(content_id):
    """AI generates optimal hashtags for this post based on content + platform."""
    from src.database.models import Content, Agent
    from src.api.llm_provider import LLMProvider

    try:
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        agent = orchestrator.db.query(Agent).filter(Agent.id == post.agent_id).first()
        platform = post.platform
        body = _clean_body_for_publish(post.body)

        counts = {'instagram': 30, 'twitter': 3, 'tiktok': 8}
        count  = counts.get(platform, 10)

        prompt = (
            f"Generate exactly {count} hashtags for this {platform} post.\n\n"
            f"Agent persona: {agent.persona if agent else 'social media influencer'}\n"
            f"Fields: {', '.join(agent.fields or []) if agent else 'real estate'}\n"
            f"Post content: {body[:500]}\n\n"
            f"Rules:\n"
            f"- Mix: 30% mega (1M+ posts), 40% mid (100k-1M), 30% niche (<100k)\n"
            f"- No spaces in hashtags, no # symbol in output\n"
            f"- Relevant to real estate, investment, property market\n"
            f"- Return ONLY a comma-separated list of hashtags, nothing else."
        )

        llm = LLMProvider()
        result = llm.generate_text(prompt)
        tags = [t.strip().lstrip('#') for t in result.split(',') if t.strip()][:count]

        # Save to post
        post.hashtags = tags
        orchestrator.db.commit()

        return jsonify({'hashtags': tags, 'count': len(tags)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/test/image', methods=['GET'])
def test_image_generation():
    """Smoke-test: generate one image and return its size."""
    import traceback
    try:
        from src.api.image_generator import GeminiImageGenerator
        gen = GeminiImageGenerator()
        img = gen.generate_image(
            "A beautiful sunny real estate property exterior, ultra realistic photography."
        )
        if img:
            return jsonify({'ok': True, 'model': gen.MODEL,
                            'size_kb': len(img) // 1000}), 200
        return jsonify({'ok': False, 'error': 'No image returned — check server logs'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e),
                        'trace': traceback.format_exc()}), 500


@app.route('/api/platform/best_times', methods=['GET'])
def get_best_times():
    """Return optimal posting times per platform."""
    from src.autopilot.engine import PEAK_HOURS, BEST_DAYS
    days_map = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return jsonify({
        platform: {
            'hours': hours,
            'best_days': [days_map[d] for d in BEST_DAYS.get(platform, list(range(7)))]
        }
        for platform, hours in PEAK_HOURS.items()
    }), 200


@app.route('/api/agents', methods=['POST'])
def create_agent():
    """Create new agent"""
    data = request.json

    required_fields = ['name', 'brand', 'persona', 'tone_of_voice', 'fields']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    agent_id = orchestrator.create_agent(
        name=data['name'],
        brand=data['brand'],
        persona=data['persona'],
        tone_of_voice=data['tone_of_voice'],
        fields=data['fields'],
        bio=data.get('bio', ''),
        avatar_url=data.get('avatar_url', '')
    )

    # Set extra fields not in create_agent signature
    from flask import g
    from src.database.models import Agent
    db = g.db
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent:
        if data.get('image_style'):
            agent.image_style = data['image_style']
        if data.get('llm_provider'):
            agent.llm_provider = data['llm_provider']
        if data.get('llm_model'):
            agent.llm_model = data['llm_model']
        db.commit()

    return jsonify({'agent_id': agent_id, 'message': 'Agent created successfully'}), 201


@app.route('/api/agents/<int:agent_id>', methods=['PUT'])
def update_agent(agent_id):
    """Update an existing agent"""
    data = request.json

    try:
        # Convert fields string to list if needed
        fields = data.get('fields')
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(',') if f.strip()]

        orchestrator.update_agent(
            agent_id=agent_id,
            name=data.get('name'),
            brand=data.get('brand'),
            persona=data.get('persona'),
            tone_of_voice=data.get('tone_of_voice'),
            fields=fields,
            bio=data.get('bio'),
            avatar_url=data.get('avatar_url'),
            image_style=data.get('image_style'),
            llm_provider=data.get('llm_provider'),
            llm_model=data.get('llm_model')
        )

        return jsonify({
            'agent_id': agent_id,
            'message': 'Agent updated successfully'
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents/<int:agent_id>', methods=['DELETE'])
def delete_agent(agent_id):
    """Delete an agent (soft delete - marks as inactive)"""
    try:
        orchestrator.delete_agent(agent_id)
        return jsonify({
            'agent_id': agent_id,
            'message': 'Agent deleted successfully'
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ==================== CONTENT ====================

@app.route('/api/content/generate', methods=['POST'])
def generate_content():
    """Generate content for an agent"""
    data = request.json

    if not data.get('agent_id') or not data.get('platform'):
        return jsonify({'error': 'Missing agent_id or platform'}), 400

    agent_id = data['agent_id']
    platform = data['platform']
    topic = data.get('topic', 'general')

    try:
        post_id = orchestrator.generate_content_for_agent(agent_id, platform, topic)
        return jsonify({
            'post_id': post_id,
            'agent_id': agent_id,
            'platform': platform,
            'message': 'Content generated successfully'
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/content/custom', methods=['POST'])
def create_custom_post():
    """Create a post with user-written text + AI-generated images"""
    data = request.json

    if not data.get('agent_id') or not data.get('platform') or not data.get('text'):
        return jsonify({'error': 'Missing agent_id, platform, or text'}), 400

    agent_id = data['agent_id']
    platform = data['platform']
    custom_text = data['text']
    hashtags = data.get('hashtags', [])
    num_images = data.get('num_images', 3)

    try:
        agent = orchestrator.get_agent(agent_id)
        if not agent:
            return jsonify({'error': 'Agent not found'}), 404

        post_id = agent.create_custom_post(
            platform=platform,
            custom_text=custom_text,
            hashtags=hashtags if isinstance(hashtags, list) else [h.strip() for h in hashtags.split(',') if h.strip()],
            num_images=num_images
        )
        return jsonify({
            'post_id': post_id,
            'agent_id': agent_id,
            'platform': platform,
            'message': 'Custom post created with AI images'
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/content/batch-generate', methods=['POST'])
def batch_generate_content():
    """Batch generate content for multiple agents"""
    data = request.json

    agent_ids = data.get('agent_ids')
    platforms = data.get('platforms', ['instagram', 'twitter', 'tiktok'])
    num_posts = data.get('num_posts_per_agent', 1)

    results = orchestrator.batch_generate_content(
        agent_ids=agent_ids,
        platforms=platforms,
        num_posts_per_agent=num_posts
    )

    return jsonify({
        'results': results,
        'message': f'Batch generation complete'
    }), 201


@app.route('/api/content/<int:content_id>/schedule', methods=['POST'])
def schedule_content(content_id):
    """Schedule content for publishing"""
    data = request.json

    if not data.get('scheduled_time'):
        return jsonify({'error': 'Missing scheduled_time'}), 400

    from datetime import datetime
    scheduled_time = datetime.fromisoformat(data['scheduled_time'])

    try:
        orchestrator.scheduler.schedule_post(content_id, scheduled_time)
        return jsonify({
            'content_id': content_id,
            'scheduled_at': scheduled_time.isoformat(),
            'message': 'Content scheduled successfully'
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/content/<int:content_id>/cancel', methods=['POST'])
def cancel_content(content_id):
    """Cancel a scheduled/published post — returns it to draft"""
    try:
        from src.database.models import Content
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
        post.status = 'draft'
        post.scheduled_at = None
        post.published_at = None
        orchestrator.db.commit()
        # Also cancel in scheduler if scheduled
        try:
            orchestrator.scheduler.cancel_scheduled_post(content_id)
        except Exception:
            pass
        return jsonify({'content_id': content_id, 'message': 'Post returned to draft'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/content/<int:content_id>/publish', methods=['POST'])
def publish_content_now(content_id):
    """Publish a post immediately — calls the real platform API if token is available"""
    import urllib.request, urllib.parse, json as jsonlib, base64, os, uuid
    from datetime import datetime
    from src.database.models import Content, SocialMediaAccount

    try:
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404

        # Find a connected account for this agent + platform (normalize platform names)
        post_plat = (post.platform or '').lower().replace('/', '').replace(' ', '')
        _plat_aliases = {'twitterx': 'twitter', 'x': 'twitter', 'ig': 'instagram', 'insta': 'instagram'}
        normalized_plat = _plat_aliases.get(post_plat, post_plat)
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == post.agent_id,
            SocialMediaAccount.platform == normalized_plat
        ).first()

        # --- Helper: save base64 images to disk and return public URLs ---
        def _upload_uguu(filepath: str) -> str:
            """Upload to uguu.se — IG-fetchable, primary CDN."""
            boundary = uuid.uuid4().hex
            with open(filepath, 'rb') as f:
                file_data = f.read()
            filename = os.path.basename(filepath)
            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="files[]"; filename="{filename}"\r\n'
                f'Content-Type: image/jpeg\r\n\r\n'
            ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()
            req = urllib.request.Request('https://uguu.se/upload.php', data=body)
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = jsonlib.loads(r.read().decode().strip())
            if not resp.get('success') or not resp.get('files'):
                raise RuntimeError(f"uguu upload failed: {resp}")
            return resp['files'][0]['url']

        def _upload_litterbox(filepath: str) -> str:
            """Fallback: litterbox.catbox.moe — Meta has been blocking this intermittently."""
            boundary = uuid.uuid4().hex
            with open(filepath, 'rb') as f:
                file_data = f.read()
            filename = os.path.basename(filepath)
            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="reqtype"\r\n\r\nfileupload\r\n'
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="time"\r\n\r\n72h\r\n'
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="fileToUpload"; filename="{filename}"\r\n'
                f'Content-Type: image/jpeg\r\n\r\n'
            ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()
            req = urllib.request.Request(
                'https://litterbox.catbox.moe/resources/internals/api.php',
                data=body,
            )
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode().strip()

        def upload_to_catbox(filepath):
            """Public-CDN upload for IG fetch. Tries uguu.se first (IG-fetchable);
            falls back to litterbox if uguu is down."""
            import logging as _lg
            try:
                url = _upload_uguu(filepath)
                _lg.warning(f"[PUBLISH] uguu OK: {url}")
                return url
            except Exception as e:
                _lg.warning(f"[PUBLISH] uguu failed ({e}); falling back to litterbox")
                url = _upload_litterbox(filepath)
            if not url.startswith('https://'):
                raise RuntimeError(f"litterbox upload failed: {url}")
            return url

        def save_images_to_disk(media_urls):
            saved = []
            media_dir = os.path.join(os.path.dirname(__file__), 'static', 'media')
            os.makedirs(media_dir, exist_ok=True)
            import logging
            for item in media_urls:
                if not item:
                    continue
                # Case A: already-saved local file path (/static/media/xxx.jpg)
                if item.startswith('/static/') or item.startswith('/media/'):
                    rel = item.lstrip('/')
                    fpath = os.path.join(os.path.dirname(__file__), rel)
                    if not os.path.exists(fpath):
                        logging.warning(f"[PUBLISH] Missing local media file: {fpath}")
                        continue
                    public_url = upload_to_catbox(fpath)
                    logging.warning(f"[PUBLISH] Uploaded local file to CDN: {public_url}")
                    saved.append(public_url)
                    continue
                # Case B: already a public URL
                if item.startswith('http://') or item.startswith('https://'):
                    saved.append(item)
                    continue
                # Case C: data URI or raw base64 — always re-encode to JPEG (IG-safe, dodges error 9004)
                if item.startswith('data:'):
                    _, data = item.split(',', 1)
                else:
                    data = item
                try:
                    raw_bytes = base64.b64decode(data)
                    from PIL import Image as _PILImage
                    import io as _io
                    img = _PILImage.open(_io.BytesIO(raw_bytes))
                    # Flatten alpha onto white so PNG-with-transparency doesn't crash JPEG encode
                    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                        bg = _PILImage.new('RGB', img.size, (255, 255, 255))
                        bg.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[-1])
                        img = bg
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    fname = f"{uuid.uuid4().hex}.jpg"
                    fpath = os.path.join(media_dir, fname)
                    img.save(fpath, format='JPEG', quality=92)
                except Exception as _e:
                    logging.warning(f"[PUBLISH] PIL re-encode failed ({_e}); falling back to raw write")
                    fname = f"{uuid.uuid4().hex}.jpg"
                    fpath = os.path.join(media_dir, fname)
                    with open(fpath, 'wb') as f:
                        f.write(base64.b64decode(data))
                public_url = upload_to_catbox(fpath)
                logging.warning(f"[PUBLISH] Uploaded image to CDN: {public_url}")
                saved.append(public_url)
            return saved

        # --- Instagram publishing ---
        def ig_api_call(url, data=None, _retries=2):
            """Make an Instagram Graph API call, raising with the full error body on failure.
            Retries on read timeouts / transient connection errors."""
            import urllib.error, socket, logging as _lg, time as _time
            last_err = None
            for attempt in range(_retries + 1):
                try:
                    if data:
                        req = urllib.request.Request(url, data=data, method='POST')
                    else:
                        req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=60) as r:
                        return jsonlib.loads(r.read())
                except urllib.error.HTTPError as e:
                    # HTTP error — handled below (no retry, IG returned a real response)
                    body = e.read().decode('utf-8', errors='replace')
                    _lg.warning(f"[IG-ERR] HTTP {e.code} on {url.split('?')[0]} :: body={body[:1000]}")
                    try:
                        err_json = jsonlib.loads(body)
                        err = err_json.get('error', {}) if isinstance(err_json, dict) else {}
                        msg = err.get('message') or body
                        code = err.get('code', e.code)
                        sub = err.get('error_subcode')
                        user_msg = err.get('error_user_msg')
                        trace = err.get('fbtrace_id')
                        extras = []
                        if sub: extras.append(f"subcode={sub}")
                        if user_msg: extras.append(f"user_msg={user_msg}")
                        if trace: extras.append(f"trace={trace}")
                        extra_str = (" [" + ", ".join(extras) + "]") if extras else ""
                        raise RuntimeError(f"Instagram API error {code}: {msg}{extra_str}")
                    except (jsonlib.JSONDecodeError, KeyError):
                        raise RuntimeError(f"Instagram API HTTP {e.code}: {body[:300]}")
                except (socket.timeout, urllib.error.URLError, ConnectionError) as e:
                    last_err = e
                    _lg.warning(f"[IG-ERR] transient on {url.split('?')[0]} attempt {attempt+1}/{_retries+1}: {type(e).__name__}: {e}")
                    if attempt < _retries:
                        _time.sleep(2 * (attempt + 1))
                        continue
                    raise RuntimeError(f"Instagram API network error after {_retries+1} attempts: {type(e).__name__}: {e}")
            # Unreachable
            raise RuntimeError(f"Instagram API failed: {last_err}")


        def publish_instagram(post, token):
            # Get IG Business Account ID
            url = f"https://graph.instagram.com/v19.0/me?fields=id,username&access_token={token}"
            me = ig_api_call(url)
            ig_id = me['id']

            images = post.media_urls or []
            caption = _clean_body_for_publish(post.body)
            tags = ' '.join(f'#{h}' for h in (post.hashtags or []))
            full_caption = f"{caption}\n\n{tags}".strip()

            if not images:
                return False, "No images to publish. Instagram requires at least one image."

            image_urls = save_images_to_disk(images)
            # Log image URLs for debugging
            import logging
            logging.warning(f"[PUBLISH] Image URLs being sent to Instagram: {image_urls}")

            base = f"https://graph.instagram.com/v19.0/{ig_id}"

            if len(image_urls) == 1:
                # Single image post
                container = ig_api_call(f"{base}/media", urllib.parse.urlencode({
                    'image_url': image_urls[0],
                    'caption': full_caption,
                    'access_token': token
                }).encode())
                container_id = container['id']
            else:
                # Carousel — create child containers first
                children = []
                for img_url in image_urls:
                    child = ig_api_call(f"{base}/media", urllib.parse.urlencode({
                        'image_url': img_url,
                        'is_carousel_item': 'true',
                        'access_token': token
                    }).encode())
                    children.append(child['id'])
                # Create carousel container
                container = ig_api_call(f"{base}/media", urllib.parse.urlencode({
                    'media_type': 'CAROUSEL',
                    'children': ','.join(children),
                    'caption': full_caption,
                    'access_token': token
                }).encode())
                container_id = container['id']

            # Poll until container is FINISHED before publishing (Instagram requires this)
            import time
            for attempt in range(15):
                status_data = ig_api_call(
                    f"https://graph.instagram.com/v19.0/{container_id}?fields=status_code&access_token={token}"
                )
                status = status_data.get('status_code', 'IN_PROGRESS')
                import logging
                logging.warning(f"[PUBLISH] Container {container_id} status: {status} (attempt {attempt+1})")
                if status == 'FINISHED':
                    break
                elif status == 'ERROR':
                    raise RuntimeError(f"Instagram media container processing failed (status: ERROR)")
                elif status == 'EXPIRED':
                    raise RuntimeError(f"Instagram media container expired before publishing")
                time.sleep(4)
            else:
                raise RuntimeError("Instagram media container took too long to process (>60s). Try again.")

            # Publish the container
            result = ig_api_call(f"{base}/media_publish", urllib.parse.urlencode({
                'creation_id': container_id,
                'access_token': token
            }).encode())
            media_id = result.get('id', 'published')
            # Resolve permalink shortcode so the "View Post" link works
            # (/p/<id>/ URLs require the shortcode, not the numeric media id).
            try:
                import re as _re
                meta = ig_api_call(
                    f"https://graph.instagram.com/v19.0/{media_id}?fields=permalink&access_token={token}"
                )
                permalink = meta.get('permalink') or ''
                # permalink shape: https://www.instagram.com/p/<shortcode>/
                m = _re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', permalink)
                if m:
                    return True, m.group(1)
            except Exception as e:
                import logging
                logging.warning(f"[PUBLISH] permalink lookup failed: {e}")
            return True, media_id

        # --- Execute platform publish ---
        platform_result = None
        platform_error = None

        def _refresh_twitter_token(acct):
            """Refresh an expired Twitter OAuth2 access token."""
            import requests as _req
            try:
                resp = _req.post(
                    'https://api.twitter.com/2/oauth2/token',
                    data={
                        'grant_type': 'refresh_token',
                        'refresh_token': acct.refresh_token,
                        'client_id': _TWITTER_CLIENT_ID,
                    },
                    auth=(_TWITTER_CLIENT_ID, _TWITTER_CLIENT_SECRET),
                    timeout=15,
                )
                if resp.status_code == 200:
                    tokens = resp.json()
                    acct.access_token = tokens.get('access_token', acct.access_token)
                    if tokens.get('refresh_token'):
                        acct.refresh_token = tokens['refresh_token']
                    orchestrator.db.commit()
                    import logging
                    logging.info(f"[Twitter] Refreshed token for @{acct.username}")
                    return acct.access_token
                else:
                    import logging
                    logging.error(f"[Twitter] Token refresh failed: {resp.status_code} {resp.text[:200]}")
                    return None
            except Exception as e:
                import logging
                logging.error(f"[Twitter] Token refresh error: {e}")
                return None

        def publish_twitter(post, token, acct):
            """Publish a tweet using Twitter API v2 with OAuth 1.0a signing."""
            import logging
            import urllib.error
            import hmac, hashlib, time as _time, uuid as _uuid
            from urllib.parse import quote as _pct, urlencode as _urlencode

            tweet_text = _clean_body_for_publish(post.body, platform='twitter')
            if not tweet_text or not tweet_text.strip():
                raise RuntimeError(f"Tweet text is empty after cleaning. Raw body: {repr(post.body[:200])}")

            # Twitter counts emojis/special chars as 2; use a weighted count
            def _tw_len(s):
                count = 0
                for ch in s:
                    count += 2 if ord(ch) > 0xFFFF else 1
                return count

            if _tw_len(tweet_text) > 260:
                # Ask the owning agent's LLM to rewrite to fit — never append "…"
                # which would publish a mid-sentence truncation.
                try:
                    from src.database.models import Agent as _Agent
                    _ag = orchestrator.db.query(_Agent).filter(_Agent.id == post.agent_id).first()
                except Exception:
                    _ag = None
                rewritten = _rewrite_tweet_to_fit(tweet_text, _ag, limit=260) if _ag else tweet_text
                if _tw_len(rewritten) <= 260 and not rewritten.rstrip().endswith(('…', '...')):
                    tweet_text = rewritten
                else:
                    # Hard fallback: cut at last sentence/word boundary, no ellipsis
                    while _tw_len(tweet_text) > 260:
                        tweet_text = tweet_text[:-1]
                    for end in ['. ', '.\n', '! ', '?\n', '? ', '.', '!', '?']:
                        idx = tweet_text.rfind(end)
                        if idx > 80:
                            tweet_text = tweet_text[:idx + len(end)].rstrip()
                            break
                    else:
                        sp = tweet_text.rfind(' ')
                        if sp > 80:
                            tweet_text = tweet_text[:sp].rstrip()

            logging.warning(f"[Twitter] Sending tweet text ({len(tweet_text)} chars): {repr(tweet_text[:100])}")

            # --- Resolve a first image (if any) to attach to the tweet ---
            def _resolve_image_bytes(media_urls):
                """Return raw image bytes for the first media item, or None.
                Handles base64, data: URIs, /static local paths, and http(s) URLs."""
                items = media_urls or []
                if isinstance(items, str):
                    try:
                        items = jsonlib.loads(items)
                    except Exception:
                        items = [items]
                if not items:
                    return None
                item = items[0]
                if not item or not isinstance(item, str):
                    return None
                try:
                    if item.startswith('data:'):
                        return base64.b64decode(item.split(',', 1)[1])
                    if item.startswith(('http://', 'https://')):
                        with urllib.request.urlopen(item, timeout=15) as r:
                            return r.read()
                    if item.startswith('/static') or item.startswith('static'):
                        rel = item.lstrip('/')
                        fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
                        if os.path.isfile(fpath):
                            with open(fpath, 'rb') as f:
                                return f.read()
                        return None
                    # Otherwise assume raw base64
                    return base64.b64decode(item)
                except Exception as _ie:
                    logging.warning(f"[Twitter] could not resolve image bytes: {_ie}")
                    return None

            def _twitter_upload_media_bearer(img_bytes, tk):
                """Upload an image via v1.1 media/upload using OAuth2 bearer
                (needs media.write scope). Returns media_id_string or None."""
                if not img_bytes:
                    return None
                try:
                    b64 = base64.b64encode(img_bytes).decode()
                    body = _urlencode({'media_data': b64, 'media_category': 'tweet_image'}).encode()
                    req = urllib.request.Request(
                        'https://upload.twitter.com/1.1/media/upload.json',
                        data=body, method='POST'
                    )
                    req.add_header('Authorization', f'Bearer {tk}')
                    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
                    with urllib.request.urlopen(req, timeout=30) as r:
                        res = jsonlib.loads(r.read())
                        mid = str(res.get('media_id_string') or res.get('media_id') or '')
                        if mid:
                            logging.info(f"[Twitter] media uploaded (id={mid})")
                        return mid or None
                except urllib.error.HTTPError as e:
                    body = e.read().decode('utf-8', errors='replace')
                    logging.warning(f"[Twitter] media upload failed {e.code}: {body[:200]} "
                                    f"(tweet will post text-only). If 403/scope: reconnect the account to grant media.write.")
                    return None
                except Exception as _ue:
                    logging.warning(f"[Twitter] media upload error: {_ue} (posting text-only)")
                    return None

            _img_bytes = _resolve_image_bytes(getattr(post, 'media_urls', None))

            # --- OAuth 1.0a signing (uses Consumer Key + Access Token from env) ---
            _api_key    = os.environ.get('TWITTER_API_KEY', '')
            _api_secret = os.environ.get('TWITTER_API_SECRET', '')
            _acc_token  = os.environ.get('TWITTER_ACCESS_TOKEN', '')
            _acc_secret = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET', '')

            def _oauth1_do_tweet(text):
                """Post tweet using OAuth 1.0a signed request to API v2."""
                url = 'https://api.twitter.com/2/tweets'
                method = 'POST'

                # OAuth params
                oauth_params = {
                    'oauth_consumer_key':     _api_key,
                    'oauth_nonce':            _uuid.uuid4().hex,
                    'oauth_signature_method': 'HMAC-SHA1',
                    'oauth_timestamp':        str(int(_time.time())),
                    'oauth_token':            _acc_token,
                    'oauth_version':          '1.0',
                }

                # Signature base string (only oauth params for POST with JSON body)
                param_str = '&'.join(
                    f"{_pct(k, safe='')}={_pct(v, safe='')}"
                    for k, v in sorted(oauth_params.items())
                )
                base_str = f"{method}&{_pct(url, safe='')}&{_pct(param_str, safe='')}"
                signing_key = f"{_pct(_api_secret, safe='')}&{_pct(_acc_secret, safe='')}"
                signature = base64.b64encode(
                    hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
                ).decode()

                oauth_params['oauth_signature'] = signature
                auth_header = 'OAuth ' + ', '.join(
                    f'{_pct(k, safe="")}="{_pct(v, safe="")}"'
                    for k, v in sorted(oauth_params.items())
                )

                payload = jsonlib.dumps({'text': text}).encode()
                req = urllib.request.Request(url, data=payload, method='POST')
                req.add_header('Authorization', auth_header)
                req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req, timeout=15) as r:
                    result = jsonlib.loads(r.read())
                    return result.get('data', {}).get('id', '')

            # --- OAuth 2.0 Bearer fallback ---
            def _bearer_do_tweet(tk, text):
                body_obj = {'text': text}
                # Attach image if we have one and can upload it (media.write scope)
                if _img_bytes:
                    mid = _twitter_upload_media_bearer(_img_bytes, tk)
                    if mid:
                        body_obj['media'] = {'media_ids': [mid]}
                payload = jsonlib.dumps(body_obj).encode()
                req = urllib.request.Request(
                    'https://api.twitter.com/2/tweets',
                    data=payload,
                    method='POST'
                )
                req.add_header('Authorization', f'Bearer {tk}')
                req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req, timeout=30) as r:
                    result = jsonlib.loads(r.read())
                    return result.get('data', {}).get('id', '')

            _has_oauth1 = all([_api_key, _api_secret, _acc_token, _acc_secret])

            # Try OAuth 2.0 Bearer first, fall back to OAuth 1.0a on 403
            try:
                tweet_id = _bearer_do_tweet(token, tweet_text)
                logging.info("[Twitter] Posted via OAuth 2.0 Bearer")
                return True, tweet_id
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', errors='replace')
                logging.error(f"[Twitter] Bearer error {e.code}: {body[:300]}")

                # 401 = expired token → try refresh
                if e.code == 401 and acct.refresh_token:
                    logging.info("[Twitter] Token expired (401), refreshing...")
                    new_token = _refresh_twitter_token(acct)
                    if new_token:
                        try:
                            tweet_id = _bearer_do_tweet(new_token, tweet_text)
                            logging.info("[Twitter] Posted via OAuth 2.0 Bearer (refreshed)")
                            return True, tweet_id
                        except urllib.error.HTTPError:
                            pass  # fall through to OAuth 1.0a

                # 403 = permission issue → fall back to OAuth 1.0a
                if _has_oauth1 and e.code in (401, 403):
                    logging.info("[Twitter] Falling back to OAuth 1.0a...")
                    try:
                        tweet_id = _oauth1_do_tweet(tweet_text)
                        logging.info("[Twitter] Posted via OAuth 1.0a")
                        return True, tweet_id
                    except urllib.error.HTTPError as e2:
                        body2 = e2.read().decode('utf-8', errors='replace')
                        logging.error(f"[Twitter] OAuth1.0a also failed {e2.code}: {body2[:300]}")
                        raise RuntimeError(f"Twitter API error {e2.code}: {body2[:300]}")

                raise RuntimeError(f"Twitter API error {e.code}: {body[:300]}")

        if account and account.access_token:
            try:
                if normalized_plat == 'instagram':
                    ok, platform_result = publish_instagram(post, account.access_token)
                    if not ok:
                        platform_error = platform_result
                        platform_result = None
                elif normalized_plat == 'twitter':
                    ok, platform_result = publish_twitter(post, account.access_token, account)
                    if not ok:
                        platform_error = platform_result
                        platform_result = None
                else:
                    platform_error = f"Direct publishing for {post.platform} not yet implemented. Post marked as published locally."
            except Exception as pe:
                platform_error = str(pe)
        else:
            platform_error = "No connected account with API token found for this platform. Post marked as published locally."

        if platform_result:
            # Actually published — mark as published and store platform post ID
            post.status = 'published'
            post.published_at = datetime.utcnow()
            post.post_id = str(platform_result)
            orchestrator.db.commit()
            return jsonify({
                'content_id': content_id,
                'message': f'Post published to {post.platform}!',
                'platform_post_id': str(platform_result)
            }), 200
        else:
            # Failed — keep as draft so user can retry
            orchestrator.db.commit()
            return jsonify({
                'content_id': content_id,
                'warning': platform_error or 'Unknown error — post kept as draft.',
                'debug_hint': 'Check server console for image URLs. Test the URL directly in your browser to verify ngrok is serving the image correctly.'
            }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 400


def _clean_body_for_publish(raw, platform=''):
    """Extract clean text from potentially JSON-encoded body.
    For Twitter/X: extracts only the first tweet from thread-formatted content."""
    import json as j
    import re
    if not raw:
        return ''
    text = raw.strip()
    # Handle JSON array: ["tweet 1", "tweet 2", ...] → take first element
    if text.startswith('['):
        try:
            parsed = j.loads(text)
            if isinstance(parsed, list):
                parts = [str(p).strip() for p in parsed if p]
                text = parts[0] if parts else raw
        except Exception:
            # JSON parse failed — strip array/string delimiters manually
            cleaned = text.lstrip('[').rstrip(']').strip()
            # Split on ", " between array elements and take the first
            if '", "' in cleaned:
                cleaned = cleaned.split('", "')[0]
            cleaned = cleaned.strip('"').strip("'").strip()
            if cleaned:
                text = cleaned
    elif text.startswith('{'):
        try:
            parsed = j.loads(text.replace("\\'", "'"))
            text = parsed.get('caption') or parsed.get('body') or raw
        except Exception:
            m = re.search(r'"caption"\s*:\s*"([\s\S]+?)"\s*,\s*"hashtags', text)
            if m:
                text = m.group(1)
    # Strip markdown code fences if present
    text = re.sub(r'^```[a-z]*\n?', '', text, flags=re.MULTILINE).strip('`').strip()
    text = text.replace('\\n', '\n').replace('\\t', '\t')

    # ── Twitter/X: extract only the first tweet from thread-formatted content ──
    if platform and platform.lower() in ('twitter', 'x', 'twitter/x'):
        # Pattern: "1/ ..." "2/ ..." — split on numbered tweet markers
        thread_split = re.split(r'\n+\s*\d+[/\.]\s+', text)
        if len(thread_split) > 1:
            # First chunk may start with "1/ " prefix — strip it
            first = re.sub(r'^\d+[/\.]\s+', '', thread_split[0] if thread_split[0].strip() else thread_split[1])
            text = first.strip()

    return text


def _sanitize_twitter_body(text):
    """Enforce 260-char limit and clean up Twitter content.
    Call this BEFORE saving any Content record with a Twitter platform."""
    import re, json as j
    if not text:
        return text
    # Reject internal operational notes that aren't real tweets
    _skip = ['capacity note', 'note to victoria', "i'm executing", "i'm running this",
             'briefing james', 'briefing elena', "problem: i don't have",
             'these are ready to go. a few notes', 'prepared by:', 'executive summary',
             'production note', "marcus webb's intel", 'intel brief has not', 'tweet copy doc',
             'validation summary', 'ready for scheduling', 'ready for scheduling.',
             'for: nadia flux', 'production manager:', 'flag me — i', 'flag me - i',
             "when webb's brief lands", 'revision pass before publish']
    if any(s in text[:200].lower() for s in _skip):
        return ''
    # Strip JSON array wrappers
    if text.strip().startswith('['):
        try:
            parsed = j.loads(text)
            if isinstance(parsed, list) and parsed:
                text = str(parsed[0]).strip()
        except Exception:
            m = re.match(r'\[\s*"(.*?)(?:"|$)', text.strip(), re.DOTALL)
            if m:
                text = m.group(1).strip()
    # Strip markdown formatting that shouldn't appear in tweets
    text = re.sub(r'^```[a-z]*\n?', '', text, flags=re.MULTILINE)  # code fences
    text = text.replace('```', '')
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)      # **bold** -> bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)           # *italic* -> italic
    text = re.sub(r'__(.+?)__', r'\1', text)           # __underline__
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)  # # headers
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)   # > blockquotes
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE) # bullet points
    # Strip LLM thinking/meta lines (labels like "FOMO Mechanic:", "Hook:", "CTA:")
    text = re.sub(r'^(?:FOMO\s+\w+|Hook|CTA|Mechanic|Format|Angle|Tone|Voice|Strategy)\s*:.*\n?',
                  '', text, flags=re.MULTILINE | re.IGNORECASE).strip()
    # Strip thread markers: "1/ ...", "THREAD:", "Tweet 1:"
    text = re.sub(r'^\d+[/\.]\s+', '', text).strip()
    text = re.sub(r'^(?:THREAD|Tweet\s*\d+|TWEET\s*\d+)\s*:\s*', '', text).strip()
    # Split multi-tweet thread, take first only
    parts = re.split(r'\n+\s*\d+[/\.]\s+', text)
    if len(parts) > 1:
        text = parts[0].strip() or parts[1].strip()
    # Collapse excessive whitespace/newlines
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    # Enforce 260-char limit (emojis count as 2)
    tw = lambda s: sum(2 if ord(c) > 0xFFFF else 1 for c in s)
    if tw(text) > 260:
        # Prefer cutting at line breaks
        lines = text.split('\n')
        trimmed = ''
        for line in lines:
            candidate = (trimmed + '\n' + line).strip() if trimmed else line.strip()
            if tw(candidate) <= 260:
                trimmed = candidate
            else:
                break
        if trimmed and tw(trimmed) >= 60:
            text = trimmed
        else:
            # Hard shrink to <=260, then back off to the last sentence/word boundary.
            # Never append "..." — a truncated mid-word tweet is worse than a shorter complete one.
            while tw(text) > 260:
                text = text[:-1]
            for end in ['. ', '.\n', '! ', '?\n', '? ', '.', '!', '?']:
                idx = text.rfind(end)
                if idx > 80:
                    text = text[:idx + len(end)].rstrip()
                    break
            else:
                # Last resort: cut at last whitespace so we don't split a word.
                sp = text.rfind(' ')
                if sp > 80:
                    text = text[:sp].rstrip()
    return text


def _rewrite_tweet_to_fit(text, agent, limit=270):
    """Use the agent's own LLM to rewrite an over-long tweet into a ≤limit, complete
    sentence in persona voice. Returns the rewrite, or the original if rewrite fails.
    Never appends '…' — an incomplete tweet is unacceptable.
    """
    tw = lambda s: sum(2 if ord(c) > 0xFFFF else 1 for c in s)
    if not text or tw(text) <= limit:
        return text
    try:
        from src.api.llm_provider import LLMProvider
        llm = LLMProvider(
            provider=getattr(agent, 'llm_provider', None) or 'claude',
            model=getattr(agent, 'llm_model', None) or 'claude-sonnet-4-6',
        )
        sys_prompt = (
            f"You are {getattr(agent, 'name', 'the author')} "
            f"({getattr(agent, 'brand', '')}). "
            f"Persona: {getattr(agent, 'persona', '')}. "
            f"Tone: {getattr(agent, 'tone_of_voice', '')}.\n\n"
            f"Rewrite the tweet below so it fits in ≤{limit} characters, is a "
            f"COMPLETE sentence, and ends with a period/!/? — never with '…'. "
            f"Preserve the core point and persona voice. Output ONLY the tweet."
        )
        for _ in range(2):
            out = (llm.generate_content(
                f"---\n{text}\n---", max_tokens=300, temperature=0.5,
                system_prompt=sys_prompt,
            ) or '').strip()
            if out.startswith('"') and out.endswith('"'):
                out = out[1:-1].strip()
            if out and tw(out) <= limit and not out.rstrip().endswith(('…', '...')):
                return out
    except Exception as e:
        logging.warning(f"[TWEET-FIT] LLM rewrite failed ({e}); falling back to sanitizer")
    return _sanitize_twitter_body(text)


@app.route('/api/content/<int:content_id>/edit', methods=['PUT'])
def edit_content(content_id):
    """Edit a post's body and hashtags"""
    data = request.json
    try:
        from src.database.models import Content
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
        if data.get('body') is not None:
            post.body = data['body']
            post.title = data['body'][:100]
        if data.get('hashtags') is not None:
            post.hashtags = data['hashtags']
        orchestrator.db.commit()
        return jsonify({'content_id': content_id, 'message': 'Post updated'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/content/<int:content_id>/delete', methods=['DELETE'])
def delete_content(content_id):
    """Delete a post and clear any AtomizedContent references."""
    try:
        from src.database.models import Content, AtomizedContent
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
        # Clear FK references so backfill doesn't re-create this post
        orchestrator.db.query(AtomizedContent).filter(
            AtomizedContent.content_id == content_id
        ).update({'content_id': None, 'status': 'deleted'})
        orchestrator.db.delete(post)
        orchestrator.db.commit()
        return jsonify({'content_id': content_id, 'message': 'Post deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ==================== ENGAGEMENT ====================

@app.route('/api/engagement/plan', methods=['POST'])
def plan_engagement():
    """Plan engagement activities"""
    data = request.json

    if not data.get('agent_id') or not data.get('platform'):
        return jsonify({'error': 'Missing agent_id or platform'}), 400

    agent_id = data['agent_id']
    platform = data['platform']
    target = data.get('target', 'brand_awareness')

    try:
        activities = orchestrator.plan_engagement_for_agent(agent_id, platform, target)
        return jsonify({
            'agent_id': agent_id,
            'platform': platform,
            'activities': activities
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


# ==================== ANALYTICS ====================

@app.route('/api/analytics/agent/<int:agent_id>', methods=['GET'])
def get_agent_analytics(agent_id):
    """Get agent analytics"""
    try:
        report = orchestrator.analytics_engine.generate_performance_report(agent_id)
        return jsonify(report), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/analytics/performance/<int:agent_id>', methods=['GET'])
def get_performance_report(agent_id):
    """Get agent performance report"""
    days = request.args.get('days', 7, type=int)

    try:
        report = orchestrator.get_agent_performance_report(agent_id, days)
        return jsonify(report), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


# ==================== CONFIGURATION ====================

@app.route('/api/config/llm', methods=['GET'])
def get_llm_config():
    """Get LLM configuration"""
    providers = LLMProvider.list_providers()
    return jsonify({'providers': providers}), 200


@app.route('/api/config/llm', methods=['POST'])
def set_llm_config():
    """Set LLM API key"""
    data = request.json

    if not data.get('provider') or not data.get('api_key'):
        return jsonify({'error': 'Missing provider or api_key'}), 400

    try:
        LLMProvider.set_api_key(
            provider=data['provider'],
            api_key=data['api_key'],
            model_name=data.get('model_name')
        )
        return jsonify({'message': 'API configuration saved'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ==================== SCHEDULER ====================

@app.route('/api/scheduler/execute', methods=['POST'])
def execute_scheduled_posts():
    """Execute all due scheduled posts"""
    results = orchestrator.execute_scheduled_posts()
    return jsonify(results), 200


@app.route('/api/scheduler/posts', methods=['GET'])
def get_scheduled_posts():
    """Get all scheduled posts"""
    agent_id = request.args.get('agent_id', type=int)
    posts = orchestrator.scheduler.get_scheduled_posts(agent_id)
    return jsonify({'scheduled_posts': posts}), 200


# ═══════════════════════════════════════════════════════
# CONTENT HUB & ANALYTICS OVERVIEW
# ═══════════════════════════════════════════════════════

@app.route('/api/content/all', methods=['GET'])
def get_all_content():
    """Get all content across all agents with filters."""
    from src.database.models import Content, Agent
    status_filter = request.args.get('status')  # draft, scheduled, published, failed
    platform_filter = request.args.get('platform')
    limit = request.args.get('limit', 100, type=int)

    q = orchestrator.db.query(Content).order_by(Content.created_at.desc())
    if status_filter:
        q = q.filter(Content.status == status_filter)
    if platform_filter:
        q = q.filter(Content.platform == platform_filter)
    posts = q.limit(limit).all()

    # Gather agent names
    agent_ids = list(set(p.agent_id for p in posts))
    agents = {a.id: a for a in orchestrator.db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}

    # Summary counts
    total = orchestrator.db.query(Content).count()
    drafts = orchestrator.db.query(Content).filter(Content.status == 'draft').count()
    scheduled = orchestrator.db.query(Content).filter(Content.status == 'scheduled').count()
    published = orchestrator.db.query(Content).filter(Content.status == 'published').count()
    failed = orchestrator.db.query(Content).filter(Content.status == 'failed').count()

    return jsonify({
        'summary': {
            'total': total,
            'draft': drafts,
            'scheduled': scheduled,
            'published': published,
            'failed': failed,
        },
        'posts': [{
            'id': p.id,
            'agent_id': p.agent_id,
            'agent_name': agents.get(p.agent_id, None) and agents[p.agent_id].name,
            'title': p.title,
            'body': p.body[:200] if p.body else '',
            'platform': p.platform,
            'status': p.status,
            'hashtags': p.hashtags or [],
            'media_urls': p.media_urls or [],
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'scheduled_at': p.scheduled_at.isoformat() if p.scheduled_at else None,
            'published_at': p.published_at.isoformat() if p.published_at else None,
        } for p in posts]
    }), 200


@app.route('/api/analytics/overview', methods=['GET'])
def get_analytics_overview():
    """Get aggregated analytics across all agents."""
    from src.database.models import Analytics, Content, Agent
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    # Get latest analytics per agent
    all_analytics = orchestrator.db.query(Analytics).order_by(Analytics.date.desc()).all()

    # Aggregate totals
    total_followers = 0
    total_impressions = 0
    total_engagement = 0.0
    agent_count = 0
    by_platform = {}

    seen_agents = set()
    for a in all_analytics:
        key = (a.agent_id, a.platform)
        if key in seen_agents:
            continue
        seen_agents.add(key)
        total_followers += a.followers or 0
        total_impressions += a.impressions or 0
        total_engagement += a.engagement_rate or 0.0
        agent_count += 1

        if a.platform not in by_platform:
            by_platform[a.platform] = {'followers': 0, 'impressions': 0, 'posts': 0}
        by_platform[a.platform]['followers'] += a.followers or 0
        by_platform[a.platform]['impressions'] += a.impressions or 0
        by_platform[a.platform]['posts'] += a.posts_published or 0

    # Content counts by time period
    posts_today = orchestrator.db.query(Content).filter(
        Content.status == 'published', Content.published_at >= today_start
    ).count()
    posts_week = orchestrator.db.query(Content).filter(
        Content.status == 'published', Content.published_at >= week_start
    ).count()
    posts_total = orchestrator.db.query(Content).filter(Content.status == 'published').count()

    return jsonify({
        'totals': {
            'followers': total_followers,
            'impressions': total_impressions,
            'avg_engagement': round(total_engagement / max(agent_count, 1), 2),
            'posts_today': posts_today,
            'posts_this_week': posts_week,
            'posts_total': posts_total,
        },
        'by_platform': by_platform,
    }), 200


@app.route('/content-hub')
def content_hub_page():
    return send_from_directory('', 'content-hub.html')


@app.route('/analytics')
def analytics_page():
    return send_from_directory('', 'analytics.html')


# ═══════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """Get recent notifications (unread first, then recent)."""
    from src.database.models import Notification
    limit = request.args.get('limit', 30, type=int)
    notifs = orchestrator.db.query(Notification).order_by(
        Notification.is_read.asc(), Notification.created_at.desc()
    ).limit(limit).all()
    unread = orchestrator.db.query(Notification).filter(Notification.is_read == False).count()
    return jsonify({
        'unread': unread,
        'notifications': [{
            'id': n.id,
            'type': n.type,
            'title': n.title,
            'body': n.body,
            'link': n.link,
            'agent_id': n.agent_id,
            'workflow_run_id': n.workflow_run_id,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat() if n.created_at else None,
        } for n in notifs]
    }), 200


@app.route('/api/notifications/read', methods=['POST'])
def mark_notifications_read():
    """Mark notifications as read."""
    from src.database.models import Notification
    data = request.json or {}
    ids = data.get('ids', [])
    if ids:
        orchestrator.db.query(Notification).filter(Notification.id.in_(ids)).update(
            {Notification.is_read: True}, synchronize_session=False)
    else:
        # Mark all as read
        orchestrator.db.query(Notification).filter(Notification.is_read == False).update(
            {Notification.is_read: True}, synchronize_session=False)
    orchestrator.db.commit()
    return jsonify({'ok': True}), 200


# ═══════════════════════════════════════════════════════
# EDITORIAL TEAM / NEWSROOM
# ═══════════════════════════════════════════════════════

@app.route('/api/team/members', methods=['GET'])
def get_team_members():
    """List all editorial team members."""
    from src.database.models import TeamMember
    members = orchestrator.db.query(TeamMember).filter(TeamMember.is_active == True).all()
    return jsonify([{
        'role_key': m.role_key,
        'display_name': m.display_name,
        'role_title': m.role_title,
        'emoji': m.emoji,
        'team': m.team or 'editorial',
        'reports_to': m.reports_to,
        'llm_provider': m.llm_provider,
        'llm_model': m.llm_model or 'claude-sonnet-4-6',
        'temperature': m.temperature,
        'system_prompt_preview': (m.system_prompt or '')[:200] + '…',
    } for m in members]), 200


@app.route('/api/team/members/<role_key>', methods=['GET'])
def get_team_member(role_key):
    """Get full details of a team member."""
    from src.database.models import TeamMember
    m = orchestrator.db.query(TeamMember).filter(TeamMember.role_key == role_key).first()
    if not m:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'role_key': m.role_key,
        'display_name': m.display_name,
        'role_title': m.role_title,
        'emoji': m.emoji,
        'team': m.team or 'editorial',
        'reports_to': m.reports_to,
        'system_prompt': m.system_prompt,
        'llm_provider': m.llm_provider,
        'llm_model': m.llm_model or 'claude-sonnet-4-6',
        'temperature': m.temperature,
    }), 200


@app.route('/api/team/members/<role_key>', methods=['PUT'])
def update_team_member(role_key):
    """Edit a team member's system prompt or settings."""
    from src.database.models import TeamMember
    data = request.json or {}
    m = orchestrator.db.query(TeamMember).filter(TeamMember.role_key == role_key).first()
    if not m:
        return jsonify({'error': 'Not found'}), 404
    if 'system_prompt' in data:
        m.system_prompt = data['system_prompt']
    if 'temperature' in data:
        m.temperature = float(data['temperature'])
    if 'display_name' in data:
        m.display_name = data['display_name']
    if 'llm_provider' in data:
        m.llm_provider = data['llm_provider']
    if 'llm_model' in data:
        m.llm_model = data['llm_model']
    orchestrator.db.commit()
    return jsonify({'message': f'{role_key} updated'}), 200


@app.route('/api/team/workflow/start', methods=['POST'])
def start_workflow():
    """Start a new editorial pipeline run."""
    data = request.json or {}
    target_ids = data.get('target_agent_ids', [])
    topics = data.get('topics', [])
    if not workflow_engine:
        return jsonify({'error': 'Workflow engine not initialized'}), 500
    run_id = workflow_engine.start_workflow(target_ids, topics)
    return jsonify({'run_id': run_id, 'status': 'pending'}), 201


@app.route('/api/team/workflows', methods=['GET'])
def list_workflows():
    """List all workflow runs. Optional ?dept= filter (newsroom, tech, sales)."""
    from src.database.models import WorkflowRun
    dept = request.args.get('dept')
    q = orchestrator.db.query(WorkflowRun).order_by(WorkflowRun.id.desc())
    if dept:
        q = q.filter(WorkflowRun.department == dept)
    runs = q.limit(50).all()
    return jsonify([{
        'id': r.id,
        'status': r.status,
        'current_step': r.current_step,
        'target_agent_ids': r.target_agent_ids,
        'department': getattr(r, 'department', 'newsroom') or 'newsroom',
        'started_at': r.started_at.isoformat() if r.started_at else None,
        'completed_at': r.completed_at.isoformat() if r.completed_at else None,
        'error_message': r.error_message,
        'is_active': workflow_engine.is_running(r.id) if workflow_engine else False,
    } for r in runs]), 200


@app.route('/api/team/workflow/<int:run_id>', methods=['GET'])
def get_workflow(run_id):
    """Get full status of a workflow run including step logs."""
    if not workflow_engine:
        return jsonify({'error': 'Workflow engine not initialized'}), 500
    status = workflow_engine.get_run_status(run_id)
    if 'error' in status:
        return jsonify(status), 404
    return jsonify(status), 200


@app.route('/api/team/workflow/<int:run_id>/artifacts', methods=['GET'])
def get_workflow_artifacts(run_id):
    """Get all artifacts for a workflow run."""
    from src.database.models import WorkflowRun, TrendReport, ContentBrief, MasterContent, AtomizedContent
    from src.database.models import Agent as _Agent
    run = orchestrator.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404

    tr = orchestrator.db.query(TrendReport).filter(TrendReport.workflow_run_id == run_id).first()
    cb = orchestrator.db.query(ContentBrief).filter(ContentBrief.workflow_run_id == run_id).first()
    mc = orchestrator.db.query(MasterContent).filter(MasterContent.workflow_run_id == run_id).first()
    atoms = orchestrator.db.query(AtomizedContent).filter(AtomizedContent.workflow_run_id == run_id).all()

    import json as _json
    def _parse(v, default=None):
        """Safely parse a JSON string or return as-is if already parsed."""
        if default is None: default = []
        if v is None: return default
        if isinstance(v, (list, dict)): return v
        try: return _json.loads(v)
        except Exception: return default

    # Build agent lookup
    _agent_rows = orchestrator.db.query(_Agent).all()
    _agent_map = {ag.id: ag for ag in _agent_rows}
    def _get_agent_name(aid): ag = _agent_map.get(aid); return ag.name if ag else f'Agent #{aid}'
    def _get_agent_username(aid): ag = _agent_map.get(aid); return ag.brand if ag else ''

    return jsonify({
        'workflow_run_id': run_id,
        'topic': run.topic_seeds,
        'trend_report': {
            'anchor_points': _parse(tr.anchor_points) if tr else [],
            'market_context': tr.market_context if tr else '',
            'raw_signals': _parse(tr.raw_signals) if tr else [],
        } if tr else None,
        'content_brief': {
            'headline': cb.headline if cb else '',
            'chosen_angle': cb.chosen_angle if cb else '',
            'narrative_hook': cb.narrative_hook if cb else '',
            'visual_direction': cb.visual_direction if cb else '',
            'tone_guidelines': cb.tone_guidelines if cb else '',
        } if cb else None,
        'master_content': {
            'headline': mc.headline if mc else '',
            'body': mc.body if mc else '',
            'key_points': _parse(mc.key_points) if mc else [],
            'num_images': len(_parse(mc.visual_assets)) if mc else 0,
            'fact_check_passed': mc.fact_check_passed if mc else False,
            'fact_check_notes': _parse(mc.fact_check_notes) if mc else [],
        } if mc else None,
        'atomized': [{
            'id': a.id,
            'agent_id': a.agent_id,
            'agent_name': _get_agent_name(a.agent_id),
            'agent_username': _get_agent_username(a.agent_id),
            'format_type': a.format_type,
            'platform': a.platform,
            'body': a.body,
            'hashtags': _parse(a.hashtags),
            'status': a.status,
            'media_urls': _parse(a.media_urls) if hasattr(a, 'media_urls') else [],
        } for a in atoms],
    }), 200


@app.route('/api/team/workflow/<int:run_id>/stop', methods=['POST'])
def stop_workflow(run_id):
    """Stop a running workflow."""
    from src.database.models import WorkflowRun
    run = orchestrator.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    if run.status not in ('pending', 'running'):
        return jsonify({'error': f'Cannot stop — status is {run.status}'}), 400
    run.status = 'failed'
    run.error_message = 'Stopped by supervisor'
    from datetime import datetime
    run.completed_at = datetime.utcnow()
    orchestrator.db.commit()
    # Remove from active runs
    if workflow_engine:
        workflow_engine._active_runs.pop(run_id, None)
    return jsonify({'message': f'Workflow #{run_id} stopped'}), 200


@app.route('/api/team/workflow/<int:run_id>/restart', methods=['POST'])
def restart_workflow(run_id):
    """Restart a failed workflow — from the failed step or from scratch."""
    from src.database.models import WorkflowRun, Notification
    data = request.json or {}
    mode = data.get('mode', 'beginning')  # 'current_step' or 'beginning'

    run = orchestrator.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        return jsonify({'error': 'Workflow not found'}), 404

    if not workflow_engine:
        return jsonify({'error': 'Workflow engine not running'}), 500

    # For both modes, start a new pipeline run with same config
    target_ids = run.target_agent_ids or []
    topics = run.topic_seeds or []
    new_run_id = workflow_engine.start_workflow(target_ids, topics)

    # Mark original as cancelled
    run.status = 'cancelled'
    run.error_message = (run.error_message or '') + f' | Restarted as #{new_run_id}'

    step_label = run.current_step or 'signal'
    label = f'from "{step_label}"' if mode == 'current_step' else 'from scratch'
    orchestrator.db.add(Notification(
        type='workflow_started',
        title=f'Pipeline #{new_run_id} restarted {label}',
        body=f'Original run #{run_id} cancelled. New pipeline is running.',
        link='/newsroom.html',
        workflow_run_id=new_run_id,
    ))
    orchestrator.db.commit()
    return jsonify({'ok': True, 'new_run_id': new_run_id, 'mode': mode}), 200


@app.route('/api/team/workflow/<int:run_id>/approve', methods=['POST'])
def approve_atomized(run_id):
    """Approve selected atomized content → create Content drafts on agents."""
    from src.database.models import AtomizedContent, Content
    data = request.json or {}
    ids = data.get('atomized_ids', [])
    if not ids:
        return jsonify({'error': 'No atomized_ids provided'}), 400

    atoms = orchestrator.db.query(AtomizedContent).filter(
        AtomizedContent.id.in_(ids),
        AtomizedContent.workflow_run_id == run_id,
    ).all()

    from src.database.models import Notification, Agent
    from src.autopilot.engine import next_peak_time
    from datetime import datetime

    created = []
    for a in atoms:
        # Schedule at next peak time for the platform
        sched_time = next_peak_time(a.platform, 2)

        # If atomization already created a Content draft, reuse it
        if a.content_id:
            post = orchestrator.db.query(Content).filter(Content.id == a.content_id).first()
            if post:
                post.status = 'scheduled'
                post.scheduled_at = sched_time
            else:
                a.content_id = None  # stale ref, will create below

        if not a.content_id:
            post = Content(
                agent_id=a.agent_id,
                title=a.body[:100],
                body=a.body,
                hashtags=a.hashtags,
                media_urls=a.media_urls,
                platform=a.platform,
                status='scheduled',
                scheduled_at=sched_time,
            )
            orchestrator.db.add(post)
            orchestrator.db.flush()
            a.content_id = post.id

        a.status = 'pushed_to_agent'

        # Get agent name for notification
        agent = orchestrator.db.query(Agent).filter(Agent.id == a.agent_id).first()
        agent_name = agent.name if agent else f'Agent #{a.agent_id}'

        # Create notification
        notif = Notification(
            type='post_scheduled',
            title=f'New post scheduled for {agent_name}',
            body=f'{a.format_type} on {a.platform} — scheduled {sched_time.strftime("%b %d at %H:%M")}',
            link=f'/agent-detail.html?id={a.agent_id}',
            agent_id=a.agent_id,
            workflow_run_id=run_id,
        )
        orchestrator.db.add(notif)

        created.append({
            'content_id': post.id, 'agent_id': a.agent_id,
            'platform': a.platform, 'scheduled_at': sched_time.isoformat(),
        })

        # ── Auto-create visual design task for Instagram posts ──
        if a.platform and a.platform.lower() == 'instagram':
            post_preview = (a.body or '')[:500]
            visual_task = Task(
                title=f'Design Instagram visuals for {agent_name} — post #{post.id}',
                description=(
                    f"A new Instagram post has been scheduled for {agent_name} (@{agent.brand if agent else '?'}).\n\n"
                    f"POST CONTENT:\n{post_preview}\n\n"
                    f"YOUR JOB:\n"
                    f"1. Analyze the post and recommend a visual format: single image, carousel (how many slides?), reel cover, or story\n"
                    f"2. For each image, describe what it should look like — composition, colors, mood, text overlays\n"
                    f"3. Instagram posts often have TEXT ON THE IMAGE (headlines, quotes, stats). Include specific text overlay content for each slide\n"
                    f"4. Consider the agent's persona and brand voice for visual style\n"
                    f"5. Generate the actual images using the prompts you designed\n\n"
                    f"IMPORTANT: This is for Instagram — visual impact is everything. "
                    f"Think bold text overlays, data callouts, provocative headlines ON the image itself. "
                    f"Not just a photo — a designed post that stops the scroll.\n\n"
                    f"Content ID: {post.id} | Agent ID: {a.agent_id}"
                ),
                status='pending',
                priority='high',
                created_by_type='system',
                created_by_key='pipeline',
                created_by_name='Pipeline',
                assignee_type='team_member',
                assignee_key='creative_director',
                assignee_name='Sasha Noir',
                requires_approval=True,
                department='newsroom',
            )
            orchestrator.db.add(visual_task)

    orchestrator.db.commit()
    return jsonify({'pushed': len(created), 'posts': created}), 200


@app.route('/api/team/workflow/<int:run_id>/schedule_all', methods=['POST'])
def schedule_all_atomized(run_id):
    """Schedule ALL draft atomized posts for a workflow run at peak times."""
    from src.database.models import AtomizedContent, Content, Agent, Notification
    from src.autopilot.engine import next_peak_time

    atoms = orchestrator.db.query(AtomizedContent).filter(
        AtomizedContent.workflow_run_id == run_id,
        AtomizedContent.status == 'draft',
    ).all()

    if not atoms:
        return jsonify({'error': 'No draft atomized posts for this workflow'}), 404

    _agent_map2 = {a.id: a for a in orchestrator.db.query(Agent).all()}
    created = []
    for a in atoms:
        sched_time = next_peak_time(a.platform, 2)

        # If atomization already created a Content draft, reuse it
        if a.content_id:
            post = orchestrator.db.query(Content).filter(Content.id == a.content_id).first()
            if post:
                post.status = 'scheduled'
                post.scheduled_at = sched_time
            else:
                a.content_id = None

        if not a.content_id:
            post = Content(
                agent_id=a.agent_id,
                title=(a.body or '')[:100],
                body=a.body,
                hashtags=a.hashtags,
                media_urls=a.media_urls if hasattr(a, 'media_urls') else None,
                platform=a.platform,
                status='scheduled',
                scheduled_at=sched_time,
            )
            orchestrator.db.add(post)
            orchestrator.db.flush()
            a.content_id = post.id

        a.status = 'pushed_to_agent'
        agent = _agent_map2.get(a.agent_id)
        agent_name = agent.name if agent else f'Agent #{a.agent_id}'
        notif = Notification(
            type='post_scheduled',
            title=f'New post scheduled for {agent_name}',
            body=f'{a.format_type} on {a.platform} — scheduled {sched_time.strftime("%b %d at %H:%M")}',
            link=f'/agent-detail.html?id={a.agent_id}',
            agent_id=a.agent_id,
            workflow_run_id=run_id,
        )
        orchestrator.db.add(notif)
        created.append({
            'content_id': post.id, 'agent_id': a.agent_id,
            'agent_name': agent_name,
            'platform': a.platform, 'scheduled_at': sched_time.isoformat(),
        })

    orchestrator.db.commit()
    return jsonify({'scheduled': len(created), 'posts': created}), 200


@app.route('/api/team/workflow/<int:run_id>/eic_schedule', methods=['POST'])
def eic_prepare_schedule(run_id):
    """Victoria Crane prepares a publishing schedule for a workflow's atomized content."""
    from flask import g
    from src.database.models import WorkflowRun, AtomizedContent, Agent, TeamMember, MasterContent, ContentBrief
    import json as _json

    db = orchestrator.db
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        return jsonify({'error': 'Workflow not found'}), 404

    atoms = db.query(AtomizedContent).filter(AtomizedContent.workflow_run_id == run_id).all()
    if not atoms:
        return jsonify({'error': 'No atomized content found for this workflow'}), 404

    # Build agent map
    agents = db.query(Agent).all()
    agent_map = {a.id: a for a in agents}

    # Get Victoria's profile
    victoria = db.query(TeamMember).filter(TeamMember.role_key == 'eic').first()

    # Build content summary for Victoria
    brief = db.query(ContentBrief).filter(ContentBrief.workflow_run_id == run_id).first()
    mc = db.query(MasterContent).filter(MasterContent.workflow_run_id == run_id).first()

    topic = run.topic_seeds or 'General content'
    headline = brief.headline if brief else (mc.headline if mc else topic)

    posts_summary = []
    for a in atoms:
        ag = agent_map.get(a.agent_id)
        posts_summary.append({
            'id': a.id,
            'agent_name': ag.name if ag else f'Agent #{a.agent_id}',
            'agent_username': ag.username if ag else '',
            'platform': a.platform,
            'format_type': a.format_type,
            'body_preview': (a.body or '')[:200],
            'status': a.status,
        })

    system_prompt = """You are Victoria Crane, Editor-in-Chief. You are preparing a publishing schedule for the founder's approval.
Your job: review the atomized posts, propose an optimal publishing schedule, and present it as a structured recommendation.

Return a JSON object with this exact structure:
{
  "schedule_summary": "2-3 sentence overview of the publishing plan",
  "total_posts": <number>,
  "posts": [
    {
      "id": <atomized_content_id>,
      "agent_name": "...",
      "platform": "...",
      "format_type": "...",
      "recommended_time": "YYYY-MM-DDTHH:MM:SS",
      "rationale": "Why this time/platform pairing works",
      "priority": "high|medium|low",
      "body_preview": "first 100 chars of content"
    }
  ],
  "victoria_note": "Your editorial note to the founder — any concerns, highlights, or strategic recommendations"
}

Be concise. Think about peak engagement times per platform. Instagram: 11am-1pm or 7-9pm. Twitter/X: 8am, 12pm, 5pm. LinkedIn: 8am-10am weekday. TikTok: 7pm-9pm. Space posts 2-4 hours apart minimum."""

    user_msg = f"""Workflow #{run_id} — Topic: {topic}
Headline: {headline}
Posts to schedule: {_json.dumps(posts_summary, indent=2)}

Prepare the optimal publishing schedule for all {len(atoms)} posts."""

    try:
        from src.api.llm_provider import LLMProvider
        victoria_model = victoria.llm_model if victoria else 'claude-haiku-4-5'
        victoria_provider = victoria.llm_provider if victoria else 'claude'
        llm = LLMProvider(provider=victoria_provider, model=victoria_model)
        reply_text = llm.generate_content(
            prompt=user_msg,
            max_tokens=2000,
            temperature=0.6,
            system_prompt=system_prompt,
        )

        # Extract JSON from reply
        import re
        json_match = re.search(r'\{[\s\S]+\}', reply_text)
        schedule_data = _json.loads(json_match.group()) if json_match else {'error': 'Could not parse schedule', 'raw': reply_text}

    except Exception as e:
        schedule_data = {'error': str(e)}

    return jsonify({'workflow_id': run_id, 'schedule': schedule_data}), 200


@app.route('/api/team/workflow/<int:run_id>/redispatch', methods=['POST'])
def redispatch_atomized(run_id):
    """Reassign an atomized post to a different agent."""
    from src.database.models import AtomizedContent, Agent
    data = request.json or {}
    atom_id = data.get('atom_id')
    new_agent_id = data.get('new_agent_id')
    if not atom_id or not new_agent_id:
        return jsonify({'error': 'atom_id and new_agent_id required'}), 400
    atom = orchestrator.db.query(AtomizedContent).filter(
        AtomizedContent.id == atom_id,
        AtomizedContent.workflow_run_id == run_id,
    ).first()
    if not atom:
        return jsonify({'error': 'Atomized post not found'}), 404
    agent = orchestrator.db.query(Agent).filter(Agent.id == new_agent_id).first()
    if not agent:
        return jsonify({'error': 'Agent not found'}), 404
    atom.agent_id = new_agent_id
    orchestrator.db.commit()
    return jsonify({'atom_id': atom_id, 'new_agent_id': new_agent_id, 'new_agent_name': agent.name}), 200


# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


# ═══════════════════════════════════════════════════════════════
# VICTORIA CRANE — EIC CHAT
# ═══════════════════════════════════════════════════════════════

@app.route('/api/team/chat', methods=['POST'])
def team_chat():
    """Chat with Victoria Crane (Editor-in-Chief) about editorial operations."""
    from flask import g
    from src.database.models import TeamMember, WorkflowRun, Agent, Content, AtomizedContent
    data = request.json
    user_msg = (data or {}).get('message', '').strip()
    if not user_msg:
        return jsonify({'error': 'message required'}), 400

    db = g.db

    # ── Gather context for Victoria ──
    # Team members
    members = db.query(TeamMember).all()
    team_info = '\n'.join(
        f"- {m.display_name} ({m.role_title}) — model: {m.llm_model}, reports to: {m.reports_to or 'you'}"
        for m in members
    )

    # Recent workflows
    recent_wfs = db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(5).all()
    wf_info = '\n'.join(
        f"- Workflow #{w.id}: status={w.status}, step={w.current_step}, "
        f"agents={w.target_agent_ids}, topics={w.topic_seeds}, "
        f"started={w.started_at}, completed={w.completed_at}"
        + (f", error={w.error_message}" if w.error_message else '')
        for w in recent_wfs
    ) if recent_wfs else 'No workflows run yet.'

    # Active workflow
    active_wf = None
    if workflow_engine:
        active_ids = workflow_engine.active_run_ids()
        if active_ids:
            active_wf = f"Currently running: workflow #{active_ids[0]}"

    # Agents
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    agents_info = ', '.join(f"{a.name} (fields: {a.fields})" for a in agents)

    # Content stats
    total_drafts = db.query(Content).filter(Content.status == 'draft').count()
    total_sched = db.query(Content).filter(Content.status == 'scheduled').count()
    total_pub = db.query(Content).filter(Content.status == 'published').count()

    # Atomized content pending
    try:
        pending_atomized = db.query(AtomizedContent).filter(AtomizedContent.status == 'draft').count()
    except Exception:
        pending_atomized = 0

    system_prompt = f"""You are Victoria Crane, Editor-in-Chief of the editorial team at this AI marketing agency.
You lead a team of 9 AI specialists who produce premium content by dispatching tasks to copywriters, prompt engineers, fact-checkers, and distribution specialists.

Your personality: Sharp, decisive, visionary. You speak with authority but warmth. You use concise, professional language.
You know everything about the current state of operations.

YOUR TEAM:
{team_info}

RECENT WORKFLOWS:
{wf_info}
{f'ACTIVE NOW: {active_wf}' if active_wf else 'No workflow currently running.'}

PUBLISHING AGENTS (11 influencers who receive atomized content):
{agents_info}

CONTENT STATS:
- Drafts: {total_drafts}
- Scheduled: {total_sched}
- Published: {total_pub}
- Atomized content pending review: {pending_atomized}

INSTRUCTIONS:
- Answer questions about team operations, workflow status, content strategy
- When asked to start a workflow, explain that the user can click "New Workflow" button and suggest topics
- When asked about a team member, describe their role and what they contribute
- Suggest content topics and strategies proactively when relevant
- Keep responses concise (2-4 sentences unless detail is needed)
- Use first person — you ARE Victoria"""

    try:
        from src.api.llm_provider import LLMProvider
        # Use Victoria's configured model
        victoria = db.query(TeamMember).filter(TeamMember.role_key == 'eic').first()
        model = victoria.llm_model if victoria else 'claude-opus-4-6'
        provider = victoria.llm_provider if victoria else 'claude'
        llm = LLMProvider(provider=provider, model=model)
        reply = llm.generate_content(
            prompt=user_msg,
            max_tokens=500,
            temperature=0.7,
            system_prompt=system_prompt
        )
        return jsonify({'reply': reply, 'from': 'Victoria Crane', 'role': 'Editor-in-Chief'}), 200
    except Exception as e:
        return jsonify({'error': f'Victoria is unavailable: {str(e)}'}), 500


# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# VISION — Company north star
# ═══════════════════════════════════════════════════════════════

@app.route('/vision')
def vision_page():
    return send_file(os.path.join(os.path.dirname(__file__), 'vision.html'))


@app.route('/api/vision', methods=['GET'])
def get_vision():
    """Get the current company vision."""
    from flask import g
    from src.database.models import CompanyVision
    import json as _json
    db = g.db
    v = db.query(CompanyVision).first()
    if not v:
        return jsonify({'mission': '', 'vision_statement': '', 'values': [], 'milestones': [], 'okrs': [], 'updated_at': None}), 200
    def _p(s):
        try: return _json.loads(s) if s else []
        except Exception: return []
    return jsonify({
        'mission': v.mission or '',
        'vision_statement': v.vision_statement or '',
        'values': _p(v.values),
        'milestones': _p(v.milestones),
        'okrs': _p(v.okrs),
        'updated_at': v.updated_at.isoformat() if v.updated_at else None,
        'updated_by': v.updated_by or '',
    }), 200


@app.route('/api/vision', methods=['PUT'])
def update_vision():
    """Update the company vision."""
    from flask import g
    from src.database.models import CompanyVision
    import json as _json
    db = g.db
    data = request.json or {}
    v = db.query(CompanyVision).first()
    if not v:
        v = CompanyVision()
        db.add(v)
    if 'mission' in data:
        v.mission = data['mission']
    if 'vision_statement' in data:
        v.vision_statement = data['vision_statement']
    if 'values' in data:
        v.values = _json.dumps(data['values']) if isinstance(data['values'], list) else data['values']
    if 'milestones' in data:
        v.milestones = _json.dumps(data['milestones']) if isinstance(data['milestones'], list) else data['milestones']
    if 'okrs' in data:
        v.okrs = _json.dumps(data['okrs']) if isinstance(data['okrs'], list) else data['okrs']
    v.updated_by = data.get('updated_by', 'supervisor')
    db.commit()
    return jsonify({'ok': True}), 200


def _extract_vision_update(reply_text, db):
    """Parse ```vision JSON from cofounder reply — extract but DO NOT save yet.
    Returns (clean_text, proposed_vision_dict). Saving requires explicit user approval."""
    import re, json as _json
    pattern = r'```vision\s*\n?(.*?)\n?```'
    match = re.search(pattern, reply_text, re.DOTALL)
    if not match:
        return reply_text, None
    clean = re.sub(pattern, '', reply_text, flags=re.DOTALL).strip()
    try:
        vdata = _json.loads(match.group(1))
        # Return proposal — frontend must call /api/vision/apply to actually save
        return clean, vdata
    except Exception as e:
        logging.warning(f"Vision extraction error: {e}")
    return clean, None


@app.route('/api/vision/apply', methods=['POST'])
def apply_vision_proposal():
    """Apply a vision proposal that was reviewed and approved by the user."""
    from flask import g
    from src.database.models import CompanyVision
    import json as _json
    db = g.db
    vdata = request.json or {}
    if not vdata:
        return jsonify({'error': 'No vision data provided'}), 400
    try:
        v = db.query(CompanyVision).first()
        if not v:
            v = CompanyVision()
            db.add(v)
        if vdata.get('mission'):
            v.mission = vdata['mission']
        if vdata.get('vision_statement'):
            v.vision_statement = vdata['vision_statement']
        if vdata.get('values'):
            v.values = _json.dumps(vdata['values'])
        if vdata.get('milestones'):
            v.milestones = _json.dumps(vdata['milestones'])
        if vdata.get('okrs'):
            v.okrs = _json.dumps(vdata['okrs'])
        v.updated_by = 'cofounder'
        db.commit()
        return jsonify({'ok': True}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# INBOX — Unified messages & chat with any entity
# ═══════════════════════════════════════════════════════════════

@app.route('/inbox')
def inbox_page():
    return send_file(os.path.join(os.path.dirname(__file__), 'inbox.html'))


TASK_INSTRUCTION = """
TASK CREATION:
When the conversation involves work to be done, you can create tasks. Include a JSON block in your response:
```tasks
[{"title": "Task title", "assignee_key": "role_key_or_agent_id", "assignee_type": "team_member or agent", "priority": "low/medium/high/urgent", "due_date": "2026-04-05", "description": "Details"}]
```
You can assign tasks to yourself, to your subordinates, or to agents. Use role_keys for team (eic, creative_director, head_intelligence, production_manager, prompt_engineer_1, prompt_engineer_2, copywriter_1, copywriter_2, distribution_specialist) or agent IDs (1-11) for agents.
Only create tasks when the user asks you to do something, or when you proactively break down work. Always explain what tasks you're creating.

HOW TO INTERACT WITH THE SUPERVISOR:
- When the supervisor asks about content ideas, propose 2-3 specific topics with brief reasoning
- Ask "Should I launch the pipeline on these?" or "Want me to kick this off?"
- When they confirm, include the ```workflow block to launch it
- If they ask you to work on something, FIRST propose a plan, THEN ask for confirmation, THEN launch
- You are the boss of the team — you decide who does what, the supervisor just approves the direction
- Be proactive: suggest topics, flag issues, propose content calendars

HIRING NEW AGENTS/TEAM MEMBERS:
When your team needs more capacity, propose hiring by including:
```hire
[{"name": "Full Name", "brand": "brand_handle", "persona": "Detailed persona", "tone_of_voice": "Tone description", "fields": ["Field1", "Field2"], "bio": "Short bio", "image_style": "visual style", "llm_model": "claude-sonnet-4-6", "reason": "Why this hire is needed"}]
```
Rules:
- Only GM, EIC, and directors can propose hires
- Always explain the business case: what gap does this fill? what capacity problem does it solve?
- The supervisor must approve before the agent is created
- Be specific about persona and tone — these agents will publish real content
- Propose 1-3 agents at a time, not more
"""


def _get_vision_block(db):
    """Load the company vision for injection into all system prompts."""
    from src.database.models import CompanyVision
    v = db.query(CompanyVision).first()
    if not v or not v.mission:
        return ''
    return (
        f"\n═══ COMPANY VISION ═══\n"
        f"Mission: {v.mission}\n"
        f"{v.vision_statement}\n"
        f"══════════════════════\n"
        f"Everything you do must serve this vision. Your content, decisions, and priorities align with it.\n"
    )


def _build_team_system_prompt(db, member):
    """Build a rich system prompt for a team member chat."""
    from src.database.models import TeamMember, WorkflowRun, Agent, Content, Task, SocialMediaAccount
    vision_block = _get_vision_block(db)
    members = db.query(TeamMember).all()
    team_info = '\n'.join(f"- {m.role_key}: {m.display_name} ({m.role_title}), reports to: {m.reports_to or 'supervisor'}" for m in members)
    recent_wfs = db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(3).all()
    wf_info = '\n'.join(
        f"- Workflow #{w.id}: status={w.status}, step={w.current_step}" for w in recent_wfs
    ) if recent_wfs else 'No workflows yet.'
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    agents_info = '\n'.join(f"- ID {a.id}: {a.name} ({a.brand})" for a in agents)
    total_drafts = db.query(Content).filter(Content.status == 'draft').count()
    total_pub = db.query(Content).filter(Content.status == 'published').count()
    my_tasks = db.query(Task).filter(Task.assignee_key == member.role_key, Task.status != 'done').all()
    tasks_info = '\n'.join(f"- [{t.priority}] {t.title} (status: {t.status})" for t in my_tasks) if my_tasks else 'No pending tasks.'

    # For Marc (cofounder): inject full influencer account status + action commands
    extra_context = ''
    if member.role_key == 'cofounder':
        accounts = db.query(SocialMediaAccount).filter(
            SocialMediaAccount.access_token != None,
            SocialMediaAccount.access_token != '',
        ).all()
        acct_map = {}
        for a in accounts:
            acct_map.setdefault(a.agent_id, []).append(a.platform)

        agent_acct_lines = []
        for a in agents:
            platforms = acct_map.get(a.id, [])
            required = {'instagram', 'twitter'}
            has = set(platforms)
            missing_core = required - has
            if not has & required:
                status = '❌ No accounts linked (need Instagram + X)'
            elif missing_core:
                status = f'⚠️ Partial — missing: {", ".join(missing_core)}'
            else:
                status = '✅ Fully active (Instagram + X connected)'
            agent_acct_lines.append(f'  - ID {a.id}: {a.name} ({a.brand}) — {status}')

        unlinked = sum(1 for a in agents if not acct_map.get(a.id))
        partial  = sum(1 for a in agents if 0 < len(acct_map.get(a.id, [])) < 3)
        full     = sum(1 for a in agents if len(acct_map.get(a.id, [])) >= 3)

        extra_context = f"""
=== INFLUENCER ACCOUNT STATUS ({len(agents)} agents) ===
Summary: {full} fully linked · {partial} partial · {unlinked} with NO accounts
{chr(10).join(agent_acct_lines)}

=== UI ACTIONS YOU CAN TRIGGER FOR THE FOUNDER ===
When the founder asks you to connect accounts, create a role, or navigate somewhere,
include an ```actions block at the end of your reply. The UI will render clickable buttons.

Format:
```actions
[{{"type": "open_connect", "agent_id": 5, "agent_name": "Name", "label": "🔗 Connect Name on social"}},
 {{"type": "create_agent", "label": "➕ Create New Influencer"}},
 {{"type": "go_to_agent", "agent_id": 5, "label": "👤 Open Name's Profile"}},
 {{"type": "go_to_room", "room": "tech", "label": "💻 Go to Tech Room"}},
 {{"type": "go_to_room", "room": "sales", "label": "🤝 Go to Sales Room"}}]
```

Action types:
- "open_connect": opens Connect Account modal for that agent (use when founder wants to link a platform)
- "create_agent": opens New Agent/Role creation modal
- "go_to_agent": navigates to agent detail page
- "go_to_room": switches to newsroom room (newsroom/tech/sales/gm)

PROACTIVELY use actions: if the founder asks about unlinked agents, give them action buttons to connect each one.
If they ask to create a new role, give them a "create_agent" action button immediately.
"""

    return f"""{member.system_prompt}
{vision_block}
You are {member.display_name}, {member.role_title} on the editorial team.
You're chatting with the supervisor. Be helpful, stay in character, and be concise.

TEAM HIERARCHY:
{team_info}

PUBLISHING AGENTS:
{agents_info}

RECENT WORKFLOWS: {wf_info}
CONTENT: {total_drafts} drafts, {total_pub} published

YOUR CURRENT TASKS:
{tasks_info}
{extra_context}
{TASK_INSTRUCTION}"""


def _extract_ui_actions(reply_text):
    """Parse ```actions [...] ``` blocks from AI reply. Returns (clean_text, actions_list)."""
    import re, json
    pattern = r'```actions\s*\n?([\s\S]*?)\n?\s*```'
    m = re.search(pattern, reply_text)
    if not m:
        return reply_text, []
    raw = m.group(1).strip()
    clean = re.sub(pattern, '', reply_text, flags=re.DOTALL).strip()
    try:
        actions = json.loads(raw)
        if not isinstance(actions, list):
            actions = []
    except Exception:
        actions = []
    return clean, actions


def _build_agent_system_prompt(db_or_none, agent):
    """Build a system prompt for chatting with a publishing agent."""
    vision_block = ''
    if db_or_none:
        vision_block = _get_vision_block(db_or_none)
    return (
        f"You are {agent.name}, a social media content creator for {agent.brand}.\n"
        f"Persona: {agent.persona}\n"
        f"Tone: {agent.tone_of_voice}\n"
        f"Expertise: {', '.join(agent.fields or [])}\n"
        f"Bio: {agent.bio or ''}\n"
        f"{vision_block}\n"
        f"You're chatting with your supervisor. Be helpful, stay in character, respond concisely.\n"
        f"{TASK_INSTRUCTION}"
    )


def _extract_and_create_tasks(db, reply_text, thread_id, entity_type, entity_key, entity_name):
    """Parse tasks JSON from AI reply. Handles multiple code-block formats:
    ```tasks [...] ```, ```json [...] ```, or a bare JSON array with 'title' keys.
    Returns (clean_text, tasks_created) — clean_text has ALL task blocks removed."""
    import re, json
    from src.database.models import Task, TeamMember, Agent

    # Try multiple patterns in priority order
    # Pattern 1: explicit ```tasks block
    pattern_tasks = r'```tasks\s*\n?(.*?)\n?\s*```'
    # Pattern 2: ```json block containing an array
    pattern_json  = r'```json\s*\n?(\[[\s\S]*?\])\s*\n?\s*```'
    # Pattern 3: any ``` block containing a JSON array with "title" key
    pattern_any   = r'```[\w_]*\s*\n?(\[[\s\S]*?"title"[\s\S]*?\])\s*\n?\s*```'

    raw_json = None
    used_pattern = None
    for pat in [pattern_tasks, pattern_json, pattern_any]:
        m = re.search(pat, reply_text, re.DOTALL)
        if m:
            raw_json = m.group(1).strip()
            used_pattern = pat
            break

    # Fallback: truncated reply — opening ```tasks / ```json but no closing fence.
    # Grab everything from the opening fence to end-of-text, then try to auto-close JSON.
    truncated_opener = None
    if not raw_json:
        trunc_match = re.search(r'```(tasks|json)\s*\n?([\s\S]*)$', reply_text)
        if trunc_match and '[' in trunc_match.group(2):
            tail = trunc_match.group(2)
            # Cut at last valid-ish comma/brace and try to balance
            body = tail[tail.index('['):]
            # Naive balance: count unmatched { and [ and close them
            opens_sq = body.count('[') - body.count(']')
            opens_cr = body.count('{') - body.count('}')
            # Strip trailing partial object after last closed }
            last_close = max(body.rfind('}'), body.rfind(']'))
            if last_close > 0:
                candidate = body[:last_close+1]
                opens_sq = candidate.count('[') - candidate.count(']')
                if opens_sq > 0:
                    candidate = candidate + (']' * opens_sq)
                try:
                    json.loads(candidate)
                    raw_json = candidate
                    truncated_opener = trunc_match.group(0)
                    logging.info(f"Task extraction: recovered {candidate.count('title')} tasks from truncated reply")
                except Exception:
                    pass

    if not raw_json:
        # Still no valid JSON — but strip any unclosed ```tasks fragment so user doesn't see garbage
        clean = re.sub(r'```(tasks|json)[\s\S]*$', '', reply_text).strip()
        return clean, []

    # Strip ALL task/json code blocks from the reply
    clean_text = reply_text
    for pat in [pattern_tasks, pattern_json, pattern_any]:
        clean_text = re.sub(pat, '', clean_text, flags=re.DOTALL)
    # Also strip truncated opener if we recovered from one
    if truncated_opener:
        clean_text = clean_text.replace(truncated_opener, '')
        clean_text = re.sub(r'```(tasks|json)[\s\S]*$', '', clean_text)
    clean_text = clean_text.strip()

    created = []
    try:
        task_list = json.loads(raw_json)
        if not isinstance(task_list, list):
            task_list = [task_list]
        for td in task_list:
            a_key = str(td.get('assignee_key', entity_key))
            a_type = td.get('assignee_type', entity_type)
            a_name = td.get('assignee_name', '')
            if not a_name:
                if a_type == 'team_member':
                    m = db.query(TeamMember).filter(TeamMember.role_key == a_key).first()
                    if m: a_name = m.display_name
                elif a_type == 'agent':
                    a = db.query(Agent).filter(Agent.id == int(a_key)).first()
                    if a: a_name = a.name
            if not a_name:
                a_name = a_key
            due = None
            if td.get('due_date'):
                try:
                    from datetime import datetime as dt
                    due = dt.fromisoformat(str(td['due_date']))
                except Exception:
                    pass
            task = Task(
                title=td.get('title', 'Untitled task'),
                description=td.get('description', ''),
                priority=td.get('priority', 'medium'),
                assignee_type=a_type,
                assignee_key=a_key,
                assignee_name=a_name,
                created_by_type=entity_type,
                created_by_key=entity_key,
                created_by_name=entity_name,
                department=_dept_from_assignee(a_key),
                thread_id=thread_id,
                due_date=due,
                requires_approval=(entity_key == 'cofounder'),
            )
            db.add(task)
            db.commit()
            created.append({'id': task.id, 'title': task.title, 'assignee': a_name, 'priority': task.priority})
    except Exception as e:
        logging.warning(f"Task extraction error: {e}")
    return clean_text, created


def _extract_and_launch_workflow(reply_text):
    """Parse ```workflow JSON from AI reply, launch the pipeline, return (clean_text, workflow_info)."""
    import re, json
    pattern = r'```workflow\s*\n?(.*?)\n?```'
    match = re.search(pattern, reply_text, re.DOTALL)
    if not match:
        return reply_text, None

    clean_text = re.sub(pattern, '', reply_text, flags=re.DOTALL).strip()
    try:
        wf_data = json.loads(match.group(1))
        topics = wf_data.get('topics', [])
        target_agents = wf_data.get('target_agents', list(range(1, 12)))  # default: all 11 agents

        if workflow_engine:
            run_id = workflow_engine.start_workflow(target_agents, topics)
            return clean_text, {
                'run_id': run_id,
                'topics': topics,
                'target_agents': target_agents,
                'status': 'launched'
            }
    except Exception as e:
        logging.warning(f"Workflow extraction error: {e}")
    return clean_text, None


def _extract_hire_proposals(reply_text):
    """Parse ```hire JSON from AI reply, return (clean_text, proposals_list)."""
    import re, json
    pattern = r'```hire\s*\n?(.*?)\n?```'
    match = re.search(pattern, reply_text, re.DOTALL)
    if not match:
        return reply_text, []

    clean_text = re.sub(pattern, '', reply_text, flags=re.DOTALL).strip()
    try:
        proposals = json.loads(match.group(1))
        if not isinstance(proposals, list):
            proposals = [proposals]
        # Validate each proposal has required fields
        valid = []
        for p in proposals:
            if p.get('name') and p.get('persona'):
                valid.append({
                    'name': p.get('name', ''),
                    'brand': p.get('brand', ''),
                    'persona': p.get('persona', ''),
                    'tone_of_voice': p.get('tone_of_voice', ''),
                    'fields': p.get('fields', []),
                    'bio': p.get('bio', ''),
                    'image_style': p.get('image_style', 'ultra realistic photography'),
                    'llm_model': p.get('llm_model', 'claude-sonnet-4-6'),
                    'reason': p.get('reason', ''),
                })
        return clean_text, valid
    except Exception as e:
        logging.warning(f"Hire extraction error: {e}")
    return clean_text, []


@app.route('/api/team/generate-agent-profile', methods=['POST'])
def generate_agent_profile():
    """Use the GM to generate a full agent profile from a description."""
    from flask import g
    from src.database.models import TeamMember
    data = request.json or {}
    description = data.get('description', '').strip()
    if not description:
        return jsonify({'error': 'description required'}), 400

    db = g.db
    gm = db.query(TeamMember).filter(TeamMember.role_key == 'general_manager').first()
    provider = gm.llm_provider if gm else 'claude'
    model = gm.llm_model if gm else 'claude-opus-4-6'

    system_prompt = (
        "You are Alexander Voss, General Manager designing a new AI agent for the team. "
        "Given a role description, create a complete, realistic agent profile. "
        "The agent must feel like a real person with 10+ years of experience. "
        "Respond ONLY in JSON with these exact keys: "
        "name (realistic full name), brand (social media handle), "
        "persona (3-4 sentences: background, experience, personality, motivations), "
        "tone_of_voice (how they communicate), "
        "fields (array of 3-5 expertise areas), "
        "bio (1-2 sentence public bio followers would see). "
        "Make the persona detailed, specific, and authentic. Include years of experience, "
        "past companies or roles, unique perspective, and what drives them."
    )

    try:
        from src.api.llm_provider import LLMProvider
        llm = LLMProvider(provider=provider, model=model)
        raw = llm.generate_content(
            prompt=f"Design an agent for: {description}",
            max_tokens=800,
            temperature=0.8,
            system_prompt=system_prompt
        )
        import json as _json
        # Try to parse JSON from the response
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        profile = _json.loads(raw)
        return jsonify({'profile': profile}), 200
    except Exception as e:
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500


@app.route('/api/team/hire/approve', methods=['POST'])
def approve_hire():
    """Create a new agent from an approved hire proposal."""
    from flask import g
    from src.database.models import Agent, Notification
    db = g.db
    data = request.json or {}

    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400

    # Create the agent
    agent = Agent(
        name=name,
        brand=data.get('brand', name.lower().replace(' ', '_')),
        persona=data.get('persona', ''),
        tone_of_voice=data.get('tone_of_voice', ''),
        fields=data.get('fields', []),
        bio=data.get('bio', ''),
        image_style=data.get('image_style', 'ultra realistic photography'),
        llm_provider=data.get('llm_provider', 'claude'),
        llm_model=data.get('llm_model', 'claude-sonnet-4-6'),
        is_active=True,
    )
    db.add(agent)
    db.commit()

    # Send notification
    notif = Notification(
        type='content_ready',
        title=f'New agent hired: {name}',
        body=f'{name} has joined the team as a publishing agent. Fields: {", ".join(data.get("fields", []))}',
        link='/',
        agent_id=agent.id,
    )
    db.add(notif)
    db.commit()

    logging.info(f"[Hire] New agent created: {name} (ID: {agent.id})")
    return jsonify({
        'ok': True,
        'agent_id': agent.id,
        'name': name,
        'message': f'{name} has been hired and is ready to publish!'
    }), 201


@app.route('/api/inbox', methods=['GET'])
def get_inbox():
    """List message threads (latest message per thread)."""
    from flask import g
    from src.database.models import InternalMessage
    from sqlalchemy import func
    db = g.db
    msg_type = request.args.get('type', 'all')

    # Subquery: latest message id per thread
    sub = db.query(
        InternalMessage.thread_id,
        func.max(InternalMessage.id).label('max_id')
    ).group_by(InternalMessage.thread_id).subquery()

    q = db.query(InternalMessage).join(
        sub, InternalMessage.id == sub.c.max_id
    )
    if msg_type == 'email':
        q = q.filter(InternalMessage.msg_type == 'email')
    elif msg_type == 'chat':
        q = q.filter(InternalMessage.msg_type == 'chat')

    threads = q.order_by(InternalMessage.created_at.desc()).limit(50).all()

    result = []
    for t in threads:
        unread = db.query(InternalMessage).filter(
            InternalMessage.thread_id == t.thread_id,
            InternalMessage.is_read == False,
            InternalMessage.from_type != 'user'
        ).count()
        msg_count = db.query(InternalMessage).filter(
            InternalMessage.thread_id == t.thread_id
        ).count()
        # Get the first message for subject
        first = db.query(InternalMessage).filter(
            InternalMessage.thread_id == t.thread_id
        ).order_by(InternalMessage.id.asc()).first()

        result.append({
            'thread_id': t.thread_id,
            'from_name': t.from_name if t.from_type != 'user' else first.from_name if first and first.from_type != 'user' else t.from_name,
            'from_key': t.from_key if t.from_type != 'user' else first.from_key if first else t.from_key,
            'from_type': t.from_type if t.from_type != 'user' else first.from_type if first else t.from_type,
            'from_emoji': t.from_emoji if t.from_type != 'user' else first.from_emoji if first else '',
            'subject': first.subject if first else None,
            'preview': t.body[:120] if t.body else '',
            'msg_type': t.msg_type,
            'unread': unread,
            'count': msg_count,
            'last_at': t.created_at.isoformat() if t.created_at else None,
        })

    return jsonify({'threads': result}), 200


@app.route('/api/inbox/thread/<thread_id>', methods=['GET'])
def get_inbox_thread(thread_id):
    """Get all messages in a thread, mark as read."""
    from flask import g
    from src.database.models import InternalMessage
    db = g.db
    msgs = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).order_by(InternalMessage.created_at.asc()).all()

    # Mark all as read
    db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id,
        InternalMessage.is_read == False
    ).update({InternalMessage.is_read: True}, synchronize_session=False)
    db.commit()

    return jsonify({
        'thread_id': thread_id,
        'messages': [{
            'id': m.id,
            'from_type': m.from_type,
            'from_key': m.from_key,
            'from_name': m.from_name,
            'from_emoji': m.from_emoji,
            'subject': m.subject,
            'body': m.body,
            'msg_type': m.msg_type,
            'is_read': m.is_read,
            'created_at': m.created_at.isoformat() if m.created_at else None,
        } for m in msgs]
    }), 200


@app.route('/api/inbox/chat', methods=['POST'])
def inbox_chat():
    """Send a message to any team member or agent and get an AI reply."""
    from flask import g
    from src.database.models import InternalMessage, TeamMember, Agent
    import uuid
    db = g.db
    data = request.json or {}
    entity_type = data.get('entity_type', '')     # 'team_member' or 'agent'
    entity_key = data.get('entity_key', '')       # role_key or agent id
    user_msg = data.get('message', '').strip()
    thread_id = data.get('thread_id', '')
    attachment = data.get('attachment')  # legacy single: {data, mime, name}
    attachments = data.get('attachments') or ([attachment] if attachment else [])
    # Split attachments into images (for vision) and PDFs (for text extraction)
    images = []
    pdf_texts = []  # list of (name, extracted_text)
    for att in attachments:
        if not att or not att.get('data'):
            continue
        mime = (att.get('mime') or '').lower()
        name = att.get('name') or 'file'
        if mime.startswith('image/'):
            images.append({'data': att['data'], 'mime': mime, 'name': name})
        elif mime == 'application/pdf' or name.lower().endswith('.pdf'):
            try:
                import base64, io
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(base64.b64decode(att['data'])))
                text = '\n'.join((p.extract_text() or '') for p in reader.pages).strip()
                if text:
                    pdf_texts.append((name, text[:20000]))  # cap 20k chars/file
            except Exception as ex:
                pdf_texts.append((name, f'[PDF extraction failed: {ex}]'))

    if (not user_msg and not attachments) or not entity_type or not entity_key:
        return jsonify({'error': 'message or attachment required, plus entity_type and entity_key'}), 400

    # Load entity
    if entity_type == 'team_member':
        entity = db.query(TeamMember).filter(TeamMember.role_key == entity_key).first()
        if not entity:
            return jsonify({'error': 'Team member not found'}), 404
        name = entity.display_name
        emoji = entity.emoji or ''
        provider = entity.llm_provider or 'claude'
        model = entity.llm_model or 'claude-sonnet-4-6'
        temp = entity.temperature or 0.7
        sys_prompt = _build_team_system_prompt(db, entity)
    elif entity_type == 'agent':
        entity = db.query(Agent).filter(Agent.id == int(entity_key)).first()
        if not entity:
            return jsonify({'error': 'Agent not found'}), 404
        name = entity.name
        emoji = ''
        provider = getattr(entity, 'llm_provider', None) or 'claude'
        model = getattr(entity, 'llm_model', None) or 'claude-sonnet-4-6'
        temp = 0.7
        sys_prompt = _build_agent_system_prompt(db, entity)
    else:
        return jsonify({'error': 'entity_type must be team_member or agent'}), 400

    # Use deterministic (permanent) thread_id per entity so memory persists across sessions
    canonical_thread = f"chat_{entity_type}_{entity_key}"
    if not thread_id:
        thread_id = canonical_thread
    # If caller passed a legacy UUID thread, honour it but also alias canonical

    # Save user message (include attachment names as note if present)
    saved_body = user_msg
    if attachments:
        names = [a.get('name', 'file') for a in attachments if a]
        saved_body = f"[📎 {', '.join(names)}]\n{user_msg}".strip()
    user_row = InternalMessage(
        from_type='user', from_key='supervisor', from_name='You', from_emoji='',
        body=saved_body, msg_type='chat', thread_id=thread_id, is_read=True
    )
    db.add(user_row)
    db.commit()

    # Build conversation history — last 40 msgs from this thread (persistent memory)
    history = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).order_by(InternalMessage.created_at.desc()).limit(40).all()
    history.reverse()

    # Count total messages ever exchanged
    total_msgs = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).count()

    conv_lines = []
    for h in history[:-1]:  # exclude the just-added user msg (sent as prompt below)
        role = 'User' if h.from_type == 'user' else name
        conv_lines.append(f"{role}: {h.body[:400]}")  # truncate very long msgs
    conv_context = '\n'.join(conv_lines)

    # Inject memory note into system prompt if prior conversation exists
    if total_msgs > 1:
        memory_note = (
            f"\n\n=== MEMORY ===\n"
            f"You have been in an ongoing conversation with the user. "
            f"Total exchanges so far: {total_msgs}. "
            f"The recent conversation history is included in this prompt — treat it as your memory. "
            f"NEVER say you don't remember previous conversations. "
            f"If something isn't in the provided history, acknowledge the gap naturally but stay in character."
        )
        sys_prompt = (sys_prompt or '') + memory_note

    # Inject extracted PDF text into the user turn so Marc can read it
    pdf_block = ''
    if pdf_texts:
        parts = [f"=== {nm} ===\n{txt}" for nm, txt in pdf_texts]
        pdf_block = "\n\n[Attached PDF content]\n" + "\n\n".join(parts) + "\n\n"
    effective_user_msg = (pdf_block + (user_msg or '')).strip()
    prompt = f"{conv_context}\nUser: {effective_user_msg}\n{name}:" if conv_context else (effective_user_msg or "")

    try:
        from src.api.llm_provider import LLMProvider
        llm = LLMProvider(provider=provider, model=model)
        # Larger budget when dispatching (cofounder tends to create multi-task plans)
        max_tok = 6000 if entity_key == 'cofounder' else 3000
        if images:
            reply = llm.generate_content_with_images(
                prompt=prompt,
                images=images,
                max_tokens=max_tok,
                temperature=temp,
                system_prompt=sys_prompt
            )
        else:
            reply = llm.generate_content(
                prompt=prompt,
                max_tokens=max_tok,
                temperature=temp,
                system_prompt=sys_prompt
            )

        # Extract tasks from reply (if AI created any)
        clean_reply, tasks_created = _extract_and_create_tasks(
            db, reply, thread_id, entity_type, entity_key, name
        )

        # Extract UI action buttons (if Marc proposed them)
        clean_reply, ui_actions = _extract_ui_actions(clean_reply)

        # Extract workflow launch (if AI triggered one)
        clean_reply, workflow_launched = _extract_and_launch_workflow(clean_reply)

        # Extract hire proposals (if AI proposed hiring)
        clean_reply, hires_proposed = _extract_hire_proposals(clean_reply)

        # Extract vision update (if cofounder updated vision)
        clean_reply, vision_updated = _extract_vision_update(clean_reply, db)

        # Save AI reply (cleaned of command JSON)
        ai_row = InternalMessage(
            from_type=entity_type, from_key=entity_key,
            from_name=name, from_emoji=emoji,
            body=clean_reply, msg_type='chat', thread_id=thread_id, is_read=False
        )
        db.add(ai_row)
        db.commit()

        return jsonify({
            'reply': clean_reply,
            'from_name': name,
            'from_emoji': emoji,
            'thread_id': thread_id,
            'message_id': ai_row.id,
            'tasks_created': tasks_created,
            'workflow_launched': workflow_launched,
            'hires_proposed': hires_proposed,
            'vision_proposed': vision_updated,
            'ui_actions': ui_actions,
        }), 200
    except Exception as e:
        return jsonify({'error': f'{name} is unavailable: {str(e)}'}), 500


@app.route('/api/inbox/thread_for_entity', methods=['GET'])
def get_thread_for_entity():
    """Return canonical thread_id and last N messages for a specific entity (for memory loading on page open)."""
    from flask import g
    from src.database.models import InternalMessage
    db = g.db
    entity_type = request.args.get('entity_type', '')
    entity_key  = request.args.get('entity_key', '')
    if not entity_type or not entity_key:
        return jsonify({'error': 'entity_type and entity_key required'}), 400

    canonical_thread = f"chat_{entity_type}_{entity_key}"
    msgs = db.query(InternalMessage).filter(
        InternalMessage.thread_id == canonical_thread
    ).order_by(InternalMessage.created_at.asc()).limit(60).all()

    return jsonify({
        'thread_id': canonical_thread,
        'messages': [{
            'id': m.id,
            'from_type': m.from_type,
            'from_name': m.from_name,
            'from_emoji': m.from_emoji or '',
            'body': m.body,
            'created_at': m.created_at.isoformat() if m.created_at else '',
        } for m in msgs]
    }), 200


@app.route('/api/inbox/send', methods=['POST'])
def inbox_send():
    """Create an internal email (used by workflow engine or manual)."""
    from flask import g
    from src.database.models import InternalMessage, TeamMember, Agent
    import uuid
    db = g.db
    data = request.json or {}

    from_type = data.get('from_type', 'team_member')
    from_key = data.get('from_key', '')
    subject = data.get('subject', '')
    body = data.get('body', '')
    thread_id = data.get('thread_id', '')

    if not body or not from_key:
        return jsonify({'error': 'from_key and body required'}), 400

    # Resolve name/emoji
    name, emoji = from_key, ''
    if from_type == 'team_member':
        m = db.query(TeamMember).filter(TeamMember.role_key == from_key).first()
        if m:
            name, emoji = m.display_name, m.emoji or ''
    elif from_type == 'agent':
        a = db.query(Agent).filter(Agent.id == int(from_key)).first()
        if a:
            name = a.name

    if not thread_id:
        thread_id = f"email_{from_key}_{uuid.uuid4().hex[:8]}"

    msg = InternalMessage(
        from_type=from_type, from_key=from_key,
        from_name=name, from_emoji=emoji,
        subject=subject, body=body,
        msg_type='email', thread_id=thread_id, is_read=False
    )
    db.add(msg)
    db.commit()
    return jsonify({'ok': True, 'thread_id': thread_id, 'id': msg.id}), 200


@app.route('/api/inbox/unread', methods=['GET'])
def inbox_unread():
    """Get unread message count for badge."""
    from flask import g
    from src.database.models import InternalMessage
    db = g.db
    total = db.query(InternalMessage).filter(
        InternalMessage.is_read == False,
        InternalMessage.from_type != 'user'
    ).count()
    return jsonify({'total_unread': total}), 200


# ═══════════════════════════════════════════════════════════════
# TASKS — Startup-style task management with hierarchy
# ═══════════════════════════════════════════════════════════════

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """List tasks with optional filters."""
    from flask import g
    from src.database.models import Task
    db = g.db
    q = db.query(Task)
    assignee = request.args.get('assignee')
    status = request.args.get('status')
    parent = request.args.get('parent_id')
    dept = request.args.get('dept')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    show_archived = request.args.get('archived')
    if assignee:
        q = q.filter(Task.assignee_key == assignee)
    if status:
        q = q.filter(Task.status == status)
    if dept:
        q = q.filter(Task.department == dept)
    if parent:
        q = q.filter(Task.parent_id == int(parent))
    elif not request.args.get('all'):
        q = q.filter(Task.parent_id == None)  # top-level only by default
    # Date range filtering — match tasks created OR completed within the range
    if date_from or date_to:
        from datetime import datetime as _dt, timedelta
        try:
            dt_from = _dt.fromisoformat(date_from) if date_from else None
        except (ValueError, TypeError):
            dt_from = None
        try:
            dt_to = (_dt.fromisoformat(date_to) + timedelta(days=1)) if date_to else None
        except (ValueError, TypeError):
            dt_to = None
        from sqlalchemy import or_
        # Match tasks where ANY timestamp falls in the range
        date_cols = [Task.created_at, Task.completed_at, Task.approved_at, Task.updated_at]
        date_conditions = []
        for col in date_cols:
            if dt_from and dt_to:
                date_conditions.append((col >= dt_from) & (col < dt_to))
            elif dt_from:
                date_conditions.append(col >= dt_from)
            elif dt_to:
                date_conditions.append(col < dt_to)
        if date_conditions:
            q = q.filter(or_(*date_conditions))
    # Exclude archived tasks by default; ?archived=1 shows them
    if not show_archived or show_archived != '1':
        q = q.filter((Task.archived == False) | (Task.archived == None))
    from sqlalchemy import func, case
    sort_col = case(
        (Task.completed_at != None, Task.completed_at),
        else_=Task.created_at,
    )
    tasks = q.order_by(sort_col.desc()).limit(500).all()

    def task_dict(t):
        subtasks = db.query(Task).filter(Task.parent_id == t.id).all()
        running_sub = next((s for s in subtasks if s.status == 'in_progress'), None)
        return {
            'id': t.id, 'title': t.title, 'description': t.description,
            'status': t.status, 'priority': t.priority,
            'department': getattr(t, 'department', None) or _dept_from_assignee(t.assignee_key),
            'requires_approval': bool(getattr(t, 'requires_approval', False)),
            'approved_at': t.approved_at.isoformat() if getattr(t, 'approved_at', None) else None,
            'created_by_type': t.created_by_type, 'created_by_key': t.created_by_key,
            'created_by_name': t.created_by_name,
            'assignee_type': t.assignee_type, 'assignee_key': t.assignee_key,
            'assignee_name': t.assignee_name,
            'parent_id': t.parent_id,
            'due_date': t.due_date.isoformat() if t.due_date else None,
            'completed_at': t.completed_at.isoformat() if t.completed_at else None,
            'thread_id': t.thread_id,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'updated_at': t.updated_at.isoformat() if getattr(t, 'updated_at', None) else None,
            'archived': bool(getattr(t, 'archived', False)),
            'subtask_count': len(subtasks),
            'subtasks_done': sum(1 for s in subtasks if s.status == 'done'),
            'subtasks_running': sum(1 for s in subtasks if s.status == 'in_progress'),
            'subtasks_blocked': sum(1 for s in subtasks if s.status == 'blocked'),
            'running_subtask': (running_sub.assignee_name or running_sub.title[:40]) if running_sub else None,
            'running_subtask_title': (running_sub.title[:60]) if running_sub else None,
        }
    return jsonify({'tasks': [task_dict(t) for t in tasks]}), 200


@app.route('/api/tasks/<int:task_id>/archive', methods=['POST'])
def archive_task(task_id):
    """Archive a single task by setting archived=True."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    task.archived = True
    db.commit()
    return jsonify({'ok': True, 'task_id': task_id}), 200


@app.route('/api/tasks/archive_batch', methods=['POST'])
def archive_tasks_batch():
    """Archive multiple tasks by status. Body: {"status": "done"} or {"status": "blocked"}."""
    from flask import g
    from src.database.models import Task
    db = g.db
    data = request.get_json(force=True) or {}
    target_status = data.get('status')
    if not target_status:
        return jsonify({'error': 'Missing "status" field (e.g. "done", "blocked")'}), 400
    tasks = db.query(Task).filter(
        Task.status == target_status,
        (Task.archived == False) | (Task.archived == None),
    ).all()
    count = len(tasks)
    for t in tasks:
        t.archived = True
    db.commit()
    return jsonify({'ok': True, 'archived_count': count, 'status': target_status}), 200


@app.route('/api/task-result/<int:task_id>', methods=['GET'])
def get_task_result(task_id):
    """Get a task's deliverable — the email/message produced when it was executed."""
    logging.info(f"[TaskResult] Hit /api/task-result/{task_id}")
    from flask import g
    from src.database.models import Task, InternalMessage
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    # Find deliverable email in assignee's thread
    thread_id = f"chat_{task.assignee_type}_{task.assignee_key}"
    deliverable = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id,
        InternalMessage.subject.like(f'%{task.title[:40]}%'),
        InternalMessage.msg_type == 'email',
    ).order_by(InternalMessage.created_at.desc()).first()

    # If no exact match, get the most recent email from this assignee around task completion time
    if not deliverable and task.completed_at:
        from datetime import timedelta
        window_start = task.completed_at - timedelta(minutes=5)
        deliverable = db.query(InternalMessage).filter(
            InternalMessage.thread_id == thread_id,
            InternalMessage.from_key == task.assignee_key,
            InternalMessage.msg_type == 'email',
            InternalMessage.created_at >= window_start,
            InternalMessage.created_at <= task.completed_at + timedelta(minutes=2),
        ).order_by(InternalMessage.created_at.desc()).first()

    # Also find any chat messages from execution
    if not deliverable:
        deliverable = db.query(InternalMessage).filter(
            InternalMessage.thread_id == thread_id,
            InternalMessage.from_key == task.assignee_key,
        ).order_by(InternalMessage.created_at.desc()).first()

    # Get subtask results too — prefer task.deliverable column, fall back to InternalMessage
    subtasks = db.query(Task).filter(Task.parent_id == task_id).all()
    sub_results = []
    for st in subtasks:
        st_deliverable = getattr(st, 'deliverable', None) or ''
        st_subject = None
        if not st_deliverable:
            # Fall back to InternalMessage lookup
            st_thread = f"chat_{st.assignee_type}_{st.assignee_key}"
            st_msg = db.query(InternalMessage).filter(
                InternalMessage.thread_id == st_thread,
                InternalMessage.from_key == st.assignee_key,
                InternalMessage.msg_type == 'email',
                InternalMessage.subject.ilike(f'%{st.title[:30]}%'),
            ).order_by(InternalMessage.created_at.desc()).first()
            if not st_msg:
                # Broader fallback — any recent email from this assignee
                st_msg = db.query(InternalMessage).filter(
                    InternalMessage.thread_id == st_thread,
                    InternalMessage.from_key == st.assignee_key,
                    InternalMessage.msg_type == 'email',
                ).order_by(InternalMessage.created_at.desc()).first()
            if st_msg:
                st_deliverable = st_msg.body[:3000]
                st_subject = st_msg.subject
        sub_results.append({
            'id': st.id, 'title': st.title, 'status': st.status,
            'assignee_name': st.assignee_name, 'assignee_key': st.assignee_key,
            'department': getattr(st, 'department', None) or _dept_from_assignee(st.assignee_key),
            'deliverable': st_deliverable[:3000] if st_deliverable else None,
            'deliverable_subject': st_subject,
        })

    # Extract image URLs from deliverable body (pattern: /static/media/...)
    images = []
    if deliverable and deliverable.body:
        import re
        img_urls = re.findall(r'(/static/media/[^\s\n"\']+\.(?:jpg|png|jpeg|webp))', deliverable.body)
        for url in img_urls:
            images.append({'url': url, 'prompt': ''})

    # Also check for images in static/media linked to this task
    if not images:
        media_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'media')
        if os.path.isdir(media_dir):
            import glob
            task_imgs = glob.glob(os.path.join(media_dir, f'task_*.jpg'))
            # Recent images (last 5 minutes around task completion)
            if task.completed_at:
                import time
                for fp in sorted(task_imgs, key=os.path.getmtime, reverse=True)[:5]:
                    mtime = os.path.getmtime(fp)
                    task_ts = task.completed_at.timestamp()
                    if abs(mtime - task_ts) < 300:  # within 5 min
                        fname = os.path.basename(fp)
                        images.append({'url': f'/static/media/{fname}', 'prompt': ''})

    # Compute timing info for in-progress / blocked tasks
    timing = {}
    if task.approved_at:
        timing['approved_at'] = task.approved_at.isoformat()
    if task.created_at:
        timing['created_at'] = task.created_at.isoformat()
        from datetime import datetime as _dt
        elapsed = (_dt.utcnow() - task.created_at).total_seconds()
        timing['elapsed_seconds'] = int(elapsed)
        if elapsed > 3600:
            timing['elapsed_label'] = f'{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m'
        elif elapsed > 60:
            timing['elapsed_label'] = f'{int(elapsed // 60)}m {int(elapsed % 60)}s'
        else:
            timing['elapsed_label'] = f'{int(elapsed)}s'
    if task.approved_at and task.status == 'in_progress':
        run_elapsed = (_dt.utcnow() - task.approved_at).total_seconds()
        timing['running_seconds'] = int(run_elapsed)
        if run_elapsed > 600:
            timing['status_hint'] = 'possibly_stuck'
        elif run_elapsed > 120:
            timing['status_hint'] = 'running_long'
        else:
            timing['status_hint'] = 'running'
    if task.status == 'blocked':
        # Check for error in description
        import re
        err = re.search(r'\[(?:ERROR|EXECUTION ERROR):?\s*(.*?)\]', task.description or '')
        timing['error'] = err.group(1) if err else None

    # Find published posts linked to this task (by agent ID in description/title)
    published_posts = []
    try:
        import re as _re
        from src.database.models import Content
        # Extract agent ID from task description or title
        aid_match = _re.search(r'Agent\s*(?:ID\s*)?(\d+)', (task.description or '') + ' ' + (task.title or ''), _re.IGNORECASE)
        if aid_match:
            _aid = int(aid_match.group(1))
            recent_pub = db.query(Content).filter(
                Content.agent_id == _aid,
                Content.status == 'published',
                Content.post_id.isnot(None),
            ).order_by(Content.published_at.desc()).limit(3).all()
            for rp in recent_pub:
                plat = (rp.platform or '').lower().replace('/', '').replace(' ', '')
                url = None
                if ('twitter' in plat or plat == 'x') and rp.post_id:
                    url = f'https://x.com/i/status/{rp.post_id}'
                elif 'instagram' in plat and rp.post_id:
                    url = f'https://www.instagram.com/p/{rp.post_id}/'
                published_posts.append({
                    'id': rp.id, 'platform': rp.platform, 'post_id': rp.post_id,
                    'url': url, 'published_at': rp.published_at.isoformat() if rp.published_at else None,
                    'title': (rp.title or '')[:80],
                })
    except Exception:
        pass

    return jsonify({
        'task': {
            'id': task.id, 'title': task.title, 'description': task.description,
            'status': task.status, 'priority': task.priority,
            'assignee_name': task.assignee_name, 'assignee_key': task.assignee_key,
            'assignee_type': task.assignee_type,
            'department': getattr(task, 'department', None) or _dept_from_assignee(task.assignee_key),
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        },
        'timing': timing,
        'deliverable': deliverable.body[:3000] if deliverable else None,
        'deliverable_subject': deliverable.subject if deliverable else None,
        'images': images,
        'subtasks': sub_results,
        'published_posts': published_posts,
        'inbox_link': f'/inbox?entity_type={task.assignee_type}&entity_key={task.assignee_key}',
    }), 200


@app.route('/api/tasks/pending_approval', methods=['GET'])
def get_pending_approval_tasks():
    """Get tasks proposed by cofounder — pending and rejected (for later reconsideration)."""
    from flask import g
    from src.database.models import Task
    db = g.db
    q = db.query(Task).filter(
        Task.requires_approval == True,
        Task.approved_at == None,
        (Task.archived == False) | (Task.archived == None),
    )
    dept = request.args.get('dept')
    if dept:
        q = q.filter(Task.department == dept)
    tasks = q.order_by(Task.created_at.desc()).all()

    def td(t):
        return {
            'id': t.id, 'title': t.title, 'description': t.description,
            'priority': t.priority, 'assignee_name': t.assignee_name,
            'assignee_key': t.assignee_key, 'status': t.status,
            'department': getattr(t, 'department', None) or _dept_from_assignee(t.assignee_key),
            'due_date': t.due_date.isoformat() if t.due_date else None,
            'created_at': t.created_at.isoformat() if t.created_at else None,
        }
    return jsonify({'tasks': [td(t) for t in tasks]}), 200


@app.route('/api/tasks/<int:task_id>/approve', methods=['POST'])
def approve_task(task_id):
    """Approve a cofounder-proposed task — activates it and dispatches background execution."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    task.approved_at = datetime.utcnow()
    task.status = 'in_progress'
    db.commit()

    # Dispatch background execution
    _task_snapshot = {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'assignee_type': task.assignee_type,
        'assignee_key': task.assignee_key,
        'assignee_name': task.assignee_name,
        'priority': task.priority,
    }
    thread = threading.Thread(
        target=_execute_task_in_background,
        args=(_task_snapshot,),
        name=f'task-exec-{task.id}',
        daemon=True,
    )
    thread.start()

    return jsonify({'ok': True, 'id': task.id, 'status': 'in_progress'}), 200


def _is_department_head(db, role_key):
    """Check if a team member has direct reports (is a manager/department head)."""
    from src.database.models import TeamMember
    reports = db.query(TeamMember).filter(TeamMember.reports_to == role_key, TeamMember.is_active == True).all()
    return reports  # returns list of direct reports (empty = not a head)


def _execute_task_in_background(task_snapshot):
    """
    Background worker: routes task execution through the org hierarchy.
    - If assignee is a department HEAD → cascade: head decomposes, sub-tasks dispatched to team, summary produced
    - If assignee is an individual contributor → direct execution
    """
    import time
    task_id = task_snapshot['id']
    assignee_type = task_snapshot['assignee_type']
    assignee_key = task_snapshot['assignee_key']
    assignee_name = task_snapshot['assignee_name']
    title = task_snapshot['title']
    description = task_snapshot['description'] or title
    priority = task_snapshot['priority'] or 'medium'

    logging.info(f"[TaskExec] Starting task #{task_id} — '{title}' → {assignee_name}")

    from src.database.db import get_db
    db = get_db()

    try:
        from src.database.models import Task, TeamMember, Agent, InternalMessage, Notification
        from src.api.llm_provider import LLMProvider

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logging.error(f"[TaskExec] Task #{task_id} not found in DB")
            return

        # Cancellation guard — if the task has been archived after being queued, abort before spending LLM tokens.
        if getattr(task, 'archived', False):
            logging.info(f"[TaskExec] Task #{task_id} archived — skipping to avoid token burn")
            task.status = 'blocked'
            db.commit()
            return

        # Resolve entity
        if assignee_type == 'team_member':
            entity = db.query(TeamMember).filter(TeamMember.role_key == assignee_key).first()
            if not entity:
                task.status = 'blocked'
                task.description = (task.description or '') + f'\n[ERROR: Team member "{assignee_key}" not found]'
                db.commit()
                return

            # Check if this person is a department head (has direct reports)
            direct_reports = _is_department_head(db, assignee_key)
            if direct_reports:
                logging.info(f"[TaskExec] {assignee_name} is a department head with {len(direct_reports)} reports — cascading")
                _execute_cascade_task(db, task, entity, direct_reports)
                return

            # Individual contributor — direct execution
            name = entity.display_name
            emoji = entity.emoji or ''
            provider = entity.llm_provider or 'claude'
            model = entity.llm_model or 'claude-sonnet-4-6'
            temp = entity.temperature or 0.7
            sys_prompt = _build_team_system_prompt(db, entity)
        elif assignee_type == 'agent':
            entity = db.query(Agent).filter(Agent.id == int(assignee_key)).first()
            if not entity:
                task.status = 'blocked'
                db.commit()
                return
            name = entity.name
            emoji = ''
            provider = getattr(entity, 'llm_provider', None) or 'claude'
            model = getattr(entity, 'llm_model', None) or 'claude-sonnet-4-6'
            temp = 0.7
            sys_prompt = _build_agent_system_prompt(db, entity)
        else:
            task.status = 'blocked'
            db.commit()
            return

        # ── Direct execution for individual contributors ──
        _execute_individual_task(db, task, entity, assignee_type, assignee_key)

    except Exception as e:
        logging.error(f"[TaskExec] ❌ Task #{task_id} failed: {e}", exc_info=True)
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = 'blocked'
                task.description = (task.description or '') + f'\n[EXECUTION ERROR: {str(e)[:200]}]'
                from src.database.models import Notification
                db.add(Notification(
                    type='task_failed',
                    title=f'❌ Task failed: {title[:60]}',
                    body=f'{assignee_name} could not complete: {str(e)[:200]}',
                    link=f'/inbox?entity_type={assignee_type}&entity_key={assignee_key}',
                ))
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


_IMAGE_ROLES = {'prompt_engineer_1', 'prompt_engineer_2'}
_IMAGE_KEYWORDS = ['profile picture', 'profile pic', 'portrait photo', 'headshot',
                   'generate.*image', 'generate.*picture', 'generate.*photo',
                   'create.*image', 'create.*portrait', 'ai.*profile',
                   'produce.*image', 'design.*profile.*pic']

def _is_image_task(assignee_key, title, description):
    """Detect if a task should trigger actual image generation."""
    import re
    if assignee_key in _IMAGE_ROLES:
        text = (title + ' ' + (description or '')).lower()
        for kw in _IMAGE_KEYWORDS:
            if re.search(kw, text):
                return True
    return False


def _is_carousel_task(title, description):
    """Detect Instagram carousel / multi-slide visual tasks (any assignee)."""
    text = (title + ' ' + (description or '')).lower()
    if 'carousel' in text:
        return True
    if 'instagram' in text and any(k in text for k in ['slide', 'visual', 'image', 'post']):
        return True
    return False


def _extract_slide_texts(deliverable: str, max_slides: int = 8) -> list[str]:
    """Parse slide text from a carousel deliverable. Returns list of short on-image texts.

    Strips production directions (`[Visual: ...]`, `[Texte sur image, fond rouge sang]`,
    `(7 mots. Curiosity gap)`), blockquote markers, markdown headings, and bold syntax
    so ONLY the actual on-image copy ends up in the image.
    """
    import re
    if not deliverable:
        return []

    # Keywords that mark a bracketed/parenthesized block as a production direction
    # (not actual copy) — matches FR + EN terms the LLM uses for art direction.
    DIRECTION_KW = (
        r'(?:visual|visuel|texte\s+sur\s+image|fond|typo|font|image|photo|'
        r'background|police|couleur|color|style|subtext|design|'
        r'layout|overlay|caption|mots?|curiosity\s*gap|hook|call[-\s]*to[-\s]*action|cta|'
        r'ic[oô]ne?|icon|emoji|embl[eè]me|pictogramme|illustration|graphique|graphic|'
        r'animation|transition|split[-\s]*screen|tableau)'
    )

    slides = []
    pat = re.compile(
        r'(?:^|\n)\s*(?:#{1,4}\s*)?\*{0,2}\s*SLIDE\s*(\d+)[^\n]*\*{0,2}\s*\n+(.+?)'
        r'(?=\n\s*(?:#{1,4}\s*)?\*{0,2}\s*SLIDE\s*\d+|\n---|\n\s*\*{0,2}(?:CAPTION|HASHTAG|CTA|NOTES)|\Z)',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pat.finditer(deliverable):
        block = m.group(2).strip()

        # 1. Strip bracketed direction blocks: [Visual: ...], [Texte sur image, fond…], etc.
        block = re.sub(rf'\[[^\[\]]*{DIRECTION_KW}[^\[\]]*\]', '', block, flags=re.IGNORECASE)
        # 2. Strip parenthetical meta-notes: (7 mots), (visual cue), (curiosity gap maximal)
        block = re.sub(rf'\([^()]*{DIRECTION_KW}[^()]*\)', '', block, flags=re.IGNORECASE)
        # 3. Strip remaining empty square brackets or parens leftover
        block = re.sub(r'\[\s*\]|\(\s*\)', '', block)
        # 4. Strip bold/italic syntax
        block = re.sub(r'\*{1,3}', '', block)
        block = re.sub(r'_{2,}', '', block)
        # 5. Strip markdown headings at line starts
        block = re.sub(r'^#{1,6}\s*', '', block, flags=re.MULTILINE)
        # 6. Strip leading blockquote/list/arrow markers
        lines = [ln.strip('>-•*#►▸▶→➜✓✗❌✅❓⚠\t ') for ln in block.split('\n') if ln.strip()]
        # 7. Drop lines that are pure art direction even after cleaning
        lines = [ln for ln in lines if not re.match(rf'^\s*{DIRECTION_KW}\s*[:\-]', ln, re.IGNORECASE)]
        # 7b. Strip label prefixes that label the copy rather than being the copy
        #     ("Titre :", "Title:", "Headline:", "Texte :", "Hook:", etc.)
        LABEL_PREFIX = re.compile(
            r'^\s*(?:titre|title|headline|texte|text|hook|accroche|slide\s*\d*|slogan|message)\s*[:\-–—]\s*',
            re.IGNORECASE,
        )
        lines = [LABEL_PREFIX.sub('', ln).strip() for ln in lines]
        lines = [ln for ln in lines if ln]

        # 8. Strip code fences / backticks — they're not on-image copy
        block_nocode = re.sub(r'```[\s\S]*?```', '', block)
        block_nocode = re.sub(r'`[^`\n]*`', '', block_nocode)
        lines_nocode = [ln.strip('>-•*#`►▸▶→➜✓✗❌✅❓⚠\t ') for ln in block_nocode.split('\n') if ln.strip()]
        lines_nocode = [ln for ln in lines_nocode
                        if not re.match(rf'^\s*{DIRECTION_KW}\s*[:\-]', ln, re.IGNORECASE)]
        lines_nocode = [LABEL_PREFIX.sub('', ln).strip() for ln in lines_nocode]
        lines_nocode = [ln for ln in lines_nocode if ln]

        # Prefer quoted copy if it's substantial (>=20 chars) — usually the headline.
        # Ignore short quoted examples like "coup de cœur" that are inside explanatory text.
        quoted = re.findall(r'[""«"]([^""«""\n]{20,120})["""»"]', block_nocode)
        if quoted:
            text = quoted[0].strip()
        else:
            # Prefer the FIRST substantive line (>= 15 chars) — avoids trailing examples.
            first_line = next((ln for ln in lines_nocode if len(ln) >= 15), '')
            text = first_line or ' '.join(lines_nocode).strip()

        # Normalise whitespace, strip leading quotes that survived
        text = re.sub(r'\s+', ' ', text).strip(' "«»""''')

        # Hard cap — Gemini image generation loses legibility past ~80 chars
        if len(text) > 80:
            text = text[:80]
            if ' ' in text:
                text = text.rsplit(' ', 1)[0]
            text = text.rstrip(',;:—–-')

        if text and len(text) > 10:
            slides.append(text)
        if len(slides) >= max_slides:
            break
    return slides


def _strip_emoji(text: str) -> str:
    """Remove emoji / pictographs — PIL's default fonts don't render them correctly,
    and Gemini-generated text with emoji tends to produce misspellings."""
    import re
    if not text:
        return ''
    # Broad emoji / symbol ranges
    pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E0-\U0001F1FF"
        "]+",
        flags=re.UNICODE,
    )
    return re.sub(r'\s+', ' ', pattern.sub('', text)).strip()


def _render_slide_text_on_image(bg_path: str, slide_text: str, slide_num: int, total: int) -> None:
    """Overlay slide_text on the image at bg_path using PIL (in-place save).
    Guarantees clean, perfectly-spelled typography regardless of the underlying image.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import os, textwrap

    FONT_BOLD = 'C:/Windows/Fonts/seguibl.ttf'   # Segoe UI Black
    FONT_REG = 'C:/Windows/Fonts/seguisb.ttf'    # Segoe UI Semibold
    if not os.path.exists(FONT_BOLD):
        FONT_BOLD = 'C:/Windows/Fonts/arialbd.ttf'
    if not os.path.exists(FONT_REG):
        FONT_REG = 'C:/Windows/Fonts/arial.ttf'

    text = _strip_emoji(slide_text).strip(' "«»""''')
    if not text:
        return

    img = Image.open(bg_path).convert('RGB')
    # Auto-crop solid-color matte/frame borders that Gemini sometimes adds
    def _autocrop_border(im):
        w, h = im.size
        px = im.load()
        corner = px[5, 5]
        def near(c): return all(abs(c[k] - corner[k]) < 12 for k in range(3))
        # Only treat as border if all 4 corners match
        if not (near(px[w - 6, 5]) and near(px[5, h - 6]) and near(px[w - 6, h - 6])):
            return im
        # Scan from top for first non-border row
        def scan_row(y):
            return all(near(px[x, y]) for x in range(0, w, max(1, w // 40)))
        def scan_col(x):
            return all(near(px[x, y]) for y in range(0, h, max(1, h // 40)))
        top = 0
        while top < h // 2 and scan_row(top): top += 1
        bot = h - 1
        while bot > h // 2 and scan_row(bot): bot -= 1
        left = 0
        while left < w // 2 and scan_col(left): left += 1
        right = w - 1
        while right > w // 2 and scan_col(right): right -= 1
        if right - left > w * 0.4 and bot - top > h * 0.4:
            return im.crop((left, top, right + 1, bot + 1))
        return im

    img = _autocrop_border(img)
    # Force square 1080x1080 for Instagram — fill the full frame
    target = 1080
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((target, target), Image.LANCZOS)

    # Darken bottom 60% with a gradient for legibility
    overlay = Image.new('RGBA', (target, target), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Gradient: transparent top -> dark bottom
    for y in range(target):
        if y < target * 0.35:
            a = 0
        else:
            frac = (y - target * 0.35) / (target * 0.65)
            a = int(180 * frac)  # max 180/255 darkness
        odraw.line([(0, y), (target, y)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    draw = ImageDraw.Draw(img)

    # Wrap text — pick font size + wrap width to fit nicely
    MARGIN = 80
    MAX_W = target - 2 * MARGIN

    def build_layout(font_size):
        font = ImageFont.truetype(FONT_BOLD, font_size)
        # Estimate chars per line from font size
        avg_char_w = font.getlength('Ma') / 2
        chars_per_line = max(10, int(MAX_W / max(avg_char_w, 1)))
        wrapped = textwrap.wrap(text, width=chars_per_line, break_long_words=False)
        # Measure real width, reduce chars if any line overflows
        while wrapped and max(font.getlength(ln) for ln in wrapped) > MAX_W and chars_per_line > 6:
            chars_per_line -= 1
            wrapped = textwrap.wrap(text, width=chars_per_line, break_long_words=False)
        line_h = font_size * 1.15
        total_h = line_h * len(wrapped)
        return font, wrapped, line_h, total_h

    font_size = 96
    font, wrapped, line_h, total_h = build_layout(font_size)
    while (total_h > target * 0.55 or len(wrapped) > 6) and font_size > 40:
        font_size -= 6
        font, wrapped, line_h, total_h = build_layout(font_size)

    # Position text block in the lower-middle
    y_start = int(target * 0.95 - total_h)
    for idx, line in enumerate(wrapped):
        line_w = font.getlength(line)
        x = (target - line_w) / 2
        y = y_start + idx * line_h
        # Soft shadow for extra contrast
        for dx, dy in [(-2, 2), (2, 2), (0, 3)]:
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Slide counter pill (top-right)
    counter = f"{slide_num}/{total}"
    cfont = ImageFont.truetype(FONT_BOLD, 34)
    cw = cfont.getlength(counter)
    pad_x, pad_y = 22, 12
    pill_w = cw + 2 * pad_x
    pill_h = 34 + 2 * pad_y
    pill_x = target - MARGIN - pill_w
    pill_y = MARGIN
    draw.rounded_rectangle(
        [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
        radius=pill_h // 2, fill=(0, 0, 0, 220),
    )
    draw.text((pill_x + pad_x, pill_y + pad_y - 4), counter, font=cfont, fill=(255, 255, 255))

    img.save(bg_path, 'JPEG', quality=92, optimize=True)


def _generate_carousel_images(title: str, description: str, deliverable: str, brand_hint: str = '') -> list[dict]:
    """Generate a backdrop image per slide with Gemini, then overlay slide text with PIL.
    Text rendering via PIL guarantees correct spelling (Gemini text-in-image is unreliable)."""
    import os, uuid, base64
    results = []
    try:
        from src.api.image_generator import GeminiImageGenerator
        gen = GeminiImageGenerator()

        slide_texts = _extract_slide_texts(deliverable)
        if not slide_texts:
            desc = (description or title)[:200]
            slide_texts = [f'Hook: {desc[:60]}', desc[60:140] or desc, 'Swipe']
        slide_texts = slide_texts[:6]

        media_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'media')
        os.makedirs(media_dir, exist_ok=True)

        theme = (description or title)[:200]
        total = len(slide_texts)
        for i, slide_text in enumerate(slide_texts):
            # Backdrop-only prompt — NO text rendering by the model
            mood_hint = _strip_emoji(slide_text)[:80]
            prompt = (
                f"Instagram carousel slide backdrop (square 1:1). Premium editorial photography "
                f"or cinematic graphic background. Theme: {theme}. {brand_hint} "
                f"Mood cue for composition: '{mood_hint}'. "
                f"Color grading: rich, high-contrast, moody. Leave the lower half of the image "
                f"visually calmer (less detail, darker or uniform tone) so text can overlay cleanly. "
                f"STRICT: NO text, NO words, NO letters, NO numbers, NO typography, NO captions, "
                f"NO watermarks, NO logos, NO UI elements. Full-bleed edge-to-edge image — "
                f"NO borders, NO frames, NO matte, NO white/gray margins around the photo. "
                f"The image must fill the ENTIRE square canvas corner to corner."
            )
            logging.info(f"[CarouselGen] Slide {i+1}/{total}: {slide_text[:60]}")
            b64_img = gen.generate_image(prompt)
            if b64_img:
                fname = f"carousel_{uuid.uuid4().hex[:12]}.jpg"
                fpath = os.path.join(media_dir, fname)
                with open(fpath, 'wb') as f:
                    f.write(base64.b64decode(b64_img))
                try:
                    _render_slide_text_on_image(fpath, slide_text, i + 1, total)
                except Exception as e:
                    logging.error(f"[CarouselGen] Text overlay failed for slide {i+1}: {e}", exc_info=True)
                results.append({'url': f"/static/media/{fname}", 'prompt': slide_text[:100]})
                logging.info(f"[CarouselGen] Slide {i+1} saved with overlay: {fpath}")
            else:
                logging.warning(f"[CarouselGen] Slide {i+1} backdrop generation failed")
    except Exception as e:
        logging.error(f"[CarouselGen] Carousel generation failed: {e}", exc_info=True)
    return results

def _generate_task_images(title, description, reply_text):
    """Generate actual images for a task. Returns list of {url, prompt} dicts."""
    import re, uuid, base64
    results = []
    try:
        from src.api.image_generator import GeminiImageGenerator
        gen = GeminiImageGenerator()

        # Extract image prompts from the LLM reply (prompt engineers write prompts)
        prompts = []
        # Look for explicit prompt blocks
        prompt_patterns = [
            r'```(?:prompt|image)[^\n]*\n(.*?)```',
            r'(?:PROMPT|Prompt|Image prompt|Generation prompt)[:\s]*["\']?([^"\'\n]{30,})["\']?',
            r'(?:--ar|style:|Generate:)[^\n]*([^\n]{30,})',
        ]
        for pat in prompt_patterns:
            matches = re.findall(pat, reply_text, re.DOTALL | re.IGNORECASE)
            for m in matches:
                cleaned = m.strip()[:500]
                if len(cleaned) > 20:
                    prompts.append(cleaned)

        # If no explicit prompts found, build one from the task context
        if not prompts:
            desc_text = (description or title)[:300]
            prompts = [
                f"Professional portrait photograph, ultra realistic, studio lighting, "
                f"high quality headshot for social media profile. Context: {desc_text}. "
                f"Photorealistic, no text, no watermarks, no logos, square format, "
                f"warm natural lighting, shallow depth of field, magazine quality."
            ]

        # Generate images (max 2 to avoid rate limits)
        media_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'media')
        os.makedirs(media_dir, exist_ok=True)

        for prompt in prompts[:2]:
            logging.info(f"[ImageGen] Generating image for task: {title[:50]}")
            b64_img = gen.generate_image(prompt)
            if b64_img:
                # Save to disk
                fname = f"task_{uuid.uuid4().hex[:12]}.jpg"
                fpath = os.path.join(media_dir, fname)
                with open(fpath, 'wb') as f:
                    f.write(base64.b64decode(b64_img))
                local_url = f"/static/media/{fname}"
                results.append({'url': local_url, 'prompt': prompt[:100], 'base64': b64_img[:100] + '...'})
                logging.info(f"[ImageGen] ✅ Saved: {fpath} ({os.path.getsize(fpath)//1024}KB)")
            else:
                logging.warning(f"[ImageGen] ❌ Failed to generate image for: {prompt[:60]}")

    except Exception as e:
        logging.error(f"[ImageGen] Image generation failed: {e}", exc_info=True)

    return results


def _execute_individual_task(db, task, entity, assignee_type, assignee_key):
    """Execute a single task by an individual contributor (not a head). Produces deliverable in inbox."""
    from src.database.models import InternalMessage, Notification
    from src.api.llm_provider import LLMProvider

    title = task.title
    description = task.description or title
    priority = task.priority or 'medium'

    if assignee_type == 'team_member':
        name = entity.display_name
        emoji = entity.emoji or ''
        provider = entity.llm_provider or 'claude'
        model = entity.llm_model or 'claude-sonnet-4-6'
        temp = entity.temperature or 0.7
        sys_prompt = _build_team_system_prompt(db, entity)
    else:
        name = entity.name
        emoji = ''
        provider = getattr(entity, 'llm_provider', None) or 'claude'
        model = getattr(entity, 'llm_model', None) or 'claude-sonnet-4-6'
        temp = 0.7
        sys_prompt = _build_agent_system_prompt(db, entity)

    # Check if this is an image generation task
    is_image = _is_image_task(assignee_key, title, description)

    if is_image:
        exec_prompt = (
            f"=== IMAGE GENERATION TASK ===\n"
            f"Title: {title}\n"
            f"Priority: {priority.upper()}\n"
            f"Description:\n{description}\n\n"
            f"You are generating an AI image for this task. Write:\n"
            f"1. A detailed IMAGE GENERATION PROMPT (start with 'PROMPT:') — ultra specific, "
            f"describing the exact scene, lighting, style, composition, colors, mood. "
            f"This prompt will be fed directly to an AI image generator.\n"
            f"2. A brief creative rationale (2-3 sentences) explaining your artistic choices.\n"
            f"3. Technical specs: aspect ratio, resolution recommendation, format.\n\n"
            f"IMPORTANT: The PROMPT line must be a single detailed paragraph that an AI image "
            f"model can use directly. Be specific about: subject, pose, expression, background, "
            f"lighting, color palette, camera angle, style (photorealistic/illustration/etc)."
        )
    else:
        exec_prompt = (
            f"=== TASK ASSIGNED TO YOU ===\n"
            f"Title: {title}\n"
            f"Priority: {priority.upper()}\n"
            f"Description:\n{description}\n\n"
            f"Execute this task now. Produce the deliverable in full — not a plan, not a summary, "
            f"but the ACTUAL WORK PRODUCT. If it's research, deliver the research. "
            f"If it's a brief, write the full brief. If it's an audit, do the audit. "
            f"Be thorough, specific, and actionable. Use data where possible.\n\n"
            f"OUTPUT FORMAT — CRITICAL:\n"
            f"Respond in clean MARKDOWN PROSE written for a human reader (headings, bullets, short paragraphs).\n"
            f"DO NOT return raw JSON objects, JSON arrays, or {{\"key\": value}} blobs — even if your role's "
            f"default instructions mention JSON. JSON in this context is legacy and renders unreadably in the inbox.\n"
            f"If you need to convey structured data, use markdown tables or labeled bullets instead.\n\n"
            f"After the deliverable, add a one-line STATUS: at the end indicating completion."
        )

    canonical_thread = f"chat_{assignee_type}_{assignee_key}"

    llm = LLMProvider(provider=provider, model=model)
    reply = llm.generate_content(
        prompt=exec_prompt, max_tokens=4000, temperature=temp, system_prompt=sys_prompt,
    )

    # ── IMAGE GENERATION: actually produce images if this is a visual task ──
    generated_images = []
    if is_image:
        logging.info(f"[TaskExec] 🎨 Image task detected — generating images for: {title[:50]}")
        generated_images = _generate_task_images(title, description, reply)
    elif _is_carousel_task(title, description):
        logging.info(f"[TaskExec] 🎠 Carousel task detected — generating slide images for: {title[:50]}")
        brand_hint = f"Agent persona: {name}." if assignee_type == 'agent' else ''
        generated_images = _generate_carousel_images(title, description, reply, brand_hint=brand_hint)

    if generated_images:
        img_section = "\n\n---\n🖼️ **GENERATED IMAGES:**\n"
        for i, img in enumerate(generated_images):
            img_section += f"\n**Image {i+1}:** {img['url']}\n"
        reply += img_section
        logging.info(f"[TaskExec] 🎨 Generated {len(generated_images)} images for task #{task.id}")

    # Save deliverable as an email (not chat blabber) — clean, professional
    subject = f'✅ Deliverable: {title[:80]}'
    if generated_images:
        subject = f'🖼️ Images + Deliverable: {title[:70]}'

    ai_msg = InternalMessage(
        from_type=assignee_type, from_key=assignee_key,
        from_name=name, from_emoji=emoji,
        subject=subject,
        body=reply, msg_type='email',
        thread_id=canonical_thread, is_read=False,
    )
    db.add(ai_msg)

    # Mark task as done — also store deliverable on the task row for quick access
    task.status = 'done'
    task.completed_at = datetime.utcnow()
    task.deliverable = reply[:5000] if reply else None

    # ── Auto-create Content draft if task produces platform content ──
    _maybe_create_content_from_task(db, task, reply, generated_images)

    notif_body = f'{reply[:150]}...' if len(reply) > 150 else reply
    if generated_images:
        notif_body = f'🖼️ {len(generated_images)} image(s) generated. {notif_body}'

    db.add(Notification(
        type='task_completed',
        title=f'✅ {name} completed: {title[:60]}',
        body=notif_body,
        link=f'/inbox?entity_type={assignee_type}&entity_key={assignee_key}',
    ))
    db.commit()
    logging.info(f"[TaskExec] ✅ Task #{task.id} completed by {name} — {len(reply)} chars, {len(generated_images)} images")
    return reply


def _maybe_create_content_from_task(db, task, deliverable, images=None):
    """If a task is about creating social content for an agent, auto-create a Content draft."""
    import re
    from src.database.models import Content, Agent

    if not deliverable:
        return

    title_lower = (task.title or '').lower()
    desc_lower = (task.description or '').lower()
    combined = f"{title_lower} {desc_lower}"

    # Detect platform from task title/description
    platform = None
    for p in ['twitter', 'instagram', 'linkedin', 'tiktok']:
        if p in combined:
            platform = p
            break
    if 'tweet' in combined or ' x ' in combined:
        platform = platform or 'twitter'

    if not platform:
        return  # Not a content-creation task

    # Detect agent from task title/description
    agent = None
    agents = db.query(Agent).all()
    # 1) Explicit "Target agent: Name" / "Target: Name" marker (our decomposition prompt emits this)
    m_target = re.search(r'target\s*agent\s*[:\-]\s*([^\n(\-]+?)(?:\s*\(|\s*\n|$)', combined, re.IGNORECASE)
    if m_target:
        target_name = m_target.group(1).strip().lower()
        for a in agents:
            if a.name.lower() == target_name or a.name.lower() in target_name:
                agent = a
                break
    # 2) "agent #N" / "Agent ID: N" explicit ID
    if not agent:
        m_id = re.search(r'agent\s*(?:id)?[:\s#]*(\d+)', combined)
        if m_id:
            agent = db.query(Agent).filter(Agent.id == int(m_id.group(1))).first()
    # 3) Agent full name appearing anywhere in title/desc
    if not agent:
        for a in agents:
            if a.name and len(a.name) > 3 and a.name.lower() in combined:
                agent = a
                break
    # 4) Brand name appearing in title/desc (e.g. "chen_invest", "marcus_offmarket")
    if not agent:
        for a in agents:
            if a.brand and len(a.brand) > 3 and a.brand.lower() in combined:
                agent = a
                break
    # 5) Parent task fallback — walk up the chain looking for an agent ref
    if not agent and getattr(task, 'parent_id', None):
        try:
            from src.database.models import Task as _T
            cur_parent_id = task.parent_id
            hops = 0
            while cur_parent_id and hops < 5:
                parent = db.query(_T).filter(_T.id == cur_parent_id).first()
                if not parent:
                    break
                ptext = f"{(parent.title or '').lower()} {(parent.description or '').lower()}"
                # parent explicit assignee
                if parent.assignee_type == 'agent' and parent.assignee_key:
                    try:
                        agent = db.query(Agent).filter(Agent.id == int(parent.assignee_key)).first()
                        if agent:
                            break
                    except (ValueError, TypeError):
                        pass
                # parent target marker
                pm = re.search(r'target\s*agent\s*[:\-]\s*([^\n(\-]+?)(?:\s*\(|\s*\n|$)', ptext, re.IGNORECASE)
                if pm:
                    pname = pm.group(1).strip().lower()
                    for a in agents:
                        if a.name.lower() == pname or a.name.lower() in pname:
                            agent = a
                            break
                    if agent:
                        break
                # parent name/brand mention
                for a in agents:
                    if a.name and len(a.name) > 3 and a.name.lower() in ptext:
                        agent = a
                        break
                    if a.brand and len(a.brand) > 3 and a.brand.lower() in ptext:
                        agent = a
                        break
                if agent:
                    break
                cur_parent_id = parent.parent_id
                hops += 1
        except Exception:
            pass
    # 6) Current task's own assignee_key as last resort
    if not agent and getattr(task, 'assignee_type', None) == 'agent' and getattr(task, 'assignee_key', None):
        try:
            agent = db.query(Agent).filter(Agent.id == int(task.assignee_key)).first()
        except (ValueError, TypeError):
            pass

    if not agent:
        return  # Can't determine which agent this is for

    # Extract the actual post content from the deliverable
    body = _extract_post_body_from_deliverable(deliverable, platform)
    if not body or len(body.strip()) < 10:
        return

    # Reject internal notes / operational content that isn't actual post copy
    _internal_markers = [
        'capacity note', 'note to victoria', 'note before we start',
        "i'm executing", "i'm running this", 'briefing james', 'briefing elena',
        "ryan's copy", "problem: i don't have", 'these are ready to go. a few notes',
        'prepared by:', '**to:**', '**from:**', '**re:**', 'executive summary',
        'before i can confirm', 'urgent flag', 'qa pass', 'standby',
        # Task-response / dispatch chatter that leaked into drafts
        'understood, supervisor', 'understood. i am on it', 'on it, supervisor',
        "what i'm doing instead", "here's what i'm doing", "here's my plan",
        'approvals land', 'execution-ready staging', 'staging document',
        'alexander\'s approvals', "victoria's approval", 'pending approval',
    ]
    body_lower = body[:200].lower()
    if any(m in body_lower for m in _internal_markers):
        return  # Not actual post content

    # Reject dispatch-list / multi-agent brief format (e.g. "## AGENT 1: FRENCHIMMOAGENT")
    import re as _re_internal
    stripped = body.strip()
    if _re_internal.match(r'^(?:-{3,}\s*)?#{1,3}\s*agent\s*\d', stripped, _re_internal.IGNORECASE):
        return
    # Reject if body is a pure dispatch list (starts with `---` THEN `## AGENT`)
    if stripped.startswith('---') and _re_internal.search(r'^#{1,3}\s*agent\s*\d', stripped[3:].lstrip(), _re_internal.IGNORECASE | _re_internal.MULTILINE):
        return

    # Twitter: sanitize, then LLM-rewrite if still over limit so we never save
    # a mid-sentence truncated tweet ("The of…" etc.).
    if platform in ('twitter', 'x'):
        platform = 'Twitter/X'
        body = _sanitize_twitter_body(body)
        _tw_len = sum(2 if ord(c) > 0xFFFF else 1 for c in body)
        if _tw_len > 270 or body.rstrip().endswith(('…', '...')):
            body = _rewrite_tweet_to_fit(body, agent, limit=270)

    media = [img['url'] for img in (images or []) if img.get('url')]

    post = Content(
        agent_id=agent.id,
        title=body[:100],
        body=body,
        hashtags=[],
        media_urls=media,
        platform=platform,
        status='draft',
    )
    db.add(post)
    db.flush()
    logging.info(f"[TaskExec] 📝 Auto-created {platform} draft #{post.id} for {agent.name} from task #{task.id}")


def _extract_post_body_from_deliverable(text, platform):
    """Extract the actual post/tweet text from an LLM deliverable.

    Deliverables are often complex documents (executive summaries, briefs) that
    contain the actual post text in blockquotes (> lines) or after variant headers.
    """
    import re

    if not text:
        return ''

    # ── Strategy 0: Labeled CAPTION / MAIN CAPTION / POST COPY block (Instagram carousels) ──
    cap_m = re.search(
        r'\*{0,2}\s*(?:MAIN\s+CAPTION|FINAL\s+CAPTION|CAPTION|POST\s+COPY|FINAL\s+COPY)'
        r'[^\n:]*:?\*{0,2}\s*\n+(.+?)(?=\n\s*(?:\*{0,2}(?:HASHTAG|CTA|NOTES|SLIDE|TWEET|---))|\Z)',
        text, re.IGNORECASE | re.DOTALL,
    )
    if cap_m:
        body = cap_m.group(1).strip()
        body = re.sub(r'^\*+|\*+$', '', body).strip()
        if len(body) > 40:
            return body

    # ── Strategy 1: Extract blockquoted content (most reliable for tweet deliverables) ──
    # Pattern: "> line1\n> line2\n> line3" — the actual post is usually in blockquotes
    blockquotes = re.findall(r'(?:^|\n)((?:>\s*[^\n]+\n?)+)', text)
    if blockquotes:
        # Take the first blockquote that has substantial content
        for bq in blockquotes:
            clean = re.sub(r'^>\s?', '', bq, flags=re.MULTILINE).strip()
            if len(clean) > 20:
                return clean

    # ── Strategy 2: Find content after Variant A / Single Tweet headers ──
    for pattern in [
        r'(?:variant\s*a|single\s*tweet|tweet\s*1\s*(?:of|/)\s*\d+)[^\n]*\n+(.*?)(?:\n\s*(?:\*\*char|char\s*count|variant\s*b|---|\Z))',
        r'(?:tweet\s*1|tweet\s*\d+\s*of\s*\d+)[:\s]*\n+(.*?)(?:\n\s*\n\s*(?:tweet|---|\Z))',
        r'(?:post|caption)[:\s]*\n+(.*?)(?:\n\s*\n|\n\s*---|\Z)',
    ]:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(r'^>\s*', '', candidate, flags=re.MULTILINE).strip()
            if len(candidate) > 20:
                return candidate

    # ── Strategy 3: If text starts directly with content (no headers/JSON) ──
    lines = text.strip().split('\n')
    first_line = lines[0].strip()
    skip_starts = ['#', '**', '===', '---', 'task', 'deliverable', 'here', 'below',
                   'running', 'brief', 'from:', 'to:', '{', '[', '```']
    if not any(first_line.lower().startswith(h) for h in skip_starts):
        para = []
        for line in lines:
            line = line.strip()
            if not line and para:
                break
            if line:
                para.append(line)
        candidate = '\n'.join(para)
        if 20 < len(candidate) < 500:
            return candidate

    return ''


def _execute_cascade_task(db, parent_task, head_entity, direct_reports):
    """
    CASCADE EXECUTION: A department head receives a task →
    1. Head AI decomposes it into sub-tasks for their direct reports
    2. Each sub-task is created in DB (parent_id linked) and executed
    3. Head AI produces a final summary of all deliverables
    4. Summary posted to inbox, parent task marked done
    5. If head decides to launch a workflow pipeline, it gets triggered
    """
    import time, json, re
    from src.database.models import Task, TeamMember, InternalMessage, Notification
    from src.api.llm_provider import LLMProvider

    task_id = parent_task.id
    title = parent_task.title
    description = parent_task.description or title
    priority = parent_task.priority or 'medium'
    head_key = head_entity.role_key
    head_name = head_entity.display_name
    head_emoji = head_entity.emoji or ''
    provider = head_entity.llm_provider or 'claude'
    model = head_entity.llm_model or 'claude-sonnet-4-6'
    temp = head_entity.temperature or 0.7

    logging.info(f"[Cascade] Head {head_name} decomposing task #{task_id}: '{title}'")

    head_thread = f"chat_team_member_{head_key}"
    sys_prompt = _build_team_system_prompt(db, head_entity)
    llm = LLMProvider(provider=provider, model=model)

    # ── RESUME: if sub-tasks already exist for this parent (orphaned by prior restart), reuse them ──
    existing_subs = db.query(Task).filter(Task.parent_id == task_id).all()
    resuming = bool(existing_subs)
    sub_task_objects = []

    if resuming:
        logging.info(f"[Cascade] Resuming #{task_id} — reusing {len(existing_subs)} existing sub-tasks (skipping decomposition)")
        sub_task_objects = list(existing_subs)
        # Reset any blocked sub-tasks so they retry this run
        for st in sub_task_objects:
            if st.status == 'blocked':
                st.status = 'in_progress'
        db.commit()

    if not resuming:
        # Build team roster for the head
        team_roster = '\n'.join(
            f"- {r.role_key}: {r.display_name} ({r.role_title})"
            for r in direct_reports
        )

        # Detect "fan-out" language: task produces N deliverables across N agents.
        # When this triggers, the head must split per-agent so each sub-task carries
        # an agent name → _maybe_create_content_from_task can auto-create a draft.
        _fanout_patterns = [
            r'\bfor\s+(?:agents?|influencers?)\s*\d+\s*[-–to]+\s*\d+\b',
            r'\bacross\s+\d+\s+(?:agents?|influencers?)\b',
            r'\b\d+\s+(?:ig|instagram|twitter|x|linkedin|tiktok)\s+(?:carousels?|posts?|tweets?|threads?|videos?)\b',
            r'\bagents?\s*\d+\s*[-–to]+\s*\d+\b',
        ]
        _fanout_text = f"{title}\n{description}".lower()
        _is_fanout = any(__import__('re').search(p, _fanout_text, __import__('re').IGNORECASE) for p in _fanout_patterns)

        _agent_roster = ''
        if _is_fanout:
            from src.database.models import Agent as _Agent
            _ags = db.query(_Agent).filter(_Agent.is_active == True).order_by(_Agent.id).limit(11).all()
            _agent_roster = '\n'.join(f"  - agent #{a.id}: {a.name} ({a.brand or ''})" for a in _ags)

        _fanout_instructions = (
            f"\n\n⚡ FAN-OUT DETECTED — this task produces MULTIPLE deliverables across MULTIPLE influencer agents.\n"
            f"INFLUENCER AGENTS (target these directly):\n{_agent_roster}\n\n"
            f"MANDATORY: Produce ONE sub-task PER agent mentioned in the parent task. "
            f"Each sub-task TITLE must include the agent's NAME explicitly (e.g. 'Write IG carousel for David Chen — ...'). "
            f"Each sub-task DESCRIPTION must include 'Target agent: <Name> (agent #<id>)' on its own line. "
            f"This is how drafts get auto-created in each agent's inbox. Without the agent name in the sub-task, "
            f"the content goes nowhere and we burn tokens for nothing.\n"
        ) if _is_fanout else ''

        # ── STEP 1: Head decomposes the task ──
        decompose_prompt = (
            f"=== TASK FROM LEADERSHIP ===\n"
            f"Title: {title}\n"
            f"Priority: {priority.upper()}\n"
            f"Description:\n{description}\n\n"
            f"You are {head_name}, department head. Your DIRECT REPORTS:\n{team_roster}"
            f"{_fanout_instructions}\n"
            f"DECOMPOSE this task into specific sub-tasks for your team members. "
            f"Each sub-task must be assigned to a specific direct report based on their expertise.\n\n"
            f"Reply with:\n"
            f"1. A brief strategy (2-3 sentences max) for how your team will tackle this\n"
            f"2. A ```tasks block with sub-tasks:\n"
            f"```tasks\n"
            f"[{{\"title\": \"Specific sub-task\", \"assignee_key\": \"role_key\", \"assignee_type\": \"team_member\", "
            f"\"assignee_name\": \"Full Name\", \"priority\": \"{priority}\", "
            f"\"description\": \"Detailed instructions for this team member\"}}]\n"
            f"```\n\n"
            f"RULES:\n"
            f"- Assign ONLY to your direct reports listed above\n"
            f"- Each sub-task must be specific and actionable\n"
            f"- Cover the full scope of the parent task\n"
            + (f"- For fan-out tasks: ONE sub-task per target agent (the agents listed above), agent name in title, 'Target agent:' line in description\n"
               if _is_fanout else
               f"- 2-4 sub-tasks is ideal\n")
        )

        decompose_reply = llm.generate_content(
            prompt=decompose_prompt, max_tokens=2000, temperature=temp, system_prompt=sys_prompt,
        )

        # Post concise dispatch notice to head's inbox (not the full decomposition blabber)
        db.add(InternalMessage(
            from_type='user', from_key='supervisor', from_name='You', from_emoji='',
            body=f"📋 **Task Approved → {title}**\n_Priority: {priority.upper()} — Executing now._",
            msg_type='chat', thread_id=head_thread, is_read=True,
        ))
        db.commit()

        # ── STEP 1b: Launch workflow if head triggered one ──
        clean_decompose, workflow_info = _extract_and_launch_workflow(decompose_reply)
        if workflow_info:
            logging.info(f"[Cascade] {head_name} launched workflow #{workflow_info.get('run_id')} from task #{task_id}")
            db.add(Notification(
                type='workflow_launched',
                title=f'🚀 {head_name} launched pipeline #{workflow_info["run_id"]}',
                body=f'Topics: {", ".join(workflow_info.get("topics", []))}',
                link='/newsroom.html',
                workflow_run_id=workflow_info.get('run_id'),
            ))
            db.commit()

        # ── STEP 2: Parse and create sub-tasks ──
        sub_tasks_data = []
        pattern_tasks = r'```tasks\s*\n?(.*?)\n?\s*```'
        pattern_json = r'```json\s*\n?(\[[\s\S]*?\])\s*\n?\s*```'
        pattern_any = r'```[\w_]*\s*\n?(\[[\s\S]*?"title"[\s\S]*?\])\s*\n?\s*```'

        raw_json = None
        for pat in [pattern_tasks, pattern_json, pattern_any]:
            m = re.search(pat, decompose_reply, re.DOTALL)
            if m:
                raw_json = m.group(1).strip()
                break

        if raw_json:
            try:
                sub_tasks_data = json.loads(raw_json)
                if not isinstance(sub_tasks_data, list):
                    sub_tasks_data = [sub_tasks_data]
            except Exception as e:
                logging.warning(f"[Cascade] Failed to parse sub-tasks JSON: {e}")

        # Validate assignees — only allow direct reports
        valid_keys = {r.role_key for r in direct_reports}

        for td in sub_tasks_data:
            a_key = str(td.get('assignee_key', ''))
            if a_key not in valid_keys:
                # Fallback: assign to first available report
                a_key = direct_reports[0].role_key if direct_reports else head_key

            a_name = td.get('assignee_name', '')
            if not a_name:
                member = db.query(TeamMember).filter(TeamMember.role_key == a_key).first()
                a_name = member.display_name if member else a_key

            sub_task = Task(
                title=td.get('title', 'Sub-task'),
                description=td.get('description', ''),
                priority=td.get('priority', priority),
                assignee_type='team_member',
                assignee_key=a_key,
                assignee_name=a_name,
                created_by_type='team_member',
                created_by_key=head_key,
                created_by_name=head_name,
                department=_dept_from_assignee(a_key),
                parent_id=task_id,
                thread_id=head_thread,
                requires_approval=False,  # head already approved — sub-tasks auto-execute
                status='in_progress',
            )
            db.add(sub_task)
            db.commit()
            sub_task_objects.append(sub_task)
            logging.info(f"[Cascade] Sub-task #{sub_task.id} '{sub_task.title}' → {a_name}")

    # If no sub-tasks were parsed, execute directly as the head
    if not sub_task_objects:
        logging.warning(f"[Cascade] No sub-tasks parsed — head {head_name} executes directly")
        _execute_individual_task(db, parent_task, head_entity, 'team_member', head_key)
        return

    # Notification: cascade started (skip on resume — user already got it)
    if not resuming:
        db.add(Notification(
            type='task_cascade_started',
            title=f'⚡ {head_name} dispatched {len(sub_task_objects)} sub-tasks',
            body=f'Task: {title[:80]} → {", ".join(st.assignee_name for st in sub_task_objects)}',
            link=f'/inbox?entity_type=team_member&entity_key={head_key}',
        ))
        db.commit()

    # ── STEP 3: Execute sub-tasks in parallel (2 workers) ──
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _run_sub(st, idx=0):
        import time as _time
        _time.sleep(idx * 0.5)  # stagger DB access slightly
        from src.database.db import get_db as _get_db
        sub_db = _get_db()
        try:
            from src.database.models import Task as _T, TeamMember as _TM
            sub_task = sub_db.query(_T).filter(_T.id == st.id).first()
            member = sub_db.query(_TM).filter(_TM.role_key == st.assignee_key).first()
            # Resume optimization: if already finished last run, don't re-run
            if sub_task and sub_task.status == 'done' and sub_task.deliverable:
                return {'task_id': st.id, 'title': st.title, 'assignee': st.assignee_name,
                        'result': (sub_task.deliverable or '')[:500], 'status': 'done'}
            if member and sub_task:
                result = _execute_individual_task(sub_db, sub_task, member, 'team_member', st.assignee_key)
                return {'task_id': st.id, 'title': st.title, 'assignee': st.assignee_name,
                        'result': (result or '')[:500], 'status': 'done'}
            else:
                if sub_task:
                    sub_task.status = 'blocked'
                    sub_task.description = (sub_task.description or '') + f'\n[EXECUTION ERROR: Team member "{st.assignee_key}" not found]'
                    sub_db.commit()
                return {'task_id': st.id, 'title': st.title, 'assignee': st.assignee_name,
                        'result': '[Member not found]', 'status': 'blocked'}
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logging.error(f"[Cascade] Sub-task #{st.id} failed: {e}\n{tb}")
            try:
                sub_task = sub_db.query(Task).filter(Task.id == st.id).first()
                if sub_task:
                    sub_task.status = 'blocked'
                    sub_task.description = (sub_task.description or '') + f'\n[EXECUTION ERROR: {type(e).__name__}: {str(e)[:400]}]'
                    sub_db.commit()
            except Exception:
                pass
            return {'task_id': st.id, 'title': st.title, 'assignee': st.assignee_name,
                    'result': f'[Error: {type(e).__name__}: {str(e)[:200]}]', 'status': 'failed'}
        finally:
            sub_db.close()

    sub_results = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='sub-task') as pool:
        futures = {pool.submit(_run_sub, st, i): st for i, st in enumerate(sub_task_objects)}
        for future in as_completed(futures):
            sub_results.append(future.result())

    # ── STEP 4: Head produces executive summary ──
    completed = sum(1 for r in sub_results if r['status'] == 'done')
    results_text = '\n\n'.join(
        f"### {r['assignee']} — {r['title']}\n{r['result']}"
        for r in sub_results
    )

    summary_prompt = (
        f"=== DEPARTMENT EXECUTION COMPLETE ===\n"
        f"Original task: {title}\n"
        f"Sub-tasks completed: {completed}/{len(sub_results)}\n\n"
        f"TEAM DELIVERABLES:\n{results_text}\n\n"
        f"Write an EXECUTIVE SUMMARY for the founder. Include:\n"
        f"1. What was accomplished (bullet points)\n"
        f"2. Key outputs/deliverables produced\n"
        f"3. Any issues or blockers encountered\n"
        f"4. Recommended next steps\n"
        f"Be concise but comprehensive. This goes directly to the founder's inbox."
    )

    summary_reply = llm.generate_content(
        prompt=summary_prompt, max_tokens=2000, temperature=0.5, system_prompt=sys_prompt,
    )

    # ── STEP 5: Post summary to head's thread + Marc's thread ──
    # In head's inbox
    db.add(InternalMessage(
        from_type='team_member', from_key=head_key,
        from_name=head_name, from_emoji=head_emoji,
        body=f"📊 **Executive Summary — Task Complete**\n\n{summary_reply}",
        msg_type='chat', thread_id=head_thread, is_read=False,
    ))

    # In Marc's inbox (so the founder sees it in the cofounder thread too)
    marc_thread = "chat_team_member_cofounder"
    db.add(InternalMessage(
        from_type='team_member', from_key=head_key,
        from_name=head_name, from_emoji=head_emoji,
        body=f"📊 **{head_name} — Task Complete: {title}**\n\n"
             f"_Sub-tasks: {completed}/{len(sub_results)} completed_\n\n{summary_reply}",
        msg_type='chat', thread_id=marc_thread, is_read=False,
    ))

    # Mark parent task done
    parent_task.status = 'done'
    parent_task.completed_at = datetime.utcnow()
    parent_task.deliverable = (summary_reply or '')[:5000]

    # Success notification with summary
    db.add(Notification(
        type='task_completed',
        title=f'✅ {head_name}\'s team completed: {title[:50]}',
        body=f'{completed}/{len(sub_results)} sub-tasks done. {summary_reply[:150]}…',
        link=f'/inbox?entity_type=team_member&entity_key={head_key}',
    ))
    db.commit()

    logging.info(f"[Cascade] ✅ Task #{task_id} cascade complete — {completed}/{len(sub_results)} sub-tasks done")


@app.route('/api/tasks/<int:task_id>/reject', methods=['POST'])
def reject_task(task_id):
    """Reject a cofounder-proposed task — keeps it for later reconsideration."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    task.status = 'rejected'
    db.commit()
    return jsonify({'ok': True}), 200


@app.route('/api/task-stop/<int:task_id>', methods=['POST'])
def stop_task(task_id):
    """Force-stop a stuck in_progress task → marks it as 'blocked'."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if task.status != 'in_progress':
        return jsonify({'error': f'Task is {task.status}, not in_progress'}), 400
    task.status = 'blocked'
    task.deliverable = (task.deliverable or '') + '\n\n[STOPPED] Task was manually stopped by user.'
    db.commit()
    # Also stop any in-progress sub-tasks
    sub_tasks = db.query(Task).filter(Task.parent_id == task_id, Task.status == 'in_progress').all()
    for st in sub_tasks:
        st.status = 'blocked'
        st.deliverable = (st.deliverable or '') + '\n\n[STOPPED] Parent task was manually stopped.'
    db.commit()
    return jsonify({'ok': True, 'stopped_subtasks': len(sub_tasks)}), 200


@app.route('/api/task-retry/<int:task_id>', methods=['POST'])
def retry_task(task_id):
    """Re-run a blocked/failed task from scratch."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if task.status not in ('blocked', 'failed'):
        return jsonify({'error': f'Task is {task.status}, only blocked/failed tasks can be retried'}), 400
    # Reset task state — strip old error messages from description
    import re as _re
    task.status = 'in_progress'
    task.deliverable = None
    task.completed_at = None
    task.approved_at = datetime.utcnow()
    if task.description:
        task.description = _re.sub(r'\n?\[(?:EXECUTION ERROR|ERROR|STOPPED):?[^\]]*\]', '', task.description).strip()
    db.commit()
    # Build snapshot and dispatch
    snapshot = {
        'id': task.id, 'title': task.title, 'description': task.description,
        'assignee_type': task.assignee_type, 'assignee_key': task.assignee_key,
        'assignee_name': task.assignee_name, 'priority': task.priority,
    }
    thread = threading.Thread(target=_execute_task_in_background, args=(snapshot,), name=f'task-retry-{task_id}', daemon=True)
    thread.start()
    return jsonify({'ok': True}), 200


_DEPT_HEADS = {
    'newsroom': 'eic',
    'tech': 'cto',
    'sales': 'vp_sales',
    'leadership': 'general_manager',
}


@app.route('/api/task-review/<int:task_id>', methods=['GET'])
def get_task_review_chat(task_id):
    """Get review chat history for a task."""
    from flask import g
    from src.database.models import Task, InternalMessage
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    thread_id = f"task_review_{task_id}"
    messages = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).order_by(InternalMessage.created_at.asc()).all()
    return jsonify({
        'messages': [{
            'from_type': m.from_type, 'from_name': m.from_name,
            'from_emoji': m.from_emoji or '', 'body': m.body,
            'created_at': m.created_at.isoformat() if m.created_at else None,
        } for m in messages]
    }), 200


@app.route('/api/task-review/<int:task_id>', methods=['POST'])
def post_task_review_chat(task_id):
    """Chat with the department head to review a task deliverable."""
    from flask import g
    from src.database.models import Task, TeamMember, InternalMessage
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    data = request.json or {}
    user_msg = data.get('message', '').strip()
    if not user_msg:
        return jsonify({'error': 'message required'}), 400

    # Determine department head for this task
    dept = getattr(task, 'department', None) or _dept_from_assignee(task.assignee_key)
    head_key = _DEPT_HEADS.get(dept, 'eic')
    head = db.query(TeamMember).filter(TeamMember.role_key == head_key).first()
    if not head:
        return jsonify({'error': f'Department head {head_key} not found'}), 404

    head_name = head.display_name
    head_emoji = head.emoji or ''
    thread_id = f"task_review_{task_id}"

    # Save user message
    user_row = InternalMessage(
        from_type='user', from_key='supervisor', from_name='You', from_emoji='',
        body=user_msg, msg_type='chat', thread_id=thread_id, is_read=True
    )
    db.add(user_row)
    db.commit()

    # Load conversation history
    history = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).order_by(InternalMessage.created_at.desc()).limit(20).all()
    history.reverse()

    conv_lines = []
    for h in history[:-1]:
        role = 'Supervisor' if h.from_type == 'user' else head_name
        conv_lines.append(f"{role}: {h.body[:500]}")
    conv_context = '\n'.join(conv_lines)

    # Build review-specific system prompt — get deliverable from task row or fall back to inbox
    deliverable_preview = task.deliverable or ''
    if not deliverable_preview:
        # Fall back: look up the deliverable email from the assignee's thread
        canonical_thread = f"chat_team_member_{task.assignee_key}"
        deliv_msg = db.query(InternalMessage).filter(
            InternalMessage.thread_id == canonical_thread,
            InternalMessage.from_type == 'team_member',
            InternalMessage.subject.ilike(f'%{task.title[:40]}%'),
        ).order_by(InternalMessage.created_at.desc()).first()
        if deliv_msg:
            deliverable_preview = deliv_msg.body[:3000]
        else:
            deliverable_preview = 'No deliverable found yet.'
    deliverable_preview = deliverable_preview[:3000]
    review_prompt = (
        f"You are {head_name}, {head.role_title}.\n"
        f"{head.system_prompt or ''}\n\n"
        f"=== TASK UNDER REVIEW ===\n"
        f"Title: {task.title}\n"
        f"Assigned to: {task.assignee_name}\n"
        f"Status: {task.status}\n"
        f"Description: {task.description or 'N/A'}\n\n"
        f"=== DELIVERABLE ===\n{deliverable_preview}\n\n"
        f"=== YOUR ROLE ===\n"
        f"The Supervisor (your boss / the founder) is reviewing this task's output with you. "
        f"You are the department head responsible for this work. "
        f"Discuss the deliverable honestly — what's good, what could be improved. "
        f"If the Supervisor asks you to send it back for rework, acknowledge it and say you'll brief the team member. "
        f"If the Supervisor validates the work, confirm it's approved. "
        f"Be concise, professional, and direct. Think like a senior creative/editorial director reviewing work."
    )

    prompt = f"{conv_context}\nSupervisor: {user_msg}\n{head_name}:" if conv_context else user_msg

    try:
        from src.api.llm_provider import LLMProvider
        provider = head.llm_provider or 'anthropic'
        model = head.llm_model or 'claude-sonnet-4-20250514'
        temp = head.temperature if head.temperature is not None else 0.7
        llm = LLMProvider(provider=provider, model=model)
        reply = llm.generate_content(
            prompt=prompt,
            max_tokens=1500,
            temperature=temp,
            system_prompt=review_prompt
        )
        clean_reply = (reply or '').strip()

        # Check if head signals rework
        rework = False
        rework_keywords = ['send it back', 'rework', 'redo', 'revise', "i'll brief", "i will brief", 'back to the team']
        if any(kw in clean_reply.lower() for kw in rework_keywords):
            rework = True

        # Save AI reply
        ai_row = InternalMessage(
            from_type='team_member', from_key=head_key,
            from_name=head_name, from_emoji=head_emoji,
            body=clean_reply, msg_type='chat', thread_id=thread_id, is_read=False
        )
        db.add(ai_row)
        db.commit()

        return jsonify({
            'ok': True,
            'reply': clean_reply,
            'head_name': head_name,
            'head_emoji': head_emoji,
            'head_key': head_key,
            'rework_detected': rework,
        }), 200

    except Exception as e:
        logging.error(f"[TaskReview] Chat error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/task-rework/<int:task_id>', methods=['POST'])
def rework_task(task_id):
    """Send a task back for rework with supervisor's feedback notes."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    data = request.json or {}
    notes = data.get('notes', 'Rework requested by supervisor.')

    # Reset task with rework context
    original_deliverable = task.deliverable or ''
    task.status = 'in_progress'
    task.deliverable = None
    task.completed_at = None
    task.description = (task.description or '') + f"\n\n[REWORK] Supervisor feedback: {notes}\n\nPrevious deliverable for reference:\n{original_deliverable[:2000]}"
    task.approved_at = datetime.utcnow()
    db.commit()

    # Re-dispatch
    snapshot = {
        'id': task.id, 'title': task.title, 'description': task.description,
        'assignee_type': task.assignee_type, 'assignee_key': task.assignee_key,
        'assignee_name': task.assignee_name, 'priority': task.priority,
    }
    thread = threading.Thread(target=_execute_task_in_background, args=(snapshot,), name=f'task-rework-{task_id}', daemon=True)
    thread.start()
    return jsonify({'ok': True}), 200


@app.route('/api/tasks/retry_all_blocked', methods=['POST'])
def retry_all_blocked():
    """Retry all blocked tasks (including sub-tasks)."""
    from flask import g
    from src.database.models import Task
    db = g.db
    _not_archived = (Task.archived == False) | (Task.archived == None)
    blocked = db.query(Task).filter(
        Task.status == 'blocked', _not_archived
    ).all()
    import re as _re
    snapshots = []
    for t in blocked:
        t.status = 'in_progress'
        t.deliverable = None
        t.completed_at = None
        t.approved_at = datetime.utcnow()
        if t.description:
            t.description = _re.sub(r'\n?\[(?:EXECUTION ERROR|ERROR|STOPPED):?[^\]]*\]', '', t.description).strip()
        snapshots.append({
            'id': t.id, 'title': t.title, 'description': t.description,
            'assignee_type': t.assignee_type, 'assignee_key': t.assignee_key,
            'assignee_name': t.assignee_name, 'priority': t.priority,
        })
    db.commit()

    from concurrent.futures import ThreadPoolExecutor
    def _run_all(snaps):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='retry-exec') as pool:
            pool.map(_execute_task_in_background, snaps)
    thread = threading.Thread(target=_run_all, args=(snapshots,), name='retry-all-blocked', daemon=True)
    thread.start()
    return jsonify({'ok': True, 'retried': len(snapshots)}), 200


@app.route('/api/tasks/approve_all', methods=['POST'])
def approve_all_tasks():
    """Approve all pending cofounder tasks at once and dispatch background execution."""
    from flask import g
    from src.database.models import Task
    db = g.db
    tasks = db.query(Task).filter(
        Task.requires_approval == True,
        Task.approved_at == None,
        Task.status != 'rejected',
    ).all()
    snapshots = []
    for t in tasks:
        t.approved_at = datetime.utcnow()
        t.status = 'in_progress'
        snapshots.append({
            'id': t.id, 'title': t.title, 'description': t.description,
            'assignee_type': t.assignee_type, 'assignee_key': t.assignee_key,
            'assignee_name': t.assignee_name, 'priority': t.priority,
        })
    db.commit()

    # Dispatch in parallel batches (3 concurrent workers to respect rate limits)
    from concurrent.futures import ThreadPoolExecutor
    def _run_all_parallel(snaps):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='task-exec') as pool:
            pool.map(_execute_task_in_background, snaps)
    thread = threading.Thread(target=_run_all_parallel, args=(snapshots,), name='task-exec-all', daemon=True)
    thread.start()

    return jsonify({'ok': True, 'approved': len(snapshots)}), 200


@app.route('/api/tasks/progress', methods=['GET'])
def get_tasks_progress():
    """Real-time progress: how many tasks are pending/in_progress/done/blocked."""
    from flask import g
    from src.database.models import Task
    db = g.db
    _not_archived = (Task.archived == False) | (Task.archived == None)
    _top_level = Task.parent_id == None
    pending = db.query(Task).filter(Task.requires_approval == True, Task.approved_at == None, Task.status != 'rejected', _not_archived, _top_level).count()
    in_progress = db.query(Task).filter(Task.status == 'in_progress', _not_archived, _top_level).count()
    in_progress_all = db.query(Task).filter(Task.status == 'in_progress', _not_archived).count()
    done = db.query(Task).filter(Task.status == 'done', _not_archived, _top_level).count()
    blocked = db.query(Task).filter(Task.status == 'blocked', _not_archived, _top_level).count()
    recent_done = db.query(Task).filter(Task.status == 'done', _not_archived, _top_level).order_by(Task.completed_at.desc()).limit(5).all()
    # Currently-running leaf tasks — what's actually firing API calls right now
    running_leaves = db.query(Task).filter(Task.status == 'in_progress', _not_archived).order_by(Task.updated_at.desc()).limit(10).all()
    return jsonify({
        'pending_approval': pending,
        'in_progress': in_progress,
        'in_progress_all': in_progress_all,
        'running_now': [{
            'id': t.id, 'title': t.title[:80], 'assignee_name': t.assignee_name,
            'parent_id': t.parent_id,
            'updated_at': t.updated_at.isoformat() if getattr(t, 'updated_at', None) else None,
        } for t in running_leaves],
        'done': done,
        'blocked': blocked,
        'recent_completed': [{
            'id': t.id, 'title': t.title, 'assignee_name': t.assignee_name,
            'department': getattr(t, 'department', None) or _dept_from_assignee(t.assignee_key),
            'completed_at': t.completed_at.isoformat() if t.completed_at else None,
        } for t in recent_done],
    }), 200


@app.route('/api/cofounder/pulse', methods=['POST'])
def cofounder_pulse():
    """Marc's proactive pulse — checks state, auto-dispatches tasks if backlog < threshold.
    Called automatically every ~60s by the frontend. Returns task counts + any new tasks created."""
    from flask import g
    from src.database.models import Task, TeamMember, WorkflowRun, Agent, Content, AtomizedContent
    db = g.db

    # Count active tasks by status
    pending = db.query(Task).filter(Task.requires_approval == True, Task.approved_at == None, Task.status != 'rejected').count()
    in_progress = db.query(Task).filter(Task.status == 'in_progress').count()
    todo = db.query(Task).filter(Task.status == 'todo').count()
    done_recent = db.query(Task).filter(Task.status == 'done').order_by(Task.completed_at.desc()).limit(5).all()
    active_total = pending + in_progress + todo

    # Gather context for response
    stats = {
        'pending_approval': pending,
        'in_progress': in_progress,
        'todo': todo,
        'active_total': active_total,
        'done_recent': [{'id': t.id, 'title': t.title, 'assignee_name': t.assignee_name,
                         'completed_at': t.completed_at.isoformat() if t.completed_at else None} for t in done_recent],
    }

    # If we have enough active tasks, just return stats — no need to generate more
    if active_total >= 5:
        return jsonify({'stats': stats, 'action': 'idle', 'new_tasks': 0}), 200

    # Marc needs to dispatch more tasks! Call his AI to assess and create.
    deficit = 5 - active_total
    try:
        cofounder = db.query(TeamMember).filter(TeamMember.role_key == 'cofounder').first()
        if not cofounder:
            return jsonify({'stats': stats, 'action': 'no_cofounder', 'new_tasks': 0}), 200

        # Build state snapshot for Marc
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        agents_info = ', '.join(f"{a.name} (fields: {', '.join(a.fields or [])})" for a in agents[:11])

        recent_wfs = db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(3).all()
        wf_info = '; '.join(f"#{w.id}: {w.status} at {w.current_step}" for w in recent_wfs) or 'None'

        total_drafts = db.query(Content).filter(Content.status == 'draft').count()
        total_sched = db.query(Content).filter(Content.status == 'scheduled').count()
        total_pub = db.query(Content).filter(Content.status == 'published').count()

        try:
            pending_atoms = db.query(AtomizedContent).filter(AtomizedContent.status == 'draft').count()
        except Exception:
            pending_atoms = 0

        # What was recently completed?
        done_info = '; '.join(f"'{t.title}' by {t.assignee_name}" for t in done_recent) if done_recent else 'Nothing completed yet'

        # Current active tasks
        active_tasks = db.query(Task).filter(Task.status.in_(['todo', 'in_progress'])).all()
        active_info = '; '.join(f"'{t.title}' → {t.assignee_name} ({t.status})" for t in active_tasks) if active_tasks else 'No active tasks'

        vision_block = _get_vision_block(db)

        pulse_prompt = (
            f"PROACTIVE PULSE — You are running a startup. There is ALWAYS work to do.\n\n"
            f"{vision_block}\n"
            f"CURRENT STATE:\n"
            f"- Active tasks: {active_total} (need minimum 5, deficit: {deficit})\n"
            f"- In progress: {in_progress} | Pending approval: {pending} | Todo: {todo}\n"
            f"- Recently completed: {done_info}\n"
            f"- Active tasks: {active_info}\n"
            f"- Workflows: {wf_info}\n"
            f"- Content: {total_drafts} drafts, {total_sched} scheduled, {total_pub} published, {pending_atoms} atomized pending\n"
            f"- Agents: {agents_info}\n\n"
            f"You MUST dispatch exactly {deficit} NEW tasks right now. Do NOT repeat tasks that are already active or recently completed.\n"
            f"IMPORTANT: Assign tasks to DEPARTMENT HEADS only (eic, cto, vp_sales, general_manager). "
            f"They will cascade to their teams automatically.\n"
            f"Think about what's missing: content gaps, pipeline health, growth experiments, distribution optimization, "
            f"competitive intelligence, product improvements, analytics, sales outreach.\n"
            f"Every task must be SPECIFIC and ACTIONABLE — not vague."
        )

        from src.api.llm_provider import LLMProvider
        sys_prompt = cofounder.system_prompt or ''
        provider = cofounder.llm_provider or 'claude'
        model = cofounder.llm_model or 'claude-sonnet-4-6'
        llm = LLMProvider(provider=provider, model=model)
        reply = llm.generate_content(
            prompt=pulse_prompt,
            max_tokens=2000,
            temperature=0.8,
            system_prompt=sys_prompt,
        )

        # Extract and create tasks from Marc's reply
        canonical_thread = "chat_team_member_cofounder"
        clean_reply, tasks_created = _extract_and_create_tasks(
            db, reply, canonical_thread, 'team_member', 'cofounder', 'Marc Andreessen'
        )

        # Save Marc's pulse message to inbox thread
        from src.database.models import InternalMessage
        ai_msg = InternalMessage(
            from_type='team_member', from_key='cofounder',
            from_name='Marc Andreessen', from_emoji='🚀',
            body=clean_reply, msg_type='chat',
            thread_id=canonical_thread, is_read=False,
        )
        db.add(ai_msg)
        db.commit()

        # Update stats
        stats['pending_approval'] += tasks_created
        stats['active_total'] += tasks_created

        return jsonify({
            'stats': stats,
            'action': 'dispatched',
            'new_tasks': tasks_created,
            'marc_message': clean_reply[:300],
        }), 200

    except Exception as e:
        logging.error(f"[CofounderPulse] Error: {e}", exc_info=True)
        return jsonify({'stats': stats, 'action': 'error', 'error': str(e), 'new_tasks': 0}), 200


@app.route('/api/cofounder/approval_email_body', methods=['GET'])
def cofounder_approval_email_body():
    """Return a formatted email body with all pending Marc tasks for the founder to review."""
    from flask import g
    from src.database.models import Task
    db = g.db
    tasks = db.query(Task).filter(
        Task.requires_approval == True,
        Task.approved_at == None,
        Task.status != 'rejected',
    ).order_by(Task.priority.desc(), Task.created_at.desc()).all()

    if not tasks:
        return jsonify({'subject': 'No pending proposals', 'body': 'No tasks awaiting approval.', 'count': 0}), 200

    lines = [f"Marc Andreessen has dispatched {len(tasks)} task(s) for your approval:\n"]
    for i, t in enumerate(tasks, 1):
        pri = (t.priority or 'medium').upper()
        lines.append(f"{i}. [{pri}] {t.title}")
        lines.append(f"   → Assigned to: {t.assignee_name or t.assignee_key}")
        if t.description:
            lines.append(f"   → {t.description[:200]}")
        if t.due_date:
            lines.append(f"   → Due: {t.due_date.strftime('%b %d, %Y')}")
        lines.append("")

    lines.append(f"Review and approve at: http://localhost:5000/inbox\n")
    body = '\n'.join(lines)
    subject = f"[Axel] Marc needs your approval on {len(tasks)} strategic task(s)"
    return jsonify({'subject': subject, 'body': body, 'count': len(tasks), 'tasks': [
        {'id': t.id, 'title': t.title, 'priority': t.priority, 'assignee_name': t.assignee_name}
        for t in tasks
    ]}), 200


@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Create a task (from UI or from AI chat)."""
    from flask import g
    from src.database.models import Task, TeamMember, Agent
    db = g.db
    data = request.json or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'title required'}), 400

    assignee_type = data.get('assignee_type', 'team_member')
    assignee_key = data.get('assignee_key', '')
    assignee_name = data.get('assignee_name', '')

    # Resolve name if not provided
    if not assignee_name:
        if assignee_type == 'team_member':
            m = db.query(TeamMember).filter(TeamMember.role_key == assignee_key).first()
            if m: assignee_name = m.display_name
        elif assignee_type == 'agent':
            a = db.query(Agent).filter(Agent.id == int(assignee_key)).first()
            if a: assignee_name = a.name
    if not assignee_name:
        assignee_name = assignee_key

    due = None
    if data.get('due_date'):
        try:
            from datetime import datetime as dt
            due = dt.fromisoformat(data['due_date'].replace('Z', '+00:00'))
        except Exception:
            pass

    task = Task(
        title=title,
        description=data.get('description', ''),
        status=data.get('status', 'todo'),
        priority=data.get('priority', 'medium'),
        created_by_type=data.get('created_by_type', 'user'),
        created_by_key=data.get('created_by_key', 'supervisor'),
        created_by_name=data.get('created_by_name', 'You'),
        assignee_type=assignee_type,
        assignee_key=assignee_key,
        assignee_name=assignee_name,
        department=data.get('department') or _dept_from_assignee(assignee_key),
        parent_id=data.get('parent_id'),
        due_date=due,
        thread_id=data.get('thread_id'),
    )
    db.add(task)
    db.commit()

    # Create notification for founder if task requires approval
    if task.requires_approval:
        from src.database.models import Notification
        db.add(Notification(
            type='task_approval_needed',
            title=f'Approval needed: {task.title[:80]}',
            body=f'Proposed by {task.created_by_name or task.created_by_key} → Assigned to {task.assignee_name or task.assignee_key}',
            link='/inbox',
        ))
        db.commit()

    return jsonify({'ok': True, 'id': task.id, 'title': task.title}), 200


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """Update a task's status, priority, assignee, etc."""
    from flask import g
    from src.database.models import Task
    db = g.db
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return jsonify({'error': 'Not found'}), 404
    data = request.json or {}
    if 'status' in data:
        task.status = data['status']
        if data['status'] == 'done':
            task.completed_at = datetime.utcnow()
    if 'priority' in data:
        task.priority = data['priority']
    if 'title' in data:
        task.title = data['title']
    if 'description' in data:
        task.description = data['description']
    if 'assignee_key' in data:
        task.assignee_key = data['assignee_key']
        task.assignee_type = data.get('assignee_type', task.assignee_type)
        task.assignee_name = data.get('assignee_name', task.assignee_name)
    db.commit()
    return jsonify({'ok': True}), 200


from datetime import datetime


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  TWITTER / X  OAuth 2.0 (PKCE)
# ─────────────────────────────────────────────────────────────────────────────
import secrets
import hashlib
import base64
import requests as _requests

_TWITTER_CLIENT_ID     = os.environ.get('TWITTER_CLIENT_ID', '')
_TWITTER_CLIENT_SECRET = os.environ.get('TWITTER_CLIENT_SECRET', '')
_TWITTER_REDIRECT_URI  = os.environ.get('TWITTER_REDIRECT_URI', 'http://localhost:5000/auth/twitter/callback')
_TWITTER_SCOPES        = 'tweet.read tweet.write users.read media.write offline.access'

# In-memory store for PKCE verifiers keyed by state (single-server, dev only)
_oauth_states: dict = {}


@app.route('/auth/twitter/start')
def twitter_oauth_start():
    """Redirect user to X authorization page. Pass ?agent_id=<id> to link the token to an agent."""
    agent_id = request.args.get('agent_id', '')
    if not _TWITTER_CLIENT_ID:
        return "TWITTER_CLIENT_ID not set in .env", 500

    # PKCE
    verifier  = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = {'verifier': verifier, 'agent_id': agent_id}

    params = {
        'response_type':         'code',
        'client_id':             _TWITTER_CLIENT_ID,
        'redirect_uri':          _TWITTER_REDIRECT_URI,
        'scope':                 _TWITTER_SCOPES,
        'state':                 state,
        'code_challenge':        challenge,
        'code_challenge_method': 'S256',
        # force_login intentionally omitted: forcing a fresh X login loops on
        # "you have to be logged in to X" when third-party cookies are strict.
        # Using the browser's active X session goes straight to "Authorize app".
        # → Log into the TARGET account (e.g. Ting Pulse) in this browser first.
    }
    from urllib.parse import urlencode
    # Use x.com (not twitter.com): post-rebrand the session cookie lives on the
    # x.com domain, and the twitter.com authorize page often can't see it →
    # loops on "you have to be logged in to X". x.com/i/oauth2/authorize shares
    # the active session and goes straight to the Authorize screen.
    url = 'https://x.com/i/oauth2/authorize?' + urlencode(params)
    from flask import redirect
    return redirect(url)


@app.route('/auth/twitter/callback')
def twitter_oauth_callback():
    """X redirects here after user authorizes. Exchanges code for tokens and saves them."""
    from flask import redirect
    from src.database.models import SocialMediaAccount

    code  = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error:
        return redirect(f'/?twitter_error={error}')

    stored = _oauth_states.pop(state, None)
    if not stored:
        return "Invalid or expired OAuth state", 400

    verifier = stored['verifier']
    agent_id = stored.get('agent_id')

    # Exchange code for tokens
    resp = _requests.post(
        'https://api.twitter.com/2/oauth2/token',
        data={
            'grant_type':    'authorization_code',
            'code':          code,
            'redirect_uri':  _TWITTER_REDIRECT_URI,
            'code_verifier': verifier,
        },
        auth=(_TWITTER_CLIENT_ID, _TWITTER_CLIENT_SECRET),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    if not resp.ok:
        return f"Token exchange failed: {resp.text}", 400

    tokens = resp.json()
    access_token  = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token', '')

    # Fetch user info
    me = _requests.get(
        'https://api.twitter.com/2/users/me',
        headers={'Authorization': f'Bearer {access_token}'},
        params={'user.fields': 'id,name,username,public_metrics'},
    ).json().get('data', {})

    username   = me.get('username', 'unknown')
    twitter_id = me.get('id', '')
    followers  = me.get('public_metrics', {}).get('followers_count', 0)

    # Save to DB — update existing or create new
    db = orchestrator.db
    existing = None
    if agent_id:
        existing = db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == int(agent_id),
            SocialMediaAccount.platform == 'twitter',
        ).first()

    if existing:
        existing.username      = username
        existing.account_id    = twitter_id
        existing.access_token  = access_token
        existing.refresh_token = refresh_token
        existing.followers     = followers
    else:
        acct = SocialMediaAccount(
            agent_id      = int(agent_id) if agent_id else None,
            platform      = 'twitter',
            username      = username,
            account_id    = twitter_id,
            access_token  = access_token,
            refresh_token = refresh_token,
            followers     = followers,
        )
        db.add(acct)
    db.commit()

    # Redirect back to agent detail or dashboard
    from urllib.parse import quote
    if agent_id:
        dest = f'/agent-detail.html?id={agent_id}&twitter_connected=1&username={quote(username)}'
    else:
        dest = f'/?twitter_connected=1&username={quote(username)}'
    return redirect(dest)


@app.route('/auth/twitter/disconnect/<int:account_id>', methods=['POST'])
def twitter_disconnect(account_id):
    """Revoke token and remove account from DB."""
    from src.database.models import SocialMediaAccount
    db = orchestrator.db
    acct = db.query(SocialMediaAccount).filter(SocialMediaAccount.id == account_id).first()
    if not acct:
        return jsonify({'error': 'Not found'}), 404

    # Attempt revocation (best-effort)
    if acct.access_token:
        try:
            _requests.post(
                'https://api.twitter.com/2/oauth2/revoke',
                data={'token': acct.access_token, 'token_type_hint': 'access_token'},
                auth=(_TWITTER_CLIENT_ID, _TWITTER_CLIENT_SECRET),
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
            )
        except Exception:
            pass

    db.delete(acct)
    db.commit()
    return jsonify({'message': 'Twitter account disconnected'}), 200


# ═══════════════════════════════════════════
# TIKTOK OAUTH 2.0
# ═══════════════════════════════════════════

_TIKTOK_CLIENT_KEY    = os.environ.get('TIKTOK_CLIENT_KEY', '')
_TIKTOK_CLIENT_SECRET = os.environ.get('TIKTOK_CLIENT_SECRET', '')
_TIKTOK_REDIRECT_URI  = os.environ.get('TIKTOK_REDIRECT_URI', 'http://localhost:5000/auth/tiktok/callback')
_TIKTOK_SCOPES        = 'user.info.basic,video.upload,video.publish'

# Reuse _oauth_states dict from Twitter section (keyed by state, value has platform flag)

@app.route('/auth/tiktok/start')
def tiktok_oauth_start():
    """Redirect user to TikTok authorization page."""
    if not _TIKTOK_CLIENT_KEY:
        return 'TIKTOK_CLIENT_KEY not set in .env', 500

    agent_id = request.args.get('agent_id', '')
    import secrets as _sec
    state = _sec.token_urlsafe(24)
    _oauth_states[state] = {'agent_id': agent_id, 'platform': 'tiktok'}

    from urllib.parse import urlencode
    params = urlencode({
        'client_key':     _TIKTOK_CLIENT_KEY,
        'scope':          _TIKTOK_SCOPES,
        'response_type':  'code',
        'redirect_uri':   _TIKTOK_REDIRECT_URI,
        'state':          state,
    })
    return redirect(f'https://www.tiktok.com/v2/auth/authorize/?{params}')


@app.route('/auth/tiktok/callback')
def tiktok_oauth_callback():
    """TikTok redirects here after user authorizes."""
    from urllib.parse import quote

    error = request.args.get('error')
    if error:
        return redirect(f'/?tiktok_error={quote(error)}')

    code  = request.args.get('code', '')
    state = request.args.get('state', '')

    state_data = _oauth_states.pop(state, None)
    if not state_data or state_data.get('platform') != 'tiktok':
        return redirect('/?tiktok_error=invalid_state')

    agent_id = state_data.get('agent_id', '')

    # Exchange code for tokens
    token_resp = _requests.post(
        'https://open.tiktokapis.com/v2/oauth/token/',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        data={
            'client_key':    _TIKTOK_CLIENT_KEY,
            'client_secret': _TIKTOK_CLIENT_SECRET,
            'code':          code,
            'grant_type':    'authorization_code',
            'redirect_uri':  _TIKTOK_REDIRECT_URI,
        },
        timeout=15,
    )
    token_json = token_resp.json()
    if 'error' in token_json or not token_json.get('access_token'):
        err = token_json.get('error_description') or token_json.get('error') or 'token_exchange_failed'
        return redirect(f'/?tiktok_error={quote(err)}')

    access_token  = token_json['access_token']
    refresh_token = token_json.get('refresh_token', '')
    open_id       = token_json.get('open_id', '')

    # Fetch user info
    display_name = open_id
    followers    = 0
    try:
        me_resp = _requests.get(
            'https://open.tiktokapis.com/v2/user/info/',
            params={'fields': 'open_id,display_name,follower_count'},
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        me_data = me_resp.json().get('data', {}).get('user', {})
        display_name = me_data.get('display_name') or open_id
        followers    = me_data.get('follower_count', 0)
    except Exception:
        pass

    # Save to DB
    from src.database.models import SocialMediaAccount
    db = orchestrator.db
    existing = None
    if agent_id:
        existing = db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == int(agent_id),
            SocialMediaAccount.platform == 'tiktok',
        ).first()

    if existing:
        existing.username      = display_name
        existing.account_id    = open_id
        existing.access_token  = access_token
        existing.refresh_token = refresh_token
        existing.followers     = followers
    else:
        acct = SocialMediaAccount(
            agent_id      = int(agent_id) if agent_id else None,
            platform      = 'tiktok',
            username      = display_name,
            account_id    = open_id,
            access_token  = access_token,
            refresh_token = refresh_token,
            followers     = followers,
        )
        db.add(acct)
    db.commit()

    if agent_id:
        dest = f'/agent-detail.html?id={agent_id}&tiktok_connected=1&username={quote(display_name)}'
    else:
        dest = f'/?tiktok_connected=1&username={quote(display_name)}'
    return redirect(dest)


@app.route('/auth/tiktok/disconnect/<int:account_id>', methods=['POST'])
def tiktok_disconnect(account_id):
    """Revoke TikTok token and remove account from DB."""
    from src.database.models import SocialMediaAccount
    db = orchestrator.db
    acct = db.query(SocialMediaAccount).filter(SocialMediaAccount.id == account_id).first()
    if not acct:
        return jsonify({'error': 'Not found'}), 404

    if acct.access_token:
        try:
            _requests.post(
                'https://open.tiktokapis.com/v2/oauth/revoke/',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data={
                    'client_key':    _TIKTOK_CLIENT_KEY,
                    'client_secret': _TIKTOK_CLIENT_SECRET,
                    'token':         acct.access_token,
                },
                timeout=10,
            )
        except Exception:
            pass

    db.delete(acct)
    db.commit()
    return jsonify({'message': 'TikTok account disconnected'}), 200


# ═══════════════════════════════════════════
# TIKTOK CONTENT POSTING API
# ═══════════════════════════════════════════

@app.route('/api/publish/tiktok', methods=['POST'])
def publish_tiktok():
    """Post content to TikTok via the official Content Posting API.

    Body: {
        agent_id: int,          # which influencer agent to post as
        video_url: str,         # publicly accessible URL to video file
        caption: str,           # post caption / title (max 2200 chars)
        privacy_level: str,     # 'PUBLIC_TO_EVERYONE' | 'MUTUAL_FOLLOW_FRIENDS' | 'SELF_ONLY'
        disable_comment: bool,  # optional
        content_id: int         # optional — link to Content row for status update
    }"""
    from src.database.models import SocialMediaAccount, Content
    data = request.json or {}
    agent_id     = data.get('agent_id')
    video_url    = data.get('video_url', '').strip()
    caption      = data.get('caption', '').strip()[:2200]
    privacy      = data.get('privacy_level', 'PUBLIC_TO_EVERYONE')
    no_comment   = bool(data.get('disable_comment', False))
    content_id   = data.get('content_id')

    if not agent_id or not video_url:
        return jsonify({'error': 'agent_id and video_url are required'}), 400

    # Get stored TikTok token for this agent
    db = orchestrator.db
    acct = db.query(SocialMediaAccount).filter(
        SocialMediaAccount.agent_id == int(agent_id),
        SocialMediaAccount.platform == 'tiktok',
        SocialMediaAccount.access_token != None,
        SocialMediaAccount.access_token != '',
    ).first()
    if not acct:
        return jsonify({'error': 'No TikTok account connected for this agent. Connect via agent detail page.'}), 400

    # Step 1: Initialize the post
    init_resp = _requests.post(
        'https://open.tiktokapis.com/v2/post/publish/video/init/',
        headers={
            'Authorization': f'Bearer {acct.access_token}',
            'Content-Type': 'application/json; charset=UTF-8',
        },
        json={
            'post_info': {
                'title':           caption,
                'privacy_level':   privacy,
                'disable_comment': no_comment,
                'auto_add_music':  True,
            },
            'source_info': {
                'source':    'PULL_FROM_URL',
                'video_url': video_url,
            },
        },
        timeout=20,
    )
    init_data = init_resp.json()

    if init_resp.status_code != 200 or init_data.get('error', {}).get('code', 'ok') != 'ok':
        err = init_data.get('error', {})
        # Handle token expiry — refresh if possible
        if err.get('code') in ('access_token_invalid', 'access_token_expired') and acct.refresh_token:
            refreshed = _tiktok_refresh_token(acct)
            if refreshed:
                return publish_tiktok()  # retry once
        return jsonify({'error': err.get('message', 'TikTok publish failed'), 'raw': init_data}), 400

    publish_id = init_data.get('data', {}).get('publish_id', '')

    # Mark content as published if content_id provided
    if content_id:
        try:
            post = db.query(Content).filter(Content.id == int(content_id)).first()
            if post:
                post.status = 'published'
                post.published_at = __import__('datetime').datetime.utcnow()
                db.commit()
        except Exception:
            pass

    return jsonify({
        'success': True,
        'publish_id': publish_id,
        'platform': 'tiktok',
        'account': acct.username,
        'message': f'Video submitted to TikTok (@{acct.username}). TikTok will process and publish it shortly.',
    }), 200


def _tiktok_refresh_token(acct):
    """Refresh a TikTok access token. Returns True on success."""
    try:
        db = orchestrator.db
        r = _requests.post(
            'https://open.tiktokapis.com/v2/oauth/token/',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={
                'client_key':    _TIKTOK_CLIENT_KEY,
                'client_secret': _TIKTOK_CLIENT_SECRET,
                'grant_type':    'refresh_token',
                'refresh_token': acct.refresh_token,
            },
            timeout=10,
        )
        d = r.json()
        if d.get('access_token'):
            acct.access_token  = d['access_token']
            acct.refresh_token = d.get('refresh_token', acct.refresh_token)
            db.commit()
            return True
    except Exception:
        pass
    return False


@app.route('/api/publish/tiktok/status/<publish_id>', methods=['GET'])
def tiktok_publish_status(publish_id):
    """Check the status of a TikTok publish job."""
    agent_id = request.args.get('agent_id')
    if not agent_id:
        return jsonify({'error': 'agent_id required'}), 400

    from src.database.models import SocialMediaAccount
    acct = orchestrator.db.query(SocialMediaAccount).filter(
        SocialMediaAccount.agent_id == int(agent_id),
        SocialMediaAccount.platform == 'tiktok',
    ).first()
    if not acct:
        return jsonify({'error': 'No TikTok account'}), 400

    r = _requests.post(
        'https://open.tiktokapis.com/v2/post/publish/status/fetch/',
        headers={
            'Authorization': f'Bearer {acct.access_token}',
            'Content-Type': 'application/json; charset=UTF-8',
        },
        json={'publish_id': publish_id},
        timeout=10,
    )
    return jsonify(r.json()), r.status_code


def _resume_orphaned_tasks():
    """On boot, re-dispatch any in_progress tasks orphaned by a prior restart.
    - Top-level tasks (no parent) are re-queued via _execute_task_in_background.
    - Cascade parents reuse existing sub-tasks (handled in _execute_cascade_task).
    - Sub-tasks already done with a deliverable are skipped by _run_sub.
    """
    try:
        from src.database.db import get_db
        from src.database.models import Task
        import threading
        db = get_db()
        _not_archived = (Task.archived == False) | (Task.archived == None)
        orphans = db.query(Task).filter(
            Task.status == 'in_progress',
            Task.parent_id == None,  # only resume top-level — children resume via their parent's cascade
            _not_archived,             # skip archived tasks (user cancelled)
        ).all()
        snapshots = [{
            'id': t.id,
            'assignee_type': t.assignee_type,
            'assignee_key': t.assignee_key,
            'assignee_name': t.assignee_name,
            'title': t.title,
            'description': t.description,
            'priority': t.priority,
        } for t in orphans]
        db.close()
        if not snapshots:
            return
        logging.info(f"[Resume] Re-dispatching {len(snapshots)} orphaned in_progress tasks")
        for snap in snapshots:
            threading.Thread(
                target=_execute_task_in_background,
                args=(snap,),
                name=f"task-resume-{snap['id']}",
                daemon=True,
            ).start()
    except Exception as e:
        logging.warning(f"[Resume] Failed: {e}")


def _start_scheduled_post_publisher():
    """Background loop that publishes scheduled posts when their time arrives.

    Polls every 60s for posts with status='scheduled' AND scheduled_at <= now (UTC).
    For each due post, calls the existing publish route via the Flask test client so
    all publish logic (platform APIs, image uploads, sanitization) is reused exactly.
    """
    import threading, time as _time, logging as _logging

    def _loop():
        from datetime import datetime
        from src.database.db import get_db
        from src.database.models import Content

        _logging.info('[SchedPub] Scheduled-post publisher started (polling every 60s).')
        while True:
            try:
                db = get_db()
                try:
                    from src.database.models import SocialMediaAccount as _SMA
                    now = datetime.utcnow()
                    due = db.query(Content).filter(
                        Content.status == 'scheduled',
                        Content.scheduled_at != None,
                        Content.scheduled_at <= now,
                    ).order_by(Content.scheduled_at.asc()).limit(50).all()

                    # Only publish posts whose agent has a connected account WITH a token
                    # for that platform. Otherwise leave them 'scheduled' (paused) — no
                    # futile retry loop, no burning. They go live the moment an account
                    # is connected.
                    def _plat_key(p):
                        pl = (p.platform or '').lower()
                        return 'twitter' if pl in ('twitter', 'x', 'twitter/x') else pl

                    connected = {}  # (agent_id, platform_key) -> bool
                    skipped = []
                    due_ids = []
                    for p in due:
                        key = (p.agent_id, _plat_key(p))
                        if key not in connected:
                            accts = db.query(_SMA).filter(
                                _SMA.agent_id == p.agent_id,
                                _SMA.access_token.isnot(None),
                            ).all()
                            connected[key] = any(
                                (a.platform or '').lower() in (key[1], 'x', 'twitter/x')
                                if key[1] == 'twitter'
                                else (a.platform or '').lower() == key[1]
                                for a in accts
                            )
                        if connected[key]:
                            due_ids.append(p.id)
                        else:
                            skipped.append(p.id)
                    if skipped:
                        _logging.info(
                            f'[SchedPub] {len(skipped)} due post(s) paused — no connected '
                            f'account yet (e.g. {skipped[:5]}). Will post once connected.'
                        )
                    due_ids = due_ids[:10]
                finally:
                    db.close()

                if due_ids:
                    _logging.info(f'[SchedPub] {len(due_ids)} post(s) due — publishing: {due_ids}')
                    client = app.test_client()
                    for pid in due_ids:
                        try:
                            resp = client.post(f'/api/content/{pid}/publish')
                            status = resp.status_code
                            payload = resp.get_json(silent=True) or {}
                            if 'platform_post_id' in payload:
                                _logging.info(
                                    f'[SchedPub] #{pid} published '
                                    f'(platform_id={payload.get("platform_post_id")})'
                                )
                            elif 'warning' in payload:
                                _logging.warning(
                                    f'[SchedPub] #{pid} publish returned warning: {payload["warning"][:200]}'
                                )
                            else:
                                _logging.warning(f'[SchedPub] #{pid} publish status={status} payload={payload}')
                        except Exception as pe:
                            _logging.error(f'[SchedPub] #{pid} publish crashed: {pe}', exc_info=True)
            except Exception as e:
                _logging.error(f'[SchedPub] Loop error: {e}', exc_info=True)
            _time.sleep(60)

    t = threading.Thread(target=_loop, name='scheduled-publisher', daemon=True)
    t.start()


if __name__ == '__main__':
    # Only auto-resume when running as the server (not when imported by scripts)
    _resume_orphaned_tasks()
    _start_scheduled_post_publisher()
    try:
        from src.automation.ting_pulse_autopilot import start_ting_pulse_autopilot
        start_ting_pulse_autopilot()
    except Exception as _e:
        logging.warning(f'[TingPulse] failed to start autopilot: {_e}')
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
