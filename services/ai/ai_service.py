"""
AI content generation using Anthropic Claude API.
Generates platform-specific social media posts.
"""

import logging
from typing import Optional

import anthropic

from shared.config import ANTHROPIC_API_KEY, AI_MODEL

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


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
    if not client:
        logger.error("Anthropic API key not configured")
        return None

    industry = ", ".join(profile.get("industry", []))
    skills = ", ".join(profile.get("skills", []))
    goals = ", ".join(profile.get("career_goals", []))
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

Author profile:
- Industry: {industry}
- Skills: {skills}
- Career goals: {goals}
- Preferred tone: {tone}
{topic_line}

Write ONE post. Output ONLY the post text, no preamble or explanation."""

    try:
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("AI generation failed: %s", e)
        return None


def generate_reply(
    platform: str,
    original_post: str,
    comment: str,
    tone: str = "professional",
) -> Optional[str]:
    """Generate an AI reply to a comment."""
    if not client:
        return None

    prompt = f"""You are replying to a comment on {platform}.

Original post: {original_post[:500]}
Comment to reply to: {comment[:500]}
Tone: {tone}

Write a brief, authentic reply (1-3 sentences). Output ONLY the reply text."""

    try:
        response = client.messages.create(
            model=AI_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("AI reply generation failed: %s", e)
        return None
