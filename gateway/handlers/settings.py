"""
Settings, platform setup, and disconnect handlers.
Uses Facebook OAuth for one-click connection. Falls back to manual token if OAuth not configured.
Supports disconnect (logout) to switch FB/IG accounts.
"""

import logging
from shared.database import BotDatabase
from shared.config import FB_APP_ID, PUBLIC_BASE_URL
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.handlers.oauth import get_oauth_url

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}


def _account_label(token_data: dict, platform: str) -> str:
    """Build a human-readable label for a connected account."""
    if not token_data:
        return "Not connected"

    name = token_data.get("page_name", "")
    username = token_data.get("account_username", "")

    if platform == "instagram" and username:
        return f"@{username}" + (f" ({name})" if name and name != username else "")
    elif name:
        return name
    elif token_data.get("page_id"):
        return f"ID: {token_data['page_id']}"
    return "Connected"


async def handle_settings(db: BotDatabase, sender: str, text: str):
    profile = db.get_user_profile(sender)
    lines = ["*Your Settings*\n"]

    if profile:
        lines.append(f"Industry: {', '.join(profile.get('industry', []))}")
        lines.append(f"Offerings: {', '.join(profile.get('offerings', []))}")
        lines.append(f"Goals: {', '.join(profile.get('business_goals', []))}")
        lines.append(f"Tone: {', '.join(profile.get('tone', []))}")
        content_style = profile.get('content_style', '')
        visual_style = profile.get('visual_style', '')
        if content_style:
            lines.append(f"Content Style: {content_style.replace('_', ' ').title()}")
        if visual_style:
            lines.append(f"Visual Style: {visual_style.replace('_', ' ').title()}")
        lines.append(f"Platform: {profile.get('platform', 'not set')}")
    else:
        lines.append("Profile not set up. Send *start* to begin.")

    lines.append("\n*Connected Accounts:*")
    any_connected = False
    for platform, label in PLATFORM_LABELS.items():
        token = db.get_platform_token(sender, platform)
        if token:
            account = _account_label(token, platform)
            lines.append(f"  {label}: *{account}*")
            any_connected = True
        else:
            lines.append(f"  {label}: Not connected")

    lines.append("")
    lines.append("*setup* — Connect or switch account")
    if any_connected:
        lines.append("*disconnect* — Remove a connected account")

    await wa.send_text(sender, "\n".join(lines))


async def handle_setup(db: BotDatabase, sender: str, text: str):
    """Start platform connection — use OAuth if available, else manual."""
    oauth_url = get_oauth_url(sender)

    if oauth_url:
        # Show current connection status
        fb_token = db.get_platform_token(sender, "facebook")
        ig_token = db.get_platform_token(sender, "instagram")

        status = ""
        if fb_token:
            fb_label = _account_label(fb_token, "facebook")
            ig_label = _account_label(ig_token, "instagram") if ig_token else "Not linked"
            status = (
                f"*Currently connected:*\n"
                f"  Facebook: *{fb_label}*\n"
                f"  Instagram: *{ig_label}*\n\n"
                f"Click below to *switch to a different account*.\n"
                f"The new account will replace the current one.\n\n"
            )

        await wa.send_text(
            sender,
            f"{status}"
            f"*Connect your Facebook & Instagram*\n\n"
            f"Click the link below to log in with Facebook. "
            f"This connects your Page and Instagram (if linked) in one step.\n\n"
            f"{oauth_url}\n\n"
            f"Your tokens are stored securely and never expire.",
        )
    else:
        # Fallback: manual token entry
        await wa.send_interactive_buttons(
            sender,
            "Which platform do you want to connect?",
            [{"id": "facebook", "title": "Facebook"}, {"id": "instagram", "title": "Instagram"}],
        )
        db.set_conversation_state(sender, ConversationState.SETUP_PLATFORM, {})


async def handle_disconnect(db: BotDatabase, sender: str, text: str):
    """Disconnect (logout) a platform — removes token so user can reconnect a different account."""
    fb_token = db.get_platform_token(sender, "facebook")
    ig_token = db.get_platform_token(sender, "instagram")

    if not fb_token and not ig_token:
        await wa.send_text(sender, "You don't have any connected accounts.\n\nSend *setup* to connect.")
        return

    buttons = []
    if fb_token:
        buttons.append({"id": "disconnect_facebook", "title": "Facebook"})
    if ig_token:
        buttons.append({"id": "disconnect_instagram", "title": "Instagram"})
    if fb_token and ig_token:
        buttons.append({"id": "disconnect_all", "title": "Disconnect All"})

    # Build status message
    lines = ["*Connected Accounts:*\n"]
    if fb_token:
        lines.append(f"  Facebook: *{_account_label(fb_token, 'facebook')}*")
    if ig_token:
        lines.append(f"  Instagram: *{_account_label(ig_token, 'instagram')}*")
    lines.append("\nWhich account do you want to disconnect?")

    await wa.send_interactive_buttons(sender, "\n".join(lines), buttons)
    db.set_conversation_state(sender, ConversationState.SETUP_PLATFORM, {"action": "disconnect"})


async def handle_setup_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    """Handle manual token setup and disconnect actions."""

    # --- DISCONNECT FLOW ---
    if data.get("action") == "disconnect":
        choice = text.lower().strip()

        if choice == "disconnect_facebook":
            db.delete_platform_token(sender, "facebook")
            db.clear_conversation_state(sender)
            await wa.send_text(
                sender,
                "*Facebook disconnected.*\n\n"
                "Send *setup* to connect a different Facebook account.",
            )
        elif choice == "disconnect_instagram":
            db.delete_platform_token(sender, "instagram")
            db.clear_conversation_state(sender)
            await wa.send_text(
                sender,
                "*Instagram disconnected.*\n\n"
                "Send *setup* to connect a different Instagram account.",
            )
        elif choice == "disconnect_all":
            db.delete_platform_token(sender, "facebook")
            db.delete_platform_token(sender, "instagram")
            db.clear_conversation_state(sender)
            await wa.send_text(
                sender,
                "*All accounts disconnected.*\n\n"
                "Send *setup* to connect new accounts.",
            )
        else:
            await wa.send_text(sender, "Please choose an account to disconnect.")
        return

    # --- MANUAL TOKEN SETUP (fallback when OAuth not configured) ---
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
