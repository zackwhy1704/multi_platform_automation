"""
AI content generation using Anthropic Claude API.
Generates platform-specific social media posts and captions.
Integrates with Pexels API for stock images.
"""

import logging
import time
from typing import Optional

import anthropic
import httpx

from shared.config import ANTHROPIC_API_KEY, AI_MODEL, PEXELS_API_KEY

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]  # seconds between retries


def _call_claude(*, model: str = AI_MODEL, max_tokens: int = 1024, messages: list) -> Optional[str]:
    """Call Claude with retry logic for transient errors (529 overloaded, 5xx)."""
    if not client:
        logger.error("Anthropic API key not configured")
        return None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
            )
            return response.content[0].text.strip()
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning("Claude API %d (attempt %d/%d), retrying in %ds...",
                               e.status_code, attempt + 1, MAX_RETRIES, delay)
                time.sleep(delay)
                continue
            logger.error("Claude API error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            return None
        except Exception as e:
            logger.error("Claude API unexpected error: %s", e)
            return None
    return None


def generate_post(
    platform: str,
    profile: dict,
    topic: Optional[str] = None,
) -> Optional[str]:
    """
    Generate a social media post using Claude.

    Args:
        platform: 'facebook' or 'instagram'
        profile: User profile dict with industry, skills, goals, tone
        topic: Optional topic/theme for the post

    Returns:
        Generated post text, or None on failure
    """
    industry = ", ".join(profile.get("industry", []))
    offerings = ", ".join(profile.get("offerings", []))
    goals = ", ".join(profile.get("business_goals", []))
    tone = ", ".join(profile.get("tone", ["professional"]))

    platform_guidance = {
        "facebook": (
            "Write a Facebook post. Keep it conversational and engaging. "
            "Include a question to drive comments. Use short paragraphs."
        ),
        "instagram": (
            "Write an Instagram caption. Start with a hook, be concise and visual. "
            "Include relevant emojis. Add 10-15 hashtags at the end."
        ),
    }

    topic_line = f"\nTopic/theme: {topic}" if topic else ""

    prompt = f"""You are a social media content strategist.

{platform_guidance.get(platform, platform_guidance['facebook'])}

Business profile:
- Industry: {industry}
- Products/Services: {offerings}
- Business goals: {goals}
- Preferred tone: {tone}
{topic_line}

Write ONE post. Output ONLY the post text, no preamble or explanation."""

    return _call_claude(max_tokens=1024, messages=[{"role": "user", "content": prompt}])


def generate_reply(
    platform: str,
    original_post: str,
    comment: str,
    tone: str = "professional",
) -> Optional[str]:
    """Generate an AI reply to a comment."""
    prompt = f"""You are replying to a comment on {platform}.

Original post: {original_post[:500]}
Comment to reply to: {comment[:500]}
Tone: {tone}

Write a brief, authentic reply (1-3 sentences). Output ONLY the reply text."""

    return _call_claude(max_tokens=256, messages=[{"role": "user", "content": prompt}])


def generate_caption_for_media(
    platform: str,
    profile: dict,
    media_type: str = "image",
    topic: Optional[str] = None,
) -> Optional[str]:
    """Generate a caption/description for user-provided media."""
    industry = ", ".join(profile.get("industry", []))
    offerings = ", ".join(profile.get("offerings", []))
    tone = ", ".join(profile.get("tone", ["professional"]))

    platform_guidance = {
        "facebook": "Write a Facebook caption for this photo/video. Conversational, include a question.",
        "instagram": "Write an Instagram caption. Start with a hook, add emojis, end with 10-15 hashtags.",
    }

    topic_line = f"\nThe {media_type} is about: {topic}" if topic else ""

    prompt = f"""You are a social media content strategist.

{platform_guidance.get(platform, platform_guidance['facebook'])}

Business profile:
- Industry: {industry}
- Products/Services: {offerings}
- Preferred tone: {tone}
{topic_line}

The user is posting a {media_type}. Write a caption that complements it.
Output ONLY the caption text, no preamble."""

    return _call_claude(max_tokens=512, messages=[{"role": "user", "content": prompt}])


def generate_image_search_query(profile: dict, topic: Optional[str] = None) -> str:
    """Use AI to generate a good Pexels search query based on the business profile."""
    industry = ", ".join(profile.get("industry", []))
    offerings = ", ".join(profile.get("offerings", []))

    topic_line = f"\nPost topic: {topic}" if topic else ""

    prompt = f"""Generate a short Pexels stock photo search query (2-4 words) for a social media post.

Business: {industry}
Products/Services: {offerings}
{topic_line}

Output ONLY the search query, nothing else. Example: "coffee shop interior" or "team meeting office"."""

    result = _call_claude(max_tokens=30, messages=[{"role": "user", "content": prompt}])
    if result:
        return result.strip('"').strip("'")
    return " ".join(profile.get("industry", ["business"]))


async def fetch_stock_image(query: str) -> Optional[dict]:
    """
    Search Pexels for a stock image.

    Returns: {"url": "https://...", "photographer": "Name", "alt": "description"}
    or None on failure.
    """
    if not PEXELS_API_KEY:
        logger.error("Pexels API key not configured")
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 5, "orientation": "square"},
                headers={"Authorization": PEXELS_API_KEY},
            )
            if resp.status_code != 200:
                logger.error("Pexels API error: %s %s", resp.status_code, resp.text)
                return None

            data = resp.json()
            photos = data.get("photos", [])
            if not photos:
                logger.warning("No Pexels results for query: %s", query)
                return None

            # Pick first result
            import random
            photo = random.choice(photos[:3])
            # Use medium size for social media (good quality, reasonable size)
            image_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")

            return {
                "url": image_url,
                "photographer": photo.get("photographer", "Unknown"),
                "alt": photo.get("alt", query),
            }
    except Exception as e:
        logger.error("Pexels fetch failed: %s", e)
        return None
