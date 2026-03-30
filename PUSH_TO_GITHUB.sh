#!/bin/bash

# Autonomous Marketing AI Agent System - GitHub Push Script
# This script pushes your project to GitHub

echo "========================================"
echo "  Pushing to GitHub"
echo "========================================"

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Install from https://git-scm.com"
    exit 1
fi

# Initialize git if needed
if [ ! -d ".git" ]; then
    echo "📦 Initializing git repository..."
    git init
fi

# Check if remote exists
if git remote | grep -q "origin"; then
    echo "✓ Git remote already configured"
else
    echo "❌ Git remote not configured. Run this command first:"
    echo ""
    echo "git remote add origin https://github.com/YOUR_USERNAME/ProjectMarketingAIAgent.git"
    echo ""
    echo "Then run this script again."
    exit 1
fi

# Add all files
echo "📝 Adding files..."
git add .

# Check status
echo ""
echo "📊 Status:"
git status

# Create commit
echo ""
read -p "✓ Continue with push? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "⏳ Creating commit..."
git commit -m "Initial commit: Autonomous Marketing AI Agent System

- Core orchestrator for managing multiple AI agents
- Support for Instagram, Twitter/X, and TikTok
- Content generation with Claude API
- Scheduling and analytics engine
- Web dashboard and REST API
- Database models and ORM setup
- CLI interface for management
- Docker and cloud-ready deployment"

# Push to GitHub
echo ""
echo "🚀 Pushing to GitHub..."
git branch -M main
git push -u origin main

echo ""
echo "✅ Push complete!"
echo ""
echo "Your repository is now available at:"
echo "https://github.com/YOUR_USERNAME/ProjectMarketingAIAgent"
echo ""
echo "Next steps:"
echo "1. Visit the GitHub repository"
echo "2. Configure settings"
echo "3. Add collaborators if needed"
echo "4. Monitor your project!"
