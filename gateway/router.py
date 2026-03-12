"""
Message router — dispatches incoming WhatsApp messages to the right handler.
"""

import logging
from shared.database import BotDatabase
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.handlers import onboarding, actions, subscription, settings

logger = logging.getLogger(__name__)

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

STATE_HANDLERS = {
    ConversationState.ONBOARDING_INDUSTRY: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_SKILLS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_GOALS: onboarding.handle_onboarding_step,
    ConversationState.ONBOARDING_TONE: onboarding.handle_onboarding_step,
    ConversationState.SETUP_PLATFORM: settings.handle_setup_step,
    ConversationState.SETUP_FB_TOKEN: settings.handle_setup_step,
    ConversationState.SETUP_IG_TOKEN: settings.handle_setup_step,
    ConversationState.AWAITING_POST_PLATFORM: actions.handle_post_step,
    ConversationState.AWAITING_POST_CONTENT: actions.handle_post_step,
    ConversationState.AWAITING_SCHEDULE_TIME: actions.handle_post_step,
    ConversationState.AWAITING_REPLY_PLATFORM: actions.handle_reply_step,
}


async def handle_incoming_message(db: BotDatabase, sender: str, message: dict, contact_name: str):
    msg_type = message.get("type", "")
    msg_id = message.get("id", "")

    await wa.mark_as_read(msg_id)
    db.create_user(sender, phone_number=sender, display_name=contact_name)
    db.update_last_seen(sender)

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

    conv = db.get_conversation_state(sender)
    if conv and conv["state"] != ConversationState.IDLE:
        if text.lower() in ("cancel", "exit", "quit"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Cancelled. Send *help* to see available commands.")
            return
        state = ConversationState(conv["state"])
        handler = STATE_HANDLERS.get(state)
        if handler:
            await handler(db=db, sender=sender, text=text, state=state, data=conv.get("data") or {})
            return

    command_word = text.lower().split()[0] if text else ""
    handler = COMMANDS.get(command_word)
    if handler:
        await handler(db=db, sender=sender, text=text)
        return

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
