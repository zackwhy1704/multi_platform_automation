"""
Subscription and credit management handlers.
"""

import logging
import stripe

from shared.database import BotDatabase
from shared.credits import CreditManager, MONTHLY_CREDITS
from shared.config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, PAYMENT_SERVER_URL
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY


async def handle_credits(db: BotDatabase, sender: str, text: str):
    """Show credit balance and usage breakdown."""
    cm = CreditManager(db)
    summary = cm.get_usage_summary(sender)

    await wa.send_text(
        sender,
        f"*Credit Balance*\n\n"
        f"Remaining: *{summary['credits_remaining']}* / {summary['credits_total']}\n"
        f"Used: {summary['credits_used']}\n\n"
        f"*Breakdown:*\n"
        f"  Posts: {summary['posts_spent']} credits ({summary['posts_spent'] // 5} posts)\n"
        f"  Replies: {summary['replies_spent']} credits ({summary['replies_spent'] // 3} replies)\n"
        f"  Total actions: {summary['total_actions']}\n\n"
        f"*Costs:*\n"
        f"  Post / Scheduled post: 5 credits\n"
        f"  Comment reply: 3 credits\n\n"
        f"Credits reset on your next billing cycle.",
    )


async def handle_subscribe(db: BotDatabase, sender: str, text: str):
    """Create a Stripe checkout session and send payment link."""
    user = db.get_user(sender)

    if user and user.get("subscription_active"):
        cm = CreditManager(db)
        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"You already have an active subscription!\n"
            f"Credits remaining: *{balance}* / {MONTHLY_CREDITS}\n\n"
            f"Send *cancel* to cancel your subscription.",
        )
        return

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        await wa.send_text(sender, "Payment system is not configured. Please contact support.")
        return

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{PAYMENT_SERVER_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}&phone={sender}",
            cancel_url=f"{PAYMENT_SERVER_URL}/payment/cancel?phone={sender}",
            client_reference_id=sender,
            metadata={"phone_number_id": sender},
            billing_address_collection="required",
            payment_method_collection="always",
        )

        await wa.send_text(
            sender,
            f"*Subscribe to Multi-Platform Automation*\n\n"
            f"Plan: *500 credits/month*\n"
            f"  - Post/Schedule: 5 credits each\n"
            f"  - Comment reply: 3 credits each\n\n"
            f"Click below to subscribe:\n{session.url}",
        )
    except Exception as e:
        logger.error("Stripe checkout error for %s: %s", sender, e)
        await wa.send_text(sender, "Something went wrong creating your checkout. Please try again.")


async def handle_cancel(db: BotDatabase, sender: str, text: str):
    """Cancel subscription via Stripe portal."""
    user = db.get_user(sender)

    if not user or not user.get("subscription_active"):
        await wa.send_text(sender, "You don't have an active subscription.")
        return

    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        await wa.send_text(sender, "No Stripe customer found. Please contact support.")
        return

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{PAYMENT_SERVER_URL}/payment/cancel-complete?phone={sender}",
        )
        await wa.send_text(
            sender,
            f"Manage your subscription here:\n{portal_session.url}\n\n"
            "You can cancel, update payment method, or view invoices.",
        )
    except Exception as e:
        logger.error("Stripe portal error for %s: %s", sender, e)
        await wa.send_text(sender, "Something went wrong. Please try again.")
