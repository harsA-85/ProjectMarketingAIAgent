from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
from src.database.db import get_db
from src.database.models import Agent, Content, Interaction
from src.agents.base_agent import BaseAgent
from src.scheduler.post_scheduler import PostScheduler
from src.analytics.analytics_engine import AnalyticsEngine


class Orchestrator:
    """Central orchestrator managing all agents and their activities"""

    def __init__(self):
        self.db = get_db()
        self.agents = {}
        self.scheduler = PostScheduler()
        self.analytics_engine = AnalyticsEngine()
        self._load_agents()

    def _load_agents(self):
        """Load all active agents from database"""
        agents = self.db.query(Agent).filter(Agent.is_active == True).all()
        for agent in agents:
            try:
                self.agents[agent.id] = BaseAgent(agent.id)
            except Exception as e:
                print(f"Error loading agent {agent.id}: {e}")

    def create_agent(
        self,
        name: str,
        brand: str,
        persona: str,
        tone_of_voice: str,
        fields: List[str],
        bio: str = "",
        avatar_url: str = ""
    ) -> int:
        """Create a new agent"""
        agent = Agent(
            name=name,
            brand=brand,
            persona=persona,
            tone_of_voice=tone_of_voice,
            fields=fields,
            bio=bio,
            avatar_url=avatar_url,
            is_active=True
        )

        self.db.add(agent)
        self.db.commit()

        # Load agent into orchestrator
        self.agents[agent.id] = BaseAgent(agent.id)
        print(f"Agent created: {agent.name} (ID: {agent.id})")

        return agent.id

    def update_agent(
        self,
        agent_id: int,
        name: Optional[str] = None,
        brand: Optional[str] = None,
        persona: Optional[str] = None,
        tone_of_voice: Optional[str] = None,
        fields: Optional[List[str]] = None,
        bio: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> bool:
        """Update an existing agent"""
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # Update only provided fields
        if name is not None:
            agent.name = name
        if brand is not None:
            agent.brand = brand
        if persona is not None:
            agent.persona = persona
        if tone_of_voice is not None:
            agent.tone_of_voice = tone_of_voice
        if fields is not None:
            agent.fields = fields
        if bio is not None:
            agent.bio = bio
        if avatar_url is not None:
            agent.avatar_url = avatar_url

        # Update timestamp
        agent.updated_at = datetime.utcnow()

        self.db.commit()
        print(f"Agent updated: {agent.name} (ID: {agent.id})")

        # Reload agent in orchestrator
        self.agents[agent_id] = BaseAgent(agent_id)

        return True

    def delete_agent(self, agent_id: int) -> bool:
        """Soft delete an agent (mark as inactive)"""
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        agent.is_active = False
        agent.updated_at = datetime.utcnow()
        self.db.commit()

        # Remove from orchestrator
        if agent_id in self.agents:
            del self.agents[agent_id]

        print(f"Agent deleted: {agent.name} (ID: {agent.id})")
        return True

    def get_agent(self, agent_id: int) -> Optional[BaseAgent]:
        """Get agent by ID"""
        if agent_id not in self.agents:
            self._load_agents()
        return self.agents.get(agent_id)

    def generate_content_for_agent(
        self,
        agent_id: int,
        platform: str,
        topic: str,
        schedule_time: Optional[datetime] = None
    ) -> int:
        """Generate and potentially schedule content for an agent"""
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        # Generate content
        post_id = agent.create_draft_post(platform, topic)

        # Schedule if time provided
        if schedule_time:
            self.scheduler.schedule_post(post_id, schedule_time)
            print(f"Post {post_id} scheduled for {schedule_time}")
        else:
            print(f"Post {post_id} created as draft")

        return post_id

    def batch_generate_content(
        self,
        agent_ids: Optional[List[int]] = None,
        platforms: Optional[List[str]] = None,
        num_posts_per_agent: int = 1
    ) -> Dict[int, List[int]]:
        """Generate content for multiple agents"""
        if agent_ids is None:
            agent_ids = list(self.agents.keys())

        if platforms is None:
            platforms = ['instagram', 'twitter', 'tiktok']

        results = {}

        for agent_id in agent_ids:
            agent = self.get_agent(agent_id)
            if not agent:
                continue

            results[agent_id] = []
            for _ in range(num_posts_per_agent):
                for platform in platforms:
                    try:
                        topic = agent.agent.fields[0] if agent.agent.fields else "general"
                        post_id = agent.create_draft_post(platform, topic)
                        results[agent_id].append(post_id)
                    except Exception as e:
                        print(f"Error generating content for agent {agent_id}: {e}")

        return results

    def plan_engagement_for_agent(
        self,
        agent_id: int,
        platform: str,
        target: str = "brand_awareness"
    ) -> List[Dict[str, Any]]:
        """Plan engagement activities for an agent"""
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        activities = agent.plan_engagement(platform, target)
        return activities

    def execute_scheduled_posts(self) -> Dict[str, Any]:
        """Execute all scheduled posts that are due"""
        due_posts = self.scheduler.get_due_posts()
        results = {'total': len(due_posts), 'successful': 0, 'failed': 0}

        for post in due_posts:
            try:
                # Publish post to platform (stub implementation)
                post.status = 'published'
                post.published_at = datetime.utcnow()
                self.db.commit()
                results['successful'] += 1
            except Exception as e:
                post.status = 'failed'
                self.db.commit()
                results['failed'] += 1
                print(f"Error publishing post {post.id}: {e}")

        return results

    def get_agent_dashboard(self, agent_id: int) -> Dict[str, Any]:
        """Get dashboard data for an agent"""
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        analytics = agent.get_analytics()

        dashboard = {
            'agent_id': agent_id,
            'agent_name': agent.agent.name,
            'brand': agent.agent.brand,
            'persona': agent.agent.persona,
            'tone': agent.agent.tone_of_voice,
            'fields': agent.agent.fields,
            'analytics': analytics,
            'draft_posts': self.db.query(Content).filter(
                Content.agent_id == agent_id,
                Content.status == 'draft'
            ).count(),
            'scheduled_posts': self.db.query(Content).filter(
                Content.agent_id == agent_id,
                Content.status == 'scheduled'
            ).count(),
            'pending_interactions': self.db.query(Interaction).filter(
                Interaction.agent_id == agent_id,
                Interaction.status == 'pending'
            ).count()
        }

        return dashboard

    def get_all_agents_dashboard(self) -> Dict[str, Any]:
        """Get overview dashboard for all agents"""
        total_agents = len(self.agents)
        total_posts = self.db.query(Content).count()
        total_interactions = self.db.query(Interaction).count()

        agents_data = []
        for agent_id in self.agents.keys():
            try:
                agents_data.append(self.get_agent_dashboard(agent_id))
            except:
                pass

        return {
            'total_agents': total_agents,
            'total_posts': total_posts,
            'total_interactions': total_interactions,
            'agents': agents_data,
            'timestamp': datetime.utcnow().isoformat()
        }

    def get_agent_performance_report(self, agent_id: int, days: int = 7) -> Dict[str, Any]:
        """Get performance report for an agent"""
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        since = datetime.utcnow() - timedelta(days=days)

        posts = self.db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.published_at >= since
        ).all()

        interactions = self.db.query(Interaction).filter(
            Interaction.agent_id == agent_id,
            Interaction.completed_at >= since
        ).all()

        return {
            'agent_id': agent_id,
            'agent_name': agent.agent.name,
            'period_days': days,
            'posts_published': len(posts),
            'interactions_completed': len(interactions),
            'platforms': list(set([p.platform for p in posts])),
            'top_topics': self._get_top_topics(posts),
            'engagement_summary': {
                'likes': len([i for i in interactions if i.interaction_type == 'like']),
                'comments': len([i for i in interactions if i.interaction_type == 'comment']),
                'follows': len([i for i in interactions if i.interaction_type == 'follow']),
                'replies': len([i for i in interactions if i.interaction_type == 'reply'])
            }
        }

    def _get_top_topics(self, posts: List[Content]) -> List[str]:
        """Extract top topics from posts"""
        topics = {}
        for post in posts:
            if post.agent.fields:
                for field in post.agent.fields:
                    topics[field] = topics.get(field, 0) + 1

        return sorted(topics.items(), key=lambda x: x[1], reverse=True)[:5]

    def save_agents_config(self, filepath: str):
        """Export agents configuration to JSON"""
        agents_data = []
        for agent in self.db.query(Agent).all():
            agents_data.append({
                'id': agent.id,
                'name': agent.name,
                'brand': agent.brand,
                'persona': agent.persona,
                'tone_of_voice': agent.tone_of_voice,
                'fields': agent.fields,
                'bio': agent.bio,
                'avatar_url': agent.avatar_url,
                'is_active': agent.is_active
            })

        with open(filepath, 'w') as f:
            json.dump(agents_data, f, indent=2)

    def load_agents_from_config(self, filepath: str):
        """Import agents from JSON config"""
        with open(filepath, 'r') as f:
            agents_data = json.load(f)

        for agent_data in agents_data:
            self.create_agent(
                name=agent_data['name'],
                brand=agent_data['brand'],
                persona=agent_data['persona'],
                tone_of_voice=agent_data['tone_of_voice'],
                fields=agent_data['fields'],
                bio=agent_data.get('bio', ''),
                avatar_url=agent_data.get('avatar_url', '')
            )

    def __del__(self):
        """Cleanup"""
        if self.db:
            self.db.close()
