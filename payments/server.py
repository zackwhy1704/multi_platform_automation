"""
Payment server — Stripe webhook handler.

All payment UI is handled by Stripe's hosted pages:
  - Checkout: Stripe Checkout (hosted) for subscriptions
  - Management: Stripe Customer Portal for cancel/update
  - Promo codes: Stripe's built-in promotion code UI at checkout

We only handle:
  1. Stripe webhooks (payment confirmation, renewals, cancellations)
  2. Minimal redirect pages (success/cancel) that tell user to return to WhatsApp

No custom payment forms, no card handling, full PCI compliance via Stripe.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

import stripe
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from shared.config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    MONTHLY_CREDITS,
)
from shared.database import BotDatabase
from shared.credits import CreditManager

logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

db: BotDatabase = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = BotDatabase()
    app.state.db = db
    logger.info("Payment server started")
    yield
    db.close()


app = FastAPI(title="Payment Server", lifespan=lifespan)


def _notify(phone: str, msg: str):
    """Send WhatsApp notification via Celery."""
    try:
        from workers.notification import send_whatsapp_notification
        send_whatsapp_notification.delay(phone, msg)
    except Exception as e:
        logger.error("Failed to queue notification for %s: %s", phone, e)


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


# =========================================================================
# REDIRECT PAGES (minimal — just tells user to go back to WhatsApp)
# Stripe Checkout handles ALL payment UI. These are just landing pages.
# =========================================================================

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Payment Successful</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4;color:#166534;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p><strong>Payment successful!</strong></p>
<p>Your subscription is being activated. Return to WhatsApp — you'll receive a confirmation message shortly.</p>
</div></body></html>"""

_CANCEL_HTML = """<!DOCTYPE html>
<html><head><title>Payment Cancelled</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fefce8;color:#854d0e;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#8592;</h1>
<p>Payment cancelled. No charges were made.</p>
<p>Return to WhatsApp and send <strong>subscribe</strong> to try again.</p>
</div></body></html>"""

_PORTAL_RETURN_HTML = """<!DOCTYPE html>
<html><head><title>Subscription Updated</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#eff6ff;color:#1e40af;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p>Subscription updated. Return to WhatsApp to continue.</p>
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
# STRIPE WEBHOOKS — the single source of truth for payment events
# =========================================================================

@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return Response(status_code=400)
    except stripe.error.SignatureVerificationError:
        return Response(status_code=400)

    event_type = event["type"]
    logger.info("Stripe event: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"])
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(event["data"]["object"])
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(event["data"]["object"])
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(event["data"]["object"])
    elif event_type == "invoice.paid":
        _handle_invoice_paid(event["data"]["object"])

    return {"status": "success"}


def _find_user_by_stripe(customer_id: str, subscription_id: str = None):
    return db.execute_query(
        "SELECT phone_number_id FROM users WHERE stripe_customer_id = %s OR stripe_subscription_id = %s",
        (customer_id, subscription_id),
        fetch="one",
    )


def _handle_checkout_completed(session):
    """Handle successful checkout — subscriptions OR one-time credit pack purchases."""
    try:
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        mode = session.get("mode")  # "subscription" or "payment"
        phone = session.get("client_reference_id") or session.get("metadata", {}).get("phone_number_id")
        metadata = session.get("metadata", {})
        purchase_type = metadata.get("purchase_type", "")

        if not phone:
            logger.warning("checkout.session.completed missing phone: %s", session.get("id"))
            return

        if mode == "subscription" and subscription_id:
            # --- Subscription purchase ---
            days = 30
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                period_end = _get_subscription_period_end(sub)
                if period_end:
                    days = max(1, (datetime.fromtimestamp(period_end) - datetime.now()).days)
            except Exception:
                pass

            db.activate_subscription(phone, stripe_customer_id=customer_id, stripe_subscription_id=subscription_id, days=days)

            _notify(
                phone,
                "Payment Successful!\n\n"
                f"Your subscription is ACTIVE with *{MONTHLY_CREDITS} credits*.\n\n"
                "Send *post* to start automating!",
            )

        elif mode == "payment" and purchase_type.startswith("pack_"):
            # --- One-time credit pack purchase ---
            try:
                pack_credits = int(purchase_type.replace("pack_", ""))
            except ValueError:
                logger.error("Invalid pack purchase_type: %s", purchase_type)
                return

            # Store stripe_customer_id for future lookups
            if customer_id:
                db.execute_query(
                    "UPDATE users SET stripe_customer_id = COALESCE(stripe_customer_id, %s) WHERE phone_number_id = %s",
                    (customer_id, phone),
                )

            db.grant_credits(phone, pack_credits, reason=f"credit_pack_{pack_credits}")

            _notify(
                phone,
                f"Payment Successful!\n\n"
                f"*{pack_credits:,} credits* have been added to your account.\n\n"
                "Send *credits* to check your balance.",
            )

        else:
            logger.warning("Unhandled checkout mode=%s for session %s", mode, session.get("id"))

    except Exception as e:
        logger.error("Error in checkout.session.completed: %s", e)


def _handle_subscription_updated(subscription):
    """Handle subscription renewals and cancellations."""
    try:
        customer_id = getattr(subscription, "customer", None) or subscription.get("customer")
        subscription_id = getattr(subscription, "id", None) or subscription.get("id")
        cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
        status = getattr(subscription, "status", None) or subscription.get("status")

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if cancel_at_period_end:
            period_end = _get_subscription_period_end(subscription)
            cancel_date = datetime.fromtimestamp(period_end).strftime("%B %d, %Y") if period_end else "your billing period end"

            _notify(
                phone,
                f"Subscription Cancelled\n\n"
                f"Access continues until: {cancel_date}\n"
                "You won't be charged again.\n\n"
                "Send *subscribe* to resubscribe anytime.",
            )
        elif status == "active":
            cm = CreditManager(db)
            cm.reset_credits(phone, MONTHLY_CREDITS)
            _notify(phone, f"Subscription renewed! Credits reset to *{MONTHLY_CREDITS}*.")

    except Exception as e:
        logger.error("Error in subscription.updated: %s", e)


def _handle_subscription_deleted(subscription):
    """Deactivate subscription."""
    try:
        customer_id = getattr(subscription, "customer", None) or subscription.get("customer")
        subscription_id = getattr(subscription, "id", None) or subscription.get("id")

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        db.deactivate_subscription(phone)
        _notify(phone, "Subscription Ended\n\nYour free credits are still available.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in subscription.deleted: %s", e)


def _handle_payment_failed(invoice):
    """Notify user of failed payment."""
    try:
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")
        next_attempt = invoice.get("next_payment_attempt")

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if next_attempt:
            retry_date = datetime.fromtimestamp(next_attempt).strftime("%B %d, %Y")
            _notify(
                phone,
                f"Payment Failed\n\n"
                f"Please update your payment method.\n"
                f"Retry on: {retry_date}\n\n"
                "Send *cancel* to manage your subscription.",
            )
        else:
            db.deactivate_subscription(phone)
            _notify(phone, "Subscription cancelled due to payment failure.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in invoice.payment_failed: %s", e)


def _handle_invoice_paid(invoice):
    """Reset credits on successful invoice payment (subscription renewal)."""
    try:
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        cm = CreditManager(db)
        cm.reset_credits(phone, MONTHLY_CREDITS)
        logger.info("Credits reset for %s on invoice.paid", phone)

    except Exception as e:
        logger.error("Error in invoice.paid: %s", e)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "payment"}
