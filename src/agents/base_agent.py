import json
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime
from src.database.models import Agent, Content, Interaction, SocialMediaAccount
from src.database.db import get_db
from src.api.llm_provider import LLMProvider
from src.api.image_generator import GeminiImageGenerator


class BaseAgent:
    """Base class for all AI agents"""

    def __init__(self, agent_id: int, llm_provider: str = 'claude', api_key: Optional[str] = None):
        self.agent_id = agent_id
        self.db = get_db()
        self.agent = self._load_agent_config()
        self.llm = LLMProvider(provider=llm_provider, custom_api_key=api_key)

    def _load_agent_config(self) -> Agent:
        """Load agent configuration from database"""
        agent = self.db.query(Agent).filter(Agent.id == self.agent_id).first()
        if not agent:
            raise ValueError(f"Agent {self.agent_id} not found")
        return agent

    def get_system_prompt(self) -> str:
        """Build system prompt based on agent personality"""
        return f"""You are {self.agent.name}, a social media marketing AI agent.

Brand: {self.agent.brand}
Persona: {self.agent.persona}
Tone of Voice: {self.agent.tone_of_voice}
Fields of Expertise: {', '.join(self.agent.fields)}
Bio: {self.agent.bio or 'Not specified'}

Your goal is to create engaging content, build community through meaningful interactions, and grow the brand's presence.
Always stay true to the brand voice and persona. Create authentic, valuable content that resonates with the target audience."""

    def generate_content(
        self,
        content_type: str,
        platform: str,
        topic: Optional[str] = None,
        target_audience: Optional[str] = None,
        max_length: int = 280
    ) -> Dict[str, Any]:
        """Generate content for a social media post"""

        if not topic:
            topic = self.agent.fields[0] if self.agent.fields else "general"

        prompt = self._build_content_prompt(content_type, platform, topic, target_audience, max_length)

        response = self.llm.generate_content(
            prompt=prompt,
            system_prompt=self.get_system_prompt(),
            max_tokens=500
        )

        content_data = self._parse_content_response(response, platform)
        return content_data

    def _build_content_prompt(
        self,
        content_type: str,
        platform: str,
        topic: str,
        target_audience: Optional[str],
        max_length: int
    ) -> str:
        """Build content generation prompt"""
        audience_context = f"for {target_audience}" if target_audience else ""

        return f"""Create a {content_type} post for {platform} {audience_context}.
Topic: {topic}
Max length: {max_length} characters

Respond with ONLY a valid JSON object, no markdown, no code blocks, no explanation. Use this exact format:
{{"caption": "the post text here", "hashtags": ["tag1", "tag2"], "emojis": ["🔥", "💡"], "engagement_tips": "tip here"}}

Make it authentic, engaging, and aligned with the brand voice."""

    def _parse_content_response(self, response: str, platform: str) -> Dict[str, Any]:
        """Parse LLM response into structured content"""
        import re
        data = None

        # Strip markdown code blocks like ```json ... ```
        cleaned = re.sub(r'```(?:json)?\s*', '', response).strip().rstrip('`').strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object anywhere in the string
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not data:
            data = {
                "caption": response,
                "hashtags": [],
                "emojis": [],
                "engagement_tips": ""
            }

        return {
            "caption": data.get("caption", ""),
            "hashtags": data.get("hashtags", []),
            "emojis": data.get("emojis", []),
            "platform": platform,
            "engagement_tips": data.get("engagement_tips", "")
        }

    def create_draft_post(
        self,
        platform: str,
        topic: str,
        target_audience: Optional[str] = None,
        generate_images: bool = True
    ) -> int:
        """Create a draft post with text + carousel images using parallel agents"""
        platform_config = self._get_platform_config(platform)

        # Results containers for parallel execution
        text_result = {}
        image_result = {"images": [], "prompts": []}

        def generate_text():
            content_data = self.generate_content(
                content_type="social media post",
                platform=platform,
                topic=topic,
                target_audience=target_audience,
                max_length=platform_config.get('max_length', 280)
            )
            text_result.update(content_data)

        def generate_images_fn():
            try:
                img_gen = GeminiImageGenerator()
                prompts = img_gen.build_image_prompts(
                    post_text=topic,
                    platform=platform,
                    brand=self.agent.brand,
                    persona=self.agent.persona,
                    topic=topic,
                    image_style=getattr(self.agent, 'image_style', None) or 'ultra realistic photography',
                    num_images=3
                )
                images = img_gen.generate_carousel(prompts)
                image_result["images"] = images
                image_result["prompts"] = prompts
            except Exception as e:
                print(f"Image generation skipped: {e}")

        # Run both agents in parallel
        text_thread = threading.Thread(target=generate_text)
        image_thread = threading.Thread(target=generate_images_fn) if generate_images else None

        text_thread.start()
        if image_thread:
            image_thread.start()

        text_thread.join()
        if image_thread:
            image_thread.join(timeout=30)

        post = Content(
            agent_id=self.agent_id,
            title=text_result.get('caption', topic)[:100],
            body=text_result.get('caption', ''),
            hashtags=text_result.get('hashtags', []),
            media_urls=image_result["images"],  # base64 images stored here
            platform=platform,
            status='draft'
        )

        self.db.add(post)
        self.db.commit()
        return post.id

    def plan_engagement(
        self,
        platform: str,
        engagement_target: str = "brand_awareness"
    ) -> List[Dict[str, Any]]:
        """Plan engagement activities"""
        prompt = f"""Plan {engagement_target} engagement activities for {platform}.
As {self.agent.name}, suggest 5 specific engagement actions:
1. Account types to interact with
2. Content themes to comment on
3. Hashtags to follow
4. Conversation starters
5. Collaboration opportunities

Format as JSON list with fields: "action", "description", "difficulty", "expected_roi" """

        response = self.llm.generate_content(
            prompt=prompt,
            system_prompt=self.get_system_prompt(),
            max_tokens=1000
        )

        try:
            import json
            activities = json.loads(response)
        except:
            activities = [{"action": "Engage with brand-relevant content", "description": response}]

        return activities

    def _get_platform_config(self, platform: str) -> Dict[str, Any]:
        """Get platform-specific configuration"""
        configs = {
            'instagram': {'max_length': 2200, 'supports_video': True},
            'twitter': {'max_length': 280, 'supports_video': True},
            'tiktok': {'max_length': 150, 'supports_video': True}
        }
        return configs.get(platform, {'max_length': 280})

    def get_analytics(self) -> Dict[str, Any]:
        """Get agent analytics summary"""
        from sqlalchemy import func

        analytics_data = {
            'total_posts': self.db.query(func.count(Content.id)).filter(
                Content.agent_id == self.agent_id,
                Content.status == 'published'
            ).scalar() or 0,
            'total_interactions': self.db.query(func.count(Interaction.id)).filter(
                Interaction.agent_id == self.agent_id,
                Interaction.status == 'completed'
            ).scalar() or 0,
            'accounts': len(self.agent.accounts),
            'is_active': self.agent.is_active
        }
        return analytics_data

    def __del__(self):
        """Cleanup database connection"""
        if self.db:
            self.db.close()
