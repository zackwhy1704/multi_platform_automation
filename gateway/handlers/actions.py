from __future__ import annotations

"""
Content creation and engagement handlers.
Facebook + Instagram only. Freemium: credits-based.

Posting flow:
  1. User sends "post" → choose platform if both connected
  2. Send a photo/video → preview shown → choose caption (AI or write own) → confirm (5 credits)
     Facebook only: type text directly → AI or write caption → confirm                 (3 credits)
  3. Preview with approve/edit/cancel buttons
  4. On approve → publish to platform

Weekly auto-post (Facebook only — text posts):
  1. User sends "weekly" → choose post count
  2. AI generates text posts → preview → schedule across the week
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost, ACTION_COSTS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}

# Map post_type → credit action name
POST_TYPE_ACTIONS = {
    "own_media": "own_media_post",
    "text_only": "text_post",
}


async def _check_credits(db: BotDatabase, sender: str, action: str) -> bool:
    """Check if user has enough credits. Prompts upgrade if not."""
    cm = CreditManager(db)
    if not cm.has_enough(sender, action):
        balance = cm.get_balance(sender)
        cost = get_action_cost(action)
        await wa.send_text(
            sender,
            f"Not enough credits. This costs *{cost}* credits but you have *{balance}*.\n\n"
            "Ways to get more credits:\n"
            "  *subscribe* — Upgrade your plan\n"
            "  *buy* — Purchase credit packs\n"
            "  *referral* — Share your code, earn 30 credits per friend\n\n"
            "Send *credits* for your full balance breakdown.",
        )
        return False
    return True


# ===========================================================================
# POST COMMAND — entry point
# ===========================================================================

async def handle_post(db: BotDatabase, sender: str, text: str):
    # Check minimum credits (text_post = 3, cheapest option)
    cm = CreditManager(db)
    if cm.get_balance(sender) < ACTION_COSTS["text_post"]:
        await wa.send_text(
            sender,
            f"You need at least *{ACTION_COSTS['text_post']}* credits to create a post.\n\n"
            "Send *buy* for credit packs or *subscribe* for a plan.",
        )
        return

    # Check if any platform is connected
    fb_token = db.get_platform_token(sender, "facebook")
    ig_token = db.get_platform_token(sender, "instagram")

    if not fb_token and not ig_token:
        await wa.send_text(
            sender,
            "You haven't connected any platform yet.\n\n"
            "Send *setup* to connect your Facebook or Instagram first.",
        )
        return

    # If only one platform is connected, skip platform selection
    if fb_token and not ig_token:
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_MEDIA, {"platform": "facebook", "post_type": "own_media"})
        await _send_media_prompt(sender, "facebook")
        return
    elif ig_token and not fb_token:
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_MEDIA, {"platform": "instagram", "post_type": "own_media"})
        await _send_media_prompt(sender, "instagram")
        return

    # Both connected — ask which platform, then go straight to media prompt
    await wa.send_interactive_buttons(
        sender,
        "Which platform do you want to post on?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {})


async def _send_media_prompt(sender: str, platform: str):
    """Ask user to send their photo/video. Facebook users can also type text directly."""
    if platform == "facebook":
        await wa.send_text(
            sender,
            f"Send your *photo or video* to create a {PLATFORM_LABELS[platform]} post.\n\n"
            "Or *type your text* directly for a text-only post.",
        )
    else:
        await wa.send_text(
            sender,
            f"Send your *photo or video* for your {PLATFORM_LABELS[platform]} post.",
        )


# ===========================================================================
# POST FLOW — state handlers
# ===========================================================================

async def handle_post_step(db: BotDatabase, sender: str, text: str,
                           state: ConversationState, data: dict,
                           media_info: dict = None):
    """Handle all post creation states. media_info is set when user sends a photo/video."""

    # --- PLATFORM SELECTION ---
    if state == ConversationState.AWAITING_POST_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_interactive_buttons(
                sender,
                "Please tap one of the buttons below:",
                [
                    {"id": "facebook", "title": "Facebook"},
                    {"id": "instagram", "title": "Instagram"},
                ],
            )
            return

        token = db.get_platform_token(sender, platform)
        if not token:
            await wa.send_text(
                sender,
                f"You haven't connected {PLATFORM_LABELS[platform]} yet.\n"
                "Send *setup* to connect it first.",
            )
            db.clear_conversation_state(sender)
            return

        data["platform"] = platform

        # If media already attached (direct-drop flow), go straight to caption choice
        if data.get("post_type") == "own_media" and data.get("media_filename"):
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_interactive_buttons(
                sender,
                f"Your media is ready for {PLATFORM_LABELS[platform]}! How would you like to add a caption?",
                [
                    {"id": "ai", "title": "Generate with AI"},
                    {"id": "write_caption", "title": "Write My Own"},
                ],
            )
        else:
            data["post_type"] = "own_media"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_MEDIA, data)
            await _send_media_prompt(sender, platform)

    # --- WAITING FOR MEDIA (photo/video) ---
    elif state == ConversationState.AWAITING_POST_MEDIA:
        platform = data.get("platform", "facebook")

        if not media_info:
            # Facebook: if user typed text instead of sending media, treat as text-only post
            if platform == "facebook" and text.strip():
                data["post_type"] = "text_only"
                data["caption"] = text.strip()  # pre-fill so user can confirm with "ok"
                db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONTENT, data)
                await wa.send_text(
                    sender,
                    f"Got it! Your post:\n\n_{text.strip()}_\n\n"
                    "Type *ok* to use it, *ai* to rewrite with AI, or type new text to replace it.",
                )
                return

            await wa.send_text(
                sender,
                "Please send a *photo or video*.\n\n"
                + ("Or type your text for a text-only Facebook post.\n\n" if platform == "facebook" else "")
                + "Type *reset* to exit.",
            )
            return

        data["media_filename"] = media_info["filename"]
        data["media_mime"] = media_info["mime_type"]

        from gateway.media import is_video, get_media_public_url
        from shared.config import PUBLIC_BASE_URL
        is_vid = is_video(media_info["mime_type"])
        media_type = "video" if is_vid else "photo"
        file_path = media_info.get("file_path", "")
        mime = media_info["mime_type"]

        # Step 1: Upload directly to WhatsApp Media API so the file is already on
        # WhatsApp's servers — renders in the chat immediately, no async URL-fetch lag.
        if is_vid:
            sent = await wa.send_video(sender, "", file_path=file_path, mime_type=mime)
        else:
            sent = await wa.send_image(sender, "", file_path=file_path, mime_type=mime)

        if not sent:
            # Fallback to public URL if direct upload failed
            if PUBLIC_BASE_URL:
                preview_url = get_media_public_url(media_info["filename"], PUBLIC_BASE_URL)
                sent = await wa.send_video(sender, preview_url) if is_vid else await wa.send_image(sender, preview_url)

        # Step 2: Move state to AWAITING_POST_CAPTION and send caption choice buttons.
        # The user MUST tap a button to continue — this is the guarantee that they have
        # seen the media preview before any caption prompt appears.
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
        await wa.send_interactive_buttons(
            sender,
            f"Your {media_type} is ready! How would you like to add a caption?",
            [
                {"id": "ai", "title": "Generate with AI"},
                {"id": "write_caption", "title": "Write My Own"},
            ],
        )

    # --- CAPTION / CONTENT ---
    elif state == ConversationState.AWAITING_POST_CAPTION:
        platform = data.get("platform", "facebook")
        normalized = text.lower().strip()

        if normalized == "write_caption":
            await wa.send_text(sender, "Type your caption below:")
            return

        if normalized == "ai":
            await wa.send_text(sender, "Generating caption...")
            profile = db.get_user_profile(sender)
            from services.ai.ai_service import generate_caption_for_media
            from gateway.media import is_video

            media_type = "video" if is_video(data.get("media_mime", "")) else "photo"
            try:
                caption = await asyncio.to_thread(
                    generate_caption_for_media, platform, profile or {}, media_type=media_type
                )
            except Exception as e:
                logger.error("Caption generation error for %s: %s", sender, e)
                caption = None

            if not caption or not caption.strip():
                await wa.send_text(
                    sender,
                    "Caption generation failed. Please try again or write your own caption.",
                )
                await wa.send_interactive_buttons(
                    sender,
                    "How would you like to add a caption?",
                    [
                        {"id": "ai", "title": "Try Again"},
                        {"id": "write_caption", "title": "Write My Own"},
                    ],
                )
                return

            caption = caption.strip()
            # Show the generated caption FIRST so user can read it before being prompted to publish
            await wa.send_text(sender, f"Here's your generated caption:\n\n{caption}")

        else:
            caption = text.strip()
            if not caption:
                await wa.send_interactive_buttons(
                    sender,
                    "How would you like to add a caption?",
                    [
                        {"id": "ai", "title": "Generate with AI"},
                        {"id": "write_caption", "title": "Write My Own"},
                    ],
                )
                return

        data["caption"] = caption
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
        await _send_preview(sender, data)

    # --- TEXT-ONLY CONTENT ---
    elif state == ConversationState.AWAITING_POST_CONTENT:
        platform = data.get("platform", "facebook")
        normalized = text.lower().strip()
        use_ai = normalized == "ai"
        use_existing = normalized == "ok" and data.get("caption")

        if use_ai:
            await wa.send_text(sender, "Generating post...")
            profile = db.get_user_profile(sender)
            from services.ai.ai_service import generate_post
            try:
                caption = await asyncio.to_thread(generate_post, platform, profile or {})
            except Exception as e:
                logger.error("Post generation error for %s: %s", sender, e)
                caption = None

            if not caption or not caption.strip():
                await wa.send_text(
                    sender,
                    "Post generation failed. Please try again or write your own text.",
                )
                await wa.send_text(
                    sender,
                    "Write your Facebook post below.\n\n"
                    "Or type *ai* to try generating again.",
                )
                return

            caption = caption.strip()
            # Show the generated post FIRST so user can read it before being prompted to publish
            await wa.send_text(sender, f"Here's your generated post:\n\n{caption}")
        elif use_existing:
            caption = data["caption"]
        else:
            caption = text.strip()
            if not caption:
                await wa.send_text(
                    sender,
                    "Write your Facebook post below.\n\n"
                    "Or type *ai* to have AI generate one for you.",
                )
                return

        data["caption"] = caption
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
        await _send_preview(sender, data)

    # --- PREVIEW CONFIRMATION ---
    elif state == ConversationState.AWAITING_POST_CONFIRM:
        choice = text.lower().strip()

        if choice in ("approve", "yes", "publish", "post"):
            await _publish_post(db, sender, data)

        elif choice in ("edit", "change"):
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            post_type = data.get("post_type", "text_only")
            if post_type == "own_media":
                await wa.send_text(sender, "Write a new caption (or type *ai* to generate one):")
            else:
                await wa.send_text(sender, "Give me a new topic or write the caption directly:")

        elif choice in ("discard", "no"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Post cancelled. No credits deducted.\n\nSend *post* to start again.")

        else:
            await wa.send_interactive_buttons(
                sender,
                "Would you like to publish this post?",
                [
                    {"id": "approve", "title": "Publish Now"},
                    {"id": "edit", "title": "Edit Caption"},
                    {"id": "discard", "title": "Cancel"},
                ],
            )

    # --- SCHEDULE TIME ---
    elif state == ConversationState.AWAITING_SCHEDULE_TIME:
        platform = data.get("platform", "facebook")
        post_type = data.get("post_type", "text_only")
        action = POST_TYPE_ACTIONS.get(post_type, "scheduled_post")
        scheduled_action = f"scheduled_{action.replace('_post', '')}" if action.endswith("_post") else action

        scheduled_at = _parse_datetime(text.strip())
        if not scheduled_at:
            await wa.send_text(
                sender,
                "Couldn't parse that time. Please try again.\n\n"
                "Examples:\n"
                "  *2026-03-15T09:00*\n"
                "  *tomorrow 9am*\n"
                "  *Monday 3pm*\n"
                "  *next Friday 10:30*",
            )
            return

        db.clear_conversation_state(sender)
        cm = CreditManager(db)
        if not cm.deduct(sender, scheduled_action, platform):
            await wa.send_text(sender, "Insufficient credits.")
            return

        media_url = _resolve_media_url(data)
        db.save_scheduled_content(sender, platform, data.get("caption", ""), scheduled_at, media_url=media_url)
        cost = get_action_cost(scheduled_action)
        await wa.send_text(
            sender,
            f"Post scheduled for {PLATFORM_LABELS[platform]} at "
            f"{scheduled_at.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Credits deducted: *{cost}*",
        )


# ===========================================================================
# DATETIME PARSING (natural language + ISO)
# ===========================================================================

def _parse_datetime(text: str) -> datetime | None:
    """Parse ISO or natural language datetime. Returns None if unparseable."""
    text = text.strip().lower()
    now = datetime.now()

    # Try ISO format first
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    # Natural language patterns
    # "tomorrow 9am", "tomorrow 10:30"
    m = re.match(r"^tomorrow\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        hour = _to_24h(hour, meridiem)
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)

    # "today 3pm"
    m = re.match(r"^today\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        hour = _to_24h(hour, meridiem)
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # "Monday 3pm", "next Friday 10:30"
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    m = re.match(r"^(?:next\s+)?(" + "|".join(day_names) + r")\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if m:
        target_day = day_names.index(m.group(1))
        hour, minute, meridiem = int(m.group(2)), int(m.group(3) or 0), m.group(4)
        hour = _to_24h(hour, meridiem)
        days_ahead = (target_day - now.weekday()) % 7 or 7
        target_date = now + timedelta(days=days_ahead)
        return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # "in 2 hours", "in 30 minutes"
    m = re.match(r"^in\s+(\d+)\s+(hour|hours|minute|minutes|min|mins)$", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if "hour" in unit:
            return now + timedelta(hours=amount)
        else:
            return now + timedelta(minutes=amount)

    return None


def _to_24h(hour: int, meridiem: str | None) -> int:
    if meridiem == "pm" and hour != 12:
        return hour + 12
    if meridiem == "am" and hour == 12:
        return 0
    return hour


# ===========================================================================
# PREVIEW
# ===========================================================================

async def _send_preview(sender: str, data: dict):
    """Send a post preview with approve/edit/cancel buttons.

    own_media: media was already shown at upload time — only show caption + buttons.
    text_only: caption text + buttons.
    """
    platform = data.get("platform", "facebook")
    caption = data.get("caption", "")
    post_type = data.get("post_type", "text_only")
    action = POST_TYPE_ACTIONS.get(post_type, "post")
    cost = get_action_cost(action)

    type_label = post_type.replace("_", " ").title()
    preview_header = (
        f"*Preview — {PLATFORM_LABELS[platform]} Post*\n"
        f"*Type: {type_label}* | *Cost: {cost} credits*"
    )

    # For own_media, media was already shown at upload — skip re-sending to avoid duplicates
    if post_type != "own_media":
        media_url = _resolve_media_url(data)
        if media_url:
            from gateway.media import is_video as _is_video
            mime = data.get("media_mime", "")
            is_vid = _is_video(mime) if mime else any(
                media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi", ".webm")
            )
            sent = False
            if is_vid:
                sent = await wa.send_video(sender, media_url, caption=preview_header)
            else:
                sent = await wa.send_image(sender, media_url, caption=preview_header)
            if not sent:
                await wa.send_text(sender, preview_header + "\n_(Media preview unavailable)_")
            else:
                # Wait for media to render before sending caption text
                await asyncio.sleep(2 if is_vid else 1)
        else:
            await wa.send_text(sender, preview_header)
    else:
        await wa.send_text(sender, preview_header)

    # Caption preview + publish buttons in one message so nothing appears out of order
    caption_preview = caption[:300] + ("..." if len(caption) > 300 else "")
    await wa.send_interactive_buttons(
        sender,
        f"*Caption:*\n{caption_preview}\n\nReady to publish?",
        [
            {"id": "approve", "title": "Publish Now"},
            {"id": "edit", "title": "Edit Caption"},
            {"id": "discard", "title": "Cancel"},
        ],
    )


# ===========================================================================
# PUBLISH
# ===========================================================================

def _resolve_media_url(data: dict) -> str | None:
    """Get the media URL from data dict based on post_type."""
    post_type = data.get("post_type", "text_only")

    if post_type == "own_media" and data.get("media_filename"):
        from shared.config import PUBLIC_BASE_URL
        from gateway.media import get_media_public_url
        if PUBLIC_BASE_URL:
            return get_media_public_url(data["media_filename"], PUBLIC_BASE_URL)

    return None


async def _publish_post(db: BotDatabase, sender: str, data: dict):
    """Deduct credits and publish to the platform directly via Graph API."""
    platform = data.get("platform", "facebook")
    caption = data.get("caption", "")
    post_type = data.get("post_type", "text_only")
    action = POST_TYPE_ACTIONS.get(post_type, "post")

    db.clear_conversation_state(sender)

    # Deduct credits
    cm = CreditManager(db)
    if not cm.deduct(sender, action, platform):
        await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
        return

    media_url = _resolve_media_url(data)

    await wa.send_text(sender, f"Publishing to {PLATFORM_LABELS[platform]}...")

    # Publish directly via Graph API (no Celery/Redis required)
    from services.publisher import publish_to_facebook, publish_to_instagram

    if platform == "facebook":
        result = await publish_to_facebook(db, sender, caption, media_url)
    else:
        result = await publish_to_instagram(db, sender, caption, media_url)

    cost = get_action_cost(action)
    balance = cm.get_balance(sender)

    if result.get("success"):
        post_url = result.get("url", "")
        url_line = f"\n🔗 {post_url}" if post_url else ""
        await wa.send_text(
            sender,
            f"✅ *Published to {PLATFORM_LABELS[platform]}!*\n\n"
            f"{caption[:100]}{'...' if len(caption) > 100 else ''}"
            f"{url_line}\n\n"
            f"Credits used: *{cost}* | Remaining: *{balance}*",
        )
    else:
        # Refund credits on failure
        db.execute_query(
            "UPDATE users SET credits_remaining = credits_remaining + %s, "
            "credits_used = GREATEST(credits_used - %s, 0) WHERE phone_number_id = %s",
            (cost, cost, sender),
        )
        balance = cm.get_balance(sender)
        error = result.get("error", "Unknown error")
        await wa.send_text(
            sender,
            f"❌ *Publishing failed:* {error}\n\n"
            f"Your *{cost} credits* have been refunded. Remaining: *{balance}*\n\n"
            f"Send *post* to try again.",
        )


# ===========================================================================
# WEEKLY AUTO-POST (STANDALONE — completely separate from single post)
# ===========================================================================

async def handle_auto(db: BotDatabase, sender: str, text: str):
    """Entry point for weekly auto-post scheduling (NOT immediate posting)."""
    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    if balance < ACTION_COSTS["text_post"]:
        await wa.send_text(
            sender,
            f"You need at least *{ACTION_COSTS['text_post']}* credits to use auto-post.\n\n"
            "Send *buy* for credit packs or *subscribe* for a plan.",
        )
        return

    fb_token = db.get_platform_token(sender, "facebook")
    ig_token = db.get_platform_token(sender, "instagram")

    if not fb_token and not ig_token:
        await wa.send_text(sender, "Connect a platform first. Send *setup*.")
        return

    intro = (
        "📅 *Weekly Auto-Post Scheduler*\n\n"
        "This will generate and *schedule posts for the week ahead* — "
        "they'll publish automatically at the right times.\n\n"
        "_This is NOT for posting right now. Use *post* for an immediate single post._"
    )

    if not fb_token:
        await wa.send_text(
            sender,
            "Weekly auto-post is for *Facebook text posts* only.\n\n"
            "Send *setup* to connect your Facebook account first.",
        )
        return

    data = {"platform": "facebook"}
    db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT, data)
    await wa.send_text(sender, intro)
    await _send_auto_count_options(sender)


async def _send_auto_count_options(sender: str):
    """Send post count options as interactive list."""
    text_3 = 3 * ACTION_COSTS["text_post"]
    text_5 = 5 * ACTION_COSTS["text_post"]
    text_7 = 7 * ACTION_COSTS["text_post"]

    await wa.send_interactive_list(
        sender,
        "How many posts should I schedule this week?",
        "Choose Count",
        [
            {
                "title": "Post Count",
                "rows": [
                    {"id": "3", "title": "3 Posts", "description": f"~{text_3} credits"},
                    {"id": "5", "title": "5 Posts", "description": f"~{text_5} credits"},
                    {"id": "7", "title": "7 Posts (Daily)", "description": f"~{text_7} credits"},
                    {"id": "others", "title": "Custom Count", "description": "Type a number from 1 to 14"},
                ],
            }
        ],
    )


def _send_auto_type_options_rows(platform: str) -> list:
    """Build the content type rows for auto-post (text-only Facebook only)."""
    rows = [
        {"id": "text_only", "title": "Text Posts", "description": f"{ACTION_COSTS['text_post']} credits each"},
        {"id": "others", "title": "Custom Theme", "description": "Describe your own content theme"},
    ]
    return rows


async def handle_auto_step(db: BotDatabase, sender: str, text: str,
                            state: ConversationState, data: dict, **kwargs):
    """Handle weekly auto-post states."""

    # --- PLATFORM ---
    if state == ConversationState.AWAITING_AUTO_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_interactive_buttons(
                sender,
                "Please tap one of the buttons below:",
                [
                    {"id": "facebook", "title": "Facebook"},
                    {"id": "instagram", "title": "Instagram"},
                ],
            )
            return
        data["platform"] = platform
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT, data)
        await _send_auto_count_options(sender)

    # --- COUNT ---
    elif state == ConversationState.AWAITING_AUTO_COUNT:
        choice = text.strip().lower()

        if choice == "others":
            db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT_CUSTOM, data)
            await wa.send_text(
                sender,
                "How many posts do you want to schedule? Type a number between 1 and 14:",
            )
            return

        try:
            count = int(choice)
        except ValueError:
            count = 0

        if count not in (3, 5, 7):
            await _send_auto_count_options(sender)
            return

        data["count"] = count
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_TYPE, data)

        platform = data.get("platform", "facebook")
        rows = _send_auto_type_options_rows(platform)
        total_text = count * ACTION_COSTS["text_post"]

        await wa.send_interactive_list(
            sender,
            f"What type of content for your *{count} scheduled posts*?\n\n"
            f"Estimated cost: {total_text} credits",
            "Choose Type",
            [{"title": "Content Types", "rows": rows}],
        )

    # --- CUSTOM COUNT INPUT ---
    elif state == ConversationState.AWAITING_AUTO_COUNT_CUSTOM:
        try:
            count = int(text.strip())
        except ValueError:
            await wa.send_text(
                sender,
                "Please type a valid number between 1 and 14.\n\nHow many posts to schedule?",
            )
            return

        if not 1 <= count <= 14:
            await wa.send_text(
                sender,
                "Please enter a number between 1 and 14.\n\nHow many posts to schedule?",
            )
            return

        data["count"] = count
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_TYPE, data)

        platform = data.get("platform", "facebook")
        rows = _send_auto_type_options_rows(platform)
        total_text = count * ACTION_COSTS["text_post"]

        await wa.send_interactive_list(
            sender,
            f"What type of content for your *{count} scheduled posts*?\n\n"
            f"Estimated cost: {total_text} credits",
            "Choose Type",
            [{"title": "Content Types", "rows": rows}],
        )

    # --- TYPE ---
    elif state == ConversationState.AWAITING_AUTO_TYPE:
        content_type = text.lower().replace(" ", "_")
        platform = data.get("platform", "facebook")
        valid_types = {"text_only"}

        if content_type == "others":
            db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_TYPE_CUSTOM, data)
            await wa.send_text(
                sender,
                "What content type or theme would you like for the batch?\n\n"
                "_e.g. \"Motivational quotes\", \"Product promotions\", \"Behind the scenes\"_",
            )
            return

        if content_type not in valid_types:
            rows = _send_auto_type_options_rows(platform)
            await wa.send_interactive_list(
                sender,
                "Please choose a content type from the list:",
                "Choose Type",
                [{"title": "Content Types", "rows": rows}],
            )
            return

        await _proceed_auto_generation(db, sender, data, content_type)

    # --- CUSTOM TYPE INPUT ---
    elif state == ConversationState.AWAITING_AUTO_TYPE_CUSTOM:
        custom_theme = text.strip()
        if not custom_theme:
            await wa.send_text(
                sender,
                "Please describe the content type or theme for your posts:",
            )
            return
        data["custom_theme"] = custom_theme
        await _proceed_auto_generation(db, sender, data, "text_only")

    # --- CONFIRM ---
    elif state == ConversationState.AWAITING_AUTO_CONFIRM:
        choice = text.lower().strip()

        if choice in ("approve_all", "approve", "yes", "schedule"):
            await _schedule_batch_posts(db, sender, data)
        elif choice in ("discard", "no"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Auto-post cancelled. No credits deducted.\n\nSend *weekly* to try again.")
        else:
            await wa.send_interactive_buttons(
                sender,
                "Schedule all posts or cancel?",
                [
                    {"id": "approve_all", "title": "Schedule All"},
                    {"id": "discard", "title": "Cancel"},
                ],
            )


async def _proceed_auto_generation(db: BotDatabase, sender: str, data: dict, content_type: str):
    """After content type is chosen, generate the batch and show preview."""
    count = data.get("count", 3)
    platform = data.get("platform", "facebook")
    action = POST_TYPE_ACTIONS.get(content_type, "text_post")
    total_cost = count * get_action_cost(action)

    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    if balance < total_cost:
        await wa.send_text(
            sender,
            f"You need *{total_cost}* credits for {count} {content_type.replace('_', ' ')} posts "
            f"but you have *{balance}*.\n\n"
            "Try fewer posts, or send *buy* for credit packs.",
        )
        rows = _send_auto_type_options_rows(platform)
        await wa.send_interactive_list(
            sender,
            "Choose a different content type:",
            "Choose Type",
            [{"title": "Content Types", "rows": rows}],
        )
        return

    data["content_type"] = content_type
    data["total_cost"] = total_cost

    await wa.send_text(
        sender,
        f"Generating *{count} {content_type.replace('_', ' ')} posts* for "
        f"{PLATFORM_LABELS[platform]}...\n\n"
        f"Total cost when scheduled: *{total_cost} credits*\n"
        f"This may take a moment.",
    )

    profile = db.get_user_profile(sender)
    if not profile:
        await wa.send_text(sender, "Profile not found. Send *start* to set up.")
        db.clear_conversation_state(sender)
        return

    custom_theme = data.get("custom_theme")
    posts = await _generate_batch_posts(profile, platform, content_type, count, custom_theme=custom_theme)
    data["posts"] = posts

    # Send preview of all posts
    for i, post in enumerate(posts, 1):
        preview = f"*Post {i}/{count}*\n"
        if post.get("media_type"):
            preview += f"Media: {post['media_type']}\n"
        preview += f"\n{post.get('caption', '')[:300]}"
        if len(post.get("caption", "")) > 300:
            preview += "..."
        await wa.send_text(sender, preview)

    db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_CONFIRM, data)
    await wa.send_interactive_buttons(
        sender,
        f"*{count} posts ready to schedule!* Total: *{total_cost} credits*\n\n"
        "Posts will be spread evenly across the next 7 days and published automatically.",
        [
            {"id": "approve_all", "title": "Schedule All"},
            {"id": "discard", "title": "Cancel"},
        ],
    )


async def _generate_batch_posts(profile: dict, platform: str, content_type: str, count: int,
                                 custom_theme: str = None) -> list:
    """Generate a batch of text-only posts for auto-post."""
    from services.ai.ai_service import generate_post

    topic = custom_theme or None
    captions = await asyncio.gather(*[
        asyncio.to_thread(generate_post, platform, profile, topic=topic)
        for _ in range(count)
    ])
    return [
        {"index": i, "caption": captions[i] or f"Post {i + 1} for the week!", "media_type": "Text only"}
        for i in range(count)
    ]


async def _schedule_batch_posts(db: BotDatabase, sender: str, data: dict):
    """Deduct credits and schedule all batch posts across the week."""
    platform = data.get("platform", "facebook")
    content_type = data.get("content_type", "text_only")
    posts = data.get("posts", [])
    action = POST_TYPE_ACTIONS.get(content_type, "text_post")

    cm = CreditManager(db)
    total_cost = data.get("total_cost", 0)

    # Verify credits one more time
    if cm.get_balance(sender) < total_cost:
        await wa.send_text(sender, "Insufficient credits. Send *buy* for credit packs.")
        db.clear_conversation_state(sender)
        return

    # Schedule posts evenly across 7 days starting tomorrow 9 AM
    now = datetime.now()
    base_time = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    interval_days = 7 / len(posts) if posts else 1

    scheduled_count = 0
    for i, post in enumerate(posts):
        scheduled_at = base_time + timedelta(days=int(i * interval_days))
        media_url = post.get("media_url")

        if not cm.deduct(sender, action, platform):
            await wa.send_text(
                sender,
                f"Ran out of credits after scheduling {scheduled_count} posts.",
            )
            break

        db.save_scheduled_content(sender, platform, post.get("caption", ""), scheduled_at, media_url=media_url)
        scheduled_count += 1

    db.clear_conversation_state(sender)
    balance = cm.get_balance(sender)
    await wa.send_text(
        sender,
        f"*{scheduled_count} posts scheduled!*\n\n"
        f"Platform: {PLATFORM_LABELS[platform]}\n"
        f"Schedule: Next 7 days starting tomorrow at 9 AM\n"
        f"Credits used: *{scheduled_count * get_action_cost(action)}* | Remaining: *{balance}*\n\n"
        "Posts will be published automatically at the scheduled times.\n\n"
        "Send *post* to publish something right now, or *weekly* to schedule another batch.",
    )


# ===========================================================================
# SCHEDULE & REPLY
# ===========================================================================

async def handle_schedule(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "scheduled_post"):
        return
    await wa.send_interactive_buttons(
        sender,
        "Schedule a post for which platform?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {"scheduling": True})


async def handle_reply(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "comment_reply"):
        return
    await wa.send_interactive_buttons(
        sender,
        "Auto-reply to comments on which platform?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_REPLY_PLATFORM, {})


async def handle_reply_step(db: BotDatabase, sender: str, text: str,
                            state: ConversationState, data: dict, **kwargs):
    platform = text.lower()
    if platform not in PLATFORM_LABELS:
        await wa.send_interactive_buttons(
            sender,
            "Please tap one of the buttons below:",
            [
                {"id": "facebook", "title": "Facebook"},
                {"id": "instagram", "title": "Instagram"},
            ],
        )
        return

    db.clear_conversation_state(sender)
    cm = CreditManager(db)
    if not cm.deduct(sender, "comment_reply", platform):
        await wa.send_text(sender, "Insufficient credits.")
        return

    # Direct API call to trigger reply service (no Celery dependency)
    try:
        import httpx
        from shared.config import INTERNAL_API_URL
        if INTERNAL_API_URL:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{INTERNAL_API_URL}/internal/trigger-reply",
                    json={"sender": sender, "platform": platform},
                )
    except Exception as e:
        logger.warning(f"Could not trigger reply service for {sender} on {platform}: {e}")

    await wa.send_text(
        sender,
        f"Auto-reply activated for {PLATFORM_LABELS[platform]}! 💬\n\n"
        "I'll automatically reply to new comments on your recent posts.\n\n"
        "Note: Replies are processed periodically. You'll see them on your page within minutes.",
    )


async def handle_stats(db: BotDatabase, sender: str, text: str):
    lines = ["*Your Automation Stats*\n"]
    for platform, label in PLATFORM_LABELS.items():
        stats = db.get_user_stats(sender, platform)
        if stats["posts_created"] or stats["comments_made"]:
            lines.append(f"*{label}:*")
            lines.append(f"  Posts: {stats['posts_created']}")
            lines.append(f"  Replies: {stats['comments_made']}")
            if stats["last_active"]:
                lines.append(f"  Last active: {str(stats['last_active'])[:10]}")
            lines.append("")
    if len(lines) == 1:
        lines.append("No activity yet. Send *post* to get started!")
    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    lines.append(f"\n*Credits remaining:* {balance}")
    await wa.send_text(sender, "\n".join(lines))
