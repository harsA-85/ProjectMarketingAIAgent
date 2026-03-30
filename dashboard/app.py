from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator.orchestrator import Orchestrator
from src.database.db import init_db
from src.api.llm_provider import LLMProvider

app = Flask(__name__)
CORS(app)

orchestrator = None


@app.before_request
def initialize():
    """Initialize orchestrator on first request"""
    global orchestrator
    if orchestrator is None:
        init_db()
        orchestrator = Orchestrator()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Marketing AI Agent System is running'}), 200


# ==================== AGENTS ====================

@app.route('/api/agents', methods=['GET'])
def get_agents():
    """Get all agents"""
    dashboard = orchestrator.get_all_agents_dashboard()
    return jsonify(dashboard), 200


@app.route('/api/agents/<int:agent_id>', methods=['GET'])
def get_agent(agent_id):
    """Get specific agent dashboard"""
    try:
        dashboard = orchestrator.get_agent_dashboard(agent_id)
        return jsonify(dashboard), 200
    except ValueError:
        return jsonify({'error': 'Agent not found'}), 404


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


# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
