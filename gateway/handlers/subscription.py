"""
Subscription, credit management, and referral handlers.

Plans (Stripe Adaptive Pricing for SGD/MYR auto-conversion):
  - Free:      30 credits on signup (+50 with referral)
  - Starter:   $14.99/mo → 500 credits
  - Pro:       $34.99/mo → 1,500 credits
  - Business:  $79.99/mo → 5,000 credits

Add-on credit packs (one-time):
  - 100 credits:   $4.99
  - 500 credits:   $24.99
  - 1,500 credits: $74.99
  - 5,000 credits: $200.00
"""

import logging
import stripe

from shared.database import BotDatabase
from shared.credits import CreditManager, PLANS, CREDIT_PACKS, ACTION_COSTS
from shared.config import (
    STRIPE_SECRET_KEY,
    STRIPE_PRICE_ID_STARTER,
    STRIPE_PRICE_ID_PRO,
    STRIPE_PRICE_ID_BUSINESS,
    STRIPE_PRICE_ID_PACK_100,
    STRIPE_PRICE_ID_PACK_500,
    STRIPE_PRICE_ID_PACK_1500,
    STRIPE_PRICE_ID_PACK_5000,
    STRIPE_PRICE_ID,
    PAYMENT_SERVER_URL,
    PUBLIC_BASE_URL,
    FREE_SIGNUP_CREDITS,
)
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

# Map plan names to Stripe price IDs
PLAN_PRICE_IDS = {
    "starter": STRIPE_PRICE_ID_STARTER or STRIPE_PRICE_ID,
    "pro": STRIPE_PRICE_ID_PRO,
    "business": STRIPE_PRICE_ID_BUSINESS,
}

# Map pack credits to Stripe price IDs
PACK_PRICE_IDS = {
    100: STRIPE_PRICE_ID_PACK_100,
    500: STRIPE_PRICE_ID_PACK_500,
    1500: STRIPE_PRICE_ID_PACK_1500,
    5000: STRIPE_PRICE_ID_PACK_5000,
}


async def handle_credits(db: BotDatabase, sender: str, text: str):
    """Show credit balance and usage breakdown with tiered costs."""
    cm = CreditManager(db)
    summary = cm.get_usage_summary(sender)
    user = db.get_user(sender)
    is_sub = user and user.get("subscription_active")

    if is_sub:
        plan_label = "Subscriber"
    else:
        plan_label = f"Free ({FREE_SIGNUP_CREDITS} signup credits)"

    await wa.send_text(
        sender,
        f"*Credit Balance*\n\n"
        f"Plan: {plan_label}\n"
        f"Remaining: *{summary['credits_remaining']}*\n"
        f"Used this period: {summary['credits_used']}\n\n"
        f"*Credit Costs:*\n"
        f"  Text post: {ACTION_COSTS['text_post']} credits\n"
        f"  Stock image post: {ACTION_COSTS['stock_image_post']} credits\n"
        f"  Own media post: {ACTION_COSTS['own_media_post']} credits\n"
        f"  AI image post: {ACTION_COSTS['ai_image_post']} credits\n"
        f"  AI video post: {ACTION_COSTS['ai_video_post']} credits\n"
        f"  Comment reply: {ACTION_COSTS['comment_reply']} credits\n\n"
        + ("Credits reset on your next billing cycle." if is_sub else
           "Want more credits?\n"
           "  *subscribe* — Monthly plans from $14.99\n"
           "  *buy* — One-time credit packs from $4.99\n"
           "  *referral* — Earn 50 credits per friend"),
    )


async def handle_subscribe(db: BotDatabase, sender: str, text: str):
    """Show subscription plans and let user choose."""
    user = db.get_user(sender)

    if user and user.get("subscription_active"):
        cm = CreditManager(db)
        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"You already have an active subscription!\n"
            f"Credits remaining: *{balance}*\n\n"
            f"Send *cancel* to manage your subscription.",
        )
        return

    if not STRIPE_SECRET_KEY:
        await wa.send_text(sender, "Payment system is not configured yet. Please contact support.")
        return

    # Show plan options
    rows = []
    for key in ("starter", "pro", "business"):
        plan = PLANS[key]
        price_id = PLAN_PRICE_IDS.get(key, "")
        if price_id:
            rows.append({
                "id": f"plan_{key}",
                "title": f"{plan['name']} — ${plan['price_usd']}/mo",
                "description": f"{plan['credits']:,} credits/month",
            })

    if rows:
        await wa.send_interactive_list(
            sender,
            "*Choose a Subscription Plan*\n\n"
            f"*Starter* — ${PLANS['starter']['price_usd']}/mo → {PLANS['starter']['credits']:,} credits\n"
            f"*Pro* — ${PLANS['pro']['price_usd']}/mo → {PLANS['pro']['credits']:,} credits\n"
            f"*Business* — ${PLANS['business']['price_usd']}/mo → {PLANS['business']['credits']:,} credits\n\n"
            "Prices shown in USD. Local currency (SGD/MYR) shown at checkout.\n"
            "Have a promo code? Enter it at checkout.",
            "Choose Plan",
            [{"title": "Plans", "rows": rows}],
        )
        db.set_conversation_state(sender, ConversationState.AWAITING_PACK_CHOICE, {"type": "plan"})
    else:
        # Fallback: single plan (legacy)
        await _create_checkout(sender, STRIPE_PRICE_ID, "subscription")


async def handle_buy_credits(db: BotDatabase, sender: str, text: str):
    """Show credit pack options for one-time purchase."""
    if not STRIPE_SECRET_KEY:
        await wa.send_text(sender, "Payment system is not configured yet. Please contact support.")
        return

    rows = []
    for pack in CREDIT_PACKS:
        price_id = PACK_PRICE_IDS.get(pack["credits"], "")
        if price_id:
            rows.append({
                "id": f"pack_{pack['credits']}",
                "title": f"{pack['label']} — ${pack['price_usd']}",
                "description": f"${pack['price_usd']:.2f} one-time",
            })

    if not rows:
        await wa.send_text(sender, "Credit packs are not configured yet. Please contact support.")
        return

    await wa.send_interactive_list(
        sender,
        "*Credit Packs (One-Time Purchase)*\n\n"
        "Top up your credits instantly:\n"
        f"  100 credits — $4.99\n"
        f"  500 credits — $24.99\n"
        f"  1,500 credits — $74.99\n"
        f"  5,000 credits — $200.00\n\n"
        "Prices in USD. Local currency at checkout.",
        "Choose Pack",
        [{"title": "Credit Packs", "rows": rows}],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_PACK_CHOICE, {"type": "pack"})


async def handle_pack_step(db: BotDatabase, sender: str, text: str,
                           state: ConversationState, data: dict, **kwargs):
    """Handle plan/pack selection from interactive list."""
    choice = text.lower().strip()
    choice_type = data.get("type", "pack")

    db.clear_conversation_state(sender)

    if choice_type == "plan":
        # Plan subscription selection
        plan_key = choice.replace("plan_", "")
        if plan_key not in PLAN_PRICE_IDS:
            await wa.send_text(sender, "Please choose a valid plan.")
            return
        price_id = PLAN_PRICE_IDS[plan_key]
        if not price_id:
            await wa.send_text(sender, f"The {plan_key} plan is not configured yet.")
            return
        await _create_checkout(sender, price_id, "subscription", plan_key)

    elif choice_type == "pack":
        # Credit pack selection
        pack_credits_str = choice.replace("pack_", "")
        try:
            pack_credits = int(pack_credits_str)
        except ValueError:
            await wa.send_text(sender, "Please choose a valid credit pack.")
            return
        price_id = PACK_PRICE_IDS.get(pack_credits, "")
        if not price_id:
            await wa.send_text(sender, "That pack is not configured yet.")
            return
        await _create_checkout(sender, price_id, "payment", f"pack_{pack_credits}")


async def _create_checkout(sender: str, price_id: str, mode: str, label: str = ""):
    """Create a Stripe Checkout session with Adaptive Pricing enabled."""
    try:
        # Use PUBLIC_BASE_URL (gateway domain) — payment routes are on the gateway
        base_url = PUBLIC_BASE_URL or PAYMENT_SERVER_URL
        session_kwargs = {
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": mode,
            "success_url": f"{base_url}/payment/success",
            "cancel_url": f"{base_url}/payment/cancel",
            "client_reference_id": sender,
            "metadata": {"phone_number_id": sender, "purchase_type": label},
            "allow_promotion_codes": True,
            # Stripe Adaptive Pricing: auto-converts to local currency (SGD/MYR)
            # Customer sees prices in their local currency; FX fee (2-4%) included
            "adaptive_pricing": {"enabled": True},
        }

        session = stripe.checkout.Session.create(**session_kwargs)

        await wa.send_text(
            sender,
            f"Complete your purchase here:\n{session.url}\n\n"
            "You'll see the price in your local currency at checkout.\n"
            "Have a promo code? Enter it on the checkout page.",
        )
    except Exception as e:
        logger.error("Stripe checkout error for %s: %s", sender, e)
        await wa.send_text(sender, "Something went wrong creating your checkout. Please try again.")


async def handle_cancel(db: BotDatabase, sender: str, text: str):
    """Open Stripe Customer Portal for subscription management."""
    user = db.get_user(sender)

    if not user or not user.get("subscription_active"):
        await wa.send_text(sender, "You don't have an active subscription.\nSend *subscribe* to upgrade.")
        return

    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        await wa.send_text(sender, "No Stripe customer found. Please contact support.")
        return

    try:
        sub_id = user.get("stripe_subscription_id")
        flow_data = None
        if sub_id:
            flow_data = {
                "type": "subscription_cancel",
                "subscription_cancel": {"subscription": sub_id},
            }

        base_url = PUBLIC_BASE_URL or PAYMENT_SERVER_URL
        portal_kwargs = {
            "customer": customer_id,
            "return_url": f"{base_url}/payment/portal-return",
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
