"""
Message logging — captures every inbound and outbound WhatsApp message
into the message_log table for the admin panel.

Designed to fail silently: a logging failure must never break message handling.
"""

import json
import logging
from typing import Any, Optional

from psycopg2.extras import Json

from shared.database import BotDatabase

logger = logging.getLogger(__name__)

# Module-global DB handle — set by gateway/app.py at startup.
# If unset, logging is a no-op (safe for tests / scripts).
_db: Optional[BotDatabase] = None


def attach_db(database: BotDatabase) -> None:
    """Bind the database used for message logging. Called once at app startup."""
    global _db
    _db = database


def _truncate(text: Optional[str], n: int = 4000) -> Optional[str]:
    if text is None:
        return None
    return text[:n]


def log_inbound(
    db: BotDatabase,
    phone_number_id: str,
    msg_type: str,
    text_body: str = "",
    wa_message_id: str = "",
    metadata: Optional[dict] = None,
) -> None:
    """Log an incoming WhatsApp message. Never raises."""
    try:
        db.execute_query(
            """INSERT INTO message_log
                 (phone_number_id, direction, msg_type, text_body, wa_message_id, metadata)
               VALUES (%s, 'in', %s, %s, %s, %s)""",
            (
                phone_number_id,
                msg_type or "unknown",
                _truncate(text_body),
                wa_message_id or None,
                Json(metadata or {}),
            ),
        )
    except Exception as e:
        logger.warning("log_inbound failed for %s: %s", phone_number_id, e)


def log_outbound(
    phone_number_id: str,
    msg_type: str,
    text_body: str = "",
    metadata: Optional[dict] = None,
) -> None:
    """Log an outgoing WhatsApp message. Never raises. No-op if DB not attached."""
    if _db is None:
        return
    try:
        _db.execute_query(
            """INSERT INTO message_log
                 (phone_number_id, direction, msg_type, text_body, metadata)
               VALUES (%s, 'out', %s, %s, %s)""",
            (
                phone_number_id,
                msg_type or "unknown",
                _truncate(text_body),
                Json(metadata or {}),
            ),
        )
    except Exception as e:
        logger.warning("log_outbound failed for %s: %s", phone_number_id, e)


def summarize_buttons(buttons: list[dict]) -> str:
    """Render a list of interactive buttons into a single-line preview string."""
    try:
        return " | ".join(b.get("title") or b.get("id") or "" for b in buttons)
    except Exception:
        return ""


def summarize_sections(sections: list[dict]) -> str:
    """Render interactive list sections into a single-line preview string."""
    try:
        rows = []
        for sec in sections:
            for r in sec.get("rows", []):
                title = r.get("title") or r.get("id") or ""
                rows.append(title)
        return " | ".join(rows)
    except Exception:
        return ""
