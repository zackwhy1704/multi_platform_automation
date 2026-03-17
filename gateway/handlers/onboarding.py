"""
Onboarding flow with full multi-select UI.

All steps 1–6 support:
  - Tap-to-select from list/buttons
  - "Add more" to pick additional options
  - "Other" → type comma-separated custom values

Flow: Welcome → Industry → Offerings → Goals → Tone → Content Style → Visual Style → Platform → Promo Code
"""

from __future__ import annotations

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


# ── Label maps ───────────────────────────────────────────────────────────────

INDUSTRY_OPTIONS = {
    "ecommerce":     "E-commerce / Retail",
    "fnb":           "Food & Beverage",
    "tech":          "Technology / SaaS",
    "health":        "Health & Fitness",
    "realestate":    "Real Estate",
    "beauty":        "Beauty & Wellness",
    "education":     "Education / Coaching",
    "marketing":     "Marketing / Agency",
    "finance":       "Finance / Insurance",
}

OFFERING_OPTIONS = {
    "physical_products": "Physical Products",
    "digital_products":  "Digital Products",
    "professional_svcs": "Professional Services",
    "food_drinks":       "Food & Drinks",
    "personal_training": "Personal Training",
    "creative_svcs":     "Creative Services",
    "online_courses":    "Online Courses",
    "events":            "Events & Experiences",
    "subscriptions":     "Subscriptions / SaaS",
}

GOAL_OPTIONS = {
    "get_customers":   "Get More Customers",
    "brand_awareness": "Build Brand Awareness",
    "drive_traffic":   "Drive Website Traffic",
    "grow_following":  "Grow Social Following",
    "product_sales":   "Promote Products / Sales",
    "educate":         "Educate My Audience",
    "community":       "Build Community",
}

TONE_OPTIONS = {
    "professional":   "Professional",
    "casual":         "Casual & Friendly",
    "thought_leader": "Thought Leader",
}

CONTENT_STYLE_OPTIONS = {
    "humorous":           "Humorous / Memes",
    "educational":        "Educational / Tips",
    "inspirational":      "Inspirational",
    "behind_the_scenes":  "Behind the Scenes",
    "product_showcase":   "Product Showcase",
    "mixed":              "Mix of Everything",
}

VISUAL_STYLE_OPTIONS = {
    "cartoon":        "Cartoon / Illustrated",
    "minimalist":     "Clean & Minimalist",
    "bold_colorful":  "Bold & Colourful",
    "photorealistic": "Photorealistic",
    "meme_style":     "Meme Style",
}


# ── Generic multi-select confirmation helper ─────────────────────────────────

def _fmt_selections(items: list[str]) -> str:
    return "\n".join(f"  ✅ {x}" for x in items)


# ── ReAct Validation: Reason about selections and challenge inconsistencies ─────

def _analyze_selections(selections: list[str], field: str, context: dict) -> tuple[bool, str | None]:
    """
    ReAct reasoning: Analyze selections for logical consistency.
    Returns (is_valid, challenge_message)

    If challenge_message is not None, bot will ask for confirmation.
    """
    if not selections:
        return True, None

    # ── Cross-field validation ────────────────────────────────────────────

    if field == "tone":
        # Tone + Content Style validation
        content_style = context.get("content_style", [])

        # Thought Leader + Humorous/Memes is unconventional
        if "Thought Leader" in selections and "Humorous / Memes" in content_style:
            return False, (
                "🤔 *Think this through:* Thought Leader tone usually avoids memes/humour "
                "to maintain authority.\n\n"
                "Are you mixing serious insights with comedy? That's *bold* but possible! "
                "Confirm to continue."
            )

        # Professional + Behind the Scenes can seem mismatched
        if "Professional" in selections and "Behind the Scenes" in content_style:
            return False, (
                "💭 *Quick check:* Professional tone + Behind the Scenes content can feel "
                "informal.\n\n"
                "Are you showing a polished/formal look behind the scenes? "
                "Or would Casual tone work better? Confirm to continue."
            )

    if field == "content_style":
        # Content Style + Tone validation
        tone = context.get("tone", [])
        industry = context.get("industry", [])

        # Humorous/Memes + Finance is risky
        if "Humorous / Memes" in selections and "Finance / Insurance" in industry:
            return False, (
                "⚠️ *Reality check:* Finance & Insurance usually demand trust, not humour.\n\n"
                "Are you a fun fintech/insurance brand that breaks stereotypes? "
                "Or should you reconsider? Confirm to continue."
            )

        # Meme Style + Professional tone
        if "Meme Style" in selections and "Professional" in tone:
            return False, (
                "🤔 *Heads up:* Meme style is inherently casual, but you selected Professional tone.\n\n"
                "Are you intentionally mixing? Or should you pick Casual tone instead? "
                "Confirm to continue."
            )

        # Product Showcase + Humorous memes
        if "Product Showcase" in selections and "Humorous / Memes" in selections:
            return False, (
                "💡 *Thought:* Product Showcase + Humorous memes work, but need balance.\n\n"
                "Heavy memes might bury your products. Confirm you want both."
            )

    if field == "visual_style":
        # Visual Style + Content Style validation
        content_style = context.get("content_style", [])

        # Photorealistic + Meme Style conflict
        if "Photorealistic" in selections and "Meme Style" in content_style:
            return False, (
                "🎨 *Visual check:* Photorealistic (real photos) + Meme Style don't typically mix.\n\n"
                "Did you mean: Realistic photos with meme-format text? Or reconsider? "
                "Confirm to continue."
            )

        # Cartoon + Photorealistic can be inconsistent
        if len([x for x in selections if x in ("Cartoon / Illustrated", "Photorealistic")]) == 2:
            return False, (
                "🎨 *Style check:* Cartoon and Photorealistic are opposites.\n\n"
                "Are you using different styles for different post types? "
                "Confirm if yes."
            )

        # Meme Style + Professional tone
        tone = context.get("tone", [])
        if "Meme Style" in selections and "Professional" in tone:
            return False, (
                "⚠️ *Mix alert:* Meme Style is casual, but you chose Professional tone.\n\n"
                "These often conflict. Confirm you're mixing styles intentionally."
            )

    return True, None


async def _confirm_selection(
    sender: str,
    step_label: str,
    selections: list[str],
    add_more_id: str,
    done_id: str,
    field: str = "",
    context: dict | None = None,
):
    """Show current selections and offer Add More / Done buttons.
    If ReAct validation finds issues, ask for confirmation first."""
    context = context or {}

    # Validate with ReAct reasoning
    is_valid, challenge = _analyze_selections(selections, field, context)

    if not is_valid and challenge:
        # Ask user to confirm or reconsider
        await wa.send_interactive_buttons(
            sender,
            challenge,
            [
                {"id": f"confirm_{field}", "title": "Yes, Confirm ✓"},
                {"id": f"revise_{field}",  "title": "Let Me Revise"},
            ],
        )
        return "awaiting_confirmation"

    # Normal flow: show selections + Add More / Done
    await wa.send_interactive_buttons(
        sender,
        f"*{step_label}* so far:\n{_fmt_selections(selections)}\n\nAdd another or continue?",
        [
            {"id": add_more_id, "title": "Add More"},
            {"id": done_id,     "title": "Done ✓"},
        ],
    )


# ── Picker senders ───────────────────────────────────────────────────────────

async def _send_industry_picker(sender: str, step="Step 1 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What industry is your business in?*\n\nChoose one (you can add more after):",
        "Select Industry",
        [{
            "title": "Industries",
            "rows": [
                {"id": "ecommerce",      "title": "E-commerce / Retail",    "description": "Online or physical product sales"},
                {"id": "fnb",            "title": "Food & Beverage",         "description": "Restaurant, café, catering, F&B"},
                {"id": "tech",           "title": "Technology / SaaS",       "description": "Software, apps, tech services"},
                {"id": "health",         "title": "Health & Fitness",        "description": "Gym, nutrition, wellness, medical"},
                {"id": "realestate",     "title": "Real Estate",             "description": "Property sales, rentals, development"},
                {"id": "beauty",         "title": "Beauty & Wellness",       "description": "Salon, spa, skincare, aesthetics"},
                {"id": "education",      "title": "Education / Coaching",    "description": "Tutoring, courses, training, coaching"},
                {"id": "marketing",      "title": "Marketing / Agency",      "description": "Creative, digital, media agency"},
                {"id": "finance",        "title": "Finance / Insurance",     "description": "Financial planning, insurance, banking"},
                {"id": "other_industry", "title": "➕ Other (type below)",   "description": "Type one or more, separated by commas"},
            ],
        }],
    )


async def _send_offerings_picker(sender: str, step="Step 2 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What does your business offer?*\n\nChoose one (you can add more after):",
        "Select Offering",
        [{
            "title": "Business Offerings",
            "rows": [
                {"id": "physical_products",  "title": "Physical Products",     "description": "Goods, merchandise, inventory"},
                {"id": "digital_products",   "title": "Digital Products",      "description": "Downloads, templates, software"},
                {"id": "professional_svcs",  "title": "Professional Services", "description": "Consulting, legal, accounting"},
                {"id": "food_drinks",        "title": "Food & Drinks",         "description": "Meals, beverages, catering"},
                {"id": "personal_training",  "title": "Personal Training",     "description": "Fitness coaching, PT sessions"},
                {"id": "creative_svcs",      "title": "Creative Services",     "description": "Design, photography, video"},
                {"id": "online_courses",     "title": "Online Courses",        "description": "eLearning, workshops, webinars"},
                {"id": "events",             "title": "Events & Experiences",  "description": "Workshops, venues, ticketed events"},
                {"id": "subscriptions",      "title": "Subscriptions / SaaS",  "description": "Recurring plans, memberships"},
                {"id": "other_offering",     "title": "➕ Other (type below)",  "description": "Type one or more, separated by commas"},
            ],
        }],
    )


async def _send_goals_picker(sender: str, step="Step 3 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What is your main social media goal?*\n\nChoose one (you can add more after):",
        "Select Goal",
        [{
            "title": "Business Goals",
            "rows": [
                {"id": "get_customers",   "title": "Get More Customers",      "description": "Drive leads, enquiries & sales"},
                {"id": "brand_awareness", "title": "Build Brand Awareness",   "description": "Get known, grow visibility"},
                {"id": "drive_traffic",   "title": "Drive Website Traffic",   "description": "Send followers to your site"},
                {"id": "grow_following",  "title": "Grow Social Following",   "description": "Increase followers & engagement"},
                {"id": "product_sales",   "title": "Promote Products / Sales","description": "Launch products, run promotions"},
                {"id": "educate",         "title": "Educate My Audience",     "description": "Share tips, news, how-tos"},
                {"id": "community",       "title": "Build Community",         "description": "Loyal fans, tribe, repeat buyers"},
                {"id": "other_goal",      "title": "➕ Other (type below)",  "description": "Type one or more, separated by commas"},
            ],
        }],
    )


async def _send_tone_picker(sender: str, step="Step 4 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What tone should I use for your content?*\n\nChoose one (you can add more after):",
        "Select Tone",
        [{
            "title": "Tone",
            "rows": [
                {"id": "professional",   "title": "Professional",      "description": "Polished, authoritative, business-like"},
                {"id": "casual",         "title": "Casual & Friendly", "description": "Warm, conversational, approachable"},
                {"id": "thought_leader", "title": "Thought Leader",    "description": "Insightful, bold, industry authority"},
                {"id": "other_tone",     "title": "➕ Other (type below)", "description": "Type one or more, separated by commas"},
            ],
        }],
    )


async def _send_content_style_picker(sender: str, step="Step 5 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What content style fits your brand?*\n\nChoose one (you can add more after):",
        "Choose Style",
        [{
            "title": "Content Styles",
            "rows": [
                {"id": "humorous",            "title": "Humorous / Memes",      "description": "Funny, relatable, meme-worthy"},
                {"id": "educational",         "title": "Educational / Tips",    "description": "Informative how-tos, industry tips"},
                {"id": "inspirational",       "title": "Inspirational",         "description": "Motivational and uplifting"},
                {"id": "behind_the_scenes",   "title": "Behind the Scenes",     "description": "Authentic day-to-day business life"},
                {"id": "product_showcase",    "title": "Product Showcase",      "description": "Highlight products and services"},
                {"id": "mixed",               "title": "Mix of Everything",     "description": "Varied for broader appeal"},
                {"id": "other_content_style", "title": "➕ Other (type below)", "description": "Type one or more, separated by commas"},
            ],
        }],
    )


async def _send_visual_style_picker(sender: str, step="Step 6 of 6"):
    await wa.send_interactive_list(
        sender,
        f"{step} — *What visual style for AI-generated images?*\n\nChoose one (you can add more after):",
        "Choose Visual",
        [{
            "title": "Visual Styles",
            "rows": [
                {"id": "cartoon",            "title": "Cartoon / Illustrated", "description": "Fun, colourful illustrations"},
                {"id": "minimalist",         "title": "Clean & Minimalist",    "description": "Modern, white space, simple"},
                {"id": "bold_colorful",      "title": "Bold & Colourful",      "description": "Vibrant, high-contrast graphics"},
                {"id": "photorealistic",     "title": "Photorealistic",        "description": "Realistic photos, natural lighting"},
                {"id": "meme_style",         "title": "Meme Style",            "description": "Internet humour, relatable format"},
                {"id": "other_visual_style", "title": "➕ Other (type below)", "description": "Type one or more, separated by commas"},
            ],
        }],
    )


# ── Generic multi-select handler with ReAct validation ──────────────────────

async def _handle_multiselect(
    sender: str,
    text: str,
    data: dict,
    field: str,           # data key to accumulate into, e.g. "industry"
    options: dict,        # id → label map
    other_id: str,        # e.g. "other_industry"
    add_more_id: str,     # e.g. "add_more_industry"
    done_id: str,         # e.g. "done_industry"
    step_label: str,      # display name e.g. "Industries"
    send_picker,          # async callable to re-show the list
) -> bool:
    """
    Returns True when done (proceed to next step), False to stay in this step.
    Mutates data[field] in-place.
    Integrates ReAct validation to challenge inconsistent selections.
    """
    selections: list[str] = data.setdefault(field, [])

    # ── Handle ReAct confirmation responses ───────────────────────────────
    if text == f"confirm_{field}":
        # User confirmed the selection despite challenge
        data.pop("awaiting_confirmation", None)
        await _confirm_selection(
            sender, step_label, selections, add_more_id, done_id,
            field=field, context=data
        )
        return False

    if text == f"revise_{field}":
        # User wants to revise; clear and re-show picker
        selections.clear()
        data.pop("awaiting_confirmation", None)
        await send_picker(sender)
        return False

    # ── "Done" button ────────────────────────────────────────────────────
    if text == done_id:
        if not selections:
            await send_picker(sender)
            return False
        return True  # caller moves to next step

    # ── "Add More" button ────────────────────────────────────────────────
    if text == add_more_id:
        await send_picker(sender)
        return False

    # ── Waiting for custom free-text ─────────────────────────────────────
    if data.get("awaiting_custom") == field:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts:
            await wa.send_text(sender, "Please type at least one value (use commas to separate multiple).")
            return False
        # Avoid duplicates
        for p in parts:
            if p not in selections:
                selections.append(p)
        data.pop("awaiting_custom", None)
        confirmation = await _confirm_selection(
            sender, step_label, selections, add_more_id, done_id,
            field=field, context=data
        )
        # If ReAct validation triggered, don't proceed
        if confirmation == "awaiting_confirmation":
            data["awaiting_confirmation"] = field
        return False

    # ── "Other" selected ─────────────────────────────────────────────────
    if text == other_id:
        data["awaiting_custom"] = field
        await wa.send_text(
            sender,
            f"Type your custom {step_label.lower()} below.\n"
            "_Separate multiple values with commas, e.g._ `Logistics, Warehousing`",
        )
        return False

    # ── Normal list/button selection ─────────────────────────────────────
    label = options.get(text)
    if not label:
        await send_picker(sender)
        return False

    if label not in selections:
        selections.append(label)

    confirmation = await _confirm_selection(
        sender, step_label, selections, add_more_id, done_id,
        field=field, context=data
    )
    # If ReAct validation triggered, don't proceed
    if confirmation == "awaiting_confirmation":
        data["awaiting_confirmation"] = field

    return False


# ── START / HELP ─────────────────────────────────────────────────────────────

async def handle_start(db: BotDatabase, sender: str, text: str):
    profile = db.get_user_profile(sender)
    if profile:
        await wa.send_interactive_buttons(
            sender,
            "Welcome back! You're already set up. What would you like to do?",
            [
                {"id": "post",    "title": "Create a Post"},
                {"id": "credits", "title": "Check Credits"},
                {"id": "setup",   "title": "Connect Account"},
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


# ── ONBOARDING STEPS ─────────────────────────────────────────────────────────

async def handle_onboarding_step(
    db: BotDatabase, sender: str, text: str,
    state: ConversationState, data: dict,
):
    text = text.strip()

    # ── INDUSTRY ──────────────────────────────────────────────────────────
    if state == ConversationState.ONBOARDING_INDUSTRY:
        done = await _handle_multiselect(
            sender, text, data,
            field="industry",
            options=INDUSTRY_OPTIONS,
            other_id="other_industry",
            add_more_id="add_more_industry",
            done_id="done_industry",
            step_label="Industries",
            send_picker=_send_industry_picker,
        )
        if done:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)
            await _send_offerings_picker(sender)
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, data)

    # ── OFFERINGS ─────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_OFFERINGS:
        done = await _handle_multiselect(
            sender, text, data,
            field="offerings",
            options=OFFERING_OPTIONS,
            other_id="other_offering",
            add_more_id="add_more_offering",
            done_id="done_offering",
            step_label="Offerings",
            send_picker=_send_offerings_picker,
        )
        if done:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
            await _send_goals_picker(sender)
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_OFFERINGS, data)

    # ── GOALS ─────────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_GOALS:
        done = await _handle_multiselect(
            sender, text, data,
            field="business_goals",
            options=GOAL_OPTIONS,
            other_id="other_goal",
            add_more_id="add_more_goal",
            done_id="done_goal",
            step_label="Goals",
            send_picker=_send_goals_picker,
        )
        if done:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_TONE, data)
            await _send_tone_picker(sender)
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)

    # ── TONE ──────────────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_TONE:
        done = await _handle_multiselect(
            sender, text, data,
            field="tone",
            options=TONE_OPTIONS,
            other_id="other_tone",
            add_more_id="add_more_tone",
            done_id="done_tone",
            step_label="Tone",
            send_picker=_send_tone_picker,
        )
        if done:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_CONTENT_STYLE, data)
            await _send_content_style_picker(sender)
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_TONE, data)

    # ── CONTENT STYLE ─────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_CONTENT_STYLE:
        done = await _handle_multiselect(
            sender, text, data,
            field="content_style",
            options=CONTENT_STYLE_OPTIONS,
            other_id="other_content_style",
            add_more_id="add_more_content_style",
            done_id="done_content_style",
            step_label="Content Styles",
            send_picker=_send_content_style_picker,
        )
        if done:
            # content_style in DB is a single VARCHAR — join multiple into comma string
            if isinstance(data.get("content_style"), list):
                data["content_style"] = ", ".join(data["content_style"])
            db.set_conversation_state(sender, ConversationState.ONBOARDING_VISUAL_STYLE, data)
            await _send_visual_style_picker(sender)
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_CONTENT_STYLE, data)

    # ── VISUAL STYLE ──────────────────────────────────────────────────────
    elif state == ConversationState.ONBOARDING_VISUAL_STYLE:
        done = await _handle_multiselect(
            sender, text, data,
            field="visual_style",
            options=VISUAL_STYLE_OPTIONS,
            other_id="other_visual_style",
            add_more_id="add_more_visual_style",
            done_id="done_visual_style",
            step_label="Visual Styles",
            send_picker=_send_visual_style_picker,
        )
        if done:
            # visual_style in DB is single VARCHAR — join if multiple
            if isinstance(data.get("visual_style"), list):
                data["visual_style"] = ", ".join(data["visual_style"])
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
        else:
            db.set_conversation_state(sender, ConversationState.ONBOARDING_VISUAL_STYLE, data)

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


# ── PROMO / REFERRAL CODE ────────────────────────────────────────────────────

async def handle_promo_step(
    db: BotDatabase, sender: str, text: str,
    state: ConversationState, data: dict,
):
    text = text.strip()

    if text == "enter_promo":
        data["awaiting_promo_text"] = True
        db.set_conversation_state(sender, ConversationState.AWAITING_PROMO_CODE, data)
        await wa.send_text(sender, "Type your promo or referral code below:")
        return

    if text in ("skip", "no", "none", ""):
        db.clear_conversation_state(sender)
        await _send_onboarding_complete(db, sender)
        return

    code = text.upper()

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


# ── ONBOARDING COMPLETE ──────────────────────────────────────────────────────

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
