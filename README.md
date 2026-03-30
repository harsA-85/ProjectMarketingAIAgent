# Autonomous Marketing AI Agent System

An enterprise-grade system for creating and managing autonomous AI agents that handle social media marketing, content creation, community engagement, and performance analytics across multiple platforms.

## 🎯 Features

### Agent Management
- **Create Custom Agents**: Define agents with unique personas, brands, tones of voice, and expertise fields
- **Multi-Platform Support**: Instagram, Twitter/X, and TikTok (extensible to other platforms)
- **AI-Powered Content**: Generate engaging, platform-specific content using Claude API
- **Flexible Architecture**: Single orchestrator managing multiple agents with plans for team managers

### Content Generation
- **AI-Driven Creation**: Uses Claude or other LLM providers for content
- **Platform Optimization**: Tailored content length, format, and style for each platform
- **Draft Management**: Save drafts before publishing
- **Scheduling System**: Schedule posts for optimal posting times

### Community Engagement
- **Automated Interactions**: Like, comment, follow, and reply actions
- **Engagement Planning**: AI-planned engagement strategies per platform
- **Interaction Tracking**: Monitor and analyze all agent interactions
- **Relationship Building**: Build authentic relationships with target audiences

### Analytics & Insights
- **Performance Metrics**: Engagement rates, reach, growth tracking
- **Platform Analytics**: Breakdown by Instagram, Twitter, TikTok
- **Content Performance**: Identify top-performing posts and topics
- **Growth Reports**: Period-based performance analysis
- **Comparative Analytics**: Compare performance across agents

### Dashboard & Monitoring
- **Web Dashboard**: Real-time agent monitoring and control
- **REST API**: Full API for integration and automation
- **Analytics Export**: Download reports and data
- **Agent Comparison**: Side-by-side agent performance analysis

## 📊 System Architecture

```
ProjectMarketingAIAgent/
├── src/
│   ├── orchestrator/          # Main orchestrator managing all agents
│   ├── agents/                # Base agent classes
│   ├── platforms/             # Instagram, Twitter, TikTok integrations
│   ├── content/               # Content generation module
│   ├── engagement/            # Engagement management
│   ├── scheduler/             # Post scheduling system
│   ├── analytics/             # Analytics engine
│   ├── api/                   # LLM provider abstraction
│   ├── database/              # Database models and connection
│   ├── config/                # Configuration management
│   └── utils/                 # Utilities and helpers
├── dashboard/                 # Flask web dashboard
├── config/                    # Configuration files
├── tests/                     # Unit tests
├── main.py                    # CLI interface
└── requirements.txt           # Python dependencies
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ProjectMarketingAIAgent.git
cd ProjectMarketingAIAgent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Copy and setup environment variables
cp .env.example .env

# Edit .env with your API keys
# Required:
# - CLAUDE_API_KEY (or other LLM provider)
# - Platform credentials (Instagram, Twitter, TikTok)
```

### 3. Initialize Database

```bash
# The database initializes automatically on first run
# Or manually:
python -c "from src.database.db import init_db; init_db()"
```

### 4. Create Your First Agent

```bash
# Use the interactive CLI
python main.py

# Select option 1 to create an agent
# Follow the prompts to define:
# - Agent name
# - Brand
# - Persona
# - Tone of voice
# - Fields of expertise
```

### 5. Generate Content

```bash
# Select option 2 from CLI to generate content
# Choose agent, platform, and topic
# Content will be saved as draft
```

### 6. Run the Dashboard

```bash
# Start the web dashboard
python dashboard/app.py

# Access at http://localhost:5000
```

## 💻 CLI Usage

### Main Commands

```bash
python main.py

1. Create New Agent
   - Interactive agent creation with custom persona

2. Generate Content
   - Single content generation for one agent
   - Options to schedule immediately

3. Batch Generate Content
   - Generate multiple posts across agents
   - Multi-platform generation

4. View Dashboard
   - Real-time agent statistics
   - Performance overview

5. View Analytics
   - Detailed performance reports
   - Historical analysis

6. Setup API Keys
   - Configure LLM providers
   - Add Claude, OpenAI, etc.

7. Export Agents
   - Export agent configs to JSON

8. Import Agents
   - Import from configuration files

9. Run Scheduler
   - Execute scheduled posts
```

## 🔌 API Endpoints

### Agents
```
GET    /api/agents              # Get all agents
GET    /api/agents/<id>         # Get specific agent
POST   /api/agents              # Create new agent
```

### Content
```
POST   /api/content/generate    # Generate content
POST   /api/content/batch-generate  # Batch generate
POST   /api/content/<id>/schedule   # Schedule post
```

### Engagement
```
POST   /api/engagement/plan     # Plan engagement activities
```

### Analytics
```
GET    /api/analytics/agent/<id>       # Agent analytics
GET    /api/analytics/performance/<id> # Performance report
```

### Configuration
```
GET    /api/config/llm          # Get LLM config
POST   /api/config/llm          # Set API key
```

### Scheduler
```
POST   /api/scheduler/execute   # Execute due posts
GET    /api/scheduler/posts     # Get scheduled posts
```

## 🔑 API Key Setup

### Claude API (Recommended)
```bash
1. Get API key from https://console.anthropic.com
2. Set in .env: CLAUDE_API_KEY=your_key
3. Or via API: POST /api/config/llm
```

### Twitter/X
```bash
Get credentials from:
https://developer.twitter.com/en/portal/dashboard
Required:
- API_KEY
- API_SECRET
- ACCESS_TOKEN
- ACCESS_TOKEN_SECRET
- BEARER_TOKEN
```

### Instagram
```bash
Get credentials from:
https://developers.facebook.com/
Required:
- APP_ID
- APP_SECRET
- Access Token
```

### TikTok
```bash
Get credentials from:
https://open.tiktok.com/
Required:
- CLIENT_KEY
- CLIENT_SECRET
- Access Token
```

## 📋 Agent Configuration

### Example Agent Config

```json
{
  "name": "TechVlogger_AI",
  "brand": "Tech Innovations Daily",
  "persona": "Enthusiastic tech expert",
  "tone_of_voice": "Educational, friendly, conversational",
  "fields": ["AI", "Machine Learning", "Tech News"],
  "bio": "Your daily source for cutting-edge tech insights",
  "avatar_url": "https://example.com/avatar.jpg"
}
```

### Bulk Import

```bash
# Create agents.json with agent configs
python main.py
# Select option 8 to import agents
```

## 📈 Performance Monitoring

### Metrics Tracked
- **Engagement Rate**: Interactions per post
- **Reach**: Number of impressions
- **Growth**: Follower growth over time
- **Content Performance**: Top performing posts
- **Topic Analysis**: Best performing topics
- **Interaction Types**: Breakdown of interactions

### Export Reports

```bash
# Via API
GET /api/analytics/agent/<id>?days=30

# Via CLI
python main.py -> Select option 5
```

## 🔄 Advanced Features

### Agent Team Manager
Create management hierarchies:
```python
from src.orchestrator.orchestrator import Orchestrator

orchestrator = Orchestrator()

# Create team of agents
team_agents = [
    orchestrator.create_agent(...),
    orchestrator.create_agent(...),
    orchestrator.create_agent(...)
]

# Manage as a team
# (Feature coming in v2)
```

### Multi-LLM Support
Switch between providers:
```python
from src.api.llm_provider import LLMProvider

# Use Claude
llm = LLMProvider(provider='claude')

# Use OpenAI
llm = LLMProvider(provider='openai')

# Switch anytime - both support the same interface
```

### Custom Content Templates
Create brand-specific templates:
```python
agent = orchestrator.get_agent(agent_id)
content_data = agent.generate_content(
    content_type="announcement",
    platform="twitter",
    topic="Product Launch"
)
```

## 🧪 Testing

```bash
# Run tests
pytest tests/

# Run specific test
pytest tests/test_agents.py
```

## 📝 Logging

Logs are saved to `logs/` directory with timestamps:
```
logs/
├── orchestrator_20240101.log
├── agents_20240101.log
└── scheduler_20240101.log
```

Configure log level in `.env`:
```
LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## 🚀 Deployment

### Local Development
```bash
python main.py
python dashboard/app.py
```

### Production

#### Docker
```bash
docker build -t marketing-ai .
docker run -p 5000:5000 --env-file .env marketing-ai
```

#### Kubernetes
See `k8s/` directory for deployment manifests

#### Cloud Deployment
- AWS: Use EC2 + RDS for database
- GCP: Cloud Run + Cloud SQL
- Azure: App Service + SQL Database

## 📚 Documentation

- [Agent Creation Guide](docs/agents.md)
- [Content Generation](docs/content.md)
- [Platform Integration](docs/platforms.md)
- [API Reference](docs/api.md)
- [Analytics Guide](docs/analytics.md)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙋 Support

- Documentation: Check docs/ directory
- Issues: GitHub Issues
- Email: support@example.com

## 🔮 Roadmap

### v1.0 (Current)
- ✅ Core agent system
- ✅ Multi-platform support
- ✅ Content generation
- ✅ Basic analytics

### v1.1 (Next)
- 🔄 AI Agent Manager (team management)
- 🔄 Advanced scheduling
- 🔄 Content calendar
- 🔄 Competitor analysis

### v2.0 (Future)
- Agent collaboration
- Real-time performance dashboards
- ML-based optimal posting times
- Advanced targeting and segmentation
- Custom training data for agents

## ⚡ Performance Tips

1. **Batch Operations**: Use batch content generation
2. **Scheduling**: Pre-schedule posts during off-hours
3. **Analytics**: Analyze weekly for better insights
4. **Engagement**: Spread interactions naturally
5. **Monitoring**: Regular performance reviews

## 🔐 Security

- API keys stored securely in database
- Environment variables for sensitive data
- No credentials in version control
- Rate limiting on API endpoints
- Input validation on all endpoints

## 🎓 Learning Resources

- [Python Best Practices](https://pep8.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Claude API Guide](https://docs.anthropic.com/)

## 📊 System Requirements

- Python 3.8+
- 2GB RAM minimum
- SQLite or PostgreSQL
- API credentials for social platforms
- Claude/OpenAI API key

---

**Created with ❤️ for autonomous marketing**
