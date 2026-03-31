import os
import json
import base64
import requests
from typing import List, Dict, Optional


class GeminiImageGenerator:
    """Generates images using Google Gemini Imagen API"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("Gemini API key not found")

    def generate_image(self, prompt: str) -> Optional[str]:
        """Generate a single image and return as base64 string"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent?key={self.api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inlineData" in part:
                    return part["inlineData"]["data"]
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
        num_images: int = 3
    ) -> List[str]:
        """Build visual prompts for carousel images"""
        styles = {
            "instagram": "high-quality Instagram photo, vibrant colors, aesthetically pleasing, lifestyle photography",
            "twitter": "bold graphic design, eye-catching, professional, clean modern design",
            "tiktok": "dynamic energetic visual, bold colors, trendy Gen-Z aesthetic, vertical format"
        }
        style = styles.get(platform, "professional marketing photo")

        base_prompt = f"{style}, for brand '{brand}', topic: {topic}, persona: {persona}. NO text or words in image."

        prompts = [
            f"Main hero image: {base_prompt} Inspiring and bold, wide shot.",
            f"Detail shot: {base_prompt} Close-up, showing emotion and engagement.",
            f"Action/lifestyle: {base_prompt} People or product in real-world context.",
        ]

        return prompts[:num_images]
