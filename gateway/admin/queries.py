"""
Read queries for the admin panel.

All functions return dicts or lists of dicts (RealDictCursor format).
Never use string formatting for SQL values — always use parameterized queries.
"""

from __future__ import annotations

from typing import Optional

from shared.database import BotDatabase


# --------------------------------------------------------------------------
# Dashboard KPIs
# --------------------------------------------------------------------------

def get_kpis(db: BotDatabase) -> dict:
    """Top-level numbers for the dashboard."""
    out = {
        "total_users": 0,
        "active_subs": 0,
        "free_users": 0,
        "banned_users": 0,
        "new_today": 0,
        "new_7d": 0,
        "new_30d": 0,
        "messages_today": 0,
        "msgs_in_today": 0,
        "msgs_out_today": 0,
        "credits_used_30d": 0,
        "credits_used_today": 0,
        "active_conversations": 0,
    }
    try:
        row = db.execute_query(
            """SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE subscription_active) AS active_subs,
                COUNT(*) FILTER (WHERE NOT subscription_active) AS free_users,
                COUNT(*) FILTER (WHERE banned) AS banned_users,
                COUNT(*) FILTER (WHERE created_at > CURRENT_DATE) AS new_today,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS new_7d,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') AS new_30d
              FROM users""",
            fetch="one",
        ) or {}
        out["total_users"]  = int(row.get("total") or 0)
        out["active_subs"]  = int(row.get("active_subs") or 0)
        out["free_users"]   = int(row.get("free_users") or 0)
        out["banned_users"] = int(row.get("banned_users") or 0)
        out["new_today"]    = int(row.get("new_today") or 0)
        out["new_7d"]       = int(row.get("new_7d") or 0)
        out["new_30d"]      = int(row.get("new_30d") or 0)
    except Exception:
        pass

    try:
        row = db.execute_query(
            """SELECT
                COUNT(*) FILTER (WHERE created_at > CURRENT_DATE) AS today,
                COUNT(*) FILTER (WHERE created_at > CURRENT_DATE AND direction='in')  AS in_today,
                COUNT(*) FILTER (WHERE created_at > CURRENT_DATE AND direction='out') AS out_today
              FROM message_log""",
            fetch="one",
        ) or {}
        out["messages_today"]  = int(row.get("today") or 0)
        out["msgs_in_today"]   = int(row.get("in_today") or 0)
        out["msgs_out_today"]  = int(row.get("out_today") or 0)
    except Exception:
        pass

    try:
        row = db.execute_query(
            """SELECT
                COALESCE(SUM(GREATEST(credits_spent, 0)), 0) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') AS used_30d,
                COALESCE(SUM(GREATEST(credits_spent, 0)), 0) FILTER (WHERE created_at > CURRENT_DATE) AS used_today
              FROM credit_ledger""",
            fetch="one",
        ) or {}
        out["credits_used_30d"]   = int(row.get("used_30d") or 0)
        out["credits_used_today"] = int(row.get("used_today") or 0)
    except Exception:
        pass

    try:
        row = db.execute_query(
            "SELECT COUNT(*) AS n FROM conversation_state WHERE updated_at > NOW() - INTERVAL '15 minutes'",
            fetch="one",
        ) or {}
        out["active_conversations"] = int(row.get("n") or 0)
    except Exception:
        pass

    return out


# --------------------------------------------------------------------------
# Users list
# --------------------------------------------------------------------------

def list_users(
    db: BotDatabase,
    search: str = "",
    filter_kind: str = "all",
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[dict], int]:
    """Paginated user search. Returns (rows, total_count)."""
    where = ["TRUE"]
    params: list = []
    if search:
        where.append(
            "(phone_number_id ILIKE %s OR phone_number ILIKE %s OR display_name ILIKE %s OR referral_code ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like])
    if filter_kind == "subscribers":
        where.append("subscription_active = TRUE")
    elif filter_kind == "free":
        where.append("subscription_active = FALSE")
    elif filter_kind == "banned":
        where.append("banned = TRUE")
    elif filter_kind == "low_credits":
        where.append("credits_remaining <= 5")

    where_sql = " AND ".join(where)

    count_row = db.execute_query(
        f"SELECT COUNT(*) AS n FROM users WHERE {where_sql}",
        tuple(params), fetch="one",
    ) or {}
    total = int(count_row.get("n") or 0)

    offset = max(0, (page - 1) * per_page)
    rows = db.execute_query(
        f"""SELECT phone_number_id, phone_number, display_name, created_at, last_seen,
                  subscription_active, subscription_expires, credits_remaining, credits_used,
                  banned, referral_code
              FROM users WHERE {where_sql}
              ORDER BY COALESCE(last_seen, created_at) DESC NULLS LAST
              LIMIT %s OFFSET %s""",
        tuple(params + [per_page, offset]), fetch="all",
    ) or []
    return rows, total


# --------------------------------------------------------------------------
# Single user details
# --------------------------------------------------------------------------

def get_user_detail(db: BotDatabase, phone_number_id: str) -> Optional[dict]:
    user = db.execute_query(
        "SELECT * FROM users WHERE phone_number_id = %s",
        (phone_number_id,), fetch="one",
    )
    if not user:
        return None

    profile = db.execute_query(
        "SELECT * FROM user_profiles WHERE phone_number_id = %s",
        (phone_number_id,), fetch="one",
    )
    platforms = db.execute_query(
        "SELECT platform, page_id, page_name, account_username, pfm_profile_key, created_at "
        "FROM platform_tokens WHERE phone_number_id = %s",
        (phone_number_id,), fetch="all",
    ) or []
    ledger = db.execute_query(
        "SELECT action, platform, credits_spent, created_at FROM credit_ledger "
        "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
        (phone_number_id,), fetch="all",
    ) or []
    posts = db.execute_query(
        "SELECT platform, action_type, action_count, performed_at, metadata FROM automation_stats "
        "WHERE phone_number_id = %s ORDER BY performed_at DESC LIMIT 50",
        (phone_number_id,), fetch="all",
    ) or []
    scheduled = db.execute_query(
        "SELECT id, platform, content, scheduled_at, status FROM scheduled_content "
        "WHERE phone_number_id = %s ORDER BY scheduled_at DESC LIMIT 20",
        (phone_number_id,), fetch="all",
    ) or []
    conv = db.execute_query(
        "SELECT state, data, updated_at FROM conversation_state WHERE phone_number_id = %s",
        (phone_number_id,), fetch="one",
    )
    referrals_made = db.execute_query(
        "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id = %s",
        (phone_number_id,), fetch="one",
    ) or {}
    return {
        "user": user,
        "profile": profile,
        "platforms": platforms,
        "ledger": ledger,
        "posts": posts,
        "scheduled": scheduled,
        "conversation": conv,
        "referral_count": int(referrals_made.get("n") or 0),
    }


# --------------------------------------------------------------------------
# Message log (per user, or global)
# --------------------------------------------------------------------------

def get_messages_for_user(db: BotDatabase, phone_number_id: str, limit: int = 100) -> list[dict]:
    return db.execute_query(
        """SELECT id, direction, msg_type, text_body, created_at, metadata
              FROM message_log WHERE phone_number_id = %s
              ORDER BY created_at DESC LIMIT %s""",
        (phone_number_id, limit), fetch="all",
    ) or []


def get_recent_messages(
    db: BotDatabase,
    direction: str = "all",
    search: str = "",
    limit: int = 100,
) -> list[dict]:
    where = ["TRUE"]
    params: list = []
    if direction in ("in", "out"):
        where.append("direction = %s")
        params.append(direction)
    if search:
        where.append("(text_body ILIKE %s OR phone_number_id ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    where_sql = " AND ".join(where)
    return db.execute_query(
        f"""SELECT m.id, m.phone_number_id, u.display_name, m.direction, m.msg_type,
                   m.text_body, m.created_at
              FROM message_log m
              LEFT JOIN users u ON u.phone_number_id = m.phone_number_id
              WHERE {where_sql}
              ORDER BY m.created_at DESC LIMIT %s""",
        tuple(params + [limit]), fetch="all",
    ) or []


# --------------------------------------------------------------------------
# Activity feed (combines signups, posts, payments)
# --------------------------------------------------------------------------

def get_activity_feed(db: BotDatabase, limit: int = 50) -> list[dict]:
    """Union of recent signups, automation actions, credit grants, ban events."""
    rows = db.execute_query(
        """
        (SELECT 'signup' AS kind, phone_number_id AS user_id, display_name,
                created_at AS at, '{}'::jsonb AS detail
           FROM users ORDER BY created_at DESC LIMIT 30)
        UNION ALL
        (SELECT 'action' AS kind, a.phone_number_id, u.display_name,
                a.performed_at AS at,
                jsonb_build_object('platform', a.platform, 'action_type', a.action_type) AS detail
           FROM automation_stats a LEFT JOIN users u ON u.phone_number_id = a.phone_number_id
           ORDER BY a.performed_at DESC LIMIT 30)
        UNION ALL
        (SELECT 'credits' AS kind, c.user_id, u.display_name, c.created_at AS at,
                jsonb_build_object('action', c.action, 'spent', c.credits_spent) AS detail
           FROM credit_ledger c LEFT JOIN users u ON u.phone_number_id = c.user_id
           ORDER BY c.created_at DESC LIMIT 30)
        ORDER BY at DESC NULLS LAST
        LIMIT %s
        """,
        (limit,), fetch="all",
    ) or []
    return rows


# --------------------------------------------------------------------------
# Revenue (queried from local DB — Stripe is source of truth, this is a snapshot)
# --------------------------------------------------------------------------

def get_revenue_summary(db: BotDatabase) -> dict:
    """Subscription counts by plan tier — derived from Stripe customer IDs."""
    out = {"active_subs": 0, "subs_with_stripe_id": 0, "trialing_or_pending": 0,
           "subs_recent": []}
    try:
        row = db.execute_query(
            """SELECT
                COUNT(*) FILTER (WHERE subscription_active) AS active,
                COUNT(*) FILTER (WHERE stripe_customer_id IS NOT NULL) AS with_stripe
              FROM users""",
            fetch="one",
        ) or {}
        out["active_subs"] = int(row.get("active") or 0)
        out["subs_with_stripe_id"] = int(row.get("with_stripe") or 0)
    except Exception:
        pass

    try:
        out["subs_recent"] = db.execute_query(
            """SELECT phone_number_id, display_name, subscription_active, subscription_expires,
                      stripe_customer_id, stripe_subscription_id, updated_at
                  FROM users WHERE stripe_customer_id IS NOT NULL
                  ORDER BY updated_at DESC LIMIT 30""",
            fetch="all",
        ) or []
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------

def get_admin_audit(db: BotDatabase, limit: int = 100) -> list[dict]:
    return db.execute_query(
        "SELECT id, actor, action, target_user, detail, ip_address, created_at "
        "FROM admin_audit ORDER BY created_at DESC LIMIT %s",
        (limit,), fetch="all",
    ) or []


def write_audit(
    db: BotDatabase,
    action: str,
    target_user: Optional[str] = None,
    detail: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    from psycopg2.extras import Json
    try:
        db.execute_query(
            "INSERT INTO admin_audit (actor, action, target_user, detail, ip_address) "
            "VALUES ('admin', %s, %s, %s, %s)",
            (action, target_user, Json(detail or {}), ip_address),
        )
    except Exception:
        pass
