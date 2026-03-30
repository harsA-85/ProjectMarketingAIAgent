# Testing Guide for Agent Management Features

## Quick Start Testing

### 1. Start the Dashboard Server
```bash
# From the project root directory
cd dashboard
python app.py
```

The server will start on `http://localhost:5000`

### 2. Test Dashboard Navigation
- Open `http://localhost:5000/` in browser
- You should see:
  - Header: "🤖 Marketing AI Agent Dashboard"
  - Stats cards: Total Agents, Total Posts, Total Interactions
  - List of all agents with their details
  - Refresh button to reload data

### 3. Test Agent Details View
1. On main dashboard, click any agent card
2. URL should change to `/agent-detail.html?id=<agent_id>`
3. Should see:
   - Agent name and brand in header
   - Back button and Edit/Delete buttons
   - Three tabs: Overview, Social Media Posts, Connected Accounts

### 4. Test Edit Agent Functionality
1. On agent detail page, click "✏️ Edit Agent" button
2. Modal should appear with form fields:
   - Agent Name
   - Brand
   - Persona
   - Tone of Voice
   - Fields (comma-separated)
   - Bio
3. Modify any field (e.g., change Tone to "More casual")
4. Click "Save Changes"
5. Should see success alert: "Agent updated successfully!"
6. Verify changes by reopening edit modal

**Testing via API (curl):**
```bash
curl -X PUT http://localhost:5000/api/agents/1 \
  -H "Content-Type: application/json" \
  -d '{"tone_of_voice": "Casual and fun"}'
```

Response should be:
```json
{
  "agent_id": 1,
  "message": "Agent updated successfully"
}
```

### 5. Test Create New Agent
**Via UI:**
1. On main dashboard, look for "Create Agent" button (if available)
2. Fill in form and submit

**Via API (curl):**
```bash
curl -X POST http://localhost:5000/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Agent ' $(date +%s) '",
    "brand": "Test Brand",
    "persona": "Test Persona",
    "tone_of_voice": "Test Tone",
    "fields": ["test", "demo"]
  }'
```

### 6. Test Generate Content
1. Navigate to any agent's detail page
2. Click "📱 Social Media Posts" tab
3. Click "✨ Generate New Post" button
4. Modal appears with:
   - Platform dropdown (Instagram, Twitter/X, TikTok)
   - Optional topic input field
5. Select platform and optionally enter topic
6. Click "Generate Post"
7. Should see: "Post generated successfully!"
8. Posts list should reload and show new post

**Testing via API (curl):**
```bash
curl -X POST http://localhost:5000/api/content/generate \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": 1,
    "platform": "twitter",
    "topic": "AI trends"
  }'
```

Response:
```json
{
  "post_id": 1,
  "agent_id": 1,
  "platform": "twitter",
  "message": "Content generated successfully"
}
```

### 7. Test Post Display and Previews
1. After generating posts, navigate to "📱 Social Media Posts" tab
2. Verify posts display with platform-specific styling:
   - **Instagram**: Light background, blue hashtags (#0095f6)
   - **Twitter/X**: White background, clean typography
   - **TikTok**: Black background, white text
3. Each post should show:
   - Platform name and icon
   - Status badge (DRAFT, PUBLISHED, SCHEDULED)
   - Post content/body
   - Hashtags (if any)
   - Creation date
   - Scheduled date (if applicable)

### 8. Test Get Agent Posts
**Via API (curl):**
```bash
curl http://localhost:5000/api/agents/1/posts
```

Response should include array of posts with all metadata

### 9. Test Delete Agent
1. On agent detail page, click "🗑️ Delete" button (red button)
2. Confirmation dialog: "Are you sure you want to delete this agent?"
3. Click "OK" to confirm
4. Should redirect to main dashboard
5. Deleted agent should no longer appear in list

**Testing via API (curl):**
```bash
curl -X DELETE http://localhost:5000/api/agents/1
```

Response:
```json
{
  "agent_id": 1,
  "message": "Agent deleted successfully"
}
```

### 10. Test Get Connected Accounts
1. On agent detail page, click "🔗 Connected Accounts" tab
2. Should show any connected accounts with:
   - Platform icon
   - Username
   - Connection status (🟢 Connected / 🔴 Disconnected)
   - Follower count
   - Verified status

**Via API (curl):**
```bash
curl http://localhost:5000/api/agents/1/accounts
```

## Database Verification

### Check Agent was Created
```bash
# Using Python
python -c "
from src.database.db import get_db
from src.database.models import Agent
db = get_db()
agents = db.query(Agent).all()
for a in agents:
    print(f'Agent {a.id}: {a.name} ({a.brand})')
"
```

### Check Posts were Generated
```bash
# Using Python
python -c "
from src.database.db import get_db
from src.database.models import Content
db = get_db()
posts = db.query(Content).all()
for p in posts:
    print(f'Post {p.id}: {p.platform} - {p.status}')
"
```

## Common Testing Scenarios

### Scenario 1: Create, Edit, Generate, Delete
1. Create new agent (API or UI)
2. Edit agent properties (change persona/tone)
3. Generate posts for all platforms (Instagram, Twitter, TikTok)
4. View posts in UI with platform previews
5. Delete agent and verify removal

### Scenario 2: Batch Content Generation
1. Navigate to agent detail page
2. Click "Generate New Post" 3 times
3. Select different platform each time
4. Verify all 3 posts appear with correct styling

### Scenario 3: Agent Update Workflow
1. Edit agent name
2. Edit agent tone
3. Edit fields (add more expertise areas)
4. Verify each change persists after page reload

## Performance Testing

### Load Multiple Agents
```bash
# Create 5 test agents via API
for i in {1..5}; do
  curl -X POST http://localhost:5000/api/agents \
    -H "Content-Type: application/json" \
    -d "{
      \"name\": \"Agent $i\",
      \"brand\": \"Brand $i\",
      \"persona\": \"Persona $i\",
      \"tone_of_voice\": \"Tone $i\",
      \"fields\": [\"field1\", \"field2\"]
    }"
done
```

Then verify dashboard loads and displays all agents.

## Troubleshooting During Tests

### Issue: 404 on agent-detail.html
- Ensure server is running with `python app.py`
- Check Flask routing in dashboard/app.py

### Issue: Update not persisting
- Check database is writable (agents.db file exists and has write permissions)
- Verify API response shows success
- Check browser console for errors

### Issue: Posts not generating
- Verify CLAUDE_API_KEY is set in .env file
- Check server logs for API errors
- Ensure agent has at least one field defined

### Issue: Modal doesn't open
- Open browser console (F12) and check for JavaScript errors
- Verify closeButton elements have correct IDs
- Check form element has correct ID

## Browser DevTools Debugging

### Network Requests
1. Open DevTools (F12)
2. Go to Network tab
3. Perform action (edit agent, generate post, etc.)
4. Check requests:
   - POST/PUT/DELETE should show status 200 or 201
   - Response should contain success message

### Console Errors
1. Open DevTools (F12)
2. Go to Console tab
3. Check for JavaScript errors (red messages)
4. Look for API response errors (blue messages with details)

### Local Storage
1. Open DevTools (F12)
2. Go to Application tab
3. Check Local Storage for any cached data
4. Clear if needed: Right-click → Clear

## Success Criteria

✅ All tests should pass when:
- Dashboard loads with agent list
- Agent detail page shows correct information
- Edit modal opens and saves changes
- Delete button removes agent
- Generate post creates new content with correct platform styling
- Posts tab displays with platform-specific CSS
- All API endpoints return correct status codes
- No JavaScript errors in console
- Database reflects all changes

## Next Steps After Testing

Once all features are tested and working:
1. Test with actual Instagram, Twitter, TikTok APIs
2. Implement account connection OAuth flows
3. Set up actual post publishing
4. Deploy to production server
5. Configure custom domain
6. Setup monitoring and logging
