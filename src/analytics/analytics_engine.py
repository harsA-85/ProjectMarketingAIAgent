from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import func
from src.database.db import get_db
from src.database.models import Content, Interaction, Analytics, Agent, SocialMediaAccount


class AnalyticsEngine:
    """Analyzes agent performance and social media metrics"""

    def __init__(self):
        self.db = get_db()

    def calculate_engagement_rate(self, agent_id: int, platform: Optional[str] = None) -> float:
        """Calculate engagement rate for an agent"""
        query = self.db.query(Interaction).filter(
            Interaction.agent_id == agent_id,
            Interaction.status == 'completed'
        )

        if platform:
            query = query.filter(Interaction.platform == platform)

        interactions = query.count()

        posts_query = self.db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.status == 'published'
        )

        if platform:
            posts_query = posts_query.filter(Content.platform == platform)

        posts = posts_query.count()

        if posts == 0:
            return 0.0

        return (interactions / posts) * 100

    def get_content_performance(self, agent_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get performance metrics for content"""
        posts = self.db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.status == 'published'
        ).order_by(Content.published_at.desc()).limit(limit).all()

        performance_data = []
        for post in posts:
            interactions = self.db.query(Interaction).filter(
                Interaction.agent_id == agent_id
            ).count()

            performance_data.append({
                'post_id': post.id,
                'platform': post.platform,
                'title': post.title[:50],
                'published_at': post.published_at.isoformat() if post.published_at else None,
                'interactions': interactions,
                'hashtags': post.hashtags,
            })

        return performance_data

    def get_platform_performance(self, agent_id: int) -> Dict[str, Any]:
        """Get performance breakdown by platform"""
        platforms = self.db.query(Content.platform).filter(
            Content.agent_id == agent_id,
            Content.status == 'published'
        ).distinct().all()

        platform_stats = {}
        for (platform,) in platforms:
            posts = self.db.query(Content).filter(
                Content.agent_id == agent_id,
                Content.platform == platform,
                Content.status == 'published'
            ).count()

            interactions = self.db.query(Interaction).filter(
                Interaction.agent_id == agent_id,
                Interaction.platform == platform,
                Interaction.status == 'completed'
            ).count()

            platform_stats[platform] = {
                'posts': posts,
                'interactions': interactions,
                'engagement_rate': (interactions / posts * 100) if posts > 0 else 0
            }

        return platform_stats

    def get_growth_metrics(self, agent_id: int, days: int = 30) -> Dict[str, Any]:
        """Calculate growth metrics over a period"""
        since = datetime.utcnow() - timedelta(days=days)

        posts_growth = self.db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.published_at >= since
        ).count()

        interactions_growth = self.db.query(Interaction).filter(
            Interaction.agent_id == agent_id,
            Interaction.completed_at >= since
        ).count()

        return {
            'period_days': days,
            'posts_published': posts_growth,
            'interactions_completed': interactions_growth,
            'daily_average_posts': posts_growth / days,
            'daily_average_interactions': interactions_growth / days
        }

    def get_account_stats(self, agent_id: int) -> Dict[str, Any]:
        """Get account statistics for an agent"""
        accounts = self.db.query(SocialMediaAccount).filter(
            SocialMediaAccount.agent_id == agent_id
        ).all()

        stats = {
            'total_accounts': len(accounts),
            'accounts_by_platform': {},
            'total_followers': 0
        }

        for account in accounts:
            platform = account.platform
            if platform not in stats['accounts_by_platform']:
                stats['accounts_by_platform'][platform] = {
                    'count': 0,
                    'followers': 0
                }

            stats['accounts_by_platform'][platform]['count'] += 1
            stats['accounts_by_platform'][platform]['followers'] += account.followers

            stats['total_followers'] += account.followers

        return stats

    def get_agent_comparison(self, agent_ids: List[int], metric: str = 'engagement_rate') -> Dict[str, Any]:
        """Compare multiple agents by a metric"""
        comparison = {}

        for agent_id in agent_ids:
            agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                continue

            if metric == 'engagement_rate':
                value = self.calculate_engagement_rate(agent_id)
            elif metric == 'posts_published':
                value = self.db.query(Content).filter(
                    Content.agent_id == agent_id,
                    Content.status == 'published'
                ).count()
            elif metric == 'total_interactions':
                value = self.db.query(Interaction).filter(
                    Interaction.agent_id == agent_id,
                    Interaction.status == 'completed'
                ).count()
            else:
                value = 0

            comparison[agent.name] = {
                'agent_id': agent_id,
                'value': value,
                'brand': agent.brand
            }

        return comparison

    def get_trending_topics(self, agent_id: int, limit: int = 5) -> List[str]:
        """Get trending topics based on agent's posts"""
        posts = self.db.query(Content).filter(
            Content.agent_id == agent_id,
            Content.status == 'published'
        ).all()

        topics = {}
        for post in posts:
            agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
            if agent and agent.fields:
                for field in agent.fields:
                    topics[field] = topics.get(field, 0) + 1

        sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)
        return [topic[0] for topic in sorted_topics[:limit]]

    def get_interaction_breakdown(self, agent_id: int) -> Dict[str, int]:
        """Get breakdown of interaction types"""
        interaction_types = {
            'like': 0,
            'comment': 0,
            'follow': 0,
            'reply': 0
        }

        interactions = self.db.query(Interaction).filter(
            Interaction.agent_id == agent_id,
            Interaction.status == 'completed'
        ).all()

        for interaction in interactions:
            if interaction.interaction_type in interaction_types:
                interaction_types[interaction.interaction_type] += 1

        return interaction_types

    def generate_performance_report(self, agent_id: int) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        report = {
            'agent_id': agent_id,
            'generated_at': datetime.utcnow().isoformat(),
            'engagement_rate': self.calculate_engagement_rate(agent_id),
            'platform_performance': self.get_platform_performance(agent_id),
            'growth_metrics': self.get_growth_metrics(agent_id),
            'account_stats': self.get_account_stats(agent_id),
            'content_performance': self.get_content_performance(agent_id, limit=5),
            'trending_topics': self.get_trending_topics(agent_id),
            'interaction_breakdown': self.get_interaction_breakdown(agent_id)
        }

        return report

    def __del__(self):
        """Cleanup"""
        if self.db:
            self.db.close()
