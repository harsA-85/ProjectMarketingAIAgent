import os
import base64
from typing import List, Optional


class GeminiImageGenerator:
    """Generates images using Google Gemini gemini-3.1-flash-image-preview"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("Gemini API key not found")

        from google import genai
        self.client = genai.Client(api_key=self.api_key)

    def generate_image(self, prompt: str) -> Optional[str]:
        """Generate a single image and return as base64 string"""
        try:
            from google.genai import types

            response = self.client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                )
            )

            for part in response.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    return base64.b64encode(part.inline_data.data).decode('utf-8')

        except Exception as e:
            print(f"Image generation error: {e}")

        return None

    def generate_carousel(self, prompts: List[str]) -> List[str]:
        """Generate multiple images for a carousel"""
        images = []
        for prompt in prompts:
            img = self.generate_image(prompt)
            if img:
                images.append(img)
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
        """Build visual prompts for carousel images"""
        platform_context = {
            "instagram": "square format, aesthetically pleasing, high contrast",
            "twitter": "wide format, bold and eye-catching",
            "tiktok": "vertical format, dynamic and energetic"
        }
        context = platform_context.get(platform, "professional")
        base = f"{image_style}, {context}, brand '{brand}', topic: {topic}. No text or words in the image."

        prompts = [
            f"Hero image: {base} Wide shot, inspiring and bold.",
            f"Detail shot: {base} Close-up, emotion and engagement.",
            f"Lifestyle: {base} Real-world context, people or product in action.",
        ]
        return prompts[:num_images]
