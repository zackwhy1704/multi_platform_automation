"""
ReAct-style input validator for onboarding.

Applies the Thought → Action → Observation loop:
  - Thought: Reason about whether the input is valid, relevant, and clear
  - Action: ACCEPT, CLARIFY (with guidance), or REJECT (not English / gibberish)
  - Observation: Structured result that drives the next state transition

Uses Claude Haiku for fast, cheap validation (~0.001 cents per call).
Falls back to basic heuristics if the API is unavailable.
"""

import json
import logging
import string
from typing import Optional

from shared.config import ANTHROPIC_API_KEY, AI_MODEL

logger = logging.getLogger(__name__)

_ASCII_LETTERS = set(string.ascii_letters)

# ---------------------------------------------------------------------------
# Step context — tells the LLM what kind of answer we expect
# ---------------------------------------------------------------------------
STEP_CONTEXT = {
    "industry": {
        "question": "What industry is your business in?",
        "expects": "One or more business industries/sectors, comma-separated",
        "examples": "E-commerce, Tech, F&B, Healthcare, Real Estate, Marketing",
    },
    "offerings": {
        "question": "What products or services does your business offer?",
        "expects": "Specific products, services, or offerings the business provides",
        "examples": "Web Development, Digital Marketing, Personal Training, Coffee & Pastries",
    },
    "goals": {
        "question": "What do you want your social media to achieve for your business?",
        "expects": "Business goals related to social media marketing",
        "examples": "Get more customers, Build brand awareness, Drive website traffic, Grow community",
    },
}


# ---------------------------------------------------------------------------
# ReAct validation via LLM
# ---------------------------------------------------------------------------
def validate_input(text: str, step: str) -> dict:
    """
    Validate user input using the ReAct pattern.

    Returns:
        {
            "action": "accept" | "clarify" | "reject",
            "thought": str,          # LLM's reasoning (logged, not shown to user)
            "cleaned": str | None,   # Cleaned/normalized input if accepted
            "message": str | None,   # Message to send if clarify/reject
        }
    """
    # Fast pre-check: empty or too short
    if not text or len(text.strip()) < 2:
        return {
            "action": "reject",
            "thought": "Input is empty or too short",
            "cleaned": None,
            "message": "That's too short. Could you give me a more detailed answer?",
        }

    # Fast pre-check: not English (> 50% non-ASCII alpha)
    alpha_chars = [c for c in text if c.isalpha()]
    if alpha_chars:
        ascii_ratio = sum(1 for c in alpha_chars if c in _ASCII_LETTERS) / len(alpha_chars)
        if ascii_ratio < 0.5:
            return {
                "action": "reject",
                "thought": f"Non-English input detected (ASCII ratio: {ascii_ratio:.0%})",
                "cleaned": None,
                "message": "Please reply in English so I can create the best content for you.",
            }

    ctx = STEP_CONTEXT.get(step)
    if not ctx:
        # No context for this step — accept with basic validation
        return {"action": "accept", "thought": "No step context, accepting", "cleaned": text.strip(), "message": None}

    # Try LLM validation
    result = _llm_validate(text, ctx)
    if result:
        logger.info("ReAct [%s] thought=%s action=%s", step, result["thought"], result["action"])
        return result

    # Fallback: basic heuristic if LLM unavailable
    return _heuristic_validate(text, ctx)


def _llm_validate(text: str, ctx: dict) -> Optional[dict]:
    """Use Claude Haiku to reason about the input."""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
        import time
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = f"""You are validating a user's input during a business profile onboarding flow.

QUESTION ASKED: {ctx['question']}
EXPECTED INPUT: {ctx['expects']}
EXAMPLES OF GOOD ANSWERS: {ctx['examples']}

USER'S ANSWER: "{text}"

Apply the ReAct reasoning pattern:

THOUGHT: Reason step by step:
1. Is this in English?
2. Is it relevant to the question asked?
3. Is it specific enough to be useful for generating social media content?
4. Does it make sense as a business-related answer?

ACTION: Choose exactly one:
- ACCEPT: Input is valid, relevant, and clear enough to use
- CLARIFY: Input is partially valid but too vague, off-topic, or could be better. Provide a helpful, friendly nudge.
- REJECT: Input is gibberish, not English, or completely unrelated

Respond in this exact JSON format (no other text):
{{"thought": "your reasoning", "action": "accept|clarify|reject", "cleaned": "normalized input if accept, null otherwise", "message": "friendly message to user if clarify/reject, null if accept"}}"""

        raw = None
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model=AI_MODEL,
                    max_tokens=256,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                break
            except anthropic.APIStatusError as e:
                if e.status_code in (429, 529, 500, 502, 503) and attempt < 2:
                    time.sleep([2, 5][attempt])
                    continue
                raise

        if not raw:
            return None
        # Parse JSON from response (handle markdown code blocks)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)

        # Normalize action
        result["action"] = result.get("action", "accept").lower()
        if result["action"] not in ("accept", "clarify", "reject"):
            result["action"] = "accept"

        return result

    except Exception as e:
        logger.warning("LLM validation failed, falling back to heuristics: %s", e)
        return None


def _heuristic_validate(text: str, ctx: dict) -> dict:
    """Fallback validation when LLM is unavailable."""
    stripped = text.strip()

    # Too short for a meaningful answer
    if len(stripped) < 3:
        return {
            "action": "clarify",
            "thought": "Input very short, asking for more detail",
            "cleaned": None,
            "message": f"Could you be more specific? For example: _{ctx['examples']}_",
        }

    # Looks like a single character or number only
    if stripped.isdigit():
        return {
            "action": "clarify",
            "thought": "Numeric-only input for a text field",
            "cleaned": None,
            "message": f"I need a text answer here. {ctx['question']}\n_e.g. {ctx['examples']}_",
        }

    # Accept anything else
    return {
        "action": "accept",
        "thought": "Heuristic pass — input looks reasonable",
        "cleaned": stripped,
        "message": None,
    }
