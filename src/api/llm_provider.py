import os
from anthropic import Anthropic
from typing import Optional, Dict, Any
from src.database.db import get_db
from src.database.models import APIConfiguration


class LLMProvider:
    """Manages LLM API calls with support for multiple providers"""

    def __init__(self, provider: str = 'claude', custom_api_key: Optional[str] = None):
        self.provider = provider.lower()
        self.api_key = custom_api_key or self._get_api_key()
        self.client = self._initialize_client()

    def _get_api_key(self) -> str:
        """Get API key from environment or database"""
        # Try environment variable first
        env_key = f'{self.provider.upper()}_API_KEY'
        if env_key in os.environ:
            return os.environ[env_key]

        # Try database
        db = get_db()
        try:
            config = db.query(APIConfiguration).filter(
                APIConfiguration.provider == self.provider,
                APIConfiguration.is_active == True
            ).first()
            if config:
                return config.api_key
        finally:
            db.close()

        raise ValueError(f"No API key found for provider: {self.provider}")

    def _initialize_client(self):
        """Initialize the appropriate LLM client"""
        if self.provider == 'claude':
            return Anthropic(api_key=self.api_key)
        elif self.provider == 'openai':
            try:
                from openai import OpenAI
                return OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("OpenAI SDK not installed. Install with: pip install openai")
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def generate_content(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate content using the configured LLM"""
        if self.provider == 'claude':
            return self._claude_generate(prompt, max_tokens, temperature, system_prompt)
        elif self.provider == 'openai':
            return self._openai_generate(prompt, max_tokens, temperature, system_prompt)

    def _claude_generate(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str]
    ) -> str:
        """Generate content using Claude API"""
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful social media content creator.",
            messages=messages
        )

        return response.content[0].text

    def _openai_generate(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str]
    ) -> str:
        """Generate content using OpenAI API"""
        response = self.client.chat.completions.create(
            model="gpt-4-turbo",
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt or "You are a helpful social media content creator."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response.choices[0].message.content

    @staticmethod
    def set_api_key(provider: str, api_key: str, model_name: Optional[str] = None):
        """Store API key in database for future use"""
        db = get_db()
        try:
            existing = db.query(APIConfiguration).filter(
                APIConfiguration.provider == provider
            ).first()

            if existing:
                existing.api_key = api_key
                existing.model_name = model_name
                existing.is_active = True
            else:
                config = APIConfiguration(
                    provider=provider,
                    api_key=api_key,
                    model_name=model_name,
                    is_active=True
                )
                db.add(config)

            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    @staticmethod
    def list_providers():
        """List all configured API providers"""
        db = get_db()
        try:
            configs = db.query(APIConfiguration).all()
            return [(c.provider, c.is_active) for c in configs]
        finally:
            db.close()
