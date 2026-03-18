"""
AI image generation using OpenAI gpt-image-1.

gpt-image-1 returns base64 by default (not URLs like DALL-E 3).
We decode the base64 image, save it locally, and return a public URL
so it can be used by Facebook/Instagram Graph API for posting.
"""

import base64
import logging
import os
import uuid
from typing import Optional

from shared.config import OPENAI_API_KEY, PUBLIC_BASE_URL

logger = logging.getLogger(__name__)

_client = None

# Use the SAME media directory as the gateway (project_root/media_files)
# gateway/media.py uses: os.path.dirname(os.path.dirname(__file__)) → project root
# This file is at services/ai/image_generator.py, so go up 2 levels to project root
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media_files")
os.makedirs(MEDIA_DIR, exist_ok=True)


def _get_client():
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def generate_image(prompt: str, size: str = "1024x1024", style: str = "vivid") -> Optional[str]:
    """
    Generate an image using OpenAI gpt-image-1.

    Returns:
        Public URL of the generated image (served from our gateway), or None on failure.
    """
    client = _get_client()
    if not client:
        logger.error("OpenAI API key not configured — cannot generate images")
        return None

    try:
        result = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            n=1,
            size=size,
        )

        image_data = result.data[0]

        # gpt-image-1 returns base64 by default
        if image_data.b64_json:
            # Decode base64 and save to file
            img_bytes = base64.b64decode(image_data.b64_json)
            filename = f"ai_{uuid.uuid4().hex}.png"
            file_path = os.path.join(MEDIA_DIR, filename)

            with open(file_path, "wb") as f:
                f.write(img_bytes)

            logger.info("Generated image saved: %s (%d bytes, prompt: %s...)",
                        filename, len(img_bytes), prompt[:50])

            # Return public URL served by our gateway
            if PUBLIC_BASE_URL:
                return f"{PUBLIC_BASE_URL}/media/{filename}"
            else:
                logger.error("PUBLIC_BASE_URL not set — cannot serve generated image")
                return None

        elif image_data.url:
            # Fallback: if URL is returned (e.g. dall-e-3 compatibility)
            logger.info("Generated image URL: %s... (prompt: %s...)",
                        image_data.url[:60], prompt[:50])
            return image_data.url

        else:
            logger.error("No image data in response")
            return None

    except Exception as e:
        logger.error("Image generation failed: %s", e)
        return None


def build_image_prompt(
    profile: dict,
    content_style: str = "",
    visual_style: str = "",
    topic: Optional[str] = None,
    platform: str = "instagram",
) -> str:
    """Build an optimized image generation prompt using the user's business profile."""
    industry = ", ".join(profile.get("industry", ["business"]))
    offerings = ", ".join(profile.get("offerings", []))
    tone = ", ".join(profile.get("tone", ["professional"]))

    style_modifiers = {
        "humorous": "funny, comedic, lighthearted, meme-worthy",
        "educational": "informative, clean, diagram-like, professional infographic style",
        "inspirational": "uplifting, warm lighting, motivational, beautiful composition",
        "behind_the_scenes": "candid, authentic, behind-the-scenes look, casual atmosphere",
        "product_showcase": "product photography, studio lighting, clean background, professional",
        "mixed": "engaging, eye-catching, social media optimized",
    }

    visual_modifiers = {
        "cartoon": "cartoon illustration style, colorful, fun, vector art",
        "minimalist": "clean minimalist design, white space, modern, simple",
        "bold_colorful": "bold colors, high contrast, vibrant, eye-catching graphic design",
        "photorealistic": "photorealistic, high quality photograph, natural lighting, DSLR quality",
        "meme_style": "meme format, bold text overlay space, internet humor style, relatable",
    }

    content_mod = style_modifiers.get(content_style, style_modifiers["mixed"])
    visual_mod = visual_modifiers.get(visual_style, visual_modifiers["photorealistic"])

    topic_line = f"Topic: {topic}. " if topic else ""

    prompt = (
        f"{topic_line}"
        f"Create a social media image for a {industry} business that offers {offerings}. "
        f"Style: {content_mod}. "
        f"Visual: {visual_mod}. "
        f"Tone: {tone}. "
        f"Optimized for {platform}. "
        f"No text overlays unless meme-style. High quality, engaging, shareable."
    )

    return prompt
