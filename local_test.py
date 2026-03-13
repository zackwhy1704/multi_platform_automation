#!/usr/bin/env python3
"""
Local test server — runs the full WhatsApp bot locally using SQLite.

Requirements:
  pip install fastapi uvicorn httpx python-dotenv stripe anthropic

Usage:
  1. Copy .env.example → .env and fill in WhatsApp + Stripe + Anthropic keys
  2. python local_test.py
  3. Expose port 8000 with ngrok:  ngrok http 8000
  4. Set Meta webhook URL to: https://<ngrok-url>/webhook
  5. Send a WhatsApp message to your business number

This replaces PostgreSQL with SQLite and Celery with synchronous calls.
"""

import os
import sys
import json
import sqlite3
import logging
import uuid
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Override config before importing anything else
# ---------------------------------------------------------------------------
os.environ.setdefault("CELERY_ALWAYS_EAGER", "true")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s %(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("local_test")

# ---------------------------------------------------------------------------
# SQLite-backed BotDatabase (drop-in replacement for PostgreSQL version)
# ---------------------------------------------------------------------------
DB_FILE = "local_test.db"


class LocalBotDatabase:
    """SQLite version of BotDatabase for local testing."""

    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info("SQLite database ready: %s", DB_FILE)

    def _create_tables(self):
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                phone_number_id TEXT PRIMARY KEY,
                phone_number TEXT,
                display_name TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                last_seen TEXT,
                subscription_active INTEGER DEFAULT 0,
                subscription_expires TEXT,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                credits_remaining INTEGER DEFAULT 30,
                credits_used INTEGER DEFAULT 0,
                credits_reset_at TEXT DEFAULT (datetime('now')),
                referral_code TEXT UNIQUE,
                referred_by TEXT,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                phone_number_id TEXT PRIMARY KEY,
                industry TEXT DEFAULT '[]',
                offerings TEXT DEFAULT '[]',
                business_goals TEXT DEFAULT '[]',
                tone TEXT DEFAULT '[]',
                platform TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS platform_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number_id TEXT,
                platform TEXT NOT NULL,
                access_token TEXT NOT NULL,
                page_id TEXT,
                token_expires TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(phone_number_id, platform)
            );

            CREATE TABLE IF NOT EXISTS credit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT NOT NULL,
                platform TEXT,
                credits_spent INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS automation_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number_id TEXT,
                platform TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_count INTEGER DEFAULT 1,
                session_id TEXT,
                metadata TEXT,
                performed_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                credits_granted INTEGER DEFAULT 50,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                expires_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            INSERT OR IGNORE INTO promo_codes (code, credits_granted, max_uses, active)
            VALUES ('CATALYX50', 50, NULL, 1);

            CREATE TABLE IF NOT EXISTS promo_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number_id TEXT,
                code TEXT NOT NULL,
                credits_granted INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(phone_number_id, code)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id TEXT,
                referred_id TEXT UNIQUE,
                referrer_credits INTEGER DEFAULT 50,
                referred_credits INTEGER DEFAULT 50,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS engaged_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number_id TEXT,
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                engagement_type TEXT DEFAULT 'reply',
                engaged_at TEXT DEFAULT (datetime('now')),
                UNIQUE(phone_number_id, platform, post_id)
            );

            CREATE TABLE IF NOT EXISTS conversation_state (
                phone_number_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scheduled_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number_id TEXT,
                platform TEXT NOT NULL,
                content TEXT NOT NULL,
                media_url TEXT,
                scheduled_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    def _row_to_dict(self, row) -> Optional[Dict]:
        if row is None:
            return None
        d = dict(row)
        # Parse JSON fields
        for key in ("industry", "offerings", "business_goals", "tone", "metadata"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        # Parse data field in conversation_state
        if "data" in d and isinstance(d["data"], str):
            try:
                d["data"] = json.loads(d["data"])
            except (json.JSONDecodeError, TypeError):
                d["data"] = {}
        # Convert subscription_active from int to bool
        if "subscription_active" in d:
            d["subscription_active"] = bool(d["subscription_active"])
        return d

    def execute_query(self, query: str, params: Tuple = None, fetch: str = None) -> Any:
        # Convert PostgreSQL-style %s to SQLite ?
        q = query.replace("%s", "?")
        # Handle RETURNING clause (not supported in SQLite)
        returning = False
        if "RETURNING" in q.upper():
            returning = True
            q = q[:q.upper().index("RETURNING")].strip()

        c = self.conn.cursor()
        c.execute(q, params or ())
        self.conn.commit()

        if returning:
            # For RETURNING credits_remaining, fetch from users
            if "credits_remaining" in query:
                phone = params[2] if len(params) > 2 else None
                if phone:
                    c.execute("SELECT credits_remaining FROM users WHERE phone_number_id = ?", (phone,))
                    row = c.fetchone()
                    return self._row_to_dict(row)
            return None

        if fetch == "one":
            return self._row_to_dict(c.fetchone())
        elif fetch == "all":
            return [self._row_to_dict(r) for r in c.fetchall()]
        return None

    def close(self):
        self.conn.close()

    # --- User Management ---
    def get_user(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query("SELECT * FROM users WHERE phone_number_id = %s", (phone_number_id,), fetch="one")

    def create_user(self, phone_number_id: str, phone_number: str = None, display_name: str = None) -> bool:
        try:
            self.execute_query(
                """INSERT OR IGNORE INTO users (phone_number_id, phone_number, display_name, credits_remaining, last_seen)
                VALUES (%s, %s, %s, 30, datetime('now'))""",
                (phone_number_id, phone_number, display_name),
            )
            self.execute_query(
                """UPDATE users SET
                    phone_number = COALESCE(%s, phone_number),
                    display_name = COALESCE(%s, display_name),
                    last_seen = datetime('now')
                WHERE phone_number_id = %s""",
                (phone_number, display_name, phone_number_id),
            )
            return True
        except Exception as e:
            logger.error("Error creating user: %s", e)
            return False

    def update_last_seen(self, phone_number_id: str):
        self.execute_query("UPDATE users SET last_seen = datetime('now') WHERE phone_number_id = %s", (phone_number_id,))

    # --- User Profiles ---
    def save_user_profile(self, phone_number_id: str, profile_data: dict) -> bool:
        try:
            self.create_user(phone_number_id)
            self.execute_query(
                """INSERT OR REPLACE INTO user_profiles (phone_number_id, industry, offerings, business_goals, tone, platform)
                VALUES (%s, %s, %s, %s, %s, %s)""",
                (phone_number_id,
                 json.dumps(profile_data.get("industry", [])),
                 json.dumps(profile_data.get("offerings", [])),
                 json.dumps(profile_data.get("business_goals", [])),
                 json.dumps(profile_data.get("tone", [])),
                 profile_data.get("platform", "")),
            )
            return True
        except Exception as e:
            logger.error("Error saving profile: %s", e)
            return False

    def get_user_profile(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query("SELECT * FROM user_profiles WHERE phone_number_id = %s", (phone_number_id,), fetch="one")

    # --- Platform Tokens ---
    def save_platform_token(self, phone_number_id: str, platform: str, access_token: str, page_id: str = None) -> bool:
        try:
            self.execute_query(
                """INSERT OR REPLACE INTO platform_tokens (phone_number_id, platform, access_token, page_id)
                VALUES (%s, %s, %s, %s)""",
                (phone_number_id, platform, access_token, page_id),
            )
            return True
        except Exception as e:
            logger.error("Error saving token: %s", e)
            return False

    def get_platform_token(self, phone_number_id: str, platform: str) -> Optional[Dict]:
        return self.execute_query(
            "SELECT access_token, page_id FROM platform_tokens WHERE phone_number_id = %s AND platform = %s",
            (phone_number_id, platform), fetch="one",
        )

    # --- Credits ---
    def grant_credits(self, phone_number_id: str, amount: int, reason: str = "bonus") -> bool:
        try:
            self.execute_query("UPDATE users SET credits_remaining = credits_remaining + %s WHERE phone_number_id = %s", (amount, phone_number_id))
            self.execute_query(
                "INSERT INTO credit_ledger (user_id, action, platform, credits_spent) VALUES (%s, %s, 'system', %s)",
                (phone_number_id, reason, -amount),
            )
            logger.info("Granted %d credits to %s (%s)", amount, phone_number_id, reason)
            return True
        except Exception as e:
            logger.error("Error granting credits: %s", e)
            return False

    # --- Subscription ---
    def activate_subscription(self, phone_number_id: str, stripe_customer_id: str = None,
                              stripe_subscription_id: str = None, days: int = 30) -> bool:
        exp = (datetime.now() + timedelta(days=days)).isoformat()
        self.execute_query(
            """UPDATE users SET subscription_active = 1, subscription_expires = %s,
                credits_remaining = 500, credits_used = 0, credits_reset_at = datetime('now'),
                stripe_customer_id = COALESCE(%s, stripe_customer_id),
                stripe_subscription_id = COALESCE(%s, stripe_subscription_id)
            WHERE phone_number_id = %s""",
            (exp, stripe_customer_id, stripe_subscription_id, phone_number_id),
        )
        return True

    def deactivate_subscription(self, phone_number_id: str) -> bool:
        self.execute_query("UPDATE users SET subscription_active = 0 WHERE phone_number_id = %s", (phone_number_id,))
        return True

    def is_subscription_active(self, phone_number_id: str) -> bool:
        r = self.execute_query("SELECT subscription_active, subscription_expires FROM users WHERE phone_number_id = %s", (phone_number_id,), fetch="one")
        if not r:
            return False
        return bool(r.get("subscription_active"))

    # --- Referral ---
    def set_referral_code(self, phone_number_id: str, code: str) -> bool:
        self.execute_query("UPDATE users SET referral_code = %s WHERE phone_number_id = %s", (code, phone_number_id))
        return True

    def find_user_by_referral_code(self, code: str) -> Optional[Dict]:
        return self.execute_query("SELECT phone_number_id, display_name FROM users WHERE referral_code = %s", (code,), fetch="one")

    def has_been_referred(self, phone_number_id: str) -> bool:
        r = self.execute_query("SELECT 1 FROM referrals WHERE referred_id = %s", (phone_number_id,), fetch="one")
        return r is not None

    def set_referred_by(self, phone_number_id: str, referrer_id: str):
        self.execute_query("UPDATE users SET referred_by = %s WHERE phone_number_id = %s", (referrer_id, phone_number_id))

    def record_referral(self, referrer_id: str, referred_id: str) -> bool:
        try:
            self.execute_query("INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (%s, %s)", (referrer_id, referred_id))
            return True
        except Exception as e:
            logger.error("Error recording referral: %s", e)
            return False

    def get_referral_count(self, phone_number_id: str) -> int:
        r = self.execute_query("SELECT COUNT(*) AS cnt FROM referrals WHERE referrer_id = %s", (phone_number_id,), fetch="one")
        return int(r["cnt"]) if r else 0

    # --- Promo Codes ---
    def validate_promo_code(self, code: str) -> Optional[Dict]:
        return self.execute_query(
            """SELECT * FROM promo_codes WHERE code = %s AND active = 1
              AND (max_uses IS NULL OR current_uses < max_uses)
              AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (code.upper(),), fetch="one",
        )

    def use_promo_code(self, code: str) -> bool:
        self.execute_query("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = %s", (code.upper(),))
        return True

    def has_used_promo(self, phone_number_id: str, code: str) -> bool:
        r = self.execute_query("SELECT 1 FROM promo_usage WHERE phone_number_id = %s AND code = %s", (phone_number_id, code.upper()), fetch="one")
        return r is not None

    def record_promo_usage(self, phone_number_id: str, code: str, credits_granted: int) -> bool:
        self.execute_query("INSERT OR IGNORE INTO promo_usage (phone_number_id, code, credits_granted) VALUES (%s, %s, %s)",
                          (phone_number_id, code.upper(), credits_granted))
        return True

    # --- Stats ---
    def log_automation_action(self, phone_number_id: str, platform: str, action_type: str,
                              action_count: int = 1, session_id: str = None, metadata: dict = None) -> bool:
        self.execute_query(
            "INSERT INTO automation_stats (phone_number_id, platform, action_type, action_count, session_id, metadata) VALUES (%s, %s, %s, %s, %s, %s)",
            (phone_number_id, platform, action_type, action_count, session_id, json.dumps(metadata) if metadata else None),
        )
        return True

    def get_user_stats(self, phone_number_id: str, platform: str = None) -> Dict:
        if platform:
            r = self.execute_query(
                """SELECT COALESCE(SUM(CASE WHEN action_type='post' THEN action_count END),0) AS posts_created,
                   COALESCE(SUM(CASE WHEN action_type='comment' THEN action_count END),0) AS comments_made,
                   MAX(performed_at) AS last_active
                FROM automation_stats WHERE phone_number_id = %s AND platform = %s""",
                (phone_number_id, platform), fetch="one",
            )
        else:
            r = self.execute_query(
                """SELECT COALESCE(SUM(CASE WHEN action_type='post' THEN action_count END),0) AS posts_created,
                   COALESCE(SUM(CASE WHEN action_type='comment' THEN action_count END),0) AS comments_made,
                   MAX(performed_at) AS last_active
                FROM automation_stats WHERE phone_number_id = %s""",
                (phone_number_id,), fetch="one",
            )
        if r:
            return {"posts_created": int(r["posts_created"]), "comments_made": int(r["comments_made"]),
                    "last_active": r["last_active"]}
        return {"posts_created": 0, "comments_made": 0, "last_active": None}

    # --- Engagement ---
    def mark_post_engaged(self, phone_number_id: str, platform: str, post_id: str, engagement_type: str = "reply") -> bool:
        self.execute_query(
            "INSERT OR REPLACE INTO engaged_posts (phone_number_id, platform, post_id, engagement_type) VALUES (%s, %s, %s, %s)",
            (phone_number_id, platform, post_id, engagement_type),
        )
        return True

    def has_engaged_post(self, phone_number_id: str, platform: str, post_id: str) -> bool:
        r = self.execute_query("SELECT 1 FROM engaged_posts WHERE phone_number_id = %s AND platform = %s AND post_id = %s",
                              (phone_number_id, platform, post_id), fetch="one")
        return r is not None

    # --- Conversation State ---
    def get_conversation_state(self, phone_number_id: str) -> Optional[Dict]:
        return self.execute_query("SELECT state, data FROM conversation_state WHERE phone_number_id = %s", (phone_number_id,), fetch="one")

    def set_conversation_state(self, phone_number_id: str, state: str, data: dict = None):
        self.execute_query(
            "INSERT OR REPLACE INTO conversation_state (phone_number_id, state, data) VALUES (%s, %s, %s)",
            (phone_number_id, state, json.dumps(data) if data else "{}"),
        )

    def clear_conversation_state(self, phone_number_id: str):
        self.execute_query("DELETE FROM conversation_state WHERE phone_number_id = %s", (phone_number_id,))

    # --- Scheduled Content ---
    def save_scheduled_content(self, phone_number_id: str, platform: str, content: str, scheduled_at, media_url: str = None) -> bool:
        self.execute_query(
            "INSERT INTO scheduled_content (phone_number_id, platform, content, media_url, scheduled_at) VALUES (%s, %s, %s, %s, %s)",
            (phone_number_id, platform, content, media_url, scheduled_at.isoformat() if hasattr(scheduled_at, 'isoformat') else str(scheduled_at)),
        )
        return True

    def get_pending_scheduled_content(self) -> List[Dict]:
        return self.execute_query(
            "SELECT * FROM scheduled_content WHERE status = 'pending' AND scheduled_at <= datetime('now') ORDER BY scheduled_at ASC",
            fetch="all",
        ) or []

    def update_scheduled_content_status(self, content_id: int, status: str):
        self.execute_query("UPDATE scheduled_content SET status = %s WHERE id = %s", (status, content_id))


# ---------------------------------------------------------------------------
# Monkey-patch: replace production DB with local SQLite DB
# ---------------------------------------------------------------------------
local_db = LocalBotDatabase()

# Patch shared.database so imports get our local DB
import shared.database
shared.database.BotDatabase = type("BotDatabase", (), {
    "__init__": lambda self, **kw: None,
    "__getattr__": lambda self, name: getattr(local_db, name),
})

# Patch the credit manager to work with our local DB
import shared.credits
_orig_cm_init = shared.credits.CreditManager.__init__


class LocalCreditManager(shared.credits.CreditManager):
    def __init__(self, db):
        self.db = db if isinstance(db, LocalBotDatabase) else local_db

    def get_balance(self, user_id) -> int:
        r = self.db.execute_query("SELECT credits_remaining FROM users WHERE phone_number_id = %s", (user_id,), fetch="one")
        return int(r["credits_remaining"]) if r else 0

    def deduct(self, user_id, action: str, platform: str) -> bool:
        cost = shared.credits.get_action_cost(action)
        if cost == 0:
            return True
        balance = self.get_balance(user_id)
        if balance < cost:
            return False
        self.db.execute_query("UPDATE users SET credits_remaining = credits_remaining - %s, credits_used = credits_used + %s WHERE phone_number_id = %s",
                             (cost, cost, user_id))
        self.db.execute_query("INSERT INTO credit_ledger (user_id, action, platform, credits_spent) VALUES (%s, %s, %s, %s)",
                             (user_id, action, platform, cost))
        return True

    def get_usage_summary(self, user_id) -> dict:
        balance = self.get_balance(user_id)
        r = self.db.execute_query(
            """SELECT COALESCE(SUM(CASE WHEN credits_spent > 0 THEN credits_spent END), 0) AS total_spent,
               COALESCE(SUM(CASE WHEN action IN ('post','scheduled_post') AND credits_spent > 0 THEN credits_spent END), 0) AS posts_spent,
               COALESCE(SUM(CASE WHEN action = 'comment_reply' AND credits_spent > 0 THEN credits_spent END), 0) AS replies_spent,
               COUNT(CASE WHEN credits_spent > 0 THEN 1 END) AS total_actions
            FROM credit_ledger WHERE user_id = %s""",
            (user_id,), fetch="one",
        )
        return {
            "credits_remaining": balance,
            "credits_total": shared.credits.MONTHLY_CREDITS,
            "credits_used": int(r["total_spent"]) if r else 0,
            "posts_spent": int(r["posts_spent"]) if r else 0,
            "replies_spent": int(r["replies_spent"]) if r else 0,
            "total_actions": int(r["total_actions"]) if r else 0,
        }


shared.credits.CreditManager = LocalCreditManager

# ---------------------------------------------------------------------------
# Mock Celery — just log tasks instead of running them
# ---------------------------------------------------------------------------


class MockCeleryApp:
    def send_task(self, name, args=None, kwargs=None, queue=None, **kw):
        logger.info("[MOCK CELERY] Task: %s | Args: %s | Queue: %s", name, args, queue)
        return None

    class conf:
        task_always_eager = True


import workers.celery_app
workers.celery_app.celery_app = MockCeleryApp()

# ---------------------------------------------------------------------------
# Now import and run the actual FastAPI app
# ---------------------------------------------------------------------------
from fastapi import FastAPI, Request, Response
from gateway.router import handle_incoming_message
from shared.config import WHATSAPP_VERIFY_TOKEN

app = FastAPI(title="Local Test — AI Automation Service")


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified!")
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    logger.info("Incoming webhook: %s", json.dumps(body, indent=2)[:500])

    for e in body.get("entry", []):
        for change in e.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])
            for i, msg in enumerate(messages):
                sender = msg.get("from", "")
                contact_name = contacts[i]["profile"]["name"] if i < len(contacts) else ""
                await handle_incoming_message(
                    db=local_db,
                    sender=sender,
                    message=msg,
                    contact_name=contact_name,
                )
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "local_test"}


@app.get("/debug/users")
async def debug_users():
    """Debug endpoint — view all users."""
    users = local_db.execute_query("SELECT phone_number_id, display_name, credits_remaining, referral_code, subscription_active FROM users", fetch="all")
    return {"users": users or []}


@app.get("/debug/reset")
async def debug_reset():
    """Debug endpoint — reset the local database."""
    os.remove(DB_FILE) if os.path.exists(DB_FILE) else None
    local_db.__init__()
    return {"status": "database reset"}


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("  AI Automation Service — LOCAL TEST SERVER")
    print("=" * 60)
    print(f"\n  WhatsApp Token: {'SET' if os.getenv('WHATSAPP_TOKEN') else 'NOT SET'}")
    print(f"  Verify Token:   {os.getenv('WHATSAPP_VERIFY_TOKEN', 'my_verify_token')}")
    print(f"  Anthropic Key:  {'SET' if os.getenv('ANTHROPIC_API_KEY') else 'NOT SET'}")
    print(f"  Stripe Key:     {'SET' if os.getenv('STRIPE_SECRET_KEY') else 'NOT SET'}")
    print(f"\n  Database: SQLite ({DB_FILE})")
    print(f"  Celery:   MOCKED (tasks logged only)")
    print(f"\n  Debug endpoints:")
    print(f"    GET /debug/users  — view all users")
    print(f"    GET /debug/reset  — reset database")
    print(f"\n  Next steps:")
    print(f"    1. Run: ngrok http 8000")
    print(f"    2. Set Meta webhook URL to: https://<ngrok>/webhook")
    print(f"    3. Send a WhatsApp message to your business number")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
