# Quick Start Guide

Get your Autonomous Marketing AI Agent System up and running in 5 minutes!

## Prerequisites

- Python 3.8+
- pip or conda
- Claude API key (free tier available)

## Installation (2 minutes)

```bash
# 1. Clone or download the project
cd ProjectMarketingAIAgent

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run setup script
python setup.py
```

## Configuration (1 minute)

```bash
# 1. Edit .env file
# Set your Claude API key:
CLAUDE_API_KEY=sk-ant-xxxxx

# Save and close
```

## Create Your First Agent (1 minute)

```bash
python main.py

# Select option: 1 (Create New Agent)
# Enter when prompted:
#   Agent name: MyBrand_AI
#   Brand name: My Brand
#   Agent persona: Friendly marketing expert
#   Tone of voice: Conversational and helpful
#   Fields: Marketing, Brand Building, Social Media
#   Bio: (optional, press enter)
#   Avatar URL: (optional, press enter)

# Agent created! Note the ID
```

## Generate Your First Content (1 minute)

```bash
python main.py

# Select option: 2 (Generate Content)
# Enter:
#   Agent ID: [your agent ID from above]
#   Platform: twitter
#   Topic: Marketing
#   Schedule for later? n

# Content generated! Check it in the dashboard
```

## View Your Dashboard

### Option A: Web Dashboard
```bash
python dashboard/app.py
# Open browser to: http://localhost:5000
```

### Option B: CLI Dashboard
```bash
python main.py
# Select option: 4 (View Dashboard)
# Enter 0 to see all agents
```

## Next Steps

### Generate More Content
```bash
python main.py
# Option 3: Batch Generate Content
# Generate for multiple agents and platforms at once
```

### Schedule Posts
```bash
python main.py
# Option 2: Generate Content
# Select "Schedule for later? y"
# Enter hours from now to schedule
```

### View Analytics
```bash
python main.py
# Option 5: View Analytics
# Enter agent ID and period
```

### Setup Additional API Keys
```bash
python main.py
# Option 6: Setup API Keys
# Add OpenAI, Twitter, Instagram, or TikTok
```

## Useful CLI Commands

```bash
# Create agent
python main.py -> 1

# Generate one post
python main.py -> 2

# Generate multiple posts
python main.py -> 3

# View dashboard
python main.py -> 4

# View analytics
python main.py -> 5

# Setup API keys
python main.py -> 6

# Export agents
python main.py -> 7

# Import agents
python main.py -> 8

# Run scheduler (auto-publish)
python main.py -> 9
```

## API Usage Examples

### Create Agent via API
```bash
curl -X POST http://localhost:5000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TechAgent",
    "brand": "TechBrand",
    "persona": "Tech expert",
    "tone_of_voice": "Professional",
    "fields": ["AI", "Tech"],
    "bio": "Tech focused agent"
  }'
```

### Generate Content via API
```bash
curl -X POST http://localhost:5000/api/content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": 1,
    "platform": "twitter",
    "topic": "AI Trends"
  }'
```

### Get Analytics via API
```bash
curl http://localhost:5000/api/analytics/agent/1
```

## Troubleshooting

### "No module named 'src'"
```bash
# Make sure you're in the project root directory
cd ProjectMarketingAIAgent
```

### "CLAUDE_API_KEY not found"
```bash
# Check your .env file
cat .env
# Make sure CLAUDE_API_KEY is set
```

### Database errors
```bash
# Reinitialize database
rm marketing_ai.db
python -c "from src.database.db import init_db; init_db()"
```

### Port 5000 already in use
```bash
# Use a different port
python -m flask run --port 5001
```

## Docker Setup (Alternative)

```bash
# Build image
docker build -t marketing-ai .

# Run container
docker run -p 5000:5000 \
  -e CLAUDE_API_KEY=sk-ant-xxxxx \
  marketing-ai

# Or use docker-compose
docker-compose up -d
```

## File Structure

```
ProjectMarketingAIAgent/
├── main.py                 # CLI interface
├── setup.py               # Setup script
├── requirements.txt       # Dependencies
├── .env                   # Configuration (edit this!)
├── README.md              # Full documentation
├── QUICKSTART.md          # This file
├── src/                   # Source code
├── config/                # Configuration files
├── dashboard/             # Web dashboard
└── logs/                  # Application logs
```

## Tips for Success

1. **Start small**: Create 1-2 agents first
2. **Test content**: Review generated content before scheduling
3. **Monitor analytics**: Check performance weekly
4. **Iterate**: Adjust agent personas based on results
5. **Batch operations**: Use batch generation for efficiency
6. **Schedule strategically**: Posts at optimal times get more engagement

## Common Workflows

### Daily Content Creation
```bash
python main.py
# Option 3: Batch Generate Content
# Generate 1 post per agent, all platforms
# Option 9: Run Scheduler (to auto-publish)
```

### Weekly Analytics Review
```bash
python main.py
# Option 5: View Analytics
# Check each agent's performance
# Adjust strategy based on results
```

### Monthly Agent Scaling
```bash
python main.py
# Option 1: Create New Agent (with new niche)
# Option 7: Export Agents (backup)
# Option 3: Batch Generate Content (new agent)
```

## Performance Optimization

### For Faster Content Generation
- Use batch generation
- Pre-configure agent personas
- Use shorter topics

### For Better Engagement
- Schedule posts during peak hours
- Vary content types
- Engage actively during peak times

### For Cost Management
- Use Claude API (cheaper than GPT-4)
- Batch operations
- Schedule off-peak scheduling

## Support

- Check README.md for full documentation
- Check logs/ directory for error details
- Review database structure in src/database/models.py

## What's Next?

1. ✅ Setup complete!
2. 📝 Create more agents with different niches
3. 🚀 Generate content at scale
4. 📊 Analyze performance
5. 🔄 Iterate and optimize

---

**You're ready! Start by running: `python main.py`**
