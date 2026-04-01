import os
import base64
import logging
import traceback
from typing import List, Optional

log = logging.getLogger(__name__)


class GeminiImageGenerator:
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
