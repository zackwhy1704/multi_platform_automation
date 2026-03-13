"""
Settings and platform setup handlers.
API-only: Facebook and Instagram via OAuth tokens. No passwords stored.
"""

import logging
from shared.database import BotDatabase
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}


async def handle_settings(db: BotDatabase, sender: str, text: str):
    profile = db.get_user_profile(sender)
    lines = ["*Your Settings*\n"]

    if profile:
        lines.append(f"Industry: {', '.join(profile.get('industry', []))}")
        lines.append(f"Offerings: {', '.join(profile.get('offerings', []))}")
        lines.append(f"Goals: {', '.join(profile.get('business_goals', []))}")
        lines.append(f"Tone: {', '.join(profile.get('tone', []))}")
        lines.append(f"Platform: {profile.get('platform', 'not set')}")
    else:
        lines.append("Profile not set up. Send *start* to begin.")

    lines.append("\n*Connected Platforms:*")
    for platform, label in PLATFORM_LABELS.items():
        token = db.get_platform_token(sender, platform)
        status = "Connected" if token else "Not connected"
        lines.append(f"  {label}: {status}")

    lines.append("\nSend *setup* to connect or update a platform.")
    await wa.send_text(sender, "\n".join(lines))


async def handle_setup(db: BotDatabase, sender: str, text: str):
    await wa.send_interactive_buttons(
        sender,
        "Which platform do you want to connect?",
        [{"id": "facebook", "title": "Facebook"}, {"id": "instagram", "title": "Instagram"}],
    )
    db.set_conversation_state(sender, ConversationState.SETUP_PLATFORM, {})


async def handle_setup_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    if state == ConversationState.SETUP_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_text(sender, "Please choose Facebook or Instagram.")
            return

        data["platform"] = platform
        if platform == "facebook":
            db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, data)
            await wa.send_text(
                sender,
                "To connect Facebook, I need your *Page Access Token*.\n\n"
                "You can get this from Facebook Developer Console:\n"
                "1. Go to developers.facebook.com\n"
                "2. Select your app > Tools > Graph API Explorer\n"
                "3. Select your Page and generate a token\n\n"
                "Paste your token below:",
            )
        elif platform == "instagram":
            db.set_conversation_state(sender, ConversationState.SETUP_IG_TOKEN, data)
            await wa.send_text(
                sender,
                "To connect Instagram, I need your *Instagram Business Account* token.\n\n"
                "This requires a Facebook Page linked to your IG Business account.\n"
                "Get a Page Access Token from developers.facebook.com.\n\n"
                "Paste your token below:",
            )

    elif state == ConversationState.SETUP_FB_TOKEN:
        db.save_platform_token(sender, "facebook", text.strip())
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "*Facebook* connected! You can now use *post* or *reply* for Facebook.")

    elif state == ConversationState.SETUP_IG_TOKEN:
        db.save_platform_token(sender, "instagram", text.strip())
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "*Instagram* connected! You can now use *post* or *reply* for Instagram.")
