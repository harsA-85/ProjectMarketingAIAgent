@echo off
REM Autonomous Marketing AI Agent System - GitHub Push Script (Windows)
REM This script pushes your project to GitHub

setlocal enabledelayedexpansion

echo ========================================
echo   Pushing to GitHub
echo ========================================

REM Check if git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git is not installed. Install from https://git-scm.com
    pause
    exit /b 1
)

REM Initialize git if needed
if not exist ".git" (
    echo Initializing git repository...
    git init
)

REM Check if remote exists
git remote | findstr /R "^origin$" >nul
if errorlevel 1 (
    echo ERROR: Git remote not configured. Run this command first:
    echo.
    echo git remote add origin https://github.com/YOUR_USERNAME/ProjectMarketingAIAgent.git
    echo.
    echo Then run this script again.
    pause
    exit /b 1
)

REM Add all files
echo Adding files...
git add .

REM Check status
echo.
echo Status:
git status

REM Create commit
echo.
set /p continue="Continue with push? (y/n): "
if /i not "%continue%"=="y" (
    echo Cancelled.
    exit /b 0
)

echo.
echo Creating commit...
git commit -m "Initial commit: Autonomous Marketing AI Agent System - Core orchestrator for managing multiple AI agents - Support for Instagram, Twitter/X, and TikTok - Content generation with Claude API - Scheduling and analytics engine - Web dashboard and REST API - Database models and ORM setup - CLI interface for management - Docker and cloud-ready deployment"

REM Push to GitHub
echo.
echo Pushing to GitHub...
git branch -M main
git push -u origin main

echo.
echo SUCCESS: Push complete!
echo.
echo Your repository is now available at:
echo https://github.com/YOUR_USERNAME/ProjectMarketingAIAgent
echo.
echo Next steps:
echo 1. Visit the GitHub repository
echo 2. Configure settings
echo 3. Add collaborators if needed
echo 4. Monitor your project!
echo.
pause
