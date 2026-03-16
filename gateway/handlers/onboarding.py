"""
Onboarding and help handlers.
Flow: Welcome → Industry → Offerings → Goals → Tone → Content Style → Visual Style → Platform → Promo Code

Uses ReAct-style input validation (Thought → Action → Observation):
  - Each free-text input is validated by the LLM for relevance and clarity
  - Invalid inputs get a helpful clarification prompt instead of a generic error

Freemium: 30 free credits on signup. Promo/referral codes grant bonus credits.
"""

import logging
import uuid

from shared.database import BotDatabase
from shared.config import FREE_SIGNUP_CREDITS
from shared.credits import ACTION_COSTS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from services.ai.input_validator import validate_input

logger = logging.getLogger(__name__)


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
        "I help businesses automate their social media with AI-powered posts, "
        "images, videos, and comment replies on *Facebook* and *Instagram*.\n\n"
        "Let's set up your profile so I can create content tailored to your business.\n\n"
        "What *industry* is your business in?\n"
        "_e.g. E-commerce, Tech, F&B, Healthcare, Real Estate, Marketing_",
    )
    db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, {})


async def handle_help(db: BotDatabase, sender: str, text: str):
    await wa.send_text(
        sender,
        "*Available Commands:*\n\n"
        "*Content Creation*\n"
        f"  post — Create a post ({ACTION_COSTS['text_post']}-{ACTION_COSTS['ai_video_post']} credits)\n"
        f"  auto — Auto-generate a week of posts\n"
        f"  schedule — Schedule a post for later\n"
        f"  reply — Auto-reply to comments ({ACTION_COSTS['comment_reply']} credits)\n\n"
        "*Quick post:* Just send a photo or video!\n\n"
        "*Credit Costs:*\n"
        f"  Text post: {ACTION_COSTS['text_post']} | Stock image: {ACTION_COSTS['stock_image_post']}\n"
        f"  Own media: {ACTION_COSTS['own_media_post']} | AI image: {ACTION_COSTS['ai_image_post']}\n"
        f"  AI video: {ACTION_COSTS['ai_video_post']} | Reply: {ACTION_COSTS['comment_reply']}\n\n"
        "*Account*\n"
        "  credits — Check balance | buy — Buy credit packs\n"
        "  stats — View stats | setup — Connect platforms\n"
        "  settings — Profile | referral — Referral code\n\n"
        "*Subscription*\n"
        "  subscribe — View plans | cancel — Cancel sub\n\n"
        "Send *cancel* at any time to exit a flow.",
    )


# ===========================================================================
# ReAct VALIDATION HELPER
# ===========================================================================

async def _validate_and_respond(sender: str, text: str, step: str):
    result = validate_input(text, step)
    if result["action"] == "accept":
        return result
    msg = result.get("message") or "I didn't quite understand that. Could you try again?"
    await wa.send_text(sender, msg)
    return None


# ===========================================================================
# ONBOARDING STEPS
# ===========================================================================

async def handle_onboarding_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    # --- INDUSTRY ---
    if state == ConversationState.ONBOARDING_INDUSTRY:
        v = await _validate_and_respond(sender, text, "industry")
        if not v:
            return
        cleaned = v.get("cleaned") or text.strip()
        data["industry"] = [t.strip() for t in cleaned.split(",") if t.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
        await wa.send_text(
            sender,
            "Great! What *products or services* does your business offer? (comma-separated)\n"
            "_e.g. Web Development, Digital Marketing, Personal Training, Coffee & Pastries_",
        )

    # --- OFFERINGS ---
    elif state == ConversationState.ONBOARDING_OFFERINGS:
        v = await _validate_and_respond(sender, text, "offerings")
        if not v:
            return
        cleaned = v.get("cleaned") or text.strip()
        data["offerings"] = [t.strip() for t in cleaned.split(",") if t.strip()]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
        await wa.send_text(
            sender,
            "What do you want your social media to *achieve*? (comma-separated)\n"
            "_e.g. Get more customers, Build brand awareness, Drive traffic, Grow community_",
        )

    # --- GOALS ---
    elif state == ConversationState.ONBOARDING_GOALS:
        v = await _validate_and_respond(sender, text, "goals")
        if not v:
            return
        cleaned = v.get("cleaned") or text.strip()
        data["business_goals"] = [t.strip() for t in cleaned.split(",") if t.strip()]
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
        db.set_conversation_state(sender, ConversationState.ONBOARDING_CONTENT_STYLE, data)
        await wa.send_interactive_list(
            sender,
            "What *type of content* works best for your brand?\n\n"
            "This helps the AI generate posts that match your style.",
            "Choose Style",
            [{
                "title": "Content Styles",
                "rows": [
                    {"id": "humorous", "title": "Humorous / Memes", "description": "Funny, relatable, meme-worthy content"},
                    {"id": "educational", "title": "Educational / Tips", "description": "Informative how-tos and industry tips"},
                    {"id": "inspirational", "title": "Inspirational", "description": "Motivational and uplifting content"},
                    {"id": "behind_the_scenes", "title": "Behind the Scenes", "description": "Authentic day-to-day business life"},
                    {"id": "product_showcase", "title": "Product Showcase", "description": "Highlight products and services"},
                    {"id": "mixed", "title": "Mix of Everything", "description": "Varied content for broader appeal"},
                ],
            }],
        )

    # --- CONTENT STYLE ---
    elif state == ConversationState.ONBOARDING_CONTENT_STYLE:
        valid_styles = ("humorous", "educational", "inspirational", "behind_the_scenes", "product_showcase", "mixed")
        style = text.lower().strip().replace(" ", "_")
        if style not in valid_styles:
            await wa.send_text(sender, "Please choose one of the content styles from the list above.")
            return
        data["content_style"] = style
        db.set_conversation_state(sender, ConversationState.ONBOARDING_VISUAL_STYLE, data)
        await wa.send_interactive_list(
            sender,
            "What *visual style* should AI-generated images and videos have?",
            "Choose Visual",
            [{
                "title": "Visual Styles",
                "rows": [
                    {"id": "cartoon", "title": "Cartoon / Illustrated", "description": "Fun, colorful illustrations and vector art"},
                    {"id": "minimalist", "title": "Clean & Minimalist", "description": "Modern, white space, simple design"},
                    {"id": "bold_colorful", "title": "Bold & Colorful", "description": "Vibrant colors, high contrast graphics"},
                    {"id": "photorealistic", "title": "Photorealistic", "description": "Realistic photos, natural lighting"},
                    {"id": "meme_style", "title": "Meme Style", "description": "Internet humor, relatable format"},
                ],
            }],
        )

    # --- VISUAL STYLE ---
    elif state == ConversationState.ONBOARDING_VISUAL_STYLE:
        valid_visuals = ("cartoon", "minimalist", "bold_colorful", "photorealistic", "meme_style")
        visual = text.lower().strip().replace(" ", "_")
        if visual not in valid_visuals:
            await wa.send_text(sender, "Please choose one of the visual styles from the list above.")
            return
        data["visual_style"] = visual
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

        # Save profile (includes content_style and visual_style)
        db.save_user_profile(sender, data)

        # Generate referral code
        referral_code = _generate_referral_code()
        db.set_referral_code(sender, referral_code)

        # Note: free signup credits (30) are already granted in create_user()

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

    # Referral code (REF-XXXXXX)
    if code.startswith("REF-"):
        referrer = db.find_user_by_referral_code(code)
        if not referrer:
            await wa.send_text(sender, "That referral code isn't valid. Try again or type *skip*.")
            return
        if referrer["phone_number_id"] == sender:
            await wa.send_text(sender, "You can't use your own referral code! Try a different code or type *skip*.")
            return
        if db.has_been_referred(sender):
            await wa.send_text(sender, "You've already used a referral code. Type *skip* to continue.")
            return

        db.grant_credits(sender, 50, reason="referral_bonus")
        db.grant_credits(referrer["phone_number_id"], 50, reason="referral_reward")
        db.record_referral(referrer["phone_number_id"], sender)
        db.set_referred_by(sender, referrer["phone_number_id"])

        await wa.send_text(
            referrer["phone_number_id"],
            "Someone used your referral code! You've earned *50 bonus credits*.",
        )

        db.clear_conversation_state(sender)
        await wa.send_text(sender, "Referral code applied! *50 bonus credits* added to your account.")
        await _send_onboarding_complete(db, sender)
        return

    # Promo code
    promo = db.validate_promo_code(code)
    if not promo:
        await wa.send_text(sender, "That code isn't valid or has expired. Try again or type *skip*.")
        return

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
        f"You're all set! Credit balance: *{balance} credits*\n\n"
        "*What you can do:*\n"
        f"  *post* — Create posts with AI images/videos\n"
        f"  *auto* — Auto-generate a week of posts\n"
        f"  *reply* — Auto-reply to comments\n\n"
        "*Credit costs:*\n"
        f"  Text: {ACTION_COSTS['text_post']} | Image: {ACTION_COSTS['ai_image_post']} | Video: {ACTION_COSTS['ai_video_post']} | Reply: {ACTION_COSTS['comment_reply']}\n\n"
        "*Next steps:*\n"
        "1. Send *setup* to connect Facebook/Instagram\n"
        "2. Send *post* to create your first post\n"
        "3. Send *subscribe* to view plans\n\n"
        f"Your referral code: *{referral_code}*\n"
        "Share it — you both get *50 bonus credits*!\n\n"
        "Send *help* anytime to see all commands.",
    )
