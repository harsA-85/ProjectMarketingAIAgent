from typing import List, Optional
from datetime import datetime, timedelta
import schedule
import time
from src.database.db import get_db
from src.database.models import Content


class PostScheduler:
    """Manages post scheduling and publication timing"""

    def __init__(self):
        self.db = get_db()
        self.scheduler = schedule.Scheduler()

    def schedule_post(self, post_id: int, publish_time: datetime) -> bool:
        """Schedule a post for future publication"""
        try:
            post = self.db.query(Content).filter(Content.id == post_id).first()
            if not post:
                return False

            post.status = 'scheduled'
            post.scheduled_at = publish_time
            self.db.commit()

            # Schedule the job
            delay_seconds = (publish_time - datetime.utcnow()).total_seconds()
            if delay_seconds > 0:
                self.scheduler.every(delay_seconds).seconds.do(
                    self._publish_post,
                    post_id=post_id
                ).tag(f'post_{post_id}')

            return True
        except Exception as e:
            print(f"Error scheduling post {post_id}: {e}")
            return False

    def schedule_recurring_posts(
        self,
        agent_id: int,
        platform: str,
        frequency: str,
        start_time: Optional[datetime] = None
    ) -> bool:
        """Schedule recurring content generation and posting"""
        try:
            if frequency == 'daily':
                hour = start_time.hour if start_time else 9
                minute = start_time.minute if start_time else 0
                self.scheduler.every().day.at(f"{hour:02d}:{minute:02d}").do(
                    self._generate_and_schedule_post,
                    agent_id=agent_id,
                    platform=platform
                ).tag(f'recurring_agent_{agent_id}')

            elif frequency == 'weekly':
                day = start_time.strftime('%A').lower() if start_time else 'monday'
                hour = start_time.hour if start_time else 9
                getattr(self.scheduler.every(), day).at(f"{hour:02d}:00").do(
                    self._generate_and_schedule_post,
                    agent_id=agent_id,
                    platform=platform
                ).tag(f'recurring_agent_{agent_id}')

            return True
        except Exception as e:
            print(f"Error setting recurring schedule: {e}")
            return False

    def get_due_posts(self) -> List[Content]:
        """Get all posts that are due for publishing"""
        now = datetime.utcnow()
        due_posts = self.db.query(Content).filter(
            Content.status == 'scheduled',
            Content.scheduled_at <= now
        ).all()
        return due_posts

    def get_scheduled_posts(self, agent_id: Optional[int] = None) -> List[dict]:
        """Get list of scheduled posts"""
        query = self.db.query(Content).filter(Content.status == 'scheduled')

        if agent_id:
            query = query.filter(Content.agent_id == agent_id)

        posts = query.order_by(Content.scheduled_at).all()
        return [
            {
                'id': p.id,
                'agent_id': p.agent_id,
                'platform': p.platform,
                'title': p.title,
                'scheduled_at': p.scheduled_at.isoformat(),
                'status': p.status
            }
            for p in posts
        ]

    def reschedule_post(self, post_id: int, new_time: datetime) -> bool:
        """Reschedule a post to a new time"""
        try:
            post = self.db.query(Content).filter(Content.id == post_id).first()
            if not post or post.status != 'scheduled':
                return False

            # Remove old schedule
            self.scheduler.clear(f'post_{post_id}')

            # Update and reschedule
            post.scheduled_at = new_time
            self.db.commit()

            delay_seconds = (new_time - datetime.utcnow()).total_seconds()
            if delay_seconds > 0:
                self.scheduler.every(delay_seconds).seconds.do(
                    self._publish_post,
                    post_id=post_id
                ).tag(f'post_{post_id}')

            return True
        except Exception as e:
            print(f"Error rescheduling post {post_id}: {e}")
            return False

    def cancel_scheduled_post(self, post_id: int) -> bool:
        """Cancel a scheduled post"""
        try:
            post = self.db.query(Content).filter(Content.id == post_id).first()
            if not post:
                return False

            post.status = 'draft'
            post.scheduled_at = None
            self.db.commit()

            self.scheduler.clear(f'post_{post_id}')
            return True
        except Exception as e:
            print(f"Error canceling post {post_id}: {e}")
            return False

    def optimize_posting_times(self, agent_id: int, platform: str) -> dict:
        """Analyze engagement data to suggest optimal posting times"""
        # This would analyze historical data to find peak engagement times
        return {
            'platform': platform,
            'suggested_times': ['09:00', '13:00', '18:00'],  # Placeholder
            'confidence': 0.75
        }

    def run_scheduler(self):
        """Run the scheduler loop (blocking)"""
        while True:
            self.scheduler.run_pending()
            time.sleep(60)  # Check every minute

    def _publish_post(self, post_id: int):
        """Internal method to publish a post"""
        try:
            post = self.db.query(Content).filter(Content.id == post_id).first()
            if post:
                post.status = 'published'
                post.published_at = datetime.utcnow()
                self.db.commit()
                print(f"Post {post_id} published to {post.platform}")
        except Exception as e:
            print(f"Error publishing post {post_id}: {e}")

    def _generate_and_schedule_post(self, agent_id: int, platform: str):
        """Internal method for recurring content generation"""
        try:
            from src.agents.base_agent import BaseAgent
            agent = BaseAgent(agent_id)
            post_id = agent.create_draft_post(platform, agent.agent.fields[0] if agent.agent.fields else "general")
            print(f"Generated recurring post {post_id} for agent {agent_id}")
        except Exception as e:
            print(f"Error generating recurring post: {e}")

    def __del__(self):
        """Cleanup"""
        if self.db:
            self.db.close()
