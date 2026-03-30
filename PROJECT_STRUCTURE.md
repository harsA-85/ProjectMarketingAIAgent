# Project Structure Overview

Complete file structure and component explanation for the Autonomous Marketing AI Agent System.

## Directory Layout

```
ProjectMarketingAIAgent/
├── src/                          # Core application code
│   ├── __init__.py
│   ├── orchestrator/             # Agent orchestration & management
│   │   ├── __init__.py
│   │   └── orchestrator.py       # Main orchestrator class
│   │
│   ├── agents/                   # AI agent implementations
│   │   ├── __init__.py
│   │   └── base_agent.py         # BaseAgent class for all agents
│   │
│   ├── platforms/                # Social media integrations
│   │   ├── __init__.py
│   │   ├── instagram.py          # Instagram API integration
│   │   ├── twitter.py            # Twitter/X API integration
│   │   └── tiktok.py             # TikTok API integration
│   │
│   ├── content/                  # Content generation
│   │   ├── __init__.py
│   │   └── generator.py          # Content generation engine (stub)
│   │
│   ├── engagement/               # Engagement management
│   │   ├── __init__.py
│   │   └── engagement_manager.py # Engagement operations (stub)
│   │
│   ├── scheduler/                # Post scheduling
│   │   ├── __init__.py
│   │   └── post_scheduler.py     # Scheduling & execution
│   │
│   ├── analytics/                # Analytics engine
│   │   ├── __init__.py
│   │   └── analytics_engine.py   # Performance metrics & reports
│   │
│   ├── api/                      # LLM provider abstraction
│   │   ├── __init__.py
│   │   └── llm_provider.py       # Claude, OpenAI, etc.
│   │
│   ├── database/                 # Database models & connection
│   │   ├── __init__.py
│   │   ├── models.py             # SQLAlchemy ORM models
│   │   └── db.py                 # Database initialization
│   │
│   ├── config/                   # Configuration management
│   │   └── __init__.py
│   │
│   └── utils/                    # Utilities
│       ├── __init__.py
│       └── logger.py             # Logging setup
│
├── dashboard/                    # Web dashboard
│   ├── __init__.py
│   ├── app.py                    # Flask web application
│   ├── templates/                # HTML templates (expand as needed)
│   └── static/                   # CSS, JS, images
│
├── config/                       # Configuration files
│   ├── agents.example.json       # Example agent configurations
│   └── agents.json               # Active agent configs (user-edited)
│
├── tests/                        # Test suite
│   ├── __init__.py
│   ├── test_agents.py            # Agent tests (stub)
│   ├── test_orchestrator.py      # Orchestrator tests (stub)
│   └── test_analytics.py         # Analytics tests (stub)
│
├── logs/                         # Application logs (auto-created)
│   ├── orchestrator_*.log
│   ├── agents_*.log
│   └── scheduler_*.log
│
├── data/                         # Data storage (auto-created)
│   ├── backups/
│   └── exports/
│
├── main.py                       # CLI entry point
├── setup.py                      # Project setup script
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
├── .env                          # Environment variables (user-created)
├── .gitignore                    # Git ignore rules
├── Dockerfile                    # Docker containerization
├── docker-compose.yml            # Docker Compose configuration
├── README.md                     # Full documentation
├── QUICKSTART.md                 # Quick start guide
└── PROJECT_STRUCTURE.md          # This file
```

## Core Components

### 1. Orchestrator (src/orchestrator/)
**Purpose**: Central management hub for all agents

**Files**:
- `orchestrator.py` - Main orchestrator class

**Key Classes**:
- `Orchestrator`: Manages agent creation, content generation, scheduling, and analytics

**Key Methods**:
- `create_agent()` - Create new AI agent
- `generate_content_for_agent()` - Generate content for specific agent
- `batch_generate_content()` - Generate content across multiple agents
- `execute_scheduled_posts()` - Publish due posts
- `get_agent_dashboard()` - Agent-specific metrics
- `get_all_agents_dashboard()` - System-wide overview

### 2. Agents (src/agents/)
**Purpose**: Individual AI agent implementations

**Files**:
- `base_agent.py` - Base class for all agents

**Key Classes**:
- `BaseAgent`: Core agent functionality

**Key Methods**:
- `generate_content()` - AI-powered content creation
- `create_draft_post()` - Create draft in database
- `plan_engagement()` - Plan engagement activities
- `get_analytics()` - Agent-specific metrics

### 3. Platforms (src/platforms/)
**Purpose**: Social media platform integrations

**Files**:
- `instagram.py` - Instagram Graph API
- `twitter.py` - Twitter/X API v2
- `tiktok.py` - TikTok Business API

**Key Classes**:
- `InstagramPlatform` - Instagram integration
- `TwitterPlatform` - Twitter integration
- `TikTokPlatform` - TikTok integration
- `InstagramAuth`, `TwitterAuth`, `TikTokAuth` - OAuth handlers

**Key Methods**:
- `post_content()` - Publish content
- `engage_with_post()` - Like, comment, reply
- `follow_user()` - Follow accounts
- `get_account_stats()` - Account metrics

### 4. Scheduling (src/scheduler/)
**Purpose**: Content scheduling and automatic publishing

**Files**:
- `post_scheduler.py` - Scheduling engine

**Key Classes**:
- `PostScheduler`: Manages post scheduling

**Key Methods**:
- `schedule_post()` - Schedule single post
- `schedule_recurring_posts()` - Setup recurring publishing
- `get_due_posts()` - Get posts ready to publish
- `reschedule_post()` - Change schedule
- `cancel_scheduled_post()` - Cancel publication
- `optimize_posting_times()` - Suggest best times

### 5. Analytics (src/analytics/)
**Purpose**: Performance metrics and insights

**Files**:
- `analytics_engine.py` - Analytics computation

**Key Classes**:
- `AnalyticsEngine`: Metrics calculation

**Key Methods**:
- `calculate_engagement_rate()` - Engagement metrics
- `get_content_performance()` - Post performance
- `get_platform_performance()` - Platform breakdown
- `get_growth_metrics()` - Growth analysis
- `get_agent_comparison()` - Compare agents
- `generate_performance_report()` - Comprehensive report

### 6. Database (src/database/)
**Purpose**: Data persistence

**Files**:
- `models.py` - SQLAlchemy ORM models
- `db.py` - Database connection

**Key Models**:
- `Agent` - Agent configuration
- `SocialMediaAccount` - Connected accounts
- `Content` - Posts and drafts
- `Interaction` - Engagement activities
- `Analytics` - Performance metrics
- `APIConfiguration` - LLM provider keys

### 7. LLM Provider (src/api/)
**Purpose**: Abstraction for multiple AI providers

**Files**:
- `llm_provider.py` - LLM provider interface

**Key Classes**:
- `LLMProvider`: Unified interface for Claude, OpenAI, etc.

**Key Methods**:
- `generate_content()` - Universal content generation
- `set_api_key()` - Store provider credentials
- `list_providers()` - List configured providers

### 8. Dashboard (dashboard/)
**Purpose**: Web interface and REST API

**Files**:
- `app.py` - Flask web application

**Endpoints**:
- `/api/agents` - Agent management
- `/api/content/*` - Content operations
- `/api/engagement/*` - Engagement planning
- `/api/analytics/*` - Performance metrics
- `/api/scheduler/*` - Scheduling control
- `/api/config/*` - Configuration

## Database Schema

### Agent
```
id (PK)
name (unique)
brand
persona
tone_of_voice
avatar_url
bio
fields (JSON array)
is_active
created_at
updated_at
```

### SocialMediaAccount
```
id (PK)
agent_id (FK)
platform (instagram/twitter/tiktok)
username
account_id
access_token
followers
is_verified
last_sync
created_at
```

### Content
```
id (PK)
agent_id (FK)
account_id (FK)
title
body
hashtags (JSON)
mentions (JSON)
media_urls (JSON)
status (draft/scheduled/published/failed)
platform
post_id
scheduled_at
published_at
created_at
```

### Interaction
```
id (PK)
agent_id (FK)
platform
target_username
target_post_id
interaction_type (like/comment/follow/reply)
content
status (pending/completed/failed)
created_at
completed_at
```

### Analytics
```
id (PK)
agent_id (FK)
platform
date
followers
impressions
engagement_rate
posts_published
interactions_completed
top_content (JSON)
metrics (JSON)
```

### APIConfiguration
```
id (PK)
provider (claude/openai/etc)
api_key
model_name
is_active
created_at
```

## Data Flow

### Content Creation Flow
```
User Input
    ↓
Orchestrator.generate_content_for_agent()
    ↓
BaseAgent.generate_content()
    ↓
LLMProvider.generate_content() [Claude API]
    ↓
Content stored as Draft
    ↓
Database (Content table)
```

### Content Publishing Flow
```
Scheduled Post Time Reached
    ↓
PostScheduler.get_due_posts()
    ↓
Platform.post_content() [Instagram/Twitter/TikTok]
    ↓
Status: published
    ↓
Database updated
```

### Analytics Flow
```
Published Posts & Interactions
    ↓
AnalyticsEngine.calculate_engagement_rate()
    ↓
AnalyticsEngine.generate_performance_report()
    ↓
Metrics stored in Analytics table
    ↓
Dashboard display
```

## Configuration Files

### .env
Environment variables for:
- Database connection
- API keys (Claude, OpenAI, Twitter, Instagram, TikTok)
- Platform credentials
- Application settings

### config/agents.json
Agent configurations:
```json
{
  "name": "Agent name",
  "brand": "Brand name",
  "persona": "Agent persona",
  "tone_of_voice": "Tone",
  "fields": ["field1", "field2"],
  "bio": "Agent bio",
  "avatar_url": "URL"
}
```

## Requirements

**Python Packages** (see requirements.txt):
- anthropic - Claude API
- sqlalchemy - ORM
- flask - Web framework
- requests - HTTP
- tweepy - Twitter API
- schedule - Scheduling
- instagrapi - Instagram API
- And more...

## Extending the System

### Adding a New Social Platform
1. Create new file in `src/platforms/platform_name.py`
2. Implement `PlatformName` class with required methods
3. Update `BaseAgent._get_platform_config()`
4. Add API keys to `.env`

### Adding New Analytics Metrics
1. Add calculation method to `AnalyticsEngine`
2. Update `generate_performance_report()`
3. Expose via API endpoint

### Adding Custom Content Generation
1. Create custom agent subclass
2. Override `generate_content()` method
3. Use in orchestrator

### Adding New LLM Provider
1. Implement in `LLMProvider._initialize_client()`
2. Add provider-specific generation method
3. Store API key configuration

## Performance Considerations

- **Database**: SQLite for development, PostgreSQL for production
- **Scheduling**: Background scheduler runs independent of main app
- **API Calls**: Rate limiting per platform (respect their limits)
- **Storage**: Store media URLs, not actual files
- **Caching**: Consider caching popular agent configs

## Security Notes

- Store API keys in `.env`, never in code
- Use environment variables for sensitive data
- Validate all user input
- Use prepared statements (SQLAlchemy handles this)
- Implement rate limiting on API endpoints
- Hash sensitive data where applicable

---

**For more details, see README.md and individual file docstrings**
