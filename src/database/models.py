from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, JSON, ForeignKey, Table, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
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

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
