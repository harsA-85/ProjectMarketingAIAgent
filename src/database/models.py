from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, JSON, ForeignKey, Table, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref
from datetime import datetime
import enum

Base = declarative_base()


class Agent(Base):
    __tablename__ = 'agents'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    brand = Column(String(255), nullable=False)
    persona = Column(String(255), nullable=False)
    tone_of_voice = Column(String(255), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    fields = Column(JSON, default=[])  # List of topics/fields agent focuses on
    image_style = Column(String(255), nullable=True, default='ultra realistic photography')  # Visual style for AI images

    # LLM configuration per agent
    llm_provider = Column(String(50), default='claude')
    llm_model    = Column(String(100), default='claude-sonnet-4-6')

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Autopilot — content engine
    autopilot_enabled       = Column(Boolean, default=False)
    autopilot_posts_per_day = Column(Integer, default=1)
    autopilot_mode          = Column(String(20), default='draft')   # 'draft' | 'publish'
    autopilot_platforms     = Column(JSON, default=['instagram'])
    autopilot_last_run      = Column(DateTime, nullable=True)

    # AI Auto — browser engagement (Playwright)
    ai_auto_enabled  = Column(Boolean, default=False)
    ai_auto_status   = Column(String(200), default='idle')
    ai_auto_ig_user  = Column(String(255), nullable=True)
    ai_auto_ig_pass  = Column(String(255), nullable=True)
    ai_auto_targets  = Column(Text, nullable=True)          # JSON list of hashtags
    ai_auto_proxy    = Column(String(500), nullable=True)   # http://user:pass@host:port

    # Relationships
    accounts = relationship('SocialMediaAccount', back_populates='agent')
    content = relationship('Content', back_populates='agent')
    interactions = relationship('Interaction', back_populates='agent')
    analytics = relationship('Analytics', back_populates='agent')

    def __repr__(self):
        return f"<Agent {self.name}>"


class SocialMediaAccount(Base):
    __tablename__ = 'social_media_accounts'

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('agents.id'), nullable=False)
    platform = Column(String(50), nullable=False)  # 'instagram', 'twitter', 'tiktok'
    username = Column(String(255), nullable=False)
    account_id = Column(String(255), nullable=True)
    access_token = Column(String(500), nullable=True)
    refresh_token = Column(String(500), nullable=True)

    followers = Column(Integer, default=0)
    is_verified = Column(Boolean, default=False)
    last_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship('Agent', back_populates='accounts')
    posts = relationship('Content', back_populates='account')

    def __repr__(self):
        return f"<SocialMediaAccount {self.platform}:{self.username}>"


class Content(Base):
    __tablename__ = 'content'

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('agents.id'), nullable=False)
    account_id = Column(Integer, ForeignKey('social_media_accounts.id'), nullable=True)

    title = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)
    hashtags = Column(JSON, default=[])
    mentions = Column(JSON, default=[])
    media_urls = Column(JSON, default=[])

    status = Column(String(50), default='draft')  # draft, scheduled, published, failed
    platform = Column(String(50), nullable=False)
    post_id = Column(String(255), nullable=True)  # Platform's post ID

    scheduled_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship('Agent', back_populates='content')
    account = relationship('SocialMediaAccount', back_populates='posts')

    def __repr__(self):
        return f"<Content {self.id}:{self.platform}>"


class Interaction(Base):
    __tablename__ = 'interactions'

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('agents.id'), nullable=False)
    platform = Column(String(50), nullable=False)

    target_username = Column(String(255), nullable=False)
    target_post_id = Column(String(255), nullable=True)
    interaction_type = Column(String(50), nullable=False)  # like, comment, follow, reply
    content = Column(Text, nullable=True)

    status = Column(String(50), default='pending')  # pending, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    agent = relationship('Agent', back_populates='interactions')

    def __repr__(self):
        return f"<Interaction {self.interaction_type}:{self.target_username}>"


class Analytics(Base):
    __tablename__ = 'analytics'

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('agents.id'), nullable=False)
    platform = Column(String(50), nullable=False)

    date = Column(DateTime, default=datetime.utcnow)
    followers = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)

    posts_published = Column(Integer, default=0)
    interactions_completed = Column(Integer, default=0)

    top_content = Column(JSON, default=[])  # List of best performing posts
    metrics = Column(JSON, default={})  # Custom metrics

    agent = relationship('Agent', back_populates='analytics')

    def __repr__(self):
        return f"<Analytics {self.agent_id}:{self.platform}>"


class APIConfiguration(Base):
    __tablename__ = 'api_configurations'

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False)  # 'claude', 'openai', etc.
    api_key = Column(String(500), nullable=False)
    model_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<APIConfiguration {self.provider}>"


# ═══════════════════════════════════════════════════════════════
# EDITORIAL TEAM — "The High-Performance Unit"
# ═══════════════════════════════════════════════════════════════

class Notification(Base):
    """In-app notifications for the supervisor."""
    __tablename__ = 'notifications'

    id          = Column(Integer, primary_key=True)
    type        = Column(String(50), nullable=False)   # post_scheduled, workflow_completed, workflow_failed, content_ready
    title       = Column(String(500), nullable=False)
    body        = Column(Text, nullable=True)
    link        = Column(String(500), nullable=True)    # URL to navigate to
    agent_id    = Column(Integer, ForeignKey('agents.id'), nullable=True)
    workflow_run_id = Column(Integer, nullable=True)
    is_read     = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Notification {self.type}: {self.title[:40]}>"


class CompanyVision(Base):
    """Single-row company vision — the north star for all agents."""
    __tablename__ = 'company_vision'

    id              = Column(Integer, primary_key=True)
    mission         = Column(Text, default='')          # One-liner
    vision_statement = Column(Text, default='')         # Full vision doc
    values          = Column(Text, default='[]')        # JSON string of core values
    milestones      = Column(Text, default='[]')        # JSON [{title, target_date, status}]
    okrs            = Column(Text, default='[]')        # JSON [{objective, key_results}]
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by      = Column(String(100), default='supervisor')

    def __repr__(self):
        return f"<CompanyVision: {self.mission[:50]}>"


class Task(Base):
    """Tasks assigned to/by team members and agents — startup-style hierarchy."""
    __tablename__ = 'tasks'

    id             = Column(Integer, primary_key=True)
    title          = Column(String(500), nullable=False)
    description    = Column(Text, nullable=True)
    status         = Column(String(20), default='todo')        # todo, in_progress, done, blocked
    priority       = Column(String(10), default='medium')      # low, medium, high, urgent
    # Who created the task
    created_by_type = Column(String(20), default='user')       # 'user', 'team_member', 'agent'
    created_by_key  = Column(String(50), default='supervisor')
    created_by_name = Column(String(255), default='You')
    # Who is assigned
    assignee_type  = Column(String(20), nullable=False)        # 'team_member', 'agent'
    assignee_key   = Column(String(50), nullable=False)        # role_key or agent id
    assignee_name  = Column(String(255), nullable=False)
    # Hierarchy — parent task for subtask delegation
    parent_id      = Column(Integer, ForeignKey('tasks.id'), nullable=True)
    # Timeline
    due_date       = Column(DateTime, nullable=True)
    completed_at   = Column(DateTime, nullable=True)
    # Approval flow — cofounder-proposed tasks need sign-off before activation
    requires_approval = Column(Boolean, default=False)
    approved_at    = Column(DateTime, nullable=True)
    # Context
    thread_id      = Column(String(100), nullable=True)        # chat thread that spawned this
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subtasks = relationship('Task', backref=backref('parent', remote_side='Task.id'), lazy='dynamic')

    def __repr__(self):
        return f"<Task {self.id}: {self.title[:40]}>"


class InternalMessage(Base):
    """Internal messages/emails between user and AI team members or agents."""
    __tablename__ = 'internal_messages'

    id          = Column(Integer, primary_key=True)
    from_type   = Column(String(20), nullable=False)     # 'team_member', 'agent', 'user'
    from_key    = Column(String(50), nullable=False)      # role_key, 'agent_3', or 'supervisor'
    from_name   = Column(String(255), nullable=False)
    from_emoji  = Column(String(10), default='')
    subject     = Column(String(500), nullable=True)      # for emails; null for chat
    body        = Column(Text, nullable=False)
    msg_type    = Column(String(20), default='chat')      # 'email' or 'chat'
    thread_id   = Column(String(100), nullable=False)     # groups conversation
    is_read     = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<InternalMessage {self.msg_type} from {self.from_name}>"


class TeamMember(Base):
    """An AI editorial team role (EIC, Creative Director, etc.)"""
    __tablename__ = 'team_members'

    id          = Column(Integer, primary_key=True)
    role_key    = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    role_title  = Column(String(255), nullable=False)
    emoji       = Column(String(10), default='🤖')
    team        = Column(String(50), default='editorial')  # editorial, production, distribution
    reports_to  = Column(String(50), nullable=True)        # role_key of manager
    system_prompt = Column(Text, nullable=False)
    llm_provider = Column(String(50), default='claude')
    llm_model    = Column(String(100), default='claude-sonnet-4-6')
    temperature  = Column(Float, default=0.7)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<TeamMember {self.role_key}>"


class WorkflowRun(Base):
    """One execution of the 5-step editorial pipeline."""
    __tablename__ = 'workflow_runs'

    id              = Column(Integer, primary_key=True)
    status          = Column(String(30), default='pending')      # pending|running|completed|failed
    current_step    = Column(String(30), default='signal')       # signal|angle|co_creation|fact_check|atomization
    target_agent_ids = Column(JSON, default=[])                  # which agents receive output
    topic_seeds     = Column(JSON, default=[])                   # optional topic hints
    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    error_message   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    # Relationships
    trend_report    = relationship('TrendReport', back_populates='workflow_run', uselist=False)
    content_brief   = relationship('ContentBrief', back_populates='workflow_run', uselist=False)
    master_content  = relationship('MasterContent', back_populates='workflow_run', uselist=False)
    atomized_content = relationship('AtomizedContent', back_populates='workflow_run')
    step_logs       = relationship('WorkflowStepLog', back_populates='workflow_run',
                                   order_by='WorkflowStepLog.id')

    def __repr__(self):
        return f"<WorkflowRun {self.id} [{self.status}]>"


class WorkflowStepLog(Base):
    """Audit log for each pipeline step execution."""
    __tablename__ = 'workflow_step_logs'

    id              = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey('workflow_runs.id'), nullable=False)
    step_name       = Column(String(30), nullable=False)
    team_member_role = Column(String(50), nullable=False)
    input_summary   = Column(Text, nullable=True)
    output_summary  = Column(Text, nullable=True)
    status          = Column(String(20), default='pending')      # pending|running|completed|failed
    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    llm_tokens_used = Column(Integer, default=0)

    workflow_run = relationship('WorkflowRun', back_populates='step_logs')

    def __repr__(self):
        return f"<StepLog {self.step_name}:{self.status}>"


class TrendReport(Base):
    """Step 1 output: intelligence scan results."""
    __tablename__ = 'trend_reports'

    id              = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey('workflow_runs.id'), nullable=False)
    report_date     = Column(DateTime, default=datetime.utcnow)
    anchor_points   = Column(Text, default='[]')  # JSON string
    raw_signals     = Column(Text, default='[]')  # JSON string
    market_context  = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    workflow_run = relationship('WorkflowRun', back_populates='trend_report')

    def __repr__(self):
        return f"<TrendReport run={self.workflow_run_id}>"


class ContentBrief(Base):
    """Step 2 output: editorial angle + visual direction."""
    __tablename__ = 'content_briefs'

    id              = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey('workflow_runs.id'), nullable=False)
    chosen_angle    = Column(Text, nullable=False)
    headline        = Column(String(500), nullable=True)
    narrative_hook  = Column(Text, nullable=True)
    visual_direction = Column(Text, nullable=True)
    target_platforms = Column(Text, default='[]')  # JSON string
    tone_guidelines = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    workflow_run = relationship('WorkflowRun', back_populates='content_brief')

    def __repr__(self):
        return f"<ContentBrief run={self.workflow_run_id}>"


class MasterContent(Base):
    """Steps 3+4 output: the master piece before atomization."""
    __tablename__ = 'master_content'

    id              = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey('workflow_runs.id'), nullable=False)
    headline        = Column(String(500), nullable=False)
    body            = Column(Text, nullable=False)
    key_points      = Column(Text, default='[]')    # JSON string
    visual_assets   = Column(Text, default='[]')    # JSON string - base64 images
    image_prompts   = Column(Text, default='[]')    # JSON string
    fact_check_notes = Column(Text, default='[]')   # JSON string
    fact_check_passed = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    workflow_run = relationship('WorkflowRun', back_populates='master_content')

    def __repr__(self):
        return f"<MasterContent run={self.workflow_run_id}>"


class AtomizedContent(Base):
    """Step 5 output: one platform variant per target agent."""
    __tablename__ = 'atomized_content'

    id              = Column(Integer, primary_key=True)
    workflow_run_id = Column(Integer, ForeignKey('workflow_runs.id'), nullable=False)
    agent_id        = Column(Integer, ForeignKey('agents.id'), nullable=False)
    content_id      = Column(Integer, ForeignKey('content.id'), nullable=True)  # filled on approval
    format_type     = Column(String(50), nullable=False)   # twitter_thread, ig_carousel, linkedin_post, tiktok_script, newsletter, etc.
    platform        = Column(String(50), nullable=False)
    body            = Column(Text, nullable=False)
    hashtags        = Column(Text, default='[]')   # JSON string
    media_urls      = Column(Text, default='[]')   # JSON string
    status          = Column(String(30), default='draft')  # draft|approved|pushed_to_agent
    created_at      = Column(DateTime, default=datetime.utcnow)

    workflow_run = relationship('WorkflowRun', back_populates='atomized_content')

    def __repr__(self):
        return f"<AtomizedContent {self.format_type} agent={self.agent_id}>"
