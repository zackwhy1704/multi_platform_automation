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
from gateway.i18n import set_language
from gateway.message_log import log_inbound

logger = logging.getLogger(__name__)

# Auto-clear stuck states after this many minutes of inactivity
STALE_STATE_MINUTES = 30

COMMANDS = {
    "start": onboarding.handle_start,
    "help": onboarding.handle_help,
    "post": actions.handle_post,
    "schedule": actions.handle_schedule,
    "reply": actions.handle_reply,
    "stats": actions.handle_stats,
    "credits": subscription.handle_credits,
    "subscribe": subscription.handle_subscribe,
    "buy": subscription.handle_buy_credits,
    "cancel subscription": subscription.handle_cancel,
    "setup": settings.handle_setup,
    "disconnect": settings.handle_disconnect,
    "settings": settings.handle_settings,
    "referral": subscription.handle_referral,
    "reset": settings.handle_reset,
    "language": settings.handle_language,
    "ai image": actions.handle_ai_image,
    "ai video": actions.handle_ai_video,
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
    # Engagement
    ConversationState.AWAITING_REPLY_PLATFORM: actions.handle_reply_step,
    # Credit packs
    ConversationState.AWAITING_PACK_CHOICE: subscription.handle_pack_step,
    # Language
    ConversationState.AWAITING_LANGUAGE: settings.handle_language_step,
    # AI content generation
    ConversationState.AWAITING_AI_IMAGE_PROMPT: actions.handle_ai_content_step,
    ConversationState.AWAITING_AI_VIDEO_PROMPT: actions.handle_ai_content_step,
    ConversationState.AWAITING_AI_VIDEO_LENGTH: actions.handle_ai_content_step,
}

def _match_command(text: str):
    """Match text against known commands, supporting multi-word commands like 'ai image'."""
    lower = text.lower().strip()
    # Check multi-word commands first (longest match)
    for cmd in sorted(COMMANDS, key=len, reverse=True):
        if " " in cmd and lower.startswith(cmd):
            return cmd
    # Single-word commands
    first_word = lower.split()[0] if lower else ""
    if first_word in COMMANDS:
        return first_word
    return None


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

    # Set display language for this request
    user_lang = db.get_display_language(sender)
    set_language(user_lang)

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

    # --- Log the inbound message (admin panel visibility) ---
    try:
        _meta = {}
        if msg_type == "interactive":
            interactive = message.get("interactive", {})
            _meta = {
                "interactive_type": interactive.get("type"),
                "reply": interactive.get(interactive.get("type") or "", {}),
            }
        elif msg_type in ("image", "video"):
            _meta = {"media": message.get(msg_type, {}).get("id"), "mime": message.get(msg_type, {}).get("mime_type")}
        log_inbound(
            db=db,
            phone_number_id=sender,
            msg_type=msg_type or "unknown",
            text_body=text,
            wa_message_id=msg_id,
            metadata=_meta,
        )
    except Exception:
        # Logging never breaks message handling
        pass

    # --- Block banned users (admin panel: ban) ---
    try:
        u = db.get_user(sender)
        if u and u.get("banned"):
            # Silent drop — don't echo replies to banned users
            return
    except Exception:
        pass

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
        cmd_match = _match_command(text) if text else None
        if cmd_match:
            db.clear_conversation_state(sender)
            handler_fn = COMMANDS[cmd_match]
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

    if not text:
        await wa.send_text(
            sender,
            "I can process *text messages*, *button replies*, *photos*, and *videos*.\n"
            "Send *help* to see what I can do.",
        )
        return

    # Check if new user (no profile) — auto-start onboarding
    command_word = _match_command(text) if text else None
    profile = db.get_user_profile(sender)
    if not profile and command_word not in ("start", "help"):
        await onboarding.handle_start(db=db, sender=sender, text=text)
        return

    handler = COMMANDS.get(command_word) if command_word else None
    if handler:
        await handler(db=db, sender=sender, text=text)
        return

    await wa.send_text(
        sender,
        "I didn't understand that. Here are the commands you can use:\n\n"
        "*post* — Create a post (photo/video/text)\n"
        "*schedule* — Schedule a post\n"
        "*reply* — Auto-reply to comments\n"
        "*ai image* — Generate an AI image\n"
        "*ai video* — Generate an AI video\n"
        "*stats* — View your stats\n"
        "*credits* — Check credit balance\n"
        "*buy* — Purchase credit packs\n"
        "*setup* — Connect a platform\n"
        "*disconnect* — Switch/remove account\n"
        "*settings* — View/update settings\n"
        "*subscribe* — Upgrade your plan\n"
        "*cancel subscription* — Cancel subscription\n"
        "*referral* — Get your referral code\n"
        "*language* — Change display language\n"
        "*reset* — Refresh / use when facing any issues\n"
        "*help* — Show all commands",
    )
