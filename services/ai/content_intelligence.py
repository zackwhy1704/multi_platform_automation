"""
Content Intelligence Pipeline — idea mining, grading, expansion, and script writing.

Stages:
  1. Idea Mining   — scrape URL via Jina AI or accept pasted text
  2. Idea Grading  — Claude scores virality / originality / pillar alignment + niche angle
  3. Content Expansion — Claude expands into Reel script / Carousel / Text post / B-roll
  4. Script Writing — refine a selected format into final production-ready copy
"""

import json
import logging
from typing import Optional

import httpx

from services.ai.ai_service import _call_claude

logger = logging.getLogger(__name__)

JINA_BASE = "https://r.jina.ai/"

# ---------------------------------------------------------------------------
# Stage 1: Idea Mining
# ---------------------------------------------------------------------------

async def scrape_url(url: str) -> Optional[str]:
    """Fetch article text via Jina AI reader (free, no key needed)."""
    jina_url = JINA_BASE + url
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                jina_url,
                headers={"Accept": "text/plain", "X-Return-Format": "text"},
            )
        if resp.status_code == 200 and resp.text.strip():
            # Jina returns markdown; trim to first ~3000 chars to stay within token budget
            return resp.text.strip()[:3000]
        logger.warning("Jina returned %s for %s", resp.status_code, url)
        return None
    except Exception as e:
        logger.error("Jina scrape error for %s: %s", url, e)
        return None


def extract_key_claims(raw_text: str) -> list[str]:
    """
    Use Claude to extract 3-5 key claims / talking points from raw article text.
    Returns a list of short bullet strings.
    """
    result = _call_claude(
        max_tokens=512,
        system=(
            "You are a content strategist. Extract the 3-5 most important, "
            "attention-grabbing claims or facts from the text below. "
            "Output ONLY a JSON array of short strings (one sentence each). "
            "No preamble, no markdown, no explanation."
        ),
        messages=[{
            "role": "user",
            "content": f"Article text:\n\n{raw_text[:2500]}",
        }],
    )
    if not result:
        return []
    try:
        # Claude may occasionally wrap in ```json ... ``` — strip fences
        cleaned = result.strip().strip("```").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        claims = json.loads(cleaned)
        if isinstance(claims, list):
            return [str(c) for c in claims[:5]]
    except Exception as e:
        logger.warning("Could not parse claims JSON: %s | raw: %s", e, result[:200])
    return []


# ---------------------------------------------------------------------------
# Stage 2: Idea Grading
# ---------------------------------------------------------------------------

def grade_idea(claims: list[str], pillars: dict) -> dict:
    """
    Score the idea against virality, originality, and pillar alignment.
    Returns:
      {
        "virality": int(1-10),
        "originality": int(1-10),
        "pillar_alignment": int(1-10),
        "niche_angle": str,
        "summary": str,          # one-line human-readable breakdown
      }
    """
    main_pillar = pillars.get("main_pillar", "")
    sub1 = pillars.get("sub_pillar_1", "")
    sub2 = pillars.get("sub_pillar_2", "")
    claims_text = "\n".join(f"- {c}" for c in claims)

    result = _call_claude(
        max_tokens=512,
        system=(
            "You are a viral content strategist scoring content ideas. "
            "Output ONLY valid JSON — no preamble, no markdown fences. "
            "Schema: {\"virality\": int, \"originality\": int, \"pillar_alignment\": int, "
            "\"niche_angle\": str, \"summary\": str}. "
            "Scores are 1-10 integers. "
            "niche_angle is a 1-sentence angle that connects the idea to the user's niche. "
            "summary is a 1-sentence overall assessment."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Content pillars:\n"
                f"  Main pillar: {main_pillar}\n"
                f"  Sub-pillar 1: {sub1}\n"
                f"  Sub-pillar 2: {sub2}\n\n"
                f"Key claims from the idea:\n{claims_text}\n\n"
                "Score this idea on:\n"
                "1. Virality (1-10): shareability, emotional hook, timeliness\n"
                "2. Originality (1-10): how fresh vs. generic this angle is\n"
                "3. Pillar alignment (1-10): how well it fits the content pillars\n"
                "Then give a niche angle and a one-line summary."
            ),
        }],
    )

    fallback = {
        "virality": 0, "originality": 0, "pillar_alignment": 0,
        "niche_angle": "", "summary": "Grading unavailable",
    }
    if not result:
        return fallback
    try:
        cleaned = result.strip().strip("```").strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)
        return {
            "virality": int(data.get("virality", 0)),
            "originality": int(data.get("originality", 0)),
            "pillar_alignment": int(data.get("pillar_alignment", 0)),
            "niche_angle": str(data.get("niche_angle", "")),
            "summary": str(data.get("summary", "")),
        }
    except Exception as e:
        logger.warning("Could not parse grading JSON: %s | raw: %s", e, result[:200])
        return fallback


# ---------------------------------------------------------------------------
# Stage 3: Content Expansion
# ---------------------------------------------------------------------------

FORMAT_LABELS = {
    "reel":      "Reel (Avatar Video Script)",
    "carousel":  "Carousel (Slide-by-Slide)",
    "text_post": "Text Post (Caption)",
    "broll":     "B-Roll Script (Voice-over)",
}

def expand_content(claims: list[str], niche_angle: str, pillars: dict,
                   profile: dict, format_type: str) -> Optional[str]:
    """
    Expand the idea into a specific content format.
    Returns the generated content string, or None on failure.
    """
    main_pillar = pillars.get("main_pillar", "")
    sub1 = pillars.get("sub_pillar_1", "")
    claims_text = "\n".join(f"- {c}" for c in claims)
    industry = ", ".join(profile.get("industry", [])) or "business"
    tone = ", ".join(profile.get("tone", ["professional"]))

    instructions = {
        "reel": (
            "Write a talking-head Reel script (spoken word) — 60-80 words, first person. "
            "Hook in the first 3 words. Include a call to action at the end. "
            "No stage directions, just the words the speaker says."
        ),
        "carousel": (
            "Write a 5-slide carousel. For each slide output: "
            "SLIDE N: [headline] / [1-2 sentence body]. "
            "Slide 1 = hook, Slide 5 = CTA."
        ),
        "text_post": (
            "Write a Facebook/Instagram text post. Conversational, 3-4 short paragraphs. "
            "Open with a bold hook, end with a question. Include 5-8 relevant hashtags."
        ),
        "broll": (
            "Write a B-roll voice-over script — 50-70 words, present tense, visual language. "
            "Each sentence should describe an on-screen visual moment. "
            "End with a punchy tagline."
        ),
    }.get(format_type, "Write a short social media post about this topic.")

    return _call_claude(
        max_tokens=800,
        system=(
            "You are a social media content creator. "
            "Output ONLY the content itself — no preamble, no labels, no explanation."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"{instructions}\n\n"
                f"Content niche: {main_pillar} / {sub1}\n"
                f"Niche angle: {niche_angle}\n"
                f"Industry: {industry}\n"
                f"Tone: {tone}\n\n"
                f"Key claims to draw from:\n{claims_text}"
            ),
        }],
    )


# ---------------------------------------------------------------------------
# Stage 4: Script Writing (Reel → Avatar Video)
# ---------------------------------------------------------------------------

def refine_reel_script(draft_script: str, pillars: dict, profile: dict) -> Optional[str]:
    """
    Refine a Reel draft script for avatar video production.
    Trims to ≤80 words, ensures it sounds natural when spoken aloud.
    """
    main_pillar = pillars.get("main_pillar", "")
    industry = ", ".join(profile.get("industry", [])) or "business"
    tone = ", ".join(profile.get("tone", ["professional"]))

    return _call_claude(
        max_tokens=400,
        system=(
            "You are a scriptwriter for talking-head social media videos. "
            "Refine the script so it sounds natural spoken aloud. "
            "Maximum 80 words. First person. No stage directions. "
            "Output ONLY the refined script — no preamble."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Niche: {main_pillar} | Industry: {industry} | Tone: {tone}\n\n"
                f"Draft script:\n{draft_script}"
            ),
        }],
    )
