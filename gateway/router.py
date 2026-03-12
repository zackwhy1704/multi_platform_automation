"""
Message router — dispatches incoming WhatsApp messages to the right handler
based on conversation state or command keywords.
"""

import logging
from shared.database import BotDatabase
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.handlers import onboarding, actions, subscription, settings

logger = logging.getLogger(__name__)

# Command map: keyword → handler coroutine
COMMANDS = {
    "start": onboarding.handle_start,
    "help": onboarding.handle_help,
    "post": actions.handle_post,
    "schedule": actions.handle_schedule,
    "reply": actions.handle_reply,
    "stats": actions.handle_stats,
    "credits": subscription.handle_credits,
    "subscribe": subscription.handle_subscribe,
    "cancel": subscription.handle_cancel,
    "setup": settings.handle_setup,
    "settings": settings.handle_settings,
}

# State → handler for multi-step flows
STATE_HANDLERS = {
    # Onboarding
    ConversationState.ONBOARDING_INDUSTRY: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_SKILLS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_GOALS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_TONE: onboarding.handle_onboarding_step,
    # Platform setup
    ConversationState.SETUP_PLATFORM: settings.handle_setup_step,
    ConversationState.SETUP_EMAIL: settings.handle_setup_step,
    ConversationState.SETUP_PASSWORD: settings.handle_setup_step,
    ConversationState.SETUP_FB_TOKEN: settings.handle_setup_step,
    ConversationState.SETUP_IG_TOKEN: settings.handle_setup_step,
    # Content creation
    ConversationState.AWAITING_POST_PLATFORM: actions.handle_post_step,
    ConversationState.AWAITING_POST_CONTENT: actions.handle_post_step,
    ConversationState.AWAITING_SCHEDULE_TIME: actions.handle_post_step,
    # Engagement
    ConversationState.AWAITING_REPLY_PLATFORM: actions.handle_reply_step,
}


async def handle_incoming_message(db: BotDatabase, sender: str, message: dict, contact_name: str):
    """Route an incoming WhatsApp message to the right handler."""
    msg_type = message.get("type", "")
    msg_id = message.get("id", "")

    # Mark as read
    await wa.mark_as_read(msg_id)

    # Ensure user exists
    db.create_user(sender, phone_number=sender, display_name=contact_name)
    db.update_last_seen(sender)

    # Extract text or button reply
    text = ""
    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        if interactive.get("type") == "button_reply":
            text = interactive.get("button_reply", {}).get("id", "")
        elif interactive.get("type") == "list_reply":
            text = interactive.get("list_reply", {}).get("id", "")

    if not text:
        await wa.send_text(sender, "Sorry, I can only process text messages and button replies right now.")
        return

    # Check for active conversation state
    conv = db.get_conversation_state(sender)
    if conv and conv["state"] != ConversationState.IDLE:
        # Allow "cancel" to break out of any flow
        if text.lower() in ("cancel", "exit", "quit"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Cancelled. Send *help* to see available commands.")
            return

        state = ConversationState(conv["state"])
        handler = STATE_HANDLERS.get(state)
        if handler:
            await handler(db=db, sender=sender, text=text, state=state, data=conv.get("data") or {})
            return

    # Command routing (first word)
    command_word = text.lower().split()[0] if text else ""
    handler = COMMANDS.get(command_word)
    if handler:
        await handler(db=db, sender=sender, text=text)
        return

    # Unknown input — show help
    await wa.send_text(
        sender,
        "I didn't understand that. Here are the commands you can use:\n\n"
        "*post* — Create a post\n"
        "*schedule* — Schedule a post\n"
        "*reply* — Auto-reply to comments\n"
        "*stats* — View your stats\n"
        "*credits* — Check credit balance\n"
        "*setup* — Connect a platform\n"
        "*settings* — View/update settings\n"
        "*subscribe* — Manage subscription\n"
        "*help* — Show all commands",
    )
