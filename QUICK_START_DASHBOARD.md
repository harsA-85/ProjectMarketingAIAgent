# Quick Start - Dashboard & Agent Management

## 🚀 Run in 30 Seconds

### Step 1: Start Server
```bash
cd dashboard
python app.py
```

### Step 2: Open Browser
```
http://localhost:5000/
```

### Step 3: You're Ready!
- View all agents on dashboard
- Click any agent to see details
- Edit agents, generate posts, view connected accounts

## 📱 Main Features

### Dashboard (http://localhost:5000/)
- ✅ View all agents
- ✅ See stats: Total Agents, Posts, Interactions
- ✅ Click agent card → Detail page

### Agent Detail Page (http://localhost:5000/agent-detail.html?id=1)

**Header Buttons:**
- `← Back` - Return to dashboard
- `✏️ Edit Agent` - Modify agent properties
- `🗑️ Delete` - Remove agent (permanent)

**Tabs:**

1. **📊 Overview**
   - Agent profile information
   - Quick statistics
   - Brand, persona, tone, fields

2. **📱 Social Media Posts**
   - View all generated posts
   - See platform-specific styling
   - ✨ Generate New Post button
   - Posts show: platform, status, dates, hashtags

3. **🔗 Connected Accounts**
   - View social media accounts
   - See connection status (🟢 Connected / 🔴 Disconnected)
   - Follower counts

## 📝 What You Can Do

### Edit Agent
1. Click `✏️ Edit Agent`
2. Modify any field:
   - Agent Name
   - Brand
   - Persona
   - Tone of Voice
   - Fields (comma-separated)
   - Bio
3. Click `Save Changes`

### Generate Posts
1. Go to `📱 Social Media Posts` tab
2. Click `✨ Generate New Post`
3. Choose platform:
   - 📷 Instagram
   - 𝕏 Twitter/X
   - 🎵 TikTok
4. (Optional) Enter topic
5. Click `Generate Post`
6. New post appears with platform-specific styling

### Delete Agent
1. Click `🗑️ Delete`
2. Confirm deletion
3. Agent removed from system

## 🌐 API Usage

**All with `http://localhost:5000`**

```bash
# Get all agents
curl http://localhost:5000/api/agents

# Get specific agent
curl http://localhost:5000/api/agents/1

# Update agent
curl -X PUT http://localhost:5000/api/agents/1 \
  -H "Content-Type: application/json" \
  -d '{"tone_of_voice":"Casual"}'

# Delete agent
curl -X DELETE http://localhost:5000/api/agents/1

# Get agent posts
curl http://localhost:5000/api/agents/1/posts

# Generate post
curl -X POST http://localhost:5000/api/content/generate \
  -H "Content-Type: application/json" \
  -d '{"agent_id":1,"platform":"twitter","topic":"AI"}'

# Get connected accounts
curl http://localhost:5000/api/agents/1/accounts
```

## 💾 Data Persistence

- ✅ All data stored in SQLite database (`agents.db`)
- ✅ Persists after server restart
- ✅ Survives power loss
- ✅ No manual data entry needed

## 🔧 Troubleshooting

### "Can't connect to server"
```bash
# Make sure you're in dashboard directory
cd dashboard

# Try starting server again
python app.py
```

### "Agent detail page won't load"
- Check URL: `http://localhost:5000/agent-detail.html?id=1`
- Verify agent ID exists (view dashboard)
- Check browser console (F12) for errors

### "Posts not generating"
- Verify `.env` file has `CLAUDE_API_KEY`
- Check agent has at least one field defined
- Look at server console for error messages

### "Page looks broken"
- Hard refresh browser: `Ctrl+F5` (Windows) or `Cmd+Shift+R` (Mac)
- Clear browser cache: Settings → Privacy → Clear browsing data

## 📚 Documentation

**Read these for more info:**
- `AGENT_MANAGEMENT_GUIDE.md` - Complete feature guide
- `TESTING_GUIDE.md` - How to test everything
- `SESSION_SUMMARY.md` - What was built this session
- `README.md` - Full project overview

## ⚡ Pro Tips

1. **Comma-separated fields:** "AI, Machine Learning, Data Science"
2. **Topic inference:** Leave topic blank to use agent's first field
3. **Multiple posts:** Generate multiple posts to see variety
4. **Platform styling:** Check Posts tab to see platform-specific designs
5. **Database check:** Close server before backing up `agents.db` file

## 🎯 Next Steps

### To Enable Real Posting:
1. Get API credentials (Instagram, Twitter/X, TikTok)
2. Set up OAuth flows
3. Connect accounts from web interface
4. Publish posts directly to platforms

### To Add More Features:
1. Read `SESSION_SUMMARY.md` for planned features
2. Check documentation for implementation guides
3. Test changes with `TESTING_GUIDE.md` procedures

## 📊 Example Workflow

```
1. Start server
   └─ python app.py

2. View agents
   └─ http://localhost:5000/

3. Select agent
   └─ Click on agent card

4. Generate content
   └─ 📱 Posts tab → Generate Post

5. Edit if needed
   └─ ✏️ Edit Agent button

6. View results
   └─ Check Posts tab with platform preview
```

## 🚨 Important Files

Keep these safe:
- `agents.db` - All agent & post data
- `.env` - API keys and secrets
- `dashboard/app.py` - Server code

## 📞 Questions?

Check:
1. Browser console (F12 → Console) for JS errors
2. Server terminal for error messages
3. `TESTING_GUIDE.md` for troubleshooting
4. `AGENT_MANAGEMENT_GUIDE.md` for feature details

---

**Status: ✅ Ready to Use!**

Your dashboard is production-ready for managing agents and generating content. All data is persistent and secure.
