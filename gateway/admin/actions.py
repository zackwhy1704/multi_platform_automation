"""
Admin actions — every state-changing operation triggered from the admin panel.

All actions:
  - Read DB from request.app.state.db
  - Write an admin_audit row
  - Return a flash string in the format "good|message" or "bad|message"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import Request

from gateway import whatsapp_client as wa
from gateway.admin import queries as Q
from shared.config import STRIPE_SECRET_KEY

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY


def _db(request: Request):
    return request.app.state.db


def _ip(request: Request) -> str:
    # Behind a proxy (Caddy/Railway), prefer X-Forwarded-For
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


# --------------------------------------------------------------------------
# Credits
# --------------------------------------------------------------------------

async def gift_credits(request: Request, phone_number_id: str, amount: int, reason: str) -> str:
    db = _db(request)
    if amount <= 0 or amount > 1_000_000:
        return "bad|Invalid amount."
    user = db.get_user(phone_number_id)
    if not user:
        return "bad|User not found."

    ok = db.grant_credits(phone_number_id, amount, reason=f"admin:{reason or 'gift'}")
    Q.write_audit(
        db, "gift_credits",
        target_user=phone_number_id,
        detail={"amount": amount, "reason": reason},
        ip_address=_ip(request),
    )
    if not ok:
        return "bad|Could not grant credits (DB error)."

    # Notify the user via WhatsApp (fire-and-forget; non-fatal if it fails)
    try:
        await wa.send_text(
            phone_number_id,
            f"You've been gifted *{amount} credits* by the admin team. Send *credits* to see your balance.",
        )
    except Exception as e:
        logger.warning("gift_credits notify failed: %s", e)

    return f"good|Granted {amount} credits to user."


# --------------------------------------------------------------------------
# Conversation state
# --------------------------------------------------------------------------

async def reset_state(request: Request, phone_number_id: str) -> str:
    db = _db(request)
    try:
        db.clear_conversation_state(phone_number_id)
    except Exception as e:
        logger.warning("reset_state failed: %s", e)
        return "bad|Could not reset state."
    Q.write_audit(db, "reset_state", target_user=phone_number_id, ip_address=_ip(request))
    return "good|Conversation state cleared."


# --------------------------------------------------------------------------
# Manual messages
# --------------------------------------------------------------------------

async def send_message(request: Request, phone_number_id: str, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return "bad|Message body is empty."
    if len(body) > 4000:
        return "bad|Message too long (max 4000 chars)."
    try:
        ok = await wa.send_text(phone_number_id, body)
    except Exception as e:
        logger.error("send_message failed: %s", e)
        ok = False
    Q.write_audit(
        _db(request), "send_message",
        target_user=phone_number_id,
        detail={"length": len(body), "ok": ok},
        ip_address=_ip(request),
    )
    if not ok:
        return "bad|WhatsApp API rejected the message."
    return "good|Message sent."


# --------------------------------------------------------------------------
# Ban / unban
# --------------------------------------------------------------------------

async def ban_user(request: Request, phone_number_id: str, reason: str) -> str:
    db = _db(request)
    try:
        db.execute_query(
            "UPDATE users SET banned = TRUE, banned_reason = %s, banned_at = CURRENT_TIMESTAMP "
            "WHERE phone_number_id = %s",
            (reason or None, phone_number_id),
        )
    except Exception as e:
        logger.warning("ban_user failed: %s", e)
        return "bad|Could not ban user."
    Q.write_audit(
        db, "ban", target_user=phone_number_id,
        detail={"reason": reason or ""}, ip_address=_ip(request),
    )
    return "good|User banned. They will be silently dropped on next message."


async def unban_user(request: Request, phone_number_id: str) -> str:
    db = _db(request)
    try:
        db.execute_query(
            "UPDATE users SET banned = FALSE, banned_reason = NULL, banned_at = NULL "
            "WHERE phone_number_id = %s",
            (phone_number_id,),
        )
    except Exception as e:
        logger.warning("unban_user failed: %s", e)
        return "bad|Could not unban user."
    Q.write_audit(db, "unban", target_user=phone_number_id, ip_address=_ip(request))
    return "good|User unbanned."


# --------------------------------------------------------------------------
# Profile editing
# --------------------------------------------------------------------------

def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


async def edit_profile(request: Request, phone_number_id: str, profile: dict) -> str:
    db = _db(request)
    payload = {
        "industry": _split_csv(profile.get("industry", "")),
        "offerings": _split_csv(profile.get("offerings", "")),
        "business_goals": _split_csv(profile.get("business_goals", "")),
        "tone": _split_csv(profile.get("tone", "")),
        "content_style": (profile.get("content_style") or "").strip(),
        "visual_style": (profile.get("visual_style") or "").strip(),
        "platform": (profile.get("platform") or "").strip(),
    }
    ok = db.save_user_profile(phone_number_id, payload)
    Q.write_audit(
        db, "edit_profile", target_user=phone_number_id,
        detail=payload, ip_address=_ip(request),
    )
    if not ok:
        return "bad|Could not save profile."
    return "good|Profile updated."


# --------------------------------------------------------------------------
# Stripe — refund & cancel
# --------------------------------------------------------------------------

async def cancel_subscription(request: Request, phone_number_id: str) -> str:
    db = _db(request)
    user = db.get_user(phone_number_id)
    if not user:
        return "bad|User not found."
    sub_id = user.get("stripe_subscription_id")
    if not sub_id:
        return "bad|No Stripe subscription on file."
    try:
        # Cancel at period end so user keeps access until they paid for
        sub = stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
        Q.write_audit(
            db, "cancel_subscription", target_user=phone_number_id,
            detail={"stripe_subscription_id": sub_id, "status": sub.get("status")},
            ip_address=_ip(request),
        )
    except Exception as e:
        logger.error("cancel_subscription Stripe error: %s", e)
        return f"bad|Stripe error: {e}"

    try:
        await wa.send_text(
            phone_number_id,
            "Your subscription has been *scheduled to cancel* by the admin team. "
            "You will keep access until your current billing period ends.",
        )
    except Exception:
        pass
    return "good|Subscription set to cancel at period end."


async def refund_subscription(request: Request, phone_number_id: str) -> str:
    """Refund the most recent paid invoice charge for this customer."""
    db = _db(request)
    user = db.get_user(phone_number_id)
    if not user:
        return "bad|User not found."
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        return "bad|No Stripe customer on file."
    try:
        # Most recent charge for this customer
        charges = stripe.Charge.list(customer=customer_id, limit=1)
        data = charges.get("data", [])
        if not data:
            return "bad|No charges found for this customer."
        charge = data[0]
        if charge.get("refunded"):
            return "bad|Most recent charge is already refunded."
        refund = stripe.Refund.create(charge=charge["id"])
        Q.write_audit(
            db, "refund", target_user=phone_number_id,
            detail={"charge_id": charge["id"], "refund_id": refund.get("id"),
                    "amount": charge.get("amount")},
            ip_address=_ip(request),
        )
    except Exception as e:
        logger.error("refund Stripe error: %s", e)
        return f"bad|Stripe error: {e}"

    try:
        await wa.send_text(
            phone_number_id,
            "A *refund* for your most recent payment has been issued. "
            "It may take a few business days to appear on your statement.",
        )
    except Exception:
        pass
    return f"good|Refunded charge {charge['id']}."
