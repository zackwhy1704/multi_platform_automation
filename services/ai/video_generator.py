"""
Avatar video generation using fal.ai Seed Dance (ByteDance Seedance 2.0).

Takes a reference photo + voiceover MP3 and returns a lip-synced talking-head video.

Flow (async):
  1. Submit reference-to-video task via fal_client.submit()
  2. Poll for completion
  3. Return video URL when ready
"""

import logging
from typing import Optional

from shared.config import FAL_KEY

logger = logging.getLogger(__name__)

SEEDANCE_MODEL = "bytedance/seedance-2.0/reference-to-video"

# Style templates: (seed_dance_prompt_suffix, aspect_ratio)
VIDEO_STYLES = {
    "professional": (
        "The person in @Image1 is speaking directly to the camera in a clean office environment, "
        "professional attire, confident posture, synchronized lip movement to @Audio1. "
        "Cinematic lighting, sharp focus.",
        "16:9",
    ),
    "warm": (
        "The person in @Image1 is speaking warmly and approachably to the camera, natural indoor setting, "
        "friendly expression, synchronized lip movement to @Audio1. "
        "Soft warm lighting, natural tones.",
        "9:16",
    ),
    "luxury": (
        "The person in @Image1 is presenting with authority in a premium luxury setting, "
        "sophisticated backdrop, synchronized lip movement to @Audio1. "
        "Dark cinematic tones, dramatic lighting.",
        "9:16",
    ),
}


async def generate_avatar_video(
    photo_url: str,
    audio_url: str,
    style: str = "professional",
) -> Optional[dict]:
    """
    Generate a lip-synced talking-head video via Seed Dance.

    Args:
        photo_url: Publicly accessible URL of the user's reference photo
        audio_url: Publicly accessible URL of the ElevenLabs-generated MP3
        style: One of "professional", "warm", "luxury"

    Returns:
        {"url": "https://...", "duration": "auto"} or None on failure.
    """
    if not FAL_KEY:
        logger.error("FAL_KEY is not configured — cannot generate avatar videos")
        return None

    import os
    os.environ["FAL_KEY"] = FAL_KEY

    prompt_suffix, aspect_ratio = VIDEO_STYLES.get(style, VIDEO_STYLES["professional"])

    try:
        import fal_client

        handler = fal_client.submit(
            SEEDANCE_MODEL,
            arguments={
                "prompt": prompt_suffix,
                "image_urls": [photo_url],
                "audio_urls": [audio_url],
                "resolution": "720p",
                "duration": "auto",
                "aspect_ratio": aspect_ratio,
                "generate_audio": False,  # we supply our own audio
            },
        )

        logger.info("Seed Dance task submitted: %s", handler.request_id)

        result = handler.get()  # blocks until complete (fal_client handles polling internally)

        video_url = result.get("video", {}).get("url")
        if not video_url:
            logger.error("No video URL in Seed Dance response: %s", result)
            return None

        logger.info("Seed Dance video ready: %s", video_url[:80])
        return {"url": video_url, "duration": "auto"}

    except Exception as e:
        logger.error("Seed Dance video generation error: %s", e)
        return None


def build_avatar_prompt(industry: list, topic: str, style: str) -> str:
    """Build the spoken script prompt sent to Claude for script generation before TTS."""
    industry_str = ", ".join(industry) if industry else "business"
    style_guidance = {
        "professional": "formal, authoritative, trust-building",
        "warm": "friendly, approachable, conversational",
        "luxury": "premium, aspirational, exclusive",
    }.get(style, "professional")
    return (
        f"Write a 30-second spoken video script for a {industry_str} professional "
        f"promoting: {topic}. Tone: {style_guidance}. "
        f"No hashtags, no stage directions. Plain spoken words only. Under 80 words."
    )
