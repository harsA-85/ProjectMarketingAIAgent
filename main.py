#!/usr/bin/env python3
"""
Main entry point for the Autonomous AI Marketing Agent System

This script provides a CLI interface to interact with the agent orchestrator,
manage agents, generate content, and monitor performance.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.db import init_db
from src.orchestrator.orchestrator import Orchestrator
from src.api.llm_provider import LLMProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
load_dotenv()


class MarketingAgentCLI:
    """CLI for managing the marketing AI agent system"""

    def __init__(self):
        init_db()
        self.orchestrator = Orchestrator()
        logger.info("Marketing Agent System initialized")

    def create_agent(self):
        """Interactive agent creation"""
        print("\n=== Create New Agent ===")
        name = input("Agent name: ").strip()
        brand = input("Brand name: ").strip()
        persona = input("Agent persona: ").strip()
        tone = input("Tone of voice: ").strip()
        fields_str = input("Fields (comma-separated): ").strip()
        bio = input("Bio/Description: ").strip()
        avatar_url = input("Avatar URL (optional): ").strip()

        fields = [f.strip() for f in fields_str.split(',')]

        agent_id = self.orchestrator.create_agent(
            name=name,
            brand=brand,
            persona=persona,
            tone_of_voice=tone,
            fields=fields,
            bio=bio,
            avatar_url=avatar_url
        )

        print(f"\n✓ Agent '{name}' created successfully with ID: {agent_id}")
        return agent_id

    def generate_content(self):
        """Generate content for an agent"""
        print("\n=== Generate Content ===")

        agent_id = int(input("Agent ID: "))
        platform = input("Platform (instagram/twitter/tiktok): ").lower()
        topic = input("Topic (optional, press Enter for default): ").strip() or None
        schedule = input("Schedule for later? (y/n): ").lower() == 'y'

        try:
            post_id = self.orchestrator.generate_content_for_agent(
                agent_id=agent_id,
                platform=platform,
                topic=topic or 'general',
                schedule_time=None
            )

            if schedule:
                hours = int(input("Hours from now to schedule: "))
                schedule_time = datetime.utcnow() + timedelta(hours=hours)
                self.orchestrator.scheduler.reschedule_post(post_id, schedule_time)
                print(f"\n✓ Content generated and scheduled for {schedule_time}")
            else:
                print(f"\n✓ Content generated (Draft) with ID: {post_id}")

        except Exception as e:
            logger.error(f"Error generating content: {e}")
            print(f"Error: {e}")

    def batch_generate(self):
        """Batch generate content"""
        print("\n=== Batch Generate Content ===")

        num_agents = int(input("Number of agents to generate for (0 for all): ") or 0)
        num_posts = int(input("Posts per agent: ") or 1)
        platforms = input("Platforms (comma-separated): ").strip().split(',')

        agent_ids = None
        if num_agents > 0:
            agent_ids = list(self.orchestrator.agents.keys())[:num_agents]

        results = self.orchestrator.batch_generate_content(
            agent_ids=agent_ids,
            platforms=[p.strip() for p in platforms],
            num_posts_per_agent=num_posts
        )

        total = sum(len(posts) for posts in results.values())
        print(f"\n✓ Generated {total} posts across {len(results)} agents")

    def view_dashboard(self):
        """View agent dashboard"""
        print("\n=== Dashboard ===")

        agent_id = int(input("Enter agent ID (0 for all): ") or 0)

        if agent_id == 0:
            dashboard = self.orchestrator.get_all_agents_dashboard()
            print(f"\nTotal Agents: {dashboard['total_agents']}")
            print(f"Total Posts: {dashboard['total_posts']}")
            print(f"Total Interactions: {dashboard['total_interactions']}\n")

            for agent_data in dashboard['agents'][:5]:
                print(f"  {agent_data['agent_name']}")
                print(f"    - Brand: {agent_data['brand']}")
                print(f"    - Posts: {agent_data['analytics']['total_posts']}")
                print()
        else:
            try:
                dashboard = self.orchestrator.get_agent_dashboard(agent_id)
                print(f"\nAgent: {dashboard['agent_name']}")
                print(f"Brand: {dashboard['brand']}")
                print(f"Persona: {dashboard['persona']}")
                print(f"Tone: {dashboard['tone']}")
                print(f"Fields: {', '.join(dashboard['fields'])}")
                print(f"\nStats:")
                print(f"  - Posts Published: {dashboard['analytics']['total_posts']}")
                print(f"  - Interactions: {dashboard['analytics']['total_interactions']}")
                print(f"  - Draft Posts: {dashboard['draft_posts']}")
                print(f"  - Scheduled Posts: {dashboard['scheduled_posts']}")
            except Exception as e:
                print(f"Error: {e}")

    def view_analytics(self):
        """View agent analytics"""
        print("\n=== Analytics ===")

        agent_id = int(input("Agent ID: "))
        days = int(input("Days to analyze (default 7): ") or 7)

        try:
            report = self.orchestrator.get_agent_performance_report(agent_id, days)

            print(f"\nPerformance Report - {report['agent_name']}")
            print(f"Period: Last {days} days\n")
            print(f"Posts Published: {report['posts_published']}")
            print(f"Interactions Completed: {report['interactions_completed']}")
            print(f"Platforms: {', '.join(report['platforms'])}\n")

            print("Engagement Breakdown:")
            for interaction_type, count in report['engagement_summary'].items():
                print(f"  - {interaction_type.capitalize()}: {count}")

            if report['top_topics']:
                print(f"\nTop Topics:")
                for topic in report['top_topics']:
                    print(f"  - {topic[0]}")

        except Exception as e:
            logger.error(f"Error generating report: {e}")
            print(f"Error: {e}")

    def setup_api_keys(self):
        """Setup API keys for LLM providers"""
        print("\n=== API Configuration ===")

        provider = input("LLM Provider (claude/openai): ").lower()
        api_key = input(f"Enter {provider.upper()} API key: ").strip()
        model_name = input(f"Model name (optional): ").strip() or None

        try:
            LLMProvider.set_api_key(provider, api_key, model_name)
            print(f"\n✓ {provider.upper()} API key configured")
        except Exception as e:
            logger.error(f"Error setting API key: {e}")
            print(f"Error: {e}")

    def export_agents(self):
        """Export agents configuration"""
        print("\n=== Export Agents ===")

        filepath = input("Export to file (default: config/agents_export.json): ").strip()
        filepath = filepath or "config/agents_export.json"

        try:
            self.orchestrator.save_agents_config(filepath)
            print(f"✓ Agents exported to {filepath}")
        except Exception as e:
            print(f"Error: {e}")

    def import_agents(self):
        """Import agents from configuration file"""
        print("\n=== Import Agents ===")

        filepath = input("Import from file: ").strip()

        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return

        try:
            self.orchestrator.load_agents_from_config(filepath)
            print(f"✓ Agents imported from {filepath}")
        except Exception as e:
            print(f"Error: {e}")

    def run_scheduler(self):
        """Run the post scheduler"""
        print("\n=== Running Scheduler ===")
        print("Press Ctrl+C to stop")

        try:
            self.orchestrator.scheduler.run_scheduler()
        except KeyboardInterrupt:
            print("\nScheduler stopped")

    def show_menu(self):
        """Display main menu"""
        print("\n" + "="*50)
        print("  Autonomous Marketing AI Agent System")
        print("="*50)
        print("1. Create New Agent")
        print("2. Generate Content")
        print("3. Batch Generate Content")
        print("4. View Dashboard")
        print("5. View Analytics")
        print("6. Setup API Keys")
        print("7. Export Agents")
        print("8. Import Agents")
        print("9. Run Scheduler")
        print("0. Exit")
        print("="*50)

    def run(self):
        """Main CLI loop"""
        while True:
            self.show_menu()
            choice = input("Select option: ").strip()

            if choice == '1':
                self.create_agent()
            elif choice == '2':
                self.generate_content()
            elif choice == '3':
                self.batch_generate()
            elif choice == '4':
                self.view_dashboard()
            elif choice == '5':
                self.view_analytics()
            elif choice == '6':
                self.setup_api_keys()
            elif choice == '7':
                self.export_agents()
            elif choice == '8':
                self.import_agents()
            elif choice == '9':
                self.run_scheduler()
            elif choice == '0':
                print("Goodbye!")
                break
            else:
                print("Invalid option. Please try again.")


def main():
    """Entry point"""
    try:
        cli = MarketingAgentCLI()
        cli.run()
    except KeyboardInterrupt:
        print("\n\nSystem stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
