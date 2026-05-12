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
import os
import re
from datetime import datetime, timedelta
from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost, ACTION_COSTS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.i18n import get_language

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

        # If media already attached (direct-drop flow), go straight to caption input
        if data.get("post_type") == "own_media" and data.get("media_filename"):
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_text(
                sender,
                f"Your media is ready for {PLATFORM_LABELS[platform]}! Type your caption below:",
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
                    "Type *ok* to use it, or type new text to replace it.",
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

        # Step 2: Move state to AWAITING_POST_CAPTION — ask user to write their caption.
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
        await wa.send_text(
            sender,
            f"Your {media_type} is ready! Type your caption below:",
        )

    # --- CAPTION / CONTENT ---
    elif state == ConversationState.AWAITING_POST_CAPTION:
        caption = text.strip()
        if not caption:
            await wa.send_text(sender, "Please type your caption:")
            return

        data["caption"] = caption
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
        await _send_preview(sender, data)

    # --- TEXT-ONLY CONTENT ---
    elif state == ConversationState.AWAITING_POST_CONTENT:
        normalized = text.lower().strip()
        use_existing = normalized == "ok" and data.get("caption")

        if use_existing:
            caption = data["caption"]
        else:
            caption = text.strip()
            if not caption:
                await wa.send_text(sender, "Write your post text below:")
                return

        data["caption"] = caption
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
        await _send_preview(sender, data)

    # --- PREVIEW CONFIRMATION ---
    elif state == ConversationState.AWAITING_POST_CONFIRM:
        choice = text.lower().strip()

        if choice in ("approve", "yes", "publish", "post"):
            await _publish_post(db, sender, data)

        elif choice == "beautify":
            await _beautify_caption(db, sender, data)

        elif choice in ("edit", "change"):
            post_type = data.get("post_type", "text_only")
            if post_type == "own_media":
                db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
                await wa.send_text(sender, "Type your new caption:")
            else:
                db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONTENT, data)
                await wa.send_text(sender, "Type your new post text:")

        elif choice in ("discard", "no", "cancel"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Post cancelled. No credits deducted.\n\nSend *post* to start again.")

        else:
            await _send_confirm_buttons(sender)

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
            {"id": "beautify", "title": "Beautify with AI"},
            {"id": "edit", "title": "Edit Caption"},
        ],
    )


async def _send_confirm_buttons(sender: str):
    """Re-send the confirm buttons."""
    await wa.send_interactive_buttons(
        sender,
        "Would you like to publish this post?",
        [
            {"id": "approve", "title": "Publish Now"},
            {"id": "beautify", "title": "Beautify with AI"},
            {"id": "edit", "title": "Edit Caption"},
        ],
    )


async def _beautify_caption(db: BotDatabase, sender: str, data: dict):
    """Beautify the user's caption with AI vision + profile context (2 credits)."""
    from shared.credits import ACTION_COSTS
    cost = ACTION_COSTS.get("beautify_caption", 2)

    cm = CreditManager(db)
    if not cm.has_enough(sender, "beautify_caption"):
        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"Beautify costs *{cost}* credits but you have *{balance}*.\n\n"
            "Send *buy* for credit packs.",
        )
        await _send_confirm_buttons(sender)
        return

    await wa.send_text(sender, "Beautifying your caption with AI...")

    platform = data.get("platform", "facebook")
    user_caption = data.get("caption", "")
    profile = db.get_user_profile(sender) or {}

    # Resolve media file path for vision context
    media_file_path = None
    media_mime = data.get("media_mime", "")
    if data.get("media_filename"):
        import os
        from gateway.media import MEDIA_DIR
        candidate = os.path.join(MEDIA_DIR, data["media_filename"])
        if os.path.exists(candidate):
            media_file_path = candidate

    from services.ai.ai_service import beautify_caption
    try:
        beautified = await asyncio.to_thread(
            beautify_caption, platform, profile, user_caption,
            media_file_path=media_file_path, media_mime=media_mime,
            language=get_language(),
        )
    except Exception as e:
        logger.error("Beautify caption error for %s: %s", sender, e)
        beautified = None

    if not beautified or not beautified.strip():
        await wa.send_text(sender, "Beautify failed. Your original caption is unchanged.")
        await _send_confirm_buttons(sender)
        return

    # Deduct credits after successful generation
    cm.deduct(sender, "beautify_caption", platform)
    balance = cm.get_balance(sender)

    beautified = beautified.strip()
    data["caption"] = beautified
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)

    await wa.send_text(
        sender,
        f"Here's your beautified caption (*{cost}* credits used, *{balance}* remaining):\n\n{beautified}",
    )
    await _send_confirm_buttons(sender)


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


# ===========================================================================
# AI IMAGE & AI VIDEO
# ===========================================================================

async def handle_ai_image(db: BotDatabase, sender: str, text: str):
    """Start AI image generation flow."""
    if not await _check_credits(db, sender, "ai_image"):
        return

    cost = ACTION_COSTS.get("ai_image", 10)
    await wa.send_text(
        sender,
        f"*AI Image Generation* 🎨\n\n"
        f"Cost: *{cost} credits* per image\n\n"
        f"⚠️ *Note:* Credits will be deducted once generation starts, "
        f"even if you're not satisfied with the result.\n\n"
        f"Type your image prompt below — describe what you want to see:",
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_AI_IMAGE_PROMPT, {})


async def handle_avatar_setup(db: BotDatabase, sender: str, text: str):
    """
    Entry point for avatar video setup or re-setup.
    Checks which setup steps are missing and guides the user through them.
    Called internally from the 'video' command flow.
    """
    avatar = db.get_avatar_profile(sender) or {}
    has_photo = bool(avatar.get("profile_photo_url"))
    has_voice = avatar.get("voice_clone_status") == "ready"

    if not has_photo:
        await wa.send_text(
            sender,
            "*Avatar Video Setup — Step 1 of 2* 📸\n\n"
            "Send a clear, front-facing photo of yourself.\n\n"
            "This will be used as your face in all avatar videos. "
            "You only need to do this once.",
        )
        db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_PHOTO, {})
    elif not has_voice:
        await _prompt_voice_sample(sender)
        db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_VOICE_SAMPLE, {})
    else:
        await wa.send_text(
            sender,
            "✅ Your avatar profile is already set up!\n\n"
            "Send *video* to create a video or update your voice sample.",
        )


async def _prompt_voice_sample(sender: str):
    await wa.send_text(
        sender,
        "*Avatar Video Setup — Step 2 of 2* 🎙\n\n"
        "Send a voice note of yourself speaking naturally for *30–60 seconds*.\n\n"
        "Tips for best results:\n"
        "  • Speak clearly in a quiet room\n"
        "  • Use your normal speaking pace\n"
        "  • Read anything — news, a script, even just describe your day\n\n"
        "This trains your personal AI voice clone.",
    )


async def handle_avatar_video(db: BotDatabase, sender: str, text: str):
    """Entry point for 'avatar video' command — checks setup is complete then starts flow."""
    avatar = db.get_avatar_profile(sender) or {}
    has_photo = bool(avatar.get("profile_photo_url"))
    has_voice = avatar.get("voice_clone_status") == "ready"

    if not has_photo or not has_voice:
        missing = []
        if not has_photo:
            missing.append("profile photo")
        if not has_voice:
            missing.append("voice clone")
        await wa.send_text(
            sender,
            f"⚠️ Your avatar profile isn't complete yet. Missing: {', '.join(missing)}.\n\n"
            "Send *video* to complete your profile first.",
        )
        return

    if not await _check_credits(db, sender, "ai_video"):
        return

    cost = ACTION_COSTS.get("ai_video", 30)
    await wa.send_text(
        sender,
        f"*Avatar Video* 🎬\n\n"
        f"Cost: *{cost} credits* per video\n\n"
        "Type the script you want to speak in your video.\n"
        "Keep it under 80 words (~30 seconds).\n\n"
        "Example: _Hi, I'm Sarah from Century 21. This stunning 3-bedroom..._",
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_SCRIPT, {})


async def handle_ai_content_step(db: BotDatabase, sender: str, text: str,
                                  state: ConversationState, data: dict, **kwargs):
    """Handle AI image/video generation states."""

    if state == ConversationState.AWAITING_AI_IMAGE_PROMPT:
        if not text.strip():
            await wa.send_text(sender, "Please type a description for the image you want to generate.")
            return

        data["prompt"] = text.strip()
        db.clear_conversation_state(sender)

        # Deduct credits before generation
        cm = CreditManager(db)
        if not cm.deduct(sender, "ai_image", "ai"):
            await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
            return

        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"Generating your image... This may take a moment.\n"
            f"Credits used: *{get_action_cost('ai_image')}* | Remaining: *{balance}*",
        )

        # Generate image
        from services.ai.image_generator import generate_image
        try:
            image_url = await asyncio.to_thread(generate_image, data["prompt"])
        except Exception as e:
            logger.error("AI image generation error for %s: %s", sender, e)
            image_url = None

        if image_url:
            sent = await wa.send_image(sender, image_url, caption="Here's your AI-generated image!")
            if not sent:
                await wa.send_text(sender, f"Your image is ready:\n{image_url}")
        else:
            await wa.send_text(
                sender,
                "❌ Image generation failed. Your credits have been used.\n\n"
                "Send *ai image* to try again with a different prompt.",
            )

async def handle_avatar_setup_step(db: BotDatabase, sender: str, text: str,
                                    state: ConversationState, data: dict,
                                    media_info: dict = None, **kwargs):
    """Handle multi-step avatar setup: photo upload → voice sample → clone."""

    if state == ConversationState.AWAITING_AVATAR_PHOTO:
        if not media_info or not media_info.get("mime_type", "").startswith("image/"):
            await wa.send_text(sender, "Please send a photo (not a document or video).")
            return

        # Upload to fal.ai CDN for a permanent URL (Railway filesystem is ephemeral)
        await wa.send_text(sender, "⏳ Saving your photo...")
        try:
            import os as _os
            import fal_client as _fal
            _os.environ["FAL_KEY"] = __import__("shared.config", fromlist=["FAL_KEY"]).FAL_KEY
            photo_url = await asyncio.to_thread(_fal.upload_file, media_info["file_path"])
        except Exception as _e:
            logger.warning("fal.ai upload failed, falling back to local URL: %s", _e)
            from gateway.media import get_media_public_url
            from shared.config import PUBLIC_BASE_URL
            photo_url = get_media_public_url(media_info["filename"], PUBLIC_BASE_URL)

        db.save_avatar_profile(sender, profile_photo_url=photo_url)
        logger.info("Avatar photo stored for %s: %s", sender, photo_url[:60])

        await _prompt_voice_sample(sender)
        db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_VOICE_SAMPLE, {})

    elif state == ConversationState.AWAITING_AVATAR_VOICE_SAMPLE:
        if not media_info or not media_info.get("mime_type", "").startswith("audio/"):
            await wa.send_text(
                sender,
                "Please send a voice note (hold the microphone button in WhatsApp).",
            )
            return

        await wa.send_text(
            sender,
            "⏳ Cloning your voice... This takes about 30 seconds.",
        )
        db.save_avatar_profile(sender, voice_clone_status="pending")
        db.clear_conversation_state(sender)

        # Delete old voice clone if re-doing
        existing = db.get_avatar_profile(sender) or {}
        old_voice_id = existing.get("voice_clone_id")

        from services.ai.voice_generator import clone_voice, delete_voice
        if old_voice_id:
            await asyncio.to_thread(delete_voice, old_voice_id)

        user_label = f"user_{sender}"
        voice_id = await asyncio.to_thread(clone_voice, user_label, media_info["file_path"])

        if voice_id:
            db.save_avatar_profile(sender, voice_clone_id=voice_id, voice_clone_status="ready")
            await wa.send_text(
                sender,
                "✅ *Avatar profile complete!*\n\n"
                "Your face and voice are saved.\n\n"
                "Send *video* to create your first video.",
            )
        else:
            db.save_avatar_profile(sender, voice_clone_status="failed")
            await wa.send_text(
                sender,
                "❌ Voice cloning failed. Please try again with a clearer recording.\n\n"
                "Send *video* to retry.",
            )


async def handle_avatar_video_step(db: BotDatabase, sender: str, text: str,
                                    state: ConversationState, data: dict, **kwargs):
    """Handle avatar video generation: script → style → generate."""

    if state == ConversationState.AWAITING_AVATAR_SCRIPT:
        script = text.strip()
        if not script:
            await wa.send_text(sender, "Please type the script you want to speak in your video.")
            return

        if len(script) > 600:
            await wa.send_text(
                sender,
                f"Your script is {len(script)} characters — please keep it under 600 "
                "(about 80 words / 30 seconds).",
            )
            return

        data["script"] = script
        db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_STYLE, data)

        await wa.send_interactive_list(
            sender,
            "Choose your video style:",
            "Select Style",
            [{
                "title": "Video Style",
                "rows": [
                    {"id": "vstyle_professional", "title": "Professional",
                     "description": "Office setting, confident, 16:9"},
                    {"id": "vstyle_warm",         "title": "Warm & Friendly",
                     "description": "Natural setting, approachable, 9:16"},
                    {"id": "vstyle_luxury",       "title": "Luxury / Premium",
                     "description": "Cinematic, dramatic lighting, 9:16"},
                ],
            }],
        )

    elif state == ConversationState.AWAITING_AVATAR_STYLE:
        style_map = {
            "vstyle_professional": "professional",
            "vstyle_warm":         "warm",
            "vstyle_luxury":       "luxury",
        }
        style = style_map.get(text.lower().strip())
        if not style:
            await wa.send_interactive_list(
                sender,
                "Please select a video style:",
                "Select Style",
                [{
                    "title": "Video Style",
                    "rows": [
                        {"id": "vstyle_professional", "title": "Professional",
                         "description": "Office setting, confident, 16:9"},
                        {"id": "vstyle_warm",         "title": "Warm & Friendly",
                         "description": "Natural setting, approachable, 9:16"},
                        {"id": "vstyle_luxury",       "title": "Luxury / Premium",
                         "description": "Cinematic, dramatic lighting, 9:16"},
                    ],
                }],
            )
            return

        db.clear_conversation_state(sender)

        cm = CreditManager(db)
        if not cm.deduct(sender, "ai_video", "ai"):
            await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
            return

        balance = cm.get_balance(sender)
        await wa.send_text(
            sender,
            f"Generating your avatar video... This may take 3–5 minutes.\n"
            f"Credits used: *{get_action_cost('ai_video')}* | Remaining: *{balance}*",
        )

        avatar = db.get_avatar_profile(sender) or {}
        photo_url = avatar.get("profile_photo_url")
        voice_id  = avatar.get("voice_clone_id")
        script    = data.get("script", "")

        # Step 1: TTS — generate MP3 from script using cloned voice
        from services.ai.voice_generator import generate_speech
        from shared.config import PUBLIC_BASE_URL, FAL_KEY
        from gateway.media import get_media_public_url

        audio_path = await asyncio.to_thread(generate_speech, voice_id, script)
        if not audio_path:
            await wa.send_text(
                sender,
                "❌ Voice generation failed. Your credits have been used.\n\n"
                "Send *video* to try again.",
            )
            return

        # Upload audio to fal.ai CDN — Railway filesystem is ephemeral
        try:
            import fal_client as _fal
            os.environ["FAL_KEY"] = FAL_KEY
            audio_url = await asyncio.to_thread(_fal.upload_file, audio_path)
        except Exception as _e:
            logger.warning("fal.ai audio upload failed, falling back to local URL: %s", _e)
            audio_filename = os.path.basename(audio_path)
            audio_url = get_media_public_url(audio_filename, PUBLIC_BASE_URL)

        # Step 2: Seed Dance — animate photo with audio
        from services.ai.video_generator import generate_avatar_video
        try:
            result = await generate_avatar_video(photo_url, audio_url, style=style)
        except Exception as e:
            logger.error("Avatar video error for %s: %s", sender, e)
            result = None

        if result and result.get("url"):
            sent = await wa.send_video(sender, result["url"], caption="Here's your avatar video!")
            if not sent:
                await wa.send_text(sender, f"Here's your avatar video:\n{result['url']}")
        elif result and result.get("error") == "billing":
            cost = get_action_cost("ai_video")
            db.execute_query(
                "UPDATE users SET credits_remaining = credits_remaining + %s, "
                "credits_used = GREATEST(credits_used - %s, 0) WHERE phone_number_id = %s",
                (cost, cost, sender),
            )
            await wa.send_text(
                sender,
                "❌ *Video generation unavailable* — the video service account is out of credits.\n\n"
                f"Your *{cost} credits* have been refunded.\n\n"
                "Please contact support.",
            )
        else:
            await wa.send_text(
                sender,
                "❌ Video generation failed. Your credits have been used.\n\n"
                "Send *video* to try again.",
            )
