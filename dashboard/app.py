from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import os
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

app = Flask(__name__, static_folder=os.path.dirname(__file__))
CORS(app)

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

orchestrator = None

autopilot      = None
ai_auto_sched  = None
workflow_engine = None

def _bootstrap():
    """Initialize orchestrator, autopilot, scheduler, workflow engine at startup."""
    global orchestrator, autopilot, ai_auto_sched, workflow_engine
    init_db()
    from src.database.db import seed_editorial_team, get_db
    seed_editorial_team()

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
    return send_file(os.path.join(os.path.dirname(__file__), 'newsroom.html'))


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
        posts = orchestrator.db.query(Content).filter(Content.agent_id == agent_id).all()
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
    limits = {'twitter': 270, 'instagram': 2200, 'tiktok': 2200}
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

        # Find a connected account for this agent + platform
        account = orchestrator.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == post.agent_id,
            SocialMediaAccount.platform == post.platform
        ).first()

        # --- Helper: save base64 images to disk and return public URLs ---
        def upload_to_catbox(filepath):
            """Upload image to catbox.moe — free, anonymous, permanent CDN. Returns public URL."""
            boundary = uuid.uuid4().hex
            with open(filepath, 'rb') as f:
                file_data = f.read()
            filename = os.path.basename(filepath)
            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="reqtype"\r\n\r\nfileupload\r\n'
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="fileToUpload"; filename="{filename}"\r\n'
                f'Content-Type: image/jpeg\r\n\r\n'
            ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()
            req = urllib.request.Request('https://catbox.moe/user/api.php', data=body)
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            with urllib.request.urlopen(req, timeout=30) as r:
                url = r.read().decode().strip()
            if not url.startswith('https://'):
                raise RuntimeError(f"catbox.moe upload failed: {url}")
            return url

        def save_images_to_disk(media_urls):
            saved = []
            media_dir = os.path.join(os.path.dirname(__file__), 'static', 'media')
            os.makedirs(media_dir, exist_ok=True)
            for b64 in media_urls:
                if b64.startswith('data:'):
                    header, data = b64.split(',', 1)
                    ext = 'jpg' if 'jpeg' in header or 'jpg' in header else 'png'
                else:
                    data = b64
                    ext = 'jpg'
                fname = f"{uuid.uuid4().hex}.{ext}"
                fpath = os.path.join(media_dir, fname)
                with open(fpath, 'wb') as f:
                    f.write(base64.b64decode(data))
                # Upload to catbox.moe for a reliable public CDN URL (bypasses ngrok/localhost issues)
                public_url = upload_to_catbox(fpath)
                import logging
                logging.warning(f"[PUBLISH] Uploaded image to CDN: {public_url}")
                saved.append(public_url)
            return saved

        # --- Instagram publishing ---
        def ig_api_call(url, data=None):
            """Make an Instagram Graph API call, raising with the full error body on failure"""
            import urllib.error
            try:
                if data:
                    req = urllib.request.Request(url, data=data, method='POST')
                else:
                    req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=15) as r:
                    return jsonlib.loads(r.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', errors='replace')
                try:
                    err_json = jsonlib.loads(body)
                    msg = err_json.get('error', {}).get('message', body)
                    code = err_json.get('error', {}).get('code', e.code)
                    raise RuntimeError(f"Instagram API error {code}: {msg}")
                except (jsonlib.JSONDecodeError, KeyError):
                    raise RuntimeError(f"Instagram API HTTP {e.code}: {body[:300]}")

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
            return True, result.get('id', 'published')

        # --- Execute platform publish ---
        platform_result = None
        platform_error = None

        if account and account.access_token:
            try:
                if post.platform == 'instagram':
                    ok, platform_result = publish_instagram(post, account.access_token)
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
            # Actually published — mark as published
            post.status = 'published'
            post.published_at = datetime.utcnow()
            orchestrator.db.commit()
            return jsonify({
                'content_id': content_id,
                'message': 'Post published to Instagram!',
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


def _clean_body_for_publish(raw):
    """Extract clean text from potentially JSON-encoded body"""
    import json as j
    if not raw:
        return ''
    text = raw.strip()
    if text.startswith('{'):
        try:
            parsed = j.loads(text.replace("\\'", "'"))
            text = parsed.get('caption') or parsed.get('body') or raw
        except Exception:
            import re
            m = re.search(r'"caption"\s*:\s*"([\s\S]+?)"\s*,\s*"hashtags', text)
            if m:
                text = m.group(1)
    return text.replace('\\n', '\n').replace('\\t', '\t')


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
    """Delete a post"""
    try:
        from src.database.models import Content
        post = orchestrator.db.query(Content).filter(Content.id == content_id).first()
        if not post:
            return jsonify({'error': 'Post not found'}), 404
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
    """List all workflow runs."""
    from src.database.models import WorkflowRun
    runs = orchestrator.db.query(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(50).all()
    return jsonify([{
        'id': r.id,
        'status': r.status,
        'current_step': r.current_step,
        'target_agent_ids': r.target_agent_ids,
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

    return jsonify({
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
            'format_type': a.format_type,
            'platform': a.platform,
            'body': a.body[:300] + '...' if a.body and len(a.body) > 300 else (a.body or ''),
            'hashtags': _parse(a.hashtags),
            'status': a.status,
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

    orchestrator.db.commit()
    return jsonify({'pushed': len(created), 'posts': created}), 200


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
You lead a team of 9 AI specialists who produce premium content through a 5-step pipeline:
Signal → Angle → Co-Creation → Fact-Check → Atomization.

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

WORKFLOW LAUNCH:
You can launch the full editorial pipeline (Signal > Angle > Co-Creation > Fact-Check > Atomization) by including:
```workflow
{"topics": ["topic 1", "topic 2"], "target_agents": [1, 2, 3]}
```
- topics: list of content themes/topics to explore
- target_agents: list of agent IDs (1-11) who will receive the atomized content. Use all 11 if not specified.
- The pipeline runs autonomously: Head of Intelligence gathers signals, you set the angle, copywriters + prompt engineers co-create, fact-checkers validate, distribution specialist atomizes for each agent.

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


def _build_team_system_prompt(db, member):
    """Build a rich system prompt for a team member chat."""
    from src.database.models import TeamMember, WorkflowRun, Agent, Content, Task
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

    return f"""{member.system_prompt}

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

{TASK_INSTRUCTION}"""


def _build_agent_system_prompt(agent):
    """Build a system prompt for chatting with a publishing agent."""
    return (
        f"You are {agent.name}, a social media content creator for {agent.brand}.\n"
        f"Persona: {agent.persona}\n"
        f"Tone: {agent.tone_of_voice}\n"
        f"Expertise: {', '.join(agent.fields or [])}\n"
        f"Bio: {agent.bio or ''}\n\n"
        f"You're chatting with your supervisor. Be helpful, stay in character, respond concisely.\n"
        f"{TASK_INSTRUCTION}"
    )


def _extract_and_create_tasks(db, reply_text, thread_id, entity_type, entity_key, entity_name):
    """Parse ```tasks JSON from AI reply, create Task rows, return (clean_text, tasks_created)."""
    import re, json
    from src.database.models import Task, TeamMember, Agent
    pattern = r'```tasks\s*\n?(.*?)\n?```'
    match = re.search(pattern, reply_text, re.DOTALL)
    if not match:
        return reply_text, []

    clean_text = re.sub(pattern, '', reply_text, flags=re.DOTALL).strip()
    created = []
    try:
        task_list = json.loads(match.group(1))
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
                thread_id=thread_id,
                due_date=due,
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

    if not user_msg or not entity_type or not entity_key:
        return jsonify({'error': 'message, entity_type, entity_key required'}), 400

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
        sys_prompt = _build_agent_system_prompt(entity)
    else:
        return jsonify({'error': 'entity_type must be team_member or agent'}), 400

    # Generate thread_id if new
    if not thread_id:
        thread_id = f"chat_{entity_type}_{entity_key}_{uuid.uuid4().hex[:8]}"

    # Save user message
    user_row = InternalMessage(
        from_type='user', from_key='supervisor', from_name='You', from_emoji='',
        body=user_msg, msg_type='chat', thread_id=thread_id, is_read=True
    )
    db.add(user_row)
    db.commit()

    # Build conversation history (last 20 msgs)
    history = db.query(InternalMessage).filter(
        InternalMessage.thread_id == thread_id
    ).order_by(InternalMessage.created_at.desc()).limit(20).all()
    history.reverse()

    conv_lines = []
    for h in history[:-1]:  # exclude the just-added user msg (we'll send it as prompt)
        role = 'User' if h.from_type == 'user' else name
        conv_lines.append(f"{role}: {h.body}")
    conv_context = '\n'.join(conv_lines)

    prompt = f"{conv_context}\nUser: {user_msg}\n{name}:" if conv_context else user_msg

    try:
        from src.api.llm_provider import LLMProvider
        llm = LLMProvider(provider=provider, model=model)
        reply = llm.generate_content(
            prompt=prompt,
            max_tokens=600,
            temperature=temp,
            system_prompt=sys_prompt
        )

        # Extract tasks from reply (if AI created any)
        clean_reply, tasks_created = _extract_and_create_tasks(
            db, reply, thread_id, entity_type, entity_key, name
        )

        # Extract workflow launch (if AI triggered one)
        clean_reply, workflow_launched = _extract_and_launch_workflow(clean_reply)

        # Extract hire proposals (if AI proposed hiring)
        clean_reply, hires_proposed = _extract_hire_proposals(clean_reply)

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
        }), 200
    except Exception as e:
        return jsonify({'error': f'{name} is unavailable: {str(e)}'}), 500


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
    if assignee:
        q = q.filter(Task.assignee_key == assignee)
    if status:
        q = q.filter(Task.status == status)
    if parent:
        q = q.filter(Task.parent_id == int(parent))
    elif not request.args.get('all'):
        q = q.filter(Task.parent_id == None)  # top-level only by default
    tasks = q.order_by(Task.created_at.desc()).limit(100).all()

    def task_dict(t):
        subtasks = db.query(Task).filter(Task.parent_id == t.id).all()
        return {
            'id': t.id, 'title': t.title, 'description': t.description,
            'status': t.status, 'priority': t.priority,
            'created_by_type': t.created_by_type, 'created_by_key': t.created_by_key,
            'created_by_name': t.created_by_name,
            'assignee_type': t.assignee_type, 'assignee_key': t.assignee_key,
            'assignee_name': t.assignee_name,
            'parent_id': t.parent_id,
            'due_date': t.due_date.isoformat() if t.due_date else None,
            'completed_at': t.completed_at.isoformat() if t.completed_at else None,
            'thread_id': t.thread_id,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'subtask_count': len(subtasks),
            'subtasks_done': sum(1 for s in subtasks if s.status == 'done'),
        }
    return jsonify({'tasks': [task_dict(t) for t in tasks]}), 200


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
        parent_id=data.get('parent_id'),
        due_date=due,
        thread_id=data.get('thread_id'),
    )
    db.add(task)
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


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
