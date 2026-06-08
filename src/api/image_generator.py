import os
import io
import base64
import logging
import traceback
from typing import List, Optional

log = logging.getLogger(__name__)


class BaseImageGenerator:
    """Shared helpers. Subclasses must implement generate_image() and set MODEL."""

    MODEL = "base"

    def generate_image(self, prompt: str) -> Optional[str]:  # pragma: no cover
        raise NotImplementedError

    def generate_carousel(self, prompts: List[str], retries: int = 1) -> List[str]:
        """Generate multiple images; skips any that fail after retries."""
        images = []
        for i, prompt in enumerate(prompts):
            img = None
            for attempt in range(retries + 1):
                img = self.generate_image(prompt)
                if img:
                    break
                log.warning(f"[ImageGen] Image {i+1}/{len(prompts)} attempt {attempt+1} failed, retrying…")
            if img:
                images.append(img)
                log.info(f"[ImageGen] ✅ Image {i+1}/{len(prompts)} generated ({len(img)//1000}KB)")
            else:
                log.error(f"[ImageGen] ❌ Image {i+1}/{len(prompts)} failed after all retries.")
        return images

    def build_image_prompts(
        self,
        post_text: str,
        platform: str,
        brand: str,
        persona: str,
        topic: str,
        image_style: str = 'ultra realistic photography',
        num_images: int = 3
    ) -> List[str]:
        """Build visual prompts for carousel images."""
        platform_context = {
            "instagram": "square format, aesthetically pleasing, high contrast",
            "twitter":   "wide format, bold and eye-catching",
            "tiktok":    "vertical format, dynamic and energetic"
        }
        context = platform_context.get(platform, "professional")
        base = (
            f"{image_style}, {context}, representing brand '{brand}', "
            f"topic: {topic}. Photorealistic. No text, no words, no letters in the image."
        )

        prompts = [
            f"Hero image: {base} Wide establishing shot, inspiring and bold.",
            f"Detail shot: {base} Close-up that evokes emotion and engagement.",
            f"Lifestyle: {base} Real-world scene with people or product in action.",
            f"Behind the scenes: {base} Candid, authentic moment that builds trust.",
        ]
        return prompts[:num_images]


class GeminiImageGenerator(BaseImageGenerator):
    """Generates images using Google Gemini gemini-3.1-flash-image-preview"""

    MODEL = "gemini-3.1-flash-image-preview"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")

        from google import genai
        self.client = genai.Client(api_key=self.api_key)

    def generate_image(self, prompt: str) -> Optional[str]:
        """Generate a single image; returns base64 JPEG string or None."""
        try:
            response = self.client.models.generate_content(
                model=self.MODEL,
                contents=[prompt],
            )

            # Image is in candidates[0].content.parts → inline_data
            parts = response.candidates[0].content.parts
            for part in parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    raw = part.inline_data.data
                    if isinstance(raw, (bytes, bytearray)):
                        return base64.b64encode(raw).decode('utf-8')
                    return raw  # already a string

            log.warning(f"[ImageGen] No image part in response for: {prompt[:80]}")

        except Exception as e:
            log.error(f"[ImageGen] generate_image FAILED: {e}\n{traceback.format_exc()}")

        return None


class OpenAIImageGenerator(BaseImageGenerator):
    """Generates images using OpenAI's gpt-image-1 model.

    Returns base64 JPEG strings (the API returns PNG b64; we transcode to JPEG
    so output is byte-compatible with the Gemini path and the IG/X upload code
    that expects JPEG)."""

    MODEL = "gpt-image-1"

    # platform → gpt-image-1 supported size
    SIZE_FOR_PLATFORM = {
        "instagram": "1024x1024",   # square
        "twitter":   "1536x1024",   # landscape
        "tiktok":    "1024x1536",   # portrait
    }

    def __init__(self, api_key: Optional[str] = None, quality: str = "high"):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key or self.api_key.strip().lower().startswith('your_'):
            raise ValueError("OPENAI_API_KEY not set (or still a placeholder) in environment")
        self.quality = quality
        from openai import OpenAI
        self.client = OpenAI(api_key=self.api_key)

    def generate_image(self, prompt: str, size: str = "1024x1024") -> Optional[str]:
        """Generate a single image; returns base64 JPEG string or None."""
        try:
            result = self.client.images.generate(
                model=self.MODEL,
                prompt=prompt,
                size=size,
                quality=self.quality,
                n=1,
            )
            b64_png = result.data[0].b64_json
            if not b64_png:
                log.warning(f"[ImageGen][OpenAI] No image data for: {prompt[:80]}")
                return None
            # Transcode PNG → JPEG to match the rest of the pipeline.
            try:
                from PIL import Image
                raw = base64.b64decode(b64_png)
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=92)
                return base64.b64encode(buf.getvalue()).decode('utf-8')
            except Exception as conv_e:
                log.warning(f"[ImageGen][OpenAI] JPEG transcode failed ({conv_e}); returning PNG b64.")
                return b64_png

        except Exception as e:
            log.error(f"[ImageGen][OpenAI] generate_image FAILED: {e}\n{traceback.format_exc()}")

        return None


# ─── Provider factory ─────────────────────────────────────────────────────
def get_image_generator(provider: Optional[str] = None) -> BaseImageGenerator:
    """Return an image generator for the requested provider.

    provider: 'openai' | 'gemini' | None. When None, uses the IMAGE_PROVIDER env
    var (default 'gemini'). Falls back to the other provider if the requested
    one is unavailable (missing/placeholder key), so image generation degrades
    gracefully instead of crashing.
    """
    choice = (provider or os.getenv('IMAGE_PROVIDER') or 'gemini').strip().lower()

    def _try(name):
        try:
            if name == 'openai':
                return OpenAIImageGenerator()
            return GeminiImageGenerator()
        except Exception as e:
            log.warning(f"[ImageGen] provider '{name}' unavailable: {e}")
            return None

    order = ['openai', 'gemini'] if choice == 'openai' else ['gemini', 'openai']
    for name in order:
        gen = _try(name)
        if gen:
            if name != choice:
                log.warning(f"[ImageGen] falling back to '{name}' (requested '{choice}').")
            log.info(f"[ImageGen] using provider '{name}' ({gen.MODEL}).")
            return gen
    raise RuntimeError("No image provider available — set GEMINI_API_KEY or OPENAI_API_KEY.")
