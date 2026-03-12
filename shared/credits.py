"""
Credit management system.

Actions and their costs:
  - post / scheduled_post: 5 credits
  - comment_reply:         3 credits

Users receive 500 credits per monthly billing cycle.
Credits reset on subscription renewal (handled by Stripe webhook).
"""

import logging
from typing import Optional
from shared.config import CREDIT_COST_POST, CREDIT_COST_REPLY, MONTHLY_CREDITS

logger = logging.getLogger(__name__)

# Action → credit cost mapping
ACTION_COSTS = {
    "post": CREDIT_COST_POST,
    "scheduled_post": CREDIT_COST_POST,
    "comment_reply": CREDIT_COST_REPLY,
}


def get_action_cost(action: str) -> int:
    return ACTION_COSTS.get(action, 0)


class CreditManager:
    """Checks and deducts credits via the database layer."""

    def __init__(self, db):
        self.db = db

    def get_balance(self, user_id: int) -> int:
        result = self.db.execute_query(
            "SELECT credits_remaining FROM users WHERE phone_number_id = %s",
            (user_id,),
            fetch="one",
        )
        return int(result["credits_remaining"]) if result else 0

    def has_enough(self, user_id: int, action: str) -> bool:
        cost = get_action_cost(action)
        if cost == 0:
            return True
        return self.get_balance(user_id) >= cost

    def deduct(self, user_id: int, action: str, platform: str) -> bool:
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

        # Log the credit usage
        self.db.execute_query(
            """
            INSERT INTO credit_ledger (user_id, action, platform, credits_spent)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, action, platform, cost),
        )

        logger.info(
            "Deducted %d credits from user %s for %s/%s (remaining: %d)",
            cost, user_id, platform, action, result["credits_remaining"],
        )
        return True

    def reset_credits(self, user_id: int, amount: int = MONTHLY_CREDITS) -> bool:
        """Reset credits on subscription renewal."""
        try:
            self.db.execute_query(
                """
                UPDATE users
                SET credits_remaining = %s,
                    credits_used = 0,
                    credits_reset_at = CURRENT_TIMESTAMP
                WHERE phone_number_id = %s
                """,
                (amount, user_id),
            )
            return True
        except Exception as e:
            logger.error("Failed to reset credits for user %s: %s", user_id, e)
            return False

    def get_usage_summary(self, user_id: int) -> dict:
        """Get credit usage breakdown for the current billing period."""
        result = self.db.execute_query(
            """
            SELECT
                COALESCE(SUM(credits_spent), 0) AS total_spent,
                COALESCE(SUM(CASE WHEN action IN ('post', 'scheduled_post') THEN credits_spent END), 0) AS posts_spent,
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
