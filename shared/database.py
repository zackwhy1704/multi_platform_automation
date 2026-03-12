"""
PostgreSQL database layer with connection pooling.
Adapted from the LinkedIn bot's bot_database_postgres.py for multi-platform use.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import pool
from psycopg2.extras import Json, RealDictCursor

from shared.config import (
    DATABASE_HOST,
    DATABASE_NAME,
    DATABASE_PASSWORD,
    DATABASE_PORT,
    DATABASE_USER,
    MONTHLY_CREDITS,
)

logger = logging.getLogger(__name__)


class BotDatabase:
    """PostgreSQL database with connection pooling."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        database: str = None,
        user: str = None,
        password: str = None,
        min_connections: int = 2,
        max_connections: int = 10,
    ):
        self.host = host or DATABASE_HOST
        self.port = port or DATABASE_PORT
        self.database = database or DATABASE_NAME
        self.user = user or DATABASE_USER
        self.password = password or DATABASE_PASSWORD

        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                min_connections,
                max_connections,
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                cursor_factory=RealDictCursor,
            )
            logger.info("PostgreSQL pool created: %s:%s/%s", self.host, self.port, self.database)
        except Exception as e:
            logger.error("Failed to create connection pool: %s", e)
            raise

    def get_connection(self):
        return self.connection_pool.getconn()

    def return_connection(self, conn):
        self.connection_pool.putconn(conn)

    def execute_query(
        self, query: str, params: Tuple = None, fetch: str = None
    ) -> Any:
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if fetch == "one":
                    result = cursor.fetchone()
                elif fetch == "all":
                    result = cursor.fetchall()
                else:
                    result = None
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            logger.error("Query error: %s | Query: %s | Params: %s", e, query, params)
            raise
        finally:
            self.return_connection(conn)

    def close(self):
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("Connection pool closed")

    # =========================================================================
    # USER MANAGEMENT
    # =========================================================================

    def get_user(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query(
            "SELECT * FROM users WHERE phone_number_id = %s",
            (phone_number_id,),
            fetch="one",
        )

    def create_user(
        self, phone_number_id: str, phone_number: str = None, display_name: str = None
    ) -> bool:
        try:
            self.execute_query(
                """
                INSERT INTO users (phone_number_id, phone_number, display_name, last_seen)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (phone_number_id) DO UPDATE SET
                    phone_number = COALESCE(EXCLUDED.phone_number, users.phone_number),
                    display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                    last_seen = CURRENT_TIMESTAMP
                """,
                (phone_number_id, phone_number, display_name),
            )
            return True
        except Exception as e:
            logger.error("Error creating user %s: %s", phone_number_id, e)
            return False

    def update_last_seen(self, phone_number_id: str):
        self.execute_query(
            "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE phone_number_id = %s",
            (phone_number_id,),
        )

    # =========================================================================
    # USER PROFILES
    # =========================================================================

    def save_user_profile(self, phone_number_id: str, profile_data: dict) -> bool:
        try:
            self.create_user(phone_number_id)
            self.execute_query(
                """
                INSERT INTO user_profiles (phone_number_id, industry, skills, career_goals, tone, interests)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (phone_number_id) DO UPDATE SET
                    industry = EXCLUDED.industry,
                    skills = EXCLUDED.skills,
                    career_goals = EXCLUDED.career_goals,
                    tone = EXCLUDED.tone,
                    interests = EXCLUDED.interests,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    phone_number_id,
                    profile_data.get("industry", []),
                    profile_data.get("skills", []),
                    profile_data.get("career_goals", []),
                    profile_data.get("tone", []),
                    profile_data.get("interests", []),
                ),
            )
            return True
        except Exception as e:
            logger.error("Error saving user profile %s: %s", phone_number_id, e)
            return False

    def get_user_profile(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query(
            "SELECT * FROM user_profiles WHERE phone_number_id = %s",
            (phone_number_id,),
            fetch="one",
        )

    # =========================================================================
    # PLATFORM CREDENTIALS
    # =========================================================================

    def save_platform_credentials(
        self, phone_number_id: str, platform: str, email: str, encrypted_password: bytes
    ) -> bool:
        try:
            self.create_user(phone_number_id)
            self.execute_query(
                """
                INSERT INTO platform_credentials (phone_number_id, platform, email, encrypted_password)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (phone_number_id, platform) DO UPDATE SET
                    email = EXCLUDED.email,
                    encrypted_password = EXCLUDED.encrypted_password,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (phone_number_id, platform, email, psycopg2.Binary(encrypted_password)),
            )
            return True
        except Exception as e:
            logger.error("Error saving %s credentials for %s: %s", platform, phone_number_id, e)
            return False

    def get_platform_credentials(self, phone_number_id: str, platform: str) -> Optional[Dict]:
        result = self.execute_query(
            "SELECT email, encrypted_password FROM platform_credentials WHERE phone_number_id = %s AND platform = %s",
            (phone_number_id, platform),
            fetch="one",
        )
        if result:
            return {
                "email": result["email"],
                "encrypted_password": bytes(result["encrypted_password"]),
            }
        return None

    def save_platform_token(
        self, phone_number_id: str, platform: str, access_token: str, page_id: str = None
    ) -> bool:
        """Save OAuth token for Facebook/Instagram Graph API."""
        try:
            self.create_user(phone_number_id)
            self.execute_query(
                """
                INSERT INTO platform_credentials (phone_number_id, platform, access_token, page_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (phone_number_id, platform) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    page_id = COALESCE(EXCLUDED.page_id, platform_credentials.page_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (phone_number_id, platform, access_token, page_id),
            )
            return True
        except Exception as e:
            logger.error("Error saving %s token for %s: %s", platform, phone_number_id, e)
            return False

    def get_platform_token(self, phone_number_id: str, platform: str) -> Optional[Dict]:
        return self.execute_query(
            "SELECT access_token, page_id FROM platform_credentials WHERE phone_number_id = %s AND platform = %s",
            (phone_number_id, platform),
            fetch="one",
        )

    # =========================================================================
    # SUBSCRIPTION MANAGEMENT
    # =========================================================================

    def activate_subscription(
        self,
        phone_number_id: str,
        stripe_customer_id: str = None,
        stripe_subscription_id: str = None,
        days: int = 30,
    ) -> bool:
        try:
            expiration = datetime.now() + timedelta(days=days)
            self.execute_query(
                """
                UPDATE users SET
                    subscription_active = TRUE,
                    subscription_expires = %s,
                    credits_remaining = %s,
                    credits_used = 0,
                    credits_reset_at = CURRENT_TIMESTAMP,
                    stripe_customer_id = COALESCE(%s, stripe_customer_id),
                    stripe_subscription_id = COALESCE(%s, stripe_subscription_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE phone_number_id = %s
                """,
                (expiration, MONTHLY_CREDITS, stripe_customer_id, stripe_subscription_id, phone_number_id),
            )
            return True
        except Exception as e:
            logger.error("Error activating subscription for %s: %s", phone_number_id, e)
            return False

    def deactivate_subscription(self, phone_number_id: str) -> bool:
        try:
            self.execute_query(
                "UPDATE users SET subscription_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE phone_number_id = %s",
                (phone_number_id,),
            )
            return True
        except Exception as e:
            logger.error("Error deactivating subscription for %s: %s", phone_number_id, e)
            return False

    def is_subscription_active(self, phone_number_id: str) -> bool:
        result = self.execute_query(
            "SELECT subscription_active, subscription_expires FROM users WHERE phone_number_id = %s",
            (phone_number_id,),
            fetch="one",
        )
        if not result:
            return False

        if result["subscription_active"] and result["subscription_expires"]:
            expires = result["subscription_expires"]
            now = datetime.now()
            if expires.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            if expires < now:
                self.deactivate_subscription(phone_number_id)
                return False

        return result.get("subscription_active", False)

    # =========================================================================
    # AUTOMATION STATS
    # =========================================================================

    def log_automation_action(
        self,
        phone_number_id: str,
        platform: str,
        action_type: str,
        action_count: int = 1,
        session_id: str = None,
        metadata: dict = None,
    ) -> bool:
        try:
            self.execute_query(
                """
                INSERT INTO automation_stats (phone_number_id, platform, action_type, action_count, session_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (phone_number_id, platform, action_type, action_count, session_id, Json(metadata) if metadata else None),
            )
            return True
        except Exception as e:
            logger.error("Error logging action for %s: %s", phone_number_id, e)
            return False

    def get_user_stats(self, phone_number_id: str, platform: str = None) -> Dict:
        platform_filter = "AND platform = %s" if platform else ""
        params = (phone_number_id, platform) if platform else (phone_number_id,)

        result = self.execute_query(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN action_type = 'post' THEN action_count END), 0) AS posts_created,
                COALESCE(SUM(CASE WHEN action_type = 'like' THEN action_count END), 0) AS likes_given,
                COALESCE(SUM(CASE WHEN action_type = 'comment' THEN action_count END), 0) AS comments_made,
                COALESCE(SUM(CASE WHEN action_type = 'connection' THEN action_count END), 0) AS connections_sent,
                MAX(performed_at) AS last_active
            FROM automation_stats
            WHERE phone_number_id = %s {platform_filter}
            """,
            params,
            fetch="one",
        )

        if result:
            return {
                "posts_created": int(result["posts_created"]),
                "likes_given": int(result["likes_given"]),
                "comments_made": int(result["comments_made"]),
                "connections_sent": int(result["connections_sent"]),
                "last_active": result["last_active"].isoformat() if result["last_active"] else None,
            }
        return {"posts_created": 0, "likes_given": 0, "comments_made": 0, "connections_sent": 0, "last_active": None}

    # =========================================================================
    # PROMO CODES
    # =========================================================================

    def validate_promo_code(self, code: str) -> Optional[Dict]:
        if code.upper() in ("FREE", "FREETRIAL"):
            return {
                "code": code.upper(),
                "discount_percent": 100,
                "is_free_bypass": True,
            }

        return self.execute_query(
            """
            SELECT * FROM promo_codes
            WHERE code = %s AND active = TRUE AND current_uses < max_uses
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """,
            (code.upper(),),
            fetch="one",
        )

    def use_promo_code(self, code: str) -> bool:
        try:
            self.execute_query(
                "UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = %s",
                (code.upper(),),
            )
            return True
        except Exception as e:
            logger.error("Error using promo code %s: %s", code, e)
            return False

    # =========================================================================
    # ENGAGEMENT TRACKING
    # =========================================================================

    def mark_post_engaged(self, phone_number_id: str, platform: str, post_id: str, engagement_type: str = "like") -> bool:
        try:
            self.execute_query(
                """
                INSERT INTO engaged_posts (phone_number_id, platform, post_id, engagement_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (phone_number_id, platform, post_id) DO UPDATE SET
                    engagement_type = EXCLUDED.engagement_type,
                    engaged_at = CURRENT_TIMESTAMP
                """,
                (phone_number_id, platform, post_id, engagement_type),
            )
            return True
        except Exception as e:
            logger.error("Error marking post engaged: %s", e)
            return False

    def has_engaged_post(self, phone_number_id: str, platform: str, post_id: str) -> bool:
        result = self.execute_query(
            "SELECT 1 FROM engaged_posts WHERE phone_number_id = %s AND platform = %s AND post_id = %s",
            (phone_number_id, platform, post_id),
            fetch="one",
        )
        return result is not None

    # =========================================================================
    # SAFETY / RATE LIMITING
    # =========================================================================

    def increment_safety_count(self, phone_number_id: str, platform: str, action_type: str, count: int = 1):
        self.execute_query(
            """
            INSERT INTO safety_counts (phone_number_id, platform, date, action_type, count)
            VALUES (%s, %s, CURRENT_DATE, %s, %s)
            ON CONFLICT (phone_number_id, platform, date, action_type) DO UPDATE SET
                count = safety_counts.count + EXCLUDED.count
            """,
            (phone_number_id, platform, action_type, count),
        )

    def get_daily_count(self, phone_number_id: str, platform: str, action_type: str) -> int:
        result = self.execute_query(
            """
            SELECT count FROM safety_counts
            WHERE phone_number_id = %s AND platform = %s AND date = CURRENT_DATE AND action_type = %s
            """,
            (phone_number_id, platform, action_type),
            fetch="one",
        )
        return result["count"] if result else 0

    # =========================================================================
    # CONVERSATION STATE (for WhatsApp multi-step flows)
    # =========================================================================

    def get_conversation_state(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query(
            "SELECT state, data FROM conversation_state WHERE phone_number_id = %s",
            (phone_number_id,),
            fetch="one",
        )

    def set_conversation_state(self, phone_number_id: str, state: str, data: dict = None):
        self.execute_query(
            """
            INSERT INTO conversation_state (phone_number_id, state, data)
            VALUES (%s, %s, %s)
            ON CONFLICT (phone_number_id) DO UPDATE SET
                state = EXCLUDED.state,
                data = EXCLUDED.data,
                updated_at = CURRENT_TIMESTAMP
            """,
            (phone_number_id, state, Json(data) if data else None),
        )

    def clear_conversation_state(self, phone_number_id: str):
        self.execute_query(
            "DELETE FROM conversation_state WHERE phone_number_id = %s",
            (phone_number_id,),
        )

    # =========================================================================
    # SCHEDULED CONTENT
    # =========================================================================

    def save_scheduled_content(
        self, phone_number_id: str, platform: str, content: str, scheduled_at: datetime, media_url: str = None
    ) -> bool:
        try:
            self.execute_query(
                """
                INSERT INTO scheduled_content (phone_number_id, platform, content, media_url, scheduled_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (phone_number_id, platform, content, media_url, scheduled_at),
            )
            return True
        except Exception as e:
            logger.error("Error saving scheduled content: %s", e)
            return False

    def get_pending_scheduled_content(self) -> List[Dict]:
        return self.execute_query(
            """
            SELECT * FROM scheduled_content
            WHERE status = 'pending' AND scheduled_at <= CURRENT_TIMESTAMP
            ORDER BY scheduled_at ASC
            """,
            fetch="all",
        ) or []

    def update_scheduled_content_status(self, content_id: int, status: str):
        self.execute_query(
            "UPDATE scheduled_content SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, content_id),
        )
