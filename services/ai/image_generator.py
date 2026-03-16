"""
AI image generation using OpenAI gpt-image-1.

Replaces DALL-E 3 (deprecated May 2026).
Generates custom images from text prompts for social media posts.
"""

import logging
from typing import Optional

from shared.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def generate_image(prompt: str, size: str = "1024x1024", style: str = "vivid") -> Optional[str]:
    """
    Generate an image using OpenAI gpt-image-1.

    Args:
        prompt: Text description of the image to generate
        size: Image size — "1024x1024", "1792x1024", or "1024x1792"
        style: "vivid" (dramatic) or "natural" (realistic)

    Returns:
        URL of the generated image, or None on failure.
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
        image_url = result.data[0].url
        logger.info("Generated image: %s... (prompt: %s...)", image_url[:60], prompt[:50])
        return image_url
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
    """
    Build an optimized image generation prompt using the user's business profile.

    Uses content_style and visual_style from enhanced onboarding to create
    on-brand images (e.g. humorous cartoon for a comedy bakery account).
    """
    industry = ", ".join(profile.get("industry", ["business"]))
    offerings = ", ".join(profile.get("offerings", []))
    tone = ", ".join(profile.get("tone", ["professional"]))

    # Map content styles to prompt modifiers
    style_modifiers = {
        "humorous": "funny, comedic, lighthearted, meme-worthy",
        "educational": "informative, clean, diagram-like, professional infographic style",
        "inspirational": "uplifting, warm lighting, motivational, beautiful composition",
        "behind_the_scenes": "candid, authentic, behind-the-scenes look, casual atmosphere",
        "product_showcase": "product photography, studio lighting, clean background, professional",
        "mixed": "engaging, eye-catching, social media optimized",
    }

    # Map visual styles to prompt modifiers
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
