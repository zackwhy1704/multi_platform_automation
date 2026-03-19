"""
Message router — dispatches incoming WhatsApp messages to the right handler.
Supports text, interactive (buttons/lists), and media (image/video) messages.

Self-healing guarantees:
- All handler exceptions are caught; user always gets a recovery message
- Conversation states older than STALE_STATE_MINUTES are auto-cleared
- "reset" command clears any stuck state instantly
"""

import logging
from datetime import datetime, timezone
from shared.database import BotDatabase
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.handlers import onboarding, actions, subscription, settings

logger = logging.getLogger(__name__)

# Auto-clear stuck states after this many minutes of inactivity
STALE_STATE_MINUTES = 30

COMMANDS = {
    "start": onboarding.handle_start,
    "help": onboarding.handle_help,
    "post": actions.handle_post,
    "weekly": actions.handle_auto,
    "schedule": actions.handle_schedule,
    "reply": actions.handle_reply,
    "stats": actions.handle_stats,
    "credits": subscription.handle_credits,
    "subscribe": subscription.handle_subscribe,
    "buy": subscription.handle_buy_credits,
    "cancel": subscription.handle_cancel,
    "setup": settings.handle_setup,
    "disconnect": settings.handle_disconnect,
    "settings": settings.handle_settings,
    "referral": subscription.handle_referral,
    "reset": settings.handle_reset,
}

STATE_HANDLERS = {
    # Onboarding
    ConversationState.ONBOARDING_INDUSTRY: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_OFFERINGS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_GOALS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_TONE: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_CONTENT_STYLE: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_VISUAL_STYLE: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_PLATFORM: onboarding.handle_onboarding_step,
    # Promo code
    ConversationState.AWAITING_PROMO_CODE: onboarding.handle_promo_step,
    # Platform setup
    ConversationState.SETUP_PLATFORM: settings.handle_setup_step,
    ConversationState.SETUP_MANUAL_CHOOSE: settings.handle_setup_step,
    # Actions — posting flow
    ConversationState.AWAITING_POST_PLATFORM: actions.handle_post_step,
    ConversationState.AWAITING_POST_MEDIA: actions.handle_post_step,
    ConversationState.AWAITING_POST_CAPTION: actions.handle_post_step,
    ConversationState.AWAITING_POST_CONFIRM: actions.handle_post_step,
    ConversationState.AWAITING_POST_CONTENT: actions.handle_post_step,
    ConversationState.AWAITING_SCHEDULE_TIME: actions.handle_post_step,
    # Weekly auto-post
    ConversationState.AWAITING_AUTO_PLATFORM: actions.handle_auto_step,
    ConversationState.AWAITING_AUTO_COUNT: actions.handle_auto_step,
    ConversationState.AWAITING_AUTO_COUNT_CUSTOM: actions.handle_auto_step,
    ConversationState.AWAITING_AUTO_TYPE: actions.handle_auto_step,
    ConversationState.AWAITING_AUTO_TYPE_CUSTOM: actions.handle_auto_step,
    ConversationState.AWAITING_AUTO_CONFIRM: actions.handle_auto_step,
    # Engagement
    ConversationState.AWAITING_REPLY_PLATFORM: actions.handle_reply_step,
    # Credit packs
    ConversationState.AWAITING_PACK_CHOICE: subscription.handle_pack_step,
}

# States that accept media messages (photo/video)
MEDIA_ACCEPTING_STATES = {
    ConversationState.AWAITING_POST_MEDIA,
}


async def handle_incoming_message(db: BotDatabase, sender: str, message: dict, contact_name: str):
    try:
        await _route_message(db, sender, message, contact_name)
    except Exception as e:
        logger.error("Unhandled exception for %s: %s", sender, e, exc_info=True)
        try:
            db.clear_conversation_state(sender)
        except Exception:
            pass
        from shared.config import PUBLIC_BASE_URL, WHATSAPP_BOT_PHONE
        fix_url = f"{PUBLIC_BASE_URL}/connect/{sender}" if PUBLIC_BASE_URL else ""
        fix_line = f"\n\nOr visit: {fix_url}" if fix_url else ""
        await wa.send_text(
            sender,
            "Something went wrong on our end. Your session has been reset.\n\n"
            "Send *help* to see available commands, or *reset* to start fresh."
            f"{fix_line}",
        )


async def _route_message(db: BotDatabase, sender: str, message: dict, contact_name: str):
    msg_type = message.get("type", "")
    msg_id = message.get("id", "")

    await wa.mark_as_read(msg_id)
    db.create_user(sender, phone_number=sender, display_name=contact_name)
    db.update_last_seen(sender)

    # --- Extract text from message ---
    text = ""
    media_info = None

    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()

    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        if interactive.get("type") == "button_reply":
            text = interactive.get("button_reply", {}).get("id", "")
        elif interactive.get("type") == "list_reply":
            text = interactive.get("list_reply", {}).get("id", "")

    elif msg_type in ("image", "video"):
        # Media message — download it
        media_obj = message.get(msg_type, {})
        media_id = media_obj.get("id")
        caption = media_obj.get("caption", "")

        if media_id:
            from gateway.media import download_whatsapp_media
            media_info = await download_whatsapp_media(media_id)

        # If media has a caption, use it as text
        text = caption.strip() if caption else ""

    elif msg_type == "document":
        await wa.send_text(
            sender,
            "I can process *photos* and *videos* but not documents.\n"
            "Please send your file as a photo or video instead.",
        )
        return

    # --- Route the message ---

    # Check conversation state first
    conv = db.get_conversation_state(sender)

    # Auto-clear stale states (stuck for > STALE_STATE_MINUTES)
    if conv and conv["state"] != ConversationState.IDLE:
        updated_at = conv.get("updated_at")
        if updated_at:
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - updated_at).total_seconds() / 60
            if age_minutes > STALE_STATE_MINUTES:
                logger.info("Auto-clearing stale state %s for %s (age: %.0fm)", conv["state"], sender, age_minutes)
                db.clear_conversation_state(sender)
                conv = None
                await wa.send_text(
                    sender,
                    "Your previous session timed out and has been reset.\n\n"
                    "Send *help* to see available commands.",
                )

    if conv and conv["state"] != ConversationState.IDLE:
        state = ConversationState(conv["state"])

        # Cancel command works in any state
        if text.lower() in ("exit", "quit"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Exited current flow. Send *help* to see available commands.")
            return

        # If user types a known command while in a flow, auto-cancel and run it
        if text and text.lower().split()[0] in COMMANDS:
            cmd_word = text.lower().split()[0]
            db.clear_conversation_state(sender)
            handler_fn = COMMANDS[cmd_word]
            await handler_fn(db=db, sender=sender, text=text)
            return

        handler = STATE_HANDLERS.get(state)
        if handler:
            # If this state accepts media, pass media_info
            if state in MEDIA_ACCEPTING_STATES and media_info:
                await handler(
                    db=db, sender=sender, text=text,
                    state=state, data=conv.get("data") or {},
                    media_info=media_info,
                )
                return
            elif state in MEDIA_ACCEPTING_STATES and not media_info and not text:
                # User sent something else (not media and not text) while we expect media
                await wa.send_text(
                    sender,
                    "Please send a *photo or video* for your post.\n"
                    "Or type *reset* to exit.",
                )
                return
            elif text or media_info:
                # For non-media states, we need text
                if not text and media_info:
                    # User sent media but we're not in a media-accepting state
                    await wa.send_text(
                        sender,
                        "I received your media but I'm not expecting it right now.\n"
                        "Type *reset* to start over, or continue with the current step.",
                    )
                    return
                await handler(
                    db=db, sender=sender, text=text,
                    state=state, data=conv.get("data") or {},
                )
                return

    # No active conversation state — handle as command or new message

    # If user sent media without being in a flow, offer to create a post
    if media_info and not text:
        profile = db.get_user_profile(sender)
        if not profile:
            await onboarding.handle_start(db=db, sender=sender, text="")
            return

        # Auto-start posting flow with this media
        fb_token = db.get_platform_token(sender, "facebook")
        ig_token = db.get_platform_token(sender, "instagram")

        if not fb_token and not ig_token:
            await wa.send_text(
                sender,
                "Nice photo/video! To post it, first connect your account.\n"
                "Send *setup* to connect Facebook or Instagram.",
            )
            return

        # Step 1: Upload media directly to WhatsApp so it renders instantly in the chat.
        from gateway.media import is_video as _is_video, get_media_public_url
        from shared.config import PUBLIC_BASE_URL
        is_vid = _is_video(media_info["mime_type"])
        media_type = "video" if is_vid else "photo"
        file_path = media_info.get("file_path", "")
        mime = media_info["mime_type"]

        if is_vid:
            sent = await wa.send_video(sender, "", file_path=file_path, mime_type=mime)
        else:
            sent = await wa.send_image(sender, "", file_path=file_path, mime_type=mime)

        if not sent and PUBLIC_BASE_URL:
            preview_url = get_media_public_url(media_info["filename"], PUBLIC_BASE_URL)
            sent = await wa.send_video(sender, preview_url) if is_vid else await wa.send_image(sender, preview_url)

        data = {
            "media_filename": media_info["filename"],
            "media_mime": media_info["mime_type"],
            "post_type": "own_media",
        }

        # Step 2: If both platforms are connected, we need platform selection first.
        # User taps platform button → that confirms they saw the preview → then caption.
        if fb_token and ig_token:
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, data)
            await wa.send_interactive_buttons(
                sender,
                f"Your {media_type} is ready! Which platform do you want to post it on?",
                [
                    {"id": "facebook", "title": "Facebook"},
                    {"id": "instagram", "title": "Instagram"},
                ],
            )
        else:
            # Single platform — caption choice buttons confirm they saw the preview.
            data["platform"] = "facebook" if fb_token else "instagram"
            platform_label = "Facebook" if fb_token else "Instagram"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_interactive_buttons(
                sender,
                f"Your {media_type} is ready for {platform_label}! How would you like to add a caption?",
                [
                    {"id": "ai", "title": "Generate with AI"},
                    {"id": "write_caption", "title": "Write My Own"},
                ],
            )
        return

    if not text:
        await wa.send_text(
            sender,
            "I can process *text messages*, *button replies*, *photos*, and *videos*.\n"
            "Send *help* to see what I can do.",
        )
        return

    # Check if new user (no profile) — auto-start onboarding
    command_word = text.lower().split()[0] if text else ""
    profile = db.get_user_profile(sender)
    if not profile and command_word not in ("start", "help"):
        await onboarding.handle_start(db=db, sender=sender, text=text)
        return

    handler = COMMANDS.get(command_word)
    if handler:
        await handler(db=db, sender=sender, text=text)
        return

    await wa.send_text(
        sender,
        "I didn't understand that. Here are the commands you can use:\n\n"
        "*post* — Create a post (photo/video/text)\n"
        "*weekly* — Auto-generate posts for the week\n"
        "*schedule* — Schedule a post\n"
        "*reply* — Auto-reply to comments\n"
        "*stats* — View your stats\n"
        "*credits* — Check credit balance\n"
        "*buy* — Purchase credit packs\n"
        "*setup* — Connect a platform\n"
        "*disconnect* — Switch/remove account\n"
        "*settings* — View/update settings\n"
        "*subscribe* — Upgrade your plan\n"
        "*referral* — Get your referral code\n"
        "*help* — Show all commands",
    )
