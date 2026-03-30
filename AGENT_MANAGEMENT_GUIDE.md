# Agent Management Guide

## Overview
This guide covers all agent management features available in the Marketing AI Agent Dashboard.

## Features Implemented

### 1. Agent CRUD Operations

#### Create Agent
- Navigate to the dashboard at `http://localhost:5000/`
- Click "Create Agent" (or use the API endpoint)
- Fill in required fields:
  - **Agent Name**: Unique identifier for your agent
  - **Brand**: Brand or company name
  - **Persona**: How the agent should behave/present itself
  - **Tone of Voice**: Writing style (professional, casual, humorous, etc.)
  - **Fields**: Comma-separated list of expertise areas
  - **Bio**: Optional biography/description

#### Read Agent
- View all agents on the main dashboard
- Click any agent card to view detailed information
- Detailed view shows:
  - Agent profile information
  - Quick statistics (posts, interactions)
  - Social media posts by platform
  - Connected accounts status

#### Update Agent
1. Navigate to agent detail page
2. Click "✏️ Edit Agent" button
3. Modify any fields:
   - Agent Name
   - Brand
   - Persona
   - Tone of Voice
   - Fields (comma-separated)
   - Bio
4. Click "Save Changes"

#### Delete Agent
1. Navigate to agent detail page
2. Click "🗑️ Delete" button (red button in header)
3. Confirm deletion (this is permanent - agent becomes inactive)

### 2. Content Generation

#### Generate New Posts
1. Navigate to agent detail page
2. Go to "📱 Social Media Posts" tab
3. Click "✨ Generate New Post" button
4. Select platform:
   - 📷 Instagram
   - 𝕏 Twitter/X
   - 🎵 TikTok
5. Optionally enter a topic (defaults to agent's first field)
6. Click "Generate Post"

Posts are generated as **draft** status and can be:
- Edited before publishing
- Scheduled for later
- Published immediately

### 3. Post Visualization

All posts are displayed with platform-specific styling:

**Instagram Preview**
- Light background with blue hashtags (#0095f6)
- Clean, visual layout

**Twitter/X Preview**
- White background with Twitter-style typography
- Character-friendly format

**TikTok Preview**
- Black background with white text
- Short-form content optimized

Each post shows:
- Platform icon and name
- Status badge (DRAFT, PUBLISHED, SCHEDULED)
- Post content
- Hashtags
- Mentions
- Creation and publication dates

### 4. Account Management

View connected social media accounts:
1. Go to "🔗 Connected Accounts" tab
2. See all connected platforms:
   - Connection status (🟢 Connected / 🔴 Disconnected)
   - Username
   - Follower count
   - Verification status

### 5. Analytics & Statistics

On the Overview tab, see quick stats:
- Total posts published
- Draft posts count
- Scheduled posts count
- Total interactions

## API Endpoints

### Agent Management
```
GET    /api/agents              - Get all agents
GET    /api/agents/<id>         - Get specific agent
POST   /api/agents              - Create new agent
PUT    /api/agents/<id>         - Update agent
DELETE /api/agents/<id>         - Delete agent (soft delete)
```

### Content Management
```
GET    /api/agents/<id>/posts       - Get all posts for agent
POST   /api/content/generate        - Generate new post
POST   /api/content/schedule        - Schedule post for publishing
```

### Accounts
```
GET    /api/agents/<id>/accounts    - Get connected accounts
```

## Request/Response Examples

### Create Agent
```bash
curl -X POST http://localhost:5000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tech Influencer",
    "brand": "TechBlog",
    "persona": "Tech-savvy content creator",
    "tone_of_voice": "Informative and engaging",
    "fields": ["AI", "Machine Learning", "Technology"],
    "bio": "Creating amazing tech content"
  }'
```

### Update Agent
```bash
curl -X PUT http://localhost:5000/api/agents/1 \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Name",
    "tone_of_voice": "More casual"
  }'
```

### Generate Content
```bash
curl -X POST http://localhost:5000/api/content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": 1,
    "platform": "twitter",
    "topic": "AI trends"
  }'
```

## Database Schema

### Agents Table
```
id (INT) - Primary key
name (VARCHAR) - Unique agent name
brand (VARCHAR) - Brand name
persona (VARCHAR) - Agent persona
tone_of_voice (VARCHAR) - Writing style
avatar_url (VARCHAR) - Profile image
bio (TEXT) - Agent description
fields (JSON) - Array of expertise areas
is_active (BOOLEAN) - Active status
created_at (DATETIME) - Creation timestamp
updated_at (DATETIME) - Last update timestamp
```

### Content Table
```
id (INT) - Primary key
agent_id (INT) - Foreign key to agents
platform (VARCHAR) - 'instagram', 'twitter', 'tiktok'
title (VARCHAR) - Post title
body (TEXT) - Post content
hashtags (JSON) - Array of hashtags
mentions (JSON) - Array of mentions
status (VARCHAR) - 'draft', 'scheduled', 'published', 'failed'
scheduled_at (DATETIME) - Scheduled publication time
published_at (DATETIME) - Actual publication time
created_at (DATETIME) - Creation timestamp
```

## Next Steps

### Planned Features
1. **Social Media Posting** - Directly post to connected accounts
2. **OAuth Integration** - Connect social media accounts
3. **Advanced Analytics** - Detailed performance metrics
4. **Engagement Automation** - Auto-like, comment, follow
5. **Batch Operations** - Generate content for multiple agents
6. **Scheduling Interface** - Visual calendar for post scheduling
7. **Content Templates** - Reusable content templates per platform
8. **Performance Dashboard** - Real-time metrics and insights

### To Enable Social Media Posting
1. Configure API credentials:
   - Instagram Graph API credentials
   - Twitter/X API v2 credentials
   - TikTok Business API credentials
2. Implement OAuth flows for each platform
3. Update platform integration modules

## Troubleshooting

### Agent Not Appearing
- Ensure agent `is_active = true` in database
- Check agent was committed (no error during creation)

### Posts Not Generating
- Verify Claude API key is set in `.env` file
- Check agent has at least one field defined
- Review server logs for API errors

### Posts Not Displaying
- Clear browser cache
- Verify posts were created in database
- Check content generation didn't fail silently

## Configuration

### Environment Variables
```
CLAUDE_API_KEY=sk-ant-...          # Claude API key (required)
DATABASE_URL=sqlite:///agents.db   # Database URL (default: SQLite)
```

### Server Configuration
See `.claude/launch.json` for server settings

## Support

For issues or questions, check:
1. Server logs in terminal
2. Browser console (F12 -> Console)
3. Network tab (F12 -> Network) for API errors
