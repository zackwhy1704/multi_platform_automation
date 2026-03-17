"""
Onboarding and help handlers.
Flow: Welcome → Industry → Offerings → Goals → Tone → Content Style → Visual Style → Platform → Promo Code

All steps use WhatsApp interactive UI (buttons/lists) — no free-text entry except
for custom industry/offerings when user picks "Other".
"""

import logging
import uuid

from shared.database import BotDatabase
from shared.config import FREE_SIGNUP_CREDITS
from shared.credits import ACTION_COSTS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)


def _generate_referral_code() -> str:
    return "REF-" + uuid.uuid4().hex[:6].upper()


# ===========================================================================
# START / HELP
# ===========================================================================

async def handle_start(db: BotDatabase, sender: str, text: str):
    profile = db.get_user_profile(sender)
    if profile:
        await wa.send_interactive_buttons(
            sender,
            "Welcome back! You're already set up. What would you like to do?",
            [
                {"id": "post", "title": "Create a Post"},
                {"id": "credits", "title": "Check Credits"},
                {"id": "setup", "title": "Connect Account"},
            ],
        )
        return

    await wa.send_text(
        sender,
        "👋 Welcome to *Catalyx AI*!\n\n"
        "I help businesses automate social media with AI-powered posts, "
        "images, and comment replies on *Facebook* and *Instagram*.\n\n"
        "Let's set up your profile in a few quick steps. "
        "You'll receive *30 free credits* to get started.\n\n"
        "_Takes about 2 minutes_ ⚡",
    )
    await _send_industry_picker(sender)
    db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, {})


async def handle_help(db: BotDatabase, sender: str, text: str):
    await wa.send_text(
        sender,
        "*Available Commands*\n\n"
        "📝 *Content*\n"
        f"  post — Create a post ({ACTION_COSTS['text_post']}–{ACTION_COSTS['ai_video_post']} credits)\n"
        "  auto — Auto-generate a week of posts\n"
        "  schedule — Schedule a post for later\n"
        f"  reply — Auto-reply to comments ({ACTION_COSTS['comment_reply']} credits)\n\n"
        "💳 *Credits & Plans*\n"
        "  credits — Check balance\n"
        "  buy — Buy credit packs\n"
        "  subscribe — View subscription plans\n"
        "  cancel — Cancel subscription\n\n"
        "⚙️ *Account*\n"
        "  setup — Connect Facebook / Instagram\n"
        "  settings — View / update profile\n"
        "  disconnect — Switch account\n"
        "  referral — Get referral code\n"
        "  stats — View your stats\n\n"
        "📷 *Quick post:* Just send a photo or video!\n\n"
        "_Send_ *cancel* _at any time to exit a flow._",
    )


# ===========================================================================
# INDUSTRY PICKER
# ===========================================================================

async def _send_industry_picker(sender: str):
    await wa.send_interactive_list(
        sender,
        "Step 1 of 6 — *What industry is your business in?*\n\n"
        "Choose the closest match from the list:",
        "Select Industry",
        [{
            "title": "Industries",
            "rows": [
                {"id": "ecommerce",     "title": "E-commerce / Retail",      "description": "Online or physical product sales"},
                {"id": "fnb",           "title": "Food & Beverage",           "description": "Restaurant, café, catering, F&B"},
                {"id": "tech",          "title": "Technology / SaaS",         "description": "Software, apps, tech services"},
                {"id": "health",        "title": "Health & Fitness",          "description": "Gym, nutrition, wellness, medical"},
                {"id": "realestate",    "title": "Real Estate",               "description": "Property sales, rentals, development"},
                {"id": "beauty",        "title": "Beauty & Wellness",         "description": "Salon, spa, skincare, aesthetics"},
                {"id": "education",     "title": "Education / Coaching",      "description": "Tutoring, courses, training, coaching"},
                {"id": "marketing",     "title": "Marketing / Agency",        "description": "Creative, digital, media agency"},
                {"id": "finance",       "title": "Finance / Insurance",       "description": "Financial planning, insurance, banking"},
                {"id": "other_industry","title": "Other (type your own)",     "description": "Not on the list? Type it below"},
            ],
        }],
    )


# ===========================================================================
# OFFERINGS PICKER
# ===========================================================================

async def _send_offerings_picker(sender: str):
    await wa.send_interactive_list(
        sender,
        "Step 2 of 6 — *What does your business offer?*\n\n"
        "Choose the best match:",
        "Select Offering",
        [{
            "title": "Business Offerings",
            "rows": [
                {"id": "physical_products",  "title": "Physical Products",      "description": "Goods, merchandise, inventory"},
                {"id": "digital_products",   "title": "Digital Products",       "description": "Downloads, templates, software"},
                {"id": "professional_svcs",  "title": "Professional Services",  "description": "Consulting, legal, accounting"},
                {"id": "food_drinks",        "title": "Food & Drinks",          "description": "Meals, beverages, catering"},
                {"id": "personal_training",  "title": "Personal Training",      "description": "Fitness coaching, PT sessions"},
                {"id": "creative_svcs",      "title": "Creative Services",      "description": "Design, photography, video"},
                {"id": "online_courses",     "title": "Online Courses",         "description": "eLearning, workshops, webinars"},
                {"id": "events",             "title": "Events & Experiences",   "description": "Workshops, venues, ticketed events"},
                {"id": "subscriptions",      "title": "Subscriptions / SaaS",   "description": "Recurring plans, memberships"},
                {"id": "other_offering",     "title": "Other (type your own)",  "description": "Not on the list? Type it below"},
            ],
        }],
    )


# ===========================================================================
# GOALS PICKER
# ===========================================================================

async def _send_goals_picker(sender: str):
    await wa.send_interactive_list(
        sender,
        "Step 3 of 6 — *What is your main social media goal?*\n\n"
        "Choose the most important one:",
        "Select Goal",
        [{
            "title": "Business Goals",
            "rows": [
                {"id": "get_customers",  "title": "Get More Customers",      "description": "Drive leads, enquiries & sales"},
                {"id": "brand_awareness","title": "Build Brand Awareness",   "description": "Get known, grow visibility"},
                {"id": "drive_traffic",  "title": "Drive Website Traffic",   "description": "Send followers to your site"},
                {"id": "grow_following", "title": "Grow Social Following",   "description": "Increase followers & engagement"},
                {"id": "product_sales",  "title": "Promote Products / Sales","description": "Launch products, run promotions"},
                {"id": "educate",        "title": "Educate My Audience",     "description": "Share tips, news, how-tos"},
                {"id": "community",      "title": "Build Community",         "description": "Loyal fans, tribe, repeat buyers"},
            ],
        }],
    )


# ===========================================================================
# LABEL MAPS (id → human-readable label)
# ===========================================================================

INDUSTRY_LABELS = {
    "ecommerce":    "E-commerce / Retail",
    "fnb":          "Food & Beverage",
    "tech":         "Technology / SaaS",
    "health":       "Health & Fitness",
    "realestate":   "Real Estate",
    "beauty":       "Beauty & Wellness",
    "education":    "Education / Coaching",
    "marketing":    "Marketing / Agency",
    "finance":      "Finance / Insurance",
}

OFFERING_LABELS = {
    "physical_products":  "Physical Products",
    "digital_products":   "Digital Products",
    "professional_svcs":  "Professional Services",
    "food_drinks":        "Food & Drinks",
    "personal_training":  "Personal Training",
    "creative_svcs":      "Creative Services",
    "online_courses":     "Online Courses",
    "events":             "Events & Experiences",
    "subscriptions":      "Subscriptions / SaaS",
}

GOAL_LABELS = {
    "get_customers":   "Get More Customers",
    "brand_awareness": "Build Brand Awareness",
    "drive_traffic":   "Drive Website Traffic",
    "grow_following":  "Grow Social Following",
    "product_sales":   "Promote Products / Sales",
    "educate":         "Educate My Audience",
    "community":       "Build Community",
}


# ===========================================================================
# ONBOARDING STEPS
# ===========================================================================

async def handle_onboarding_step(
    db: BotDatabase, sender: str, text: str,
    state: ConversationState, data: dict
):
    text = text.strip()

    # ── INDUSTRY ──────────────────────────────────────────────────────────
    if state == ConversationState.ONBOARDING_INDUSTRY:

        # Waiting for custom text after picking "Other"
        if data.get("awaiting_custom") == "industry":
            if len(text) < 2:
                await wa.send_text(sender, "Please type your industry (at least 2 characters).")
                return
            data["industry"] = [text]
            data.pop("awaiting_custom", None)
            db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
            await _send_offerings_picker(sender)
            return

        if text == "other_industry":
            data["awaiting_custom"] = "industry"
            db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, data)
            await wa.send_text(sender, "Type your industry below:")
            return

        label = INDUSTRY_LABELS.get(text)
        if not label:
            await _send_industry_picker(sender)
            return

        data["industry"] = [label]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
        await _send_offerings_picker(sender)

    # ── OFFERINGS ─────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_OFFERINGS:

        if data.get("awaiting_custom") == "offering":
            if len(text) < 2:
                await wa.send_text(sender, "Please type your offering (at least 2 characters).")
                return
            data["offerings"] = [text]
            data.pop("awaiting_custom", None)
            db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
            await _send_goals_picker(sender)
            return

        if text == "other_offering":
            data["awaiting_custom"] = "offering"
            db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
            await wa.send_text(sender, "Type your product or service below:")
            return

        label = OFFERING_LABELS.get(text)
        if not label:
            await _send_offerings_picker(sender)
            return

        data["offerings"] = [label]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
        await _send_goals_picker(sender)

    # ── GOALS ─────────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_GOALS:

        label = GOAL_LABELS.get(text)
        if not label:
            await _send_goals_picker(sender)
            return

        data["business_goals"] = [label]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_TONE, data)
        await wa.send_interactive_buttons(
            sender,
            "Step 4 of 6 — *What tone should I use for your content?*",
            [
                {"id": "professional",  "title": "Professional"},
                {"id": "casual",        "title": "Casual & Friendly"},
                {"id": "thought_leader","title": "Thought Leader"},
            ],
        )

    # ── TONE ──────────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_TONE:
        valid = {"professional": "Professional", "casual": "Casual & Friendly", "thought_leader": "Thought Leader"}
        if text not in valid:
            await wa.send_interactive_buttons(
                sender,
                "Please choose a tone:",
                [
                    {"id": "professional",  "title": "Professional"},
                    {"id": "casual",        "title": "Casual & Friendly"},
                    {"id": "thought_leader","title": "Thought Leader"},
                ],
            )
            return
        data["tone"] = [valid[text]]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_CONTENT_STYLE, data)
        await wa.send_interactive_list(
            sender,
            "Step 5 of 6 — *What content style fits your brand?*\n\n"
            "This shapes how the AI writes your posts:",
            "Choose Style",
            [{
                "title": "Content Styles",
                "rows": [
                    {"id": "humorous",          "title": "Humorous / Memes",     "description": "Funny, relatable, meme-worthy"},
                    {"id": "educational",       "title": "Educational / Tips",   "description": "Informative how-tos, industry tips"},
                    {"id": "inspirational",     "title": "Inspirational",        "description": "Motivational and uplifting"},
                    {"id": "behind_the_scenes", "title": "Behind the Scenes",    "description": "Authentic day-to-day business life"},
                    {"id": "product_showcase",  "title": "Product Showcase",     "description": "Highlight products and services"},
                    {"id": "mixed",             "title": "Mix of Everything",    "description": "Varied for broader appeal"},
                ],
            }],
        )

    # ── CONTENT STYLE ─────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_CONTENT_STYLE:
        valid = ("humorous", "educational", "inspirational", "behind_the_scenes", "product_showcase", "mixed")
        if text not in valid:
            await wa.send_text(sender, "Please choose a style from the list above.")
            return
        data["content_style"] = text
        db.set_conversation_state(sender, ConversationState.ONBOARDING_VISUAL_STYLE, data)
        await wa.send_interactive_list(
            sender,
            "Step 6 of 6 — *What visual style for AI-generated images?*",
            "Choose Visual",
            [{
                "title": "Visual Styles",
                "rows": [
                    {"id": "cartoon",        "title": "Cartoon / Illustrated", "description": "Fun, colourful illustrations"},
                    {"id": "minimalist",     "title": "Clean & Minimalist",    "description": "Modern, white space, simple"},
                    {"id": "bold_colorful",  "title": "Bold & Colourful",      "description": "Vibrant, high-contrast graphics"},
                    {"id": "photorealistic", "title": "Photorealistic",        "description": "Realistic photos, natural lighting"},
                    {"id": "meme_style",     "title": "Meme Style",            "description": "Internet humour, relatable format"},
                ],
            }],
        )

    # ── VISUAL STYLE ──────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_VISUAL_STYLE:
        valid = ("cartoon", "minimalist", "bold_colorful", "photorealistic", "meme_style")
        if text not in valid:
            await wa.send_text(sender, "Please choose a visual style from the list above.")
            return
        data["visual_style"] = text
        db.set_conversation_state(sender, ConversationState.ONBOARDING_PLATFORM, data)
        await wa.send_interactive_buttons(
            sender,
            "Almost done! 🎉\n\n*Which platform do you primarily want to post on?*",
            [
                {"id": "instagram", "title": "Instagram"},
                {"id": "facebook",  "title": "Facebook"},
                {"id": "both",      "title": "Both"},
            ],
        )

    # ── PLATFORM ──────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_PLATFORM:
        if text not in ("instagram", "facebook", "both"):
            await wa.send_interactive_buttons(
                sender, "Please choose a platform:",
                [
                    {"id": "instagram", "title": "Instagram"},
                    {"id": "facebook",  "title": "Facebook"},
                    {"id": "both",      "title": "Both"},
                ],
            )
            return
        data["platform"] = text
        db.save_user_profile(sender, data)

        referral_code = _generate_referral_code()
        db.set_referral_code(sender, referral_code)

        db.set_conversation_state(sender, ConversationState.AWAITING_PROMO_CODE, data)
        await wa.send_interactive_buttons(
            sender,
            f"Profile saved! 🎉 You have *{FREE_SIGNUP_CREDITS} free credits*.\n\n"
            "Do you have a promo or referral code?",
            [
                {"id": "enter_promo", "title": "Enter Code"},
                {"id": "skip",        "title": "Skip"},
            ],
        )

    else:
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "Something went wrong. Send *start* to begin again.")


# ===========================================================================
# PROMO / REFERRAL CODE
# ===========================================================================

async def handle_promo_step(
    db: BotDatabase, sender: str, text: str,
    state: ConversationState, data: dict
):
    text = text.strip()

    # "Enter Code" button → ask them to type the code
    if text == "enter_promo":
        data["awaiting_promo_text"] = True
        db.set_conversation_state(sender, ConversationState.AWAITING_PROMO_CODE, data)
        await wa.send_text(sender, "Type your promo or referral code below:")
        return

    # Skip button or skip text
    if text in ("skip", "no", "none", ""):
        db.clear_conversation_state(sender)
        await _send_onboarding_complete(db, sender)
        return

    # If they clicked Enter Code but haven't typed yet, wait
    if not data.get("awaiting_promo_text") and text not in ("enter_promo", "skip"):
        # Might be typing directly — handle it
        pass

    code = text.upper()

    # Referral code
    if code.startswith("REF-"):
        referrer = db.find_user_by_referral_code(code)
        if not referrer:
            await wa.send_text(sender, "That referral code isn't valid. Try again or type *skip*.")
            return
        if referrer["phone_number_id"] == sender:
            await wa.send_text(sender, "You can't use your own referral code! Type *skip* to continue.")
            return
        if db.has_been_referred(sender):
            await wa.send_text(sender, "You've already used a referral code. Type *skip* to continue.")
            return

        db.grant_credits(sender, 50, reason="referral_bonus")
        db.grant_credits(referrer["phone_number_id"], 50, reason="referral_reward")
        db.record_referral(referrer["phone_number_id"], sender)
        db.set_referred_by(sender, referrer["phone_number_id"])
        await wa.send_text(referrer["phone_number_id"], "Someone used your referral code! You earned *50 bonus credits*.")

        db.clear_conversation_state(sender)
        await wa.send_text(sender, "✅ Referral code applied! *50 bonus credits* added.")
        await _send_onboarding_complete(db, sender)
        return

    # Promo code
    promo = db.validate_promo_code(code)
    if not promo:
        await wa.send_text(sender, "That code isn't valid or has expired. Try again or type *skip*.")
        return
    if db.has_used_promo(sender, code):
        await wa.send_text(sender, "You've already used this code. Try another or type *skip*.")
        return

    credits_granted = promo.get("credits_granted", 50)
    db.grant_credits(sender, credits_granted, reason=f"promo_{code}")
    db.use_promo_code(code)
    db.record_promo_usage(sender, code, credits_granted)

    db.clear_conversation_state(sender)
    await wa.send_text(sender, f"✅ Code *{code}* applied! *{credits_granted} bonus credits* added.")
    await _send_onboarding_complete(db, sender)


# ===========================================================================
# ONBOARDING COMPLETE
# ===========================================================================

async def _send_onboarding_complete(db: BotDatabase, sender: str):
    user = db.get_user(sender)
    balance = user["credits_remaining"] if user else FREE_SIGNUP_CREDITS
    referral_code = user.get("referral_code", "") if user else ""

    await wa.send_text(
        sender,
        f"🚀 *You're all set!*\n\n"
        f"💳 Credit balance: *{balance} credits*\n\n"
        "*What to do next:*\n"
        "1️⃣  Send *setup* — connect Facebook or Instagram\n"
        "2️⃣  Send *post* — create your first AI post\n"
        "3️⃣  Send *subscribe* — view plans for more credits\n\n"
        "*Credit costs:*\n"
        f"  Text: {ACTION_COSTS['text_post']} | Stock image: {ACTION_COSTS['stock_image_post']}\n"
        f"  AI image: {ACTION_COSTS['ai_image_post']} | AI video: {ACTION_COSTS['ai_video_post']}\n"
        f"  Comment reply: {ACTION_COSTS['comment_reply']}\n\n"
        f"🎁 Your referral code: *{referral_code}*\n"
        "Share it — you both get *50 bonus credits*!\n\n"
        "_Send_ *help* _anytime for all commands._",
    )
    await wa.send_interactive_buttons(
        sender,
        "Where would you like to start?",
        [
            {"id": "setup",     "title": "Connect Account"},
            {"id": "post",      "title": "Create a Post"},
            {"id": "subscribe", "title": "View Plans"},
        ],
    )
