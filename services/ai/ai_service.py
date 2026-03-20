"""
AI content generation using Anthropic Claude API.
Generates platform-specific social media posts and captions.
Integrates with Pexels API for stock images.
"""

import logging
import re
import time
from typing import Optional

import anthropic
import httpx

from shared.config import ANTHROPIC_API_KEY, AI_MODEL, PEXELS_API_KEY

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]  # seconds between retries

# Conversational preamble phrases Claude sometimes emits — strip them from output
_PREAMBLE_PATTERNS = re.compile(
    r"^(i'?d be happy to help[.!]*|sure[,!]|certainly[,!]|of course[,!]|"
    r"here'?s? (is )?(your|a|an|the)|here you go[.!]*|"
    r"absolutely[,!]|great[,!]|no problem[,!])[^\n]*\n*",
    re.IGNORECASE,
)


def _strip_preamble(text: str) -> str:
    """Remove any conversational opener Claude might prepend."""
    return _PREAMBLE_PATTERNS.sub("", text).strip()


def _call_claude(
    *,
    model: str = AI_MODEL,
    max_tokens: int = 1024,
    system: str,
    messages: list,
) -> Optional[str]:
    """Call Claude with a system prompt and retry logic for transient errors."""
    if not client:
        logger.error("Anthropic API key not configured")
        return None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            raw = response.content[0].text.strip()
            cleaned = _strip_preamble(raw)
            if cleaned:
                return cleaned
            # If stripping removed everything, return raw (better than empty)
            logger.warning("Preamble strip removed entire response — returning raw")
            return raw.strip() or None
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "Claude API %d (attempt %d/%d), retrying in %ds...",
                    e.status_code, attempt + 1, MAX_RETRIES, delay,
                )
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
    """Generate a social media post using Claude."""
    industry = ", ".join(profile.get("industry", [])) or "general business"
    offerings = ", ".join(profile.get("offerings", [])) or "products and services"
    goals = ", ".join(profile.get("business_goals", [])) or "grow the business"
    tone = ", ".join(profile.get("tone", ["professional"]))

    platform_instruction = {
        "facebook": (
            "Write a single Facebook post. Be conversational and engaging. "
            "End with a question to drive comments. Use short paragraphs."
        ),
        "instagram": (
            "Write a single Instagram caption. Open with a strong hook, be concise and visual. "
            "Include relevant emojis. End with 10-15 relevant hashtags."
        ),
    }.get(platform, "Write a single engaging social media post.")

    topic_line = f"\nPost topic/theme: {topic}" if topic else ""

    return _call_claude(
        max_tokens=1024,
        system=(
            "You are a social media content strategist. "
            "Output ONLY the post text — no preamble, no explanation, no labels."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"{platform_instruction}\n\n"
                f"Business details:\n"
                f"- Industry: {industry}\n"
                f"- Products/Services: {offerings}\n"
                f"- Goals: {goals}\n"
                f"- Tone: {tone}"
                f"{topic_line}"
            ),
        }],
    )


def generate_reply(
    platform: str,
    original_post: str,
    comment: str,
    tone: str = "professional",
) -> Optional[str]:
    """Generate an AI reply to a comment."""
    return _call_claude(
        max_tokens=256,
        system=(
            "You are a community manager replying to comments on social media. "
            "Output ONLY the reply text — no preamble, no explanation."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Platform: {platform}\n"
                f"Tone: {tone}\n\n"
                f"Original post: {original_post[:500]}\n"
                f"Comment to reply to: {comment[:500]}\n\n"
                "Write a brief, authentic reply (1-3 sentences)."
            ),
        }],
    )


def generate_caption_for_media(
    platform: str,
    profile: dict,
    media_type: str = "photo",
    topic: Optional[str] = None,
) -> Optional[str]:
    """Generate a caption for user-provided photo or video."""
    industry = ", ".join(profile.get("industry", [])) or "general business"
    offerings = ", ".join(profile.get("offerings", [])) or "products and services"
    tone = ", ".join(profile.get("tone", ["professional"]))

    platform_instruction = {
        "facebook": (
            f"Write a Facebook caption for this {media_type}. "
            "Be conversational. End with a question to drive comments."
        ),
        "instagram": (
            f"Write an Instagram caption for this {media_type}. "
            "Open with a strong hook, add relevant emojis, end with 10-15 hashtags."
        ),
    }.get(platform, f"Write a caption for this {media_type}.")

    topic_line = f"\nThe {media_type} is about: {topic}" if topic else ""

    return _call_claude(
        max_tokens=512,
        system=(
            "You are a social media content strategist. "
            "Output ONLY the caption text — no preamble, no explanation, no labels."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"{platform_instruction}\n\n"
                f"Business details:\n"
                f"- Industry: {industry}\n"
                f"- Products/Services: {offerings}\n"
                f"- Tone: {tone}"
                f"{topic_line}"
            ),
        }],
    )


def generate_image_search_query(profile: dict, topic: Optional[str] = None) -> str:
    """Generate a Pexels stock photo search query from the business profile."""
    industry = ", ".join(profile.get("industry", [])) or "business"
    offerings = ", ".join(profile.get("offerings", [])) or ""
    topic_line = f"\nPost topic: {topic}" if topic else ""

    result = _call_claude(
        max_tokens=30,
        system="Output ONLY a short search query (2-4 words). No punctuation, no explanation.",
        messages=[{
            "role": "user",
            "content": (
                f"Generate a Pexels stock photo search query for a social media post.\n"
                f"Business: {industry}\n"
                f"Products/Services: {offerings}"
                f"{topic_line}"
            ),
        }],
    )
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

            import random
            photo = random.choice(photos[:3])
            image_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("original")

            return {
                "url": image_url,
                "photographer": photo.get("photographer", "Unknown"),
                "alt": photo.get("alt", query),
            }
    except Exception as e:
        logger.error("Pexels fetch failed: %s", e)
        return None
