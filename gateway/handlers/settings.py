"""
Settings, platform setup, and disconnect handlers.

Connection flow: Post For Me hosted OAuth — no Facebook App Review needed.
Each user connects their own Facebook/Instagram via Post For Me's OAuth,
which is already approved. We store their Post For Me profile key.
"""

import logging

from shared.database import BotDatabase
from shared.config import PUBLIC_BASE_URL, WHATSAPP_BOT_PHONE, POSTFORME_API_KEY
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

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
    """Start platform connection via Post For Me OAuth."""
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
            f"Tap below to *switch account* or reconnect.\n\n"
        )

    from services.publisher import generate_auth_url
    result = await generate_auth_url(sender, "facebook")
    if result.get("success"):
        connect_url = result["url"]
        await wa.send_text(
            sender,
            f"{status}"
            f"*Connect your Facebook & Instagram*\n\n"
            f"Tap the link below, log in with Facebook, and select your Page:\n\n"
            f"{connect_url}\n\n"
            f"_Works for any Facebook account — no app approval needed._\n\n"
            f"Once connected, come back and send *done* to confirm.",
        )
        await wa.send_interactive_buttons(
            sender,
            "After connecting on the website, tap Done:",
            [{"id": "pfm_done", "title": "Done — I connected"}],
        )
        db.set_conversation_state(sender, ConversationState.SETUP_MANUAL_CHOOSE, {})
    else:
        logger.error("PFM auth URL failed for %s: %s", sender, result.get("error"))
        await wa.send_text(
            sender,
            "⚠️ Could not generate a connection link right now.\n\n"
            "Please try again in a moment, or contact support.",
        )


async def handle_disconnect(db: BotDatabase, sender: str, text: str):
    """Disconnect a platform — removes token so user can reconnect a different account."""
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

    lines = ["*Connected Accounts:*\n"]
    if fb_token:
        lines.append(f"  Facebook: *{_account_label(fb_token, 'facebook')}*")
    if ig_token:
        lines.append(f"  Instagram: *{_account_label(ig_token, 'instagram')}*")
    lines.append("\nWhich account do you want to disconnect?")

    await wa.send_interactive_buttons(sender, "\n".join(lines), buttons)
    db.set_conversation_state(sender, ConversationState.SETUP_PLATFORM, {"action": "disconnect"})


async def handle_setup_step(
    db: BotDatabase, sender: str, text: str,
    state: ConversationState, data: dict,
):
    """Handle setup states and disconnect actions."""

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

    # --- SETUP_MANUAL_CHOOSE: waiting for "Done" after OAuth ---
    if state == ConversationState.SETUP_MANUAL_CHOOSE:
        normalized = text.lower().strip().replace(" ", "_")

        if normalized in ("pfm_done", "done"):
            await wa.send_text(sender, "🔄 Checking your connection...")
            from services.publisher import get_connected_accounts, store_accounts_for_sender
            accounts = await get_connected_accounts(sender)
            connected_platforms = [
                a.get("platform", "").lower() for a in accounts
                if a.get("platform", "").lower() in ("facebook", "instagram")
            ]

            if connected_platforms:
                await store_accounts_for_sender(db, sender, accounts)
                platform_list = " & ".join(sorted(set(p.title() for p in connected_platforms)))
                db.clear_conversation_state(sender)
                await wa.send_text(
                    sender,
                    f"✅ *{platform_list} connected!*\n\n"
                    f"You're all set. Send *post* to create your first post!",
                )
            else:
                from services.publisher import generate_auth_url
                result = await generate_auth_url(sender, "facebook")
                connect_url = result.get("url", "")
                await wa.send_text(
                    sender,
                    "⚠️ No accounts detected yet.\n\n"
                    f"Please complete the connection:\n{connect_url}\n\n"
                    "Make sure to approve all permissions, then tap *Done* again.",
                )
        else:
            # Re-send a fresh connect URL
            from services.publisher import generate_auth_url
            result = await generate_auth_url(sender, "facebook")
            connect_url = result.get("url", "")
            if connect_url:
                await wa.send_text(sender, f"Use this link to connect:\n{connect_url}")
            await wa.send_interactive_buttons(
                sender,
                "After connecting on the website, tap Done:",
                [{"id": "pfm_done", "title": "Done — I connected"}],
            )
        return
