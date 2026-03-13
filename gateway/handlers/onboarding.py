"""
Onboarding and help handlers.
Flow: Welcome → Industry → Offerings → Goals → Tone → Platform → Promo Code (optional)
Freemium: 30 free credits on signup. Promo/referral codes grant bonus credits.
"""

import logging
import re
import string
import uuid

from shared.database import BotDatabase
from shared.config import FREE_SIGNUP_CREDITS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# English validation — rejects inputs that are clearly not English
# ---------------------------------------------------------------------------
# We allow ASCII letters, digits, common punctuation, and spaces.
# If more than 40% of alpha characters are non-ASCII, we reject.
_ASCII_LETTERS = set(string.ascii_letters)


def _is_valid_english(text: str) -> bool:
    """Return True if the text looks like valid English input."""
    if not text or len(text.strip()) < 2:
        return False
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return True  # numbers/punctuation only — allow
    ascii_ratio = sum(1 for c in alpha_chars if c in _ASCII_LETTERS) / len(alpha_chars)
    return ascii_ratio >= 0.6


ENGLISH_ERROR = "Please reply in English. Your input doesn't look like valid English text — try again."


def _generate_referral_code() -> str:
    """Generate a short unique referral code like 'REF-A1B2C3'."""
    return "REF-" + uuid.uuid4().hex[:6].upper()


# ===========================================================================
# START / HELP
# ===========================================================================

async def handle_start(db: BotDatabase, sender: str, text: str):
    """Welcome message → begin onboarding or greet returning user."""
    profile = db.get_user_profile(sender)
    if profile:
        await wa.send_text(
            sender,
            "Welcome back! You're already set up.\n\n"
            "Send *help* to see what I can do, or *credits* to check your balance.",
        )
        return

    await wa.send_text(
        sender,
        "Welcome to the *AI Automation Service*!\n\n"
        "I help businesses automate their social media with AI-powered posts "
        "and comment replies on *Facebook* and *Instagram* — all through the "
        "official Meta Graph API. Safe, reliable, zero risk of account bans.\n\n"
        "Let's set up your profile so I can create content tailored to your business.\n\n"
        "What *industry* is your business in?\n"
        "_e.g. E-commerce, Tech, F&B, Healthcare, Real Estate, Marketing_",
    )
    db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, {})


async def handle_help(db: BotDatabase, sender: str, text: str):
    await wa.send_text(
        sender,
        "*Available Commands:*\n\n"
        "*Content*\n"
        "  post — Create and publish a post (5 credits)\n"
        "  schedule — Schedule a post for later (5 credits)\n"
        "  reply — Auto-reply to comments (3 credits)\n\n"
        "*Account*\n"
        "  credits — Check credit balance\n"
        "  stats — View automation statistics\n"
        "  setup — Connect Facebook / Instagram\n"
        "  settings — View/update your profile\n"
        "  referral — Get your referral code\n\n"
        "*Subscription*\n"
        "  subscribe — Upgrade for 500 credits/month\n"
        "  cancel — Cancel subscription\n\n"
        "Send *cancel* at any time to exit a multi-step flow.",
    )


# ===========================================================================
# ONBOARDING STEPS
# ===========================================================================

async def handle_onboarding_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    # --- INDUSTRY ---
    if state == ConversationState.ONBOARDING_INDUSTRY:
        if not _is_valid_english(text):
            await wa.send_text(sender, ENGLISH_ERROR)
            return
        data["industry"] = [t.strip() for t in text.split(",") if t.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
        await wa.send_text(
            sender,
            "Great! What *products or services* does your business offer? (comma-separated)\n"
            "_e.g. Web Development, Digital Marketing, Personal Training, Coffee & Pastries_",
        )

    # --- OFFERINGS ---
    elif state == ConversationState.ONBOARDING_OFFERINGS:
        if not _is_valid_english(text):
            await wa.send_text(sender, ENGLISH_ERROR)
            return
        data["offerings"] = [t.strip() for t in text.split(",") if t.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
        await wa.send_text(
            sender,
            "What do you want your social media to *achieve for your business*? (comma-separated)\n"
            "_e.g. Get more customers, Build brand awareness, Drive website traffic, Grow community_",
        )

    # --- GOALS ---
    elif state == ConversationState.ONBOARDING_GOALS:
        if not _is_valid_english(text):
            await wa.send_text(sender, ENGLISH_ERROR)
            return
        data["business_goals"] = [t.strip() for t in text.split(",") if t.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_TONE, data)
        await wa.send_interactive_buttons(
            sender,
            "What *tone* should I use for your content?",
            [
                {"id": "professional", "title": "Professional"},
                {"id": "casual", "title": "Casual & Friendly"},
                {"id": "thought_leader", "title": "Thought Leader"},
            ],
        )

    # --- TONE ---
    elif state == ConversationState.ONBOARDING_TONE:
        data["tone"] = [text.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_PLATFORM, data)
        await wa.send_interactive_buttons(
            sender,
            "Which platform would you like to use primarily?",
            [
                {"id": "instagram", "title": "Instagram"},
                {"id": "facebook", "title": "Facebook"},
                {"id": "both", "title": "Both"},
            ],
        )

    # --- PLATFORM ---
    elif state == ConversationState.ONBOARDING_PLATFORM:
        platform = text.lower()
        if platform not in ("instagram", "facebook", "both"):
            await wa.send_text(sender, "Please choose Instagram, Facebook, or Both.")
            return
        data["platform"] = platform

        # Save profile
        db.save_user_profile(sender, data)

        # Generate referral code for this user
        referral_code = _generate_referral_code()
        db.set_referral_code(sender, referral_code)

        # Grant free signup credits
        db.grant_credits(sender, FREE_SIGNUP_CREDITS, reason="signup_bonus")

        # Ask for promo/referral code
        db.set_conversation_state(sender, ConversationState.AWAITING_PROMO_CODE, data)
        await wa.send_text(
            sender,
            f"Profile saved! You've received *{FREE_SIGNUP_CREDITS} free credits* to get started.\n\n"
            "Do you have a *promo code* or *referral code*? Enter it now for bonus credits.\n\n"
            "Or type *skip* to continue.",
        )

    else:
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "Something went wrong. Send *start* to begin again.")


# ===========================================================================
# PROMO / REFERRAL CODE
# ===========================================================================

async def handle_promo_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    """Handle promo/referral code entry after onboarding."""
    code = text.strip().upper()

    if code in ("SKIP", "NO", "NONE", ""):
        db.clear_conversation_state(sender)
        await _send_onboarding_complete(db, sender)
        return

    # Check if it's a referral code (REF-XXXXXX)
    if code.startswith("REF-"):
        referrer = db.find_user_by_referral_code(code)
        if not referrer:
            await wa.send_text(sender, "That referral code isn't valid. Try again or type *skip*.")
            return
        if referrer["phone_number_id"] == sender:
            await wa.send_text(sender, "You can't use your own referral code! Try a different code or type *skip*.")
            return

        # Check if already referred
        if db.has_been_referred(sender):
            await wa.send_text(sender, "You've already used a referral code. Type *skip* to continue.")
            return

        # Grant credits to both
        db.grant_credits(sender, 50, reason="referral_bonus")
        db.grant_credits(referrer["phone_number_id"], 50, reason="referral_reward")
        db.record_referral(referrer["phone_number_id"], sender)
        db.set_referred_by(sender, referrer["phone_number_id"])

        # Notify referrer
        await wa.send_text(
            referrer["phone_number_id"],
            f"Someone used your referral code! You've earned *50 bonus credits*.",
        )

        db.clear_conversation_state(sender)
        await wa.send_text(sender, "Referral code applied! *50 bonus credits* added to your account.")
        await _send_onboarding_complete(db, sender)
        return

    # Check if it's a promo code
    promo = db.validate_promo_code(code)
    if not promo:
        await wa.send_text(sender, "That code isn't valid or has expired. Try again or type *skip*.")
        return

    # Check if user already used this promo code
    if db.has_used_promo(sender, code):
        await wa.send_text(sender, "You've already used this promo code. Try a different one or type *skip*.")
        return

    credits_granted = promo.get("credits_granted", 50)
    db.grant_credits(sender, credits_granted, reason=f"promo_{code}")
    db.use_promo_code(code)
    db.record_promo_usage(sender, code, credits_granted)

    db.clear_conversation_state(sender)
    await wa.send_text(sender, f"Promo code *{code}* applied! *{credits_granted} bonus credits* added.")
    await _send_onboarding_complete(db, sender)


async def _send_onboarding_complete(db: BotDatabase, sender: str):
    """Send the post-onboarding welcome with next steps."""
    user = db.get_user(sender)
    balance = user["credits_remaining"] if user else FREE_SIGNUP_CREDITS
    referral_code = user.get("referral_code", "") if user else ""

    await wa.send_text(
        sender,
        f"You're all set! Your credit balance: *{balance} credits*\n\n"
        "*What you can do:*\n"
        "  *post* — AI-powered posts to Facebook/Instagram (5 credits)\n"
        "  *reply* — Auto-reply to comments (3 credits)\n"
        "  *schedule* — Schedule posts for later (5 credits)\n\n"
        "*Next steps:*\n"
        "1. Send *setup* to connect your Facebook or Instagram\n"
        "2. Send *post* to create your first AI post\n"
        "3. Send *subscribe* to upgrade to 500 credits/month\n\n"
        f"Your referral code: *{referral_code}*\n"
        "Share it with friends — you both get *50 bonus credits*!\n\n"
        "Send *help* anytime to see all commands.",
    )
