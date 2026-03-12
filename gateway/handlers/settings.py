"""
Settings and platform setup handlers.
Manages connecting LinkedIn/Facebook/Instagram accounts.
"""

import logging

from shared.database import BotDatabase
from shared.encryption import encrypt
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)


async def handle_settings(db: BotDatabase, sender: str, text: str):
    """Show current settings and connected platforms."""
    profile = db.get_user_profile(sender)
    lines = ["*Your Settings*\n"]

    if profile:
        lines.append(f"Industry: {', '.join(profile.get('industry', []))}")
        lines.append(f"Skills: {', '.join(profile.get('skills', []))}")
        lines.append(f"Goals: {', '.join(profile.get('career_goals', []))}")
        lines.append(f"Tone: {', '.join(profile.get('tone', []))}")
    else:
        lines.append("Profile not set up. Send *start* to begin.")

    lines.append("\n*Connected Platforms:*")
    for platform in ("linkedin", "facebook", "instagram"):
        creds = db.get_platform_credentials(sender, platform)
        token = db.get_platform_token(sender, platform)
        status = "Connected" if (creds or token) else "Not connected"
        lines.append(f"  {platform.title()}: {status}")

    lines.append("\nSend *setup* to connect or update a platform.")
    await wa.send_text(sender, "\n".join(lines))


async def handle_setup(db: BotDatabase, sender: str, text: str):
    """Start platform connection flow."""
    await wa.send_interactive_buttons(
        sender,
        "Which platform do you want to connect?",
        [
            {"id": "linkedin", "title": "LinkedIn"},
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.SETUP_PLATFORM, {})


async def handle_setup_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    """Process platform setup steps."""

    if state == ConversationState.SETUP_PLATFORM:
        platform = text.lower()
        if platform not in ("linkedin", "facebook", "instagram"):
            await wa.send_text(sender, "Please choose LinkedIn, Facebook, or Instagram.")
            return

        data["platform"] = platform

        if platform == "linkedin":
            db.set_conversation_state(sender, ConversationState.SETUP_EMAIL, data)
            await wa.send_text(sender, "Enter your *LinkedIn email address*:")
        elif platform == "facebook":
            db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, data)
            await wa.send_text(
                sender,
                "To connect Facebook, I need your *Page Access Token*.\n\n"
                "You can get this from Facebook Developer Console:\n"
                "1. Go to developers.facebook.com\n"
                "2. Select your app → Tools → Graph API Explorer\n"
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

    elif state == ConversationState.SETUP_EMAIL:
        data["email"] = text.strip()
        db.set_conversation_state(sender, ConversationState.SETUP_PASSWORD, data)
        await wa.send_text(
            sender,
            "Now enter your *LinkedIn password*.\n"
            "It will be encrypted and stored securely.",
        )

    elif state == ConversationState.SETUP_PASSWORD:
        platform = data.get("platform", "linkedin")
        email = data.get("email", "")
        password = text.strip()

        encrypted = encrypt(password)
        db.save_platform_credentials(sender, platform, email, encrypted)
        db.clear_conversation_state(sender)

        await wa.send_text(
            sender,
            f"*{platform.title()}* account connected!\n"
            f"Email: {email}\n"
            f"Password: (encrypted and stored securely)\n\n"
            "You can now use *post* or *reply* for this platform.",
        )

    elif state == ConversationState.SETUP_FB_TOKEN:
        token = text.strip()
        db.save_platform_token(sender, "facebook", token)
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "*Facebook* connected! You can now use *post* or *reply* for Facebook.")

    elif state == ConversationState.SETUP_IG_TOKEN:
        token = text.strip()
        db.save_platform_token(sender, "instagram", token)
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "*Instagram* connected! You can now use *post* or *reply* for Instagram.")
