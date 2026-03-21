"""
Credit management system — tiered pricing by content type.

Action costs:
  - text_post / scheduled_text:     3 credits
  - stock_image_post:               5 credits
  - own_media_post:                 5 credits
  - comment_reply:                  2 credits

Plans:
  - Free:       FREE_SIGNUP_CREDITS on signup (+30 with referral code)
  - Pro:        $34.99/mo → 500 credits
  - Business:   $79.99/mo → 1,500 credits

Add-on packs:
  - 100 credits:   $4.99
  - 500 credits:   $24.99
  - 1,500 credits: $74.99
  - 5,000 credits: $200.00
"""

import logging
from shared.config import MONTHLY_CREDITS, FREE_SIGNUP_CREDITS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action → credit cost mapping (tiered by content type)
# ---------------------------------------------------------------------------
ACTION_COSTS = {
    # Text-only posts
    "text_post": 3,
    "scheduled_text": 3,
    # Stock image (Pexels) posts
    "stock_image_post": 5,
    "scheduled_stock": 5,
    # User's own media + AI caption
    "own_media_post": 5,
    "scheduled_own_media": 5,
    # Beautify caption with AI (vision + profile context)
    "beautify_caption": 2,
    # AI content generation
    "ai_image": 10,
    "ai_video": 30,
    # Comment auto-reply
    "comment_reply": 2,
    # Legacy (backwards compat)
    "post": 5,
    "scheduled_post": 5,
}

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------
PLANS = {
    "free": {"name": "Free", "credits": FREE_SIGNUP_CREDITS, "price_usd": 0},
    "pro": {"name": "Pro", "credits": 500, "price_usd": 34.99},
    "business": {"name": "Business", "credits": 1500, "price_usd": 79.99},
}

# ---------------------------------------------------------------------------
# Add-on credit packs
# ---------------------------------------------------------------------------
CREDIT_PACKS = [
    {"credits": 100, "price_usd": 4.99, "label": "100 credits"},
    {"credits": 500, "price_usd": 24.99, "label": "500 credits"},
    {"credits": 1500, "price_usd": 74.99, "label": "1,500 credits"},
    {"credits": 5000, "price_usd": 200.00, "label": "5,000 credits (Enterprise)"},
]


def get_action_cost(action: str) -> int:
    return ACTION_COSTS.get(action, 0)


def get_action_label(action: str) -> str:
    """Human-readable label for an action."""
    labels = {
        "text_post": "Text post",
        "stock_image_post": "Stock image post",
        "own_media_post": "Own media post",
        "comment_reply": "Comment reply",
    }
    return labels.get(action, action.replace("_", " ").title())


class CreditManager:
    """Checks and deducts credits via the database layer."""

    def __init__(self, db):
        self.db = db

    def get_balance(self, user_id) -> int:
        result = self.db.execute_query(
            "SELECT credits_remaining FROM users WHERE phone_number_id = %s",
            (user_id,),
            fetch="one",
        )
        return int(result["credits_remaining"]) if result else 0

    def has_enough(self, user_id, action: str) -> bool:
        cost = get_action_cost(action)
        if cost == 0:
            return True
        return self.get_balance(user_id) >= cost

    def deduct(self, user_id, action: str, platform: str) -> bool:
        """Deduct credits atomically. Returns True on success."""
        cost = get_action_cost(action)
        if cost == 0:
            return True

        result = self.db.execute_query(
            """
            UPDATE users
            SET credits_remaining = credits_remaining - %s,
                credits_used = credits_used + %s
            WHERE phone_number_id = %s AND credits_remaining >= %s
            RETURNING credits_remaining
            """,
            (cost, cost, user_id, cost),
            fetch="one",
        )

        if result is None:
            logger.warning("Insufficient credits for user %s (action=%s, cost=%s)", user_id, action, cost)
            return False

        self.db.execute_query(
            "INSERT INTO credit_ledger (user_id, action, platform, credits_spent) VALUES (%s, %s, %s, %s)",
            (user_id, action, platform, cost),
        )

        logger.info(
            "Deducted %d credits from user %s for %s/%s (remaining: %d)",
            cost, user_id, platform, action, result["credits_remaining"],
        )
        return True

    def reset_credits(self, user_id, amount: int = MONTHLY_CREDITS) -> bool:
        """Reset credits on subscription renewal."""
        try:
            self.db.execute_query(
                "UPDATE users SET credits_remaining = %s, credits_used = 0, credits_reset_at = CURRENT_TIMESTAMP WHERE phone_number_id = %s",
                (amount, user_id),
            )
            return True
        except Exception as e:
            logger.error("Failed to reset credits for user %s: %s", user_id, e)
            return False

    def get_usage_summary(self, user_id) -> dict:
        """Get credit usage breakdown for the current billing period."""
        result = self.db.execute_query(
            """
            SELECT
                COALESCE(SUM(credits_spent), 0) AS total_spent,
                COALESCE(SUM(CASE WHEN action IN ('text_post','stock_image_post','own_media_post','ai_image_post','ai_video_post','post','scheduled_post','scheduled_text','scheduled_stock','scheduled_own_media','scheduled_ai_image','scheduled_ai_video') THEN credits_spent END), 0) AS posts_spent,
                COALESCE(SUM(CASE WHEN action = 'comment_reply' THEN credits_spent END), 0) AS replies_spent,
                COUNT(*) AS total_actions
            FROM credit_ledger
            WHERE user_id = %s
              AND created_at >= (SELECT COALESCE(credits_reset_at, created_at) FROM users WHERE phone_number_id = %s)
            """,
            (user_id, user_id),
            fetch="one",
        )

        balance = self.get_balance(user_id)

        return {
            "credits_remaining": balance,
            "credits_total": MONTHLY_CREDITS,
            "credits_used": int(result["total_spent"]) if result else 0,
            "posts_spent": int(result["posts_spent"]) if result else 0,
            "replies_spent": int(result["replies_spent"]) if result else 0,
            "total_actions": int(result["total_actions"]) if result else 0,
        }
