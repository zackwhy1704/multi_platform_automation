"""
AI video generation using Kling AI API.

Generates short-form video (5-10s) from text prompts for social media Reels/posts.
Uses the official Kling AI API with JWT authentication.

Flow (async):
  1. Submit text-to-video task → get task_id
  2. Poll for completion (typically 1-3 minutes)
  3. Return video URL when ready
"""

import time
import logging
from typing import Optional

import httpx

from shared.config import KLING_ACCESS_KEY, KLING_SECRET_KEY

logger = logging.getLogger(__name__)

KLING_API_BASE = "https://api.klingai.com/v1"


def _generate_jwt_token() -> Optional[str]:
    """Generate JWT token for Kling API authentication."""
    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        return None

    try:
        import jwt
        import time as t

        payload = {
            "iss": KLING_ACCESS_KEY,
            "exp": int(t.time()) + 1800,  # 30 min expiry
            "nbf": int(t.time()) - 5,
        }
        token = jwt.encode(payload, KLING_SECRET_KEY, algorithm="HS256")
        return token
    except ImportError:
        logger.error("PyJWT not installed — run: pip install PyJWT")
        return None
    except Exception as e:
        logger.error("JWT token generation failed: %s", e)
        return None


async def generate_video(
    prompt: str,
    duration: str = "5",
    aspect_ratio: str = "1:1",
    model: str = "kling-v1",
) -> Optional[dict]:
    """
    Generate a video using Kling AI text-to-video.

    Args:
        prompt: Text description of the video to generate
        duration: Video duration in seconds ("5" or "10")
        aspect_ratio: "1:1", "16:9", "9:16"
        model: "kling-v1", "kling-v1-5", "kling-v2"

    Returns:
        {"url": "https://...", "task_id": "...", "duration": "5s"}
        or None on failure.
    """
    token = _generate_jwt_token()
    if not token:
        logger.error("Kling API keys not configured — cannot generate videos")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "model_name": model,
        "prompt": prompt,
        "cfg_scale": 0.5,
        "mode": "std",
        "duration": duration,
        "aspect_ratio": aspect_ratio,
    }

    try:
        # Step 1: Submit the task
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{KLING_API_BASE}/videos/text2video",
                json=payload,
                headers=headers,
            )

        if resp.status_code != 200:
            logger.error("Kling API task submission failed: %s %s", resp.status_code, resp.text)
            return None

        data = resp.json().get("data", {})
        task_id = data.get("task_id")
        if not task_id:
            logger.error("No task_id in Kling response: %s", resp.json())
            return None

        logger.info("Kling video task submitted: %s (prompt: %s...)", task_id, prompt[:50])

        # Step 2: Poll for completion (max ~5 minutes)
        for attempt in range(60):  # 60 × 5s = 5 minutes
            await _async_sleep(5)

            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    status_resp = await client.get(
                        f"{KLING_API_BASE}/videos/text2video/{task_id}",
                        headers=headers,
                    )
            except Exception as poll_err:
                logger.warning("Kling poll attempt %d failed: %s", attempt, poll_err)
                continue

            if status_resp.status_code != 200:
                logger.warning("Kling poll status %d on attempt %d", status_resp.status_code, attempt)
                continue

            status_data = status_resp.json().get("data", {})
            task_status = status_data.get("task_status")

            if task_status == "succeed":
                works = status_data.get("task_result", {}).get("videos", [])
                if works:
                    video_url = works[0].get("url")
                    logger.info("Kling video ready: %s", video_url[:80] if video_url else "no url")
                    return {
                        "url": video_url,
                        "task_id": task_id,
                        "duration": f"{duration}s",
                    }

            elif task_status == "failed":
                error_msg = status_data.get("task_status_msg", "Unknown error")
                logger.error("Kling video generation failed: %s", error_msg)
                return None

            # Still processing — continue polling

        logger.error("Kling video generation timed out after 5 minutes (task: %s)", task_id)
        return None

    except Exception as e:
        logger.error("Kling video generation error: %s", e)
        return None


async def _async_sleep(seconds: int):
    """Async-friendly sleep."""
    import asyncio
    await asyncio.sleep(seconds)


def build_video_prompt(
    profile: dict,
    content_style: str = "",
    visual_style: str = "",
    topic: Optional[str] = None,
    platform: str = "instagram",
) -> str:
    """Build an optimized video generation prompt from the user's profile."""
    industry = ", ".join(profile.get("industry", ["business"]))
    offerings = ", ".join(profile.get("offerings", []))
    tone = ", ".join(profile.get("tone", ["professional"]))

    style_modifiers = {
        "humorous": "funny, comedic scene, lighthearted animation",
        "educational": "informative explainer, clean motion graphics",
        "inspirational": "uplifting atmosphere, cinematic, warm tones",
        "behind_the_scenes": "candid camera, authentic workplace footage style",
        "product_showcase": "product reveal, smooth camera movement, studio setting",
        "mixed": "engaging social media video, dynamic movement",
    }

    visual_modifiers = {
        "cartoon": "animated cartoon style, colorful 2D animation",
        "minimalist": "clean minimal motion design, white background",
        "bold_colorful": "vibrant colors, fast cuts, bold graphics",
        "photorealistic": "cinematic, realistic footage, natural lighting",
        "meme_style": "meme video format, quick transitions, relatable scenarios",
    }

    content_mod = style_modifiers.get(content_style, style_modifiers["mixed"])
    visual_mod = visual_modifiers.get(visual_style, visual_modifiers["photorealistic"])

    topic_line = f"about {topic}, " if topic else ""

    prompt = (
        f"Short social media video {topic_line}"
        f"for a {industry} business. "
        f"{content_mod}. {visual_mod}. "
        f"Tone: {tone}. Optimized for {platform} Reels. "
        f"5 seconds, engaging, shareable."
    )

    return prompt
