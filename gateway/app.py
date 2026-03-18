"""
WhatsApp Gateway — FastAPI application.
Receives Meta Cloud API webhooks and dispatches to conversation handlers.
Includes OAuth callback, media serving, payment redirect pages, and Stripe webhook.

This is the SINGLE deployed service on Railway — all routes live here.
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import stripe
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, FileResponse

from shared.config import (
    WHATSAPP_VERIFY_TOKEN,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    MONTHLY_CREDITS,
    PAYMENT_SERVER_URL,
    WHATSAPP_BOT_PHONE,
)
from shared.database import BotDatabase
from shared.credits import CreditManager
from gateway.router import handle_incoming_message
from gateway.handlers.oauth import (
    handle_oauth_callback,
    OAUTH_SUCCESS_HTML,
    OAUTH_ERROR_HTML,
    OAUTH_DENIED_HTML,
    OAUTH_EXPIRED_HTML,
    _verify_state,
)
from gateway.media import MEDIA_DIR
from gateway import whatsapp_client as wa

logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

db: BotDatabase = None


def _seed_defaults(database: BotDatabase):
    """Insert default promo codes if they don't exist yet (idempotent)."""
    defaults = [
        ("CATALYX50", 50, None),
        ("ADMIN99", 999999, None),
        ("FIRSTMONTHFREE", 1500, None),
    ]
    for code, credits, max_uses in defaults:
        try:
            database.execute_query(
                "INSERT INTO promo_codes (code, credits_granted, max_uses, active) "
                "VALUES (%s, %s, %s, TRUE) ON CONFLICT DO NOTHING",
                (code, credits, max_uses),
            )
        except Exception as e:
            logger.warning("Could not seed promo code %s: %s", code, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = BotDatabase()
    app.state.db = db
    logger.info("Gateway started — database pool ready")
    _seed_defaults(db)
    yield
    db.close()
    logger.info("Gateway shutdown — pool closed")


app = FastAPI(title="Multi-Platform Automation Gateway", lifespan=lifespan)


@app.get("/")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "ok", "service": "gateway"}


# =========================================================================
# WHATSAPP WEBHOOK
# =========================================================================

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification (GET challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    entry = body.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            for i, msg in enumerate(messages):
                sender = msg.get("from", "")
                contact_name = contacts[i]["profile"]["name"] if i < len(contacts) else ""

                await handle_incoming_message(
                    db=app.state.db,
                    sender=sender,
                    message=msg,
                    contact_name=contact_name,
                )

    return {"status": "ok"}


# =========================================================================
# FACEBOOK OAUTH CALLBACK
# =========================================================================

@app.get("/auth/callback")
async def oauth_callback(request: Request):
    """Facebook OAuth callback — exchanges auth code for tokens."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    error_reason = request.query_params.get("error_reason", "")

    # User denied permissions
    if error == "access_denied" or error_reason == "user_denied":
        logger.info("OAuth: user denied permissions (state=%s)", state)
        # Try to notify user via WhatsApp
        if state:
            phone = _verify_state(state)
            if phone:
                await wa.send_text(phone,
                    "You didn't grant the required permissions.\n\n"
                    "The bot needs access to your Pages and Instagram to post on your behalf.\n"
                    "Send *setup* to try again — make sure to allow all permissions.")
        return HTMLResponse(OAUTH_DENIED_HTML)

    if error:
        logger.warning("OAuth error: %s — %s", error, request.query_params.get("error_description"))
        return HTMLResponse(OAUTH_ERROR_HTML)

    if not code or not state:
        return HTMLResponse(OAUTH_ERROR_HTML)

    # Verify state hasn't expired
    phone = _verify_state(state)
    if not phone:
        return HTMLResponse(OAUTH_EXPIRED_HTML)

    result = await handle_oauth_callback(code, state, app.state.db)
    if result.get("success"):
        return HTMLResponse(OAUTH_SUCCESS_HTML)
    return HTMLResponse(OAUTH_ERROR_HTML)


# =========================================================================
# MEDIA SERVING
# =========================================================================

@app.get("/media/{filename}")
async def serve_media(filename: str):
    """Serve downloaded media files (for Facebook/Instagram Graph API to access)."""
    file_path = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(file_path):
        return Response(status_code=404)
    return FileResponse(file_path)


# =========================================================================
# PAYMENT REDIRECT PAGES (Stripe Checkout redirects here)
# =========================================================================

def _wa_btn(label: str = "Return to WhatsApp") -> str:
    href = f"https://wa.me/{WHATSAPP_BOT_PHONE}" if WHATSAPP_BOT_PHONE else "https://wa.me/"
    return (
        f'<a href="{href}" style="display:inline-block;margin-top:24px;padding:14px 28px;'
        f'background:#25D366;color:#fff;text-decoration:none;border-radius:8px;'
        f'font-size:16px;font-weight:600;">&#x21A9; {label}</a>'
    )


_SUCCESS_HTML = f"""<!DOCTYPE html>
<html><head><title>Payment Successful</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4;color:#166534;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p><strong>Payment successful!</strong></p>
<p>Your subscription is being activated. You'll receive a confirmation message in WhatsApp shortly.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""

_CANCEL_HTML = f"""<!DOCTYPE html>
<html><head><title>Payment Cancelled</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fefce8;color:#854d0e;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#8592;</h1>
<p>Payment cancelled. No charges were made.</p>
<p>Send <strong>subscribe</strong> in WhatsApp to try again.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""

_PORTAL_RETURN_HTML = f"""<!DOCTYPE html>
<html><head><title>Subscription Updated</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#eff6ff;color:#1e40af;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p>Subscription updated.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success():
    """Redirect page after Stripe Checkout. Activation happens via webhook."""
    return HTMLResponse(_SUCCESS_HTML)


@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel():
    """Redirect page when user cancels Stripe Checkout."""
    return HTMLResponse(_CANCEL_HTML)


@app.get("/payment/portal-return", response_class=HTMLResponse)
async def portal_return():
    """Return page after Stripe Customer Portal."""
    return HTMLResponse(_PORTAL_RETURN_HTML)


# =========================================================================
# STRIPE WEBHOOK — single source of truth for payment events
# =========================================================================

def _get_subscription_period_end(subscription) -> int | None:
    """Get current_period_end from Stripe subscription (handles old + new API)."""
    period_end = getattr(subscription, "current_period_end", None)
    if period_end is None:
        try:
            period_end = subscription["current_period_end"]
        except (KeyError, TypeError):
            pass
    if period_end is None:
        try:
            items = getattr(subscription, "items", None)
            if callable(items):
                items = items()
            item_list = getattr(items, "data", []) if items else []
            if item_list:
                period_end = getattr(item_list[0], "current_period_end", None)
        except (AttributeError, IndexError):
            pass
    return period_end


def _find_user_by_stripe(customer_id: str, subscription_id: str = None):
    """Find user by Stripe customer or subscription ID."""
    if subscription_id:
        row = db.execute_query(
            "SELECT phone_number_id FROM users WHERE stripe_subscription_id = %s",
            (subscription_id,), fetch="one",
        )
        if row:
            return row
    if customer_id:
        return db.execute_query(
            "SELECT phone_number_id FROM users WHERE stripe_customer_id = %s",
            (customer_id,), fetch="one",
        )
    return None


def _is_duplicate_event(event_id: str) -> bool:
    """Check if we've already processed this Stripe event (idempotency)."""
    try:
        existing = db.execute_query(
            "SELECT 1 FROM webhook_events WHERE event_id = %s", (event_id,), fetch="one"
        )
        if existing:
            return True
        db.execute_query(
            "INSERT INTO webhook_events (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (event_id,),
        )
        return False
    except Exception as e:
        # Table might not exist yet — log and proceed (non-blocking)
        logger.warning("Idempotency check failed (table may not exist): %s", e)
        return False


async def _notify_whatsapp(phone: str, msg: str):
    """Send WhatsApp notification directly (no Celery needed)."""
    try:
        await wa.send_text(phone, msg)
    except Exception as e:
        logger.error("Failed to notify %s: %s", phone, e)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            logger.warning("Stripe webhook: invalid payload")
            return Response(status_code=400)
        except stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook: invalid signature")
            return Response(status_code=400)
    else:
        # No webhook secret configured — parse raw (dev/testing only)
        import json
        event = json.loads(payload)

    event_id = event.get("id", "")
    event_type = event.get("type", "") if isinstance(event, dict) else event["type"]
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    # Idempotency: skip duplicate events
    if event_id and _is_duplicate_event(event_id):
        logger.info("Duplicate Stripe event skipped: %s", event_id)
        return {"status": "duplicate"}

    data_object = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data_object)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data_object)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data_object)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data_object)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data_object)

    return {"status": "success"}


async def _handle_checkout_completed(session):
    """Handle successful checkout — subscriptions OR one-time credit pack purchases."""
    try:
        customer_id = session.get("customer") if isinstance(session, dict) else getattr(session, "customer", None)
        subscription_id = session.get("subscription") if isinstance(session, dict) else getattr(session, "subscription", None)
        mode = session.get("mode") if isinstance(session, dict) else getattr(session, "mode", None)
        metadata = session.get("metadata", {}) if isinstance(session, dict) else getattr(session, "metadata", {})
        phone = (session.get("client_reference_id") if isinstance(session, dict) else getattr(session, "client_reference_id", None))
        if not phone:
            phone = metadata.get("phone_number_id") if isinstance(metadata, dict) else getattr(metadata, "phone_number_id", None)
        purchase_type = metadata.get("purchase_type", "") if isinstance(metadata, dict) else getattr(metadata, "purchase_type", "")

        if not phone:
            logger.warning("checkout.session.completed missing phone: %s",
                           session.get("id") if isinstance(session, dict) else getattr(session, "id", "?"))
            return

        if mode == "subscription" and subscription_id:
            days = 30
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                period_end = _get_subscription_period_end(sub)
                if period_end:
                    days = max(1, (datetime.fromtimestamp(period_end) - datetime.now()).days)
            except Exception:
                pass

            db.activate_subscription(phone, stripe_customer_id=customer_id,
                                     stripe_subscription_id=subscription_id, days=days)

            await _notify_whatsapp(
                phone,
                "Payment Successful!\n\n"
                f"Your subscription is ACTIVE with *{MONTHLY_CREDITS} credits*.\n\n"
                "Send *post* to start automating!",
            )

        elif mode == "payment" and purchase_type.startswith("pack_"):
            try:
                pack_credits = int(purchase_type.replace("pack_", ""))
            except ValueError:
                logger.error("Invalid pack purchase_type: %s", purchase_type)
                return

            if customer_id:
                db.execute_query(
                    "UPDATE users SET stripe_customer_id = COALESCE(stripe_customer_id, %s) WHERE phone_number_id = %s",
                    (customer_id, phone),
                )

            db.grant_credits(phone, pack_credits, reason=f"credit_pack_{pack_credits}")

            await _notify_whatsapp(
                phone,
                f"Payment Successful!\n\n"
                f"*{pack_credits:,} credits* have been added to your account.\n\n"
                "Send *credits* to check your balance.",
            )
        else:
            logger.warning("Unhandled checkout mode=%s for session %s", mode,
                           session.get("id") if isinstance(session, dict) else getattr(session, "id", "?"))

    except Exception as e:
        logger.error("Error in checkout.session.completed: %s", e, exc_info=True)


async def _handle_subscription_updated(subscription):
    """Handle subscription renewals and cancellations."""
    try:
        customer_id = getattr(subscription, "customer", None) or (subscription.get("customer") if isinstance(subscription, dict) else None)
        subscription_id = getattr(subscription, "id", None) or (subscription.get("id") if isinstance(subscription, dict) else None)
        cancel_at_period_end = getattr(subscription, "cancel_at_period_end", None)
        if cancel_at_period_end is None and isinstance(subscription, dict):
            cancel_at_period_end = subscription.get("cancel_at_period_end", False)
        status = getattr(subscription, "status", None) or (subscription.get("status") if isinstance(subscription, dict) else None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if cancel_at_period_end:
            period_end = _get_subscription_period_end(subscription)
            cancel_date = datetime.fromtimestamp(period_end).strftime("%B %d, %Y") if period_end else "your billing period end"

            await _notify_whatsapp(
                phone,
                f"Subscription Cancelled\n\n"
                f"Access continues until: {cancel_date}\n"
                "You won't be charged again.\n\n"
                "Send *subscribe* to resubscribe anytime.",
            )
        elif status == "active":
            cm = CreditManager(db)
            cm.reset_credits(phone, MONTHLY_CREDITS)
            await _notify_whatsapp(phone, f"Subscription renewed! Credits reset to *{MONTHLY_CREDITS}*.")

    except Exception as e:
        logger.error("Error in subscription.updated: %s", e, exc_info=True)


async def _handle_subscription_deleted(subscription):
    """Deactivate subscription."""
    try:
        customer_id = getattr(subscription, "customer", None) or (subscription.get("customer") if isinstance(subscription, dict) else None)
        subscription_id = getattr(subscription, "id", None) or (subscription.get("id") if isinstance(subscription, dict) else None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        db.deactivate_subscription(phone)
        await _notify_whatsapp(phone, "Subscription Ended\n\nYour free credits are still available.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in subscription.deleted: %s", e, exc_info=True)


async def _handle_payment_failed(invoice):
    """Notify user of failed payment."""
    try:
        customer_id = invoice.get("customer") if isinstance(invoice, dict) else getattr(invoice, "customer", None)
        subscription_id = invoice.get("subscription") if isinstance(invoice, dict) else getattr(invoice, "subscription", None)
        next_attempt = invoice.get("next_payment_attempt") if isinstance(invoice, dict) else getattr(invoice, "next_payment_attempt", None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if next_attempt:
            retry_date = datetime.fromtimestamp(next_attempt).strftime("%B %d, %Y")
            await _notify_whatsapp(
                phone,
                f"Payment Failed\n\n"
                f"Please update your payment method.\n"
                f"Retry on: {retry_date}\n\n"
                "Send *cancel* to manage your subscription.",
            )
        else:
            db.deactivate_subscription(phone)
            await _notify_whatsapp(phone, "Subscription cancelled due to payment failure.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in invoice.payment_failed: %s", e, exc_info=True)


async def _handle_invoice_paid(invoice):
    """Reset credits on successful invoice payment (subscription renewal)."""
    try:
        customer_id = invoice.get("customer") if isinstance(invoice, dict) else getattr(invoice, "customer", None)
        subscription_id = invoice.get("subscription") if isinstance(invoice, dict) else getattr(invoice, "subscription", None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        cm = CreditManager(db)
        cm.reset_credits(phone, MONTHLY_CREDITS)
        logger.info("Credits reset for %s on invoice.paid", phone)

    except Exception as e:
        logger.error("Error in invoice.paid: %s", e, exc_info=True)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}
