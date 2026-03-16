"""
Subscription, credit management, and referral handlers.

All payment UI uses Stripe's hosted pages:
  - Stripe Checkout: subscription signup + promo codes
  - Stripe Customer Portal: cancel, update payment method, view invoices

Freemium: all users get 30 free credits. Subscribers get 500/month.
"""

import logging
import stripe

from shared.database import BotDatabase
from shared.credits import CreditManager, MONTHLY_CREDITS
from shared.config import STRIPE_SECRET_KEY, STRIPE_PRICE_ID, PAYMENT_SERVER_URL, FREE_SIGNUP_CREDITS
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY


async def handle_credits(db: BotDatabase, sender: str, text: str):
    """Show credit balance and usage breakdown."""
    cm = CreditManager(db)
    summary = cm.get_usage_summary(sender)
    user = db.get_user(sender)
    is_sub = user and user.get("subscription_active")

    plan_label = f"Subscriber ({MONTHLY_CREDITS}/month)" if is_sub else f"Free ({FREE_SIGNUP_CREDITS} signup credits)"

    await wa.send_text(
        sender,
        f"*Credit Balance*\n\n"
        f"Plan: {plan_label}\n"
        f"Remaining: *{summary['credits_remaining']}*\n"
        f"Used this period: {summary['credits_used']}\n\n"
        f"*Breakdown:*\n"
        f"  Posts: {summary['posts_spent']} credits\n"
        f"  Replies: {summary['replies_spent']} credits\n\n"
        f"*Costs:*\n"
        f"  Post / Scheduled post: 5 credits\n"
        f"  Comment reply: 3 credits\n\n"
        + ("Credits reset on your next billing cycle." if is_sub else
           "Want more credits? Send *subscribe* for 500/month or *referral* to earn free credits."),
    )


async def handle_subscribe(db: BotDatabase, sender: str, text: str):
    """Create a Stripe Checkout session (hosted by Stripe) and send the link."""
    user = db.get_user(sender)

    if user and user.get("subscription_active"):
        cm = CreditManager(db)
        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"You already have an active subscription!\n"
            f"Credits remaining: *{balance}* / {MONTHLY_CREDITS}\n\n"
            f"Send *cancel* to manage your subscription.",
        )
        return

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        await wa.send_text(sender, "Payment system is not configured yet. Please contact support.")
        return

    try:
        # Stripe Checkout handles ALL payment UI:
        # - Card input, validation, 3D Secure
        # - Promo code entry (allow_promotion_codes=True)
        # - Tax collection, address collection
        # - PCI compliance — we never touch card data
        session = stripe.checkout.Session.create(
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{PAYMENT_SERVER_URL}/payment/success",
            cancel_url=f"{PAYMENT_SERVER_URL}/payment/cancel",
            client_reference_id=sender,
            metadata={"phone_number_id": sender},
            allow_promotion_codes=True,
        )

        await wa.send_text(
            sender,
            f"*Upgrade to AI Automation Pro*\n\n"
            f"*500 credits/month* — automate your social media:\n"
            f"  - Up to 100 AI posts/month\n"
            f"  - Up to 166 auto-replies/month\n"
            f"  - Priority content generation\n"
            f"  - Credits reset every billing cycle\n\n"
            f"Have a promo code? You can enter it at checkout.\n\n"
            f"Subscribe here:\n{session.url}",
        )
    except Exception as e:
        logger.error("Stripe checkout error for %s: %s", sender, e)
        await wa.send_text(sender, "Something went wrong creating your checkout. Please try again.")


async def handle_cancel(db: BotDatabase, sender: str, text: str):
    """Open Stripe Customer Portal for subscription management.

    Stripe's hosted portal handles:
      - Cancel subscription (immediate or end-of-period)
      - Update payment method
      - View invoice history
      - Resume cancelled subscriptions
    """
    user = db.get_user(sender)

    if not user or not user.get("subscription_active"):
        await wa.send_text(sender, "You don't have an active subscription.\nSend *subscribe* to upgrade.")
        return

    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        await wa.send_text(sender, "No Stripe customer found. Please contact support.")
        return

    try:
        # Use Stripe Customer Portal with cancel flow deep link
        # This takes the user directly to the cancellation page
        sub_id = user.get("stripe_subscription_id")
        flow_data = None
        if sub_id:
            flow_data = {
                "type": "subscription_cancel",
                "subscription_cancel": {"subscription": sub_id},
            }

        portal_kwargs = {
            "customer": customer_id,
            "return_url": f"{PAYMENT_SERVER_URL}/payment/portal-return",
        }
        if flow_data:
            portal_kwargs["flow_data"] = flow_data

        portal_session = stripe.billing_portal.Session.create(**portal_kwargs)

        await wa.send_text(
            sender,
            f"Manage your subscription here:\n{portal_session.url}\n\n"
            "You can cancel, update payment method, or view invoices.\n"
            "All handled securely by Stripe.",
        )
    except Exception as e:
        logger.error("Stripe portal error for %s: %s", sender, e)
        await wa.send_text(sender, "Something went wrong. Please try again.")


async def handle_referral(db: BotDatabase, sender: str, text: str):
    """Show user's referral code and stats."""
    user = db.get_user(sender)
    if not user:
        await wa.send_text(sender, "Send *start* to set up your account first.")
        return

    referral_code = user.get("referral_code", "")
    if not referral_code:
        import uuid
        referral_code = "REF-" + uuid.uuid4().hex[:6].upper()
        db.set_referral_code(sender, referral_code)

    referral_count = db.get_referral_count(sender)

    await wa.send_text(
        sender,
        f"*Your Referral Program*\n\n"
        f"Your code: *{referral_code}*\n"
        f"Successful referrals: {referral_count}\n"
        f"Credits earned from referrals: {referral_count * 50}\n\n"
        f"*How it works:*\n"
        f"1. Share your code with friends\n"
        f"2. They enter it during signup\n"
        f"3. You both get *50 bonus credits*!\n\n"
        f"Share this message:\n"
        f"_Try the AI Automation Service for your social media! "
        f"Use my code {referral_code} when you sign up and we both get 50 free credits._",
    )
