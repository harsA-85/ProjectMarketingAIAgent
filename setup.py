#!/usr/bin/env python3
"""
Setup script for Autonomous Marketing AI Agent System
Initializes the project, creates necessary directories, and sets up configuration
"""

import os
import sys
import json
from pathlib import Path
from shutil import copyfile


def setup_project():
    """Setup the project structure and files"""

    print("🚀 Setting up Autonomous Marketing AI Agent System\n")

    # Create necessary directories
    directories = [
        'logs',
        'config',
        'data',
        'temp',
        'tests',
        'dashboard/templates',
        'dashboard/static'
    ]

    print("📁 Creating directories...")
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {directory}/")

    # Copy .env.example if .env doesn't exist
    print("\n🔐 Setting up environment configuration...")
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            copyfile('.env.example', '.env')
            print("  ✓ Created .env from .env.example")
        else:
            print("  ⚠ .env.example not found, skipping .env creation")
    else:
        print("  ✓ .env already exists")

    # Create __init__.py files for packages
    print("\n📦 Creating package files...")
    packages = [
        'src',
        'src/orchestrator',
        'src/agents',
        'src/platforms',
        'src/content',
        'src/engagement',
        'src/scheduler',
        'src/analytics',
        'src/api',
        'src/database',
        'src/config',
        'src/utils',
        'tests'
    ]

    for package in packages:
        init_file = f'{package}/__init__.py'
        Path(init_file).touch(exist_ok=True)
        print(f"  ✓ {init_file}")

    # Initialize database
    print("\n📊 Initializing database...")
    try:
        from src.database.db import init_db
        init_db()
        print("  ✓ Database initialized successfully")
    except Exception as e:
        print(f"  ⚠ Database initialization warning: {e}")

    # Create sample agents config if it doesn't exist
    print("\n🤖 Setting up sample configuration...")
    if not os.path.exists('config/agents.json'):
        if os.path.exists('config/agents.example.json'):
            copyfile('config/agents.example.json', 'config/agents.json')
            print("  ✓ Created config/agents.json")
    else:
        print("  ✓ config/agents.json already exists")

    print("\n✅ Setup completed successfully!\n")
    print("📋 Next steps:")
    print("  1. Edit .env with your API keys")
    print("  2. Run: python main.py")
    print("  3. Create your first agent")
    print("  4. Start generating content!\n")

    print("📚 For more information, see README.md")


if __name__ == '__main__':
    try:
        setup_project()
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1)
