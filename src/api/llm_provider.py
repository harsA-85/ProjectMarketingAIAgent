import os
import time
import logging
from anthropic import Anthropic
from typing import Optional, Dict, Any, Callable
from src.database.db import get_db
from src.database.models import APIConfiguration


def _retry_on_transient(fn: Callable, max_attempts: int = 3, base_delay: float = 2.0):
    """Retry fn() on transient network/API errors with exponential backoff.
    Retries on: connection errors, timeouts, 429, 5xx, overloaded.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            transient = any(k in msg for k in [
                'connection error', 'timeout', 'timed out', 'overloaded',
                'rate limit', 'too many requests', '429',
                '500', '502', '503', '504', 'service unavailable',
                'read timeout', 'connection reset', 'connection aborted',
            ])
            if not transient or attempt == max_attempts - 1:
                raise
            delay = base_delay * (3 ** attempt)
            logging.warning(
                f"[LLMProvider] Transient error (attempt {attempt + 1}/{max_attempts}): "
                f"{type(e).__name__}: {str(e)[:120]} — retrying in {delay:.1f}s"
            )
            last_exc = e
            time.sleep(delay)
    if last_exc:
        raise last_exc


class LLMProvider:
    """Manages LLM API calls with support for multiple providers"""

    def __init__(self, provider: str = 'claude', custom_api_key: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider.lower()
        self.model = model  # specific model override (e.g. claude-opus-4-6)
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
        elif self.provider == 'gemini':
            try:
                from google import genai
                return genai.Client(api_key=self.api_key)
            except ImportError:
                raise ImportError("Google GenAI SDK not installed. Install with: pip install google-genai")
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
        elif self.provider == 'gemini':
            return self._gemini_generate(prompt, max_tokens, temperature, system_prompt)

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

        response = _retry_on_transient(lambda: self.client.messages.create(
            model=self.model or "claude-sonnet-4-6",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "You are a helpful social media content creator.",
            messages=messages
        ))

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
            model=self.model or "gpt-4o",
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

    def _gemini_generate(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str]
    ) -> str:
        """Generate content using Google Gemini API"""
        from google.genai import types
        full_prompt = f"{system_prompt or 'You are a helpful social media content creator.'}\n\n{prompt}"
        response = self.client.models.generate_content(
            model=self.model or 'gemini-3-flash-preview',
            contents=full_prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        return response.text

    def generate_content_with_image(
        self,
        prompt: str,
        image_b64: str,
        image_mime: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate content that includes an image (base64). Supports Claude and Gemini."""
        if self.provider == 'claude':
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": image_b64}},
                    {"type": "text", "text": prompt or "Please analyse this image."}
                ]
            }]
            response = _retry_on_transient(lambda: self.client.messages.create(
                model=self.model or "claude-sonnet-4-6",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt or "You are a helpful assistant.",
                messages=messages
            ))
            return response.content[0].text

        elif self.provider == 'gemini':
            import base64
            from google.genai import types
            image_bytes = base64.b64decode(image_b64)
            full_text = f"{system_prompt or ''}\n\n{prompt or 'Please analyse this image.'}".strip()
            response = self.client.models.generate_content(
                model=self.model or 'gemini-3-flash-preview',
                contents=[
                    types.Content(parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type=image_mime),
                        types.Part.from_text(text=full_text),
                    ])
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                ),
            )
            return response.text

        else:
            # Fallback for providers without vision: treat as text-only
            return self.generate_content(prompt, max_tokens, temperature, system_prompt)

    def generate_content_with_images(
        self,
        prompt: str,
        images: list,  # [{'data': b64, 'mime': 'image/png'}, ...]
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate content with multiple images. Claude only (falls back to single-image for others)."""
        if not images:
            return self.generate_content(prompt, max_tokens, temperature, system_prompt)
        if len(images) == 1:
            return self.generate_content_with_image(
                prompt, images[0]['data'], images[0].get('mime', 'image/png'),
                max_tokens, temperature, system_prompt
            )
        if self.provider == 'claude':
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": img.get('mime', 'image/png'), "data": img['data']}}
                for img in images
            ]
            content.append({"type": "text", "text": prompt or "Please analyse these images."})
            response = _retry_on_transient(lambda: self.client.messages.create(
                model=self.model or "claude-sonnet-4-6",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt or "You are a helpful assistant.",
                messages=[{"role": "user", "content": content}]
            ))
            return response.content[0].text
        # Non-Claude fallback: use the first image only
        return self.generate_content_with_image(
            prompt, images[0]['data'], images[0].get('mime', 'image/png'),
            max_tokens, temperature, system_prompt
        )

    def generate_with_search(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.5,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate content with live Google Search grounding (Gemini only).
        Falls back to regular generation for other providers."""
        if self.provider != 'gemini':
            return self.generate_content(prompt, max_tokens, temperature, system_prompt)

        from google.genai import types
        full_prompt = f"{system_prompt or 'You are a research and fact-checking assistant.'}\n\n{prompt}"
        try:
            response = self.client.models.generate_content(
                model=self.model or 'gemini-3-flash-preview',
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = response.text or ''
            # Append grounding sources if available
            try:
                meta = response.candidates[0].grounding_metadata
                if meta and meta.grounding_chunks:
                    sources = []
                    for chunk in meta.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web:
                            sources.append(f"- {chunk.web.title}: {chunk.web.uri}")
                    if sources:
                        text += '\n\n[Sources checked]\n' + '\n'.join(sources)
            except Exception:
                pass
            return text
        except Exception as e:
            # Graceful fallback if search tool isn't available
            import logging
            logging.getLogger(__name__).warning(f"Search grounding failed ({e}), falling back to plain generation")
            return self.generate_content(prompt, max_tokens, temperature, system_prompt)

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
