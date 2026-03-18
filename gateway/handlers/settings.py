"""
Settings, platform setup, and disconnect handlers.

Primary flow: Facebook OAuth (one-click, connects FB + IG together).
Fallback flow: Manual token entry (works for any user, no App Review required).

Manual flow uses Facebook's Graph API Explorer — user gets a User Access Token,
pastes it here, and we extract the Page token + IG account server-side.
"""

import logging
import httpx

from shared.database import BotDatabase
from shared.config import FB_APP_ID, FB_APP_SECRET, PUBLIC_BASE_URL, WHATSAPP_BOT_PHONE
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa
from gateway.handlers.oauth import get_oauth_url

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}
GRAPH_API = "https://graph.facebook.com/v21.0"


def _looks_like_token(text: str) -> bool:
    """Check if text looks like a Facebook access token (EAA... 50+ chars)."""
    s = text.strip()
    return len(s) > 50 and s.startswith("EAA")


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


def _wa_return_btn(label: str = "Return to WhatsApp") -> str:
    """WhatsApp deep link for inline use in WhatsApp messages."""
    href = f"https://wa.me/{WHATSAPP_BOT_PHONE}" if WHATSAPP_BOT_PHONE else "https://wa.me/"
    return href


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
    """Start platform connection — OAuth is primary, manual token is parallel fallback."""
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
                f"Connect below to *switch to a different account*.\n\n"
            )

        await wa.send_text(
            sender,
            f"{status}"
            f"*Connect your Facebook & Instagram*\n\n"
            f"*Option 1 — One-click (recommended):*\n"
            f"Tap the link below to connect via Facebook Login:\n\n"
            f"{oauth_url}\n\n"
            f"_If Facebook shows an error, use Option 2 instead._",
        )
        await wa.send_interactive_buttons(
            sender,
            "Facebook Login not working? Connect manually instead:",
            [{"id": "connect_manually", "title": "Connect Manually"}],
        )
        # Keep state so both "Connect Manually" button AND direct token pastes are handled
        db.set_conversation_state(sender, ConversationState.SETUP_MANUAL_CHOOSE, {})

    else:
        # OAuth not configured — go straight to manual
        await _send_manual_token_guide(sender)
        db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, {})


async def _send_manual_token_guide(sender: str):
    """Send step-by-step instructions for getting a Facebook token manually."""
    guide_url = f"{PUBLIC_BASE_URL}/guide/connect-facebook" if PUBLIC_BASE_URL else None
    wa_url = _wa_return_btn()

    if guide_url:
        await wa.send_text(
            sender,
            "*Manual Connection*\n\n"
            "Follow this step-by-step guide to get your Facebook token:\n\n"
            f"📖 *Guide:* {guide_url}\n\n"
            "After getting the token, come back here and *paste it below*.\n\n"
            f"📲 *Return here:* {wa_url}\n\n"
            "_Type *cancel* to go back._",
        )
    else:
        await wa.send_text(
            sender,
            "*Manual Connection — Step by Step*\n\n"
            "1️⃣ Open: *developers.facebook.com/tools/explorer*\n\n"
            "2️⃣ Top-right dropdown → select your *Facebook App*\n\n"
            "3️⃣ Click *'Add a Permission'* and select:\n"
            "   • *pages_manage_posts*\n"
            "   • *pages_read_engagement*\n"
            "   • *instagram_basic*\n"
            "   • *instagram_content_publish*\n\n"
            "4️⃣ Click *'Generate Access Token'* (blue button)\n\n"
            "5️⃣ Click *'Continue as [Your Name]'* → grant *all permissions*\n\n"
            "6️⃣ Copy the long token from the *Access Token* field\n"
            "   (starts with *EAA...*)\n\n"
            "7️⃣ Paste the token here ↓\n\n"
            "_Type *cancel* to go back._",
        )


async def _validate_and_store_manual_token(sender: str, token: str, db: BotDatabase):
    """
    Validate a manually-pasted Facebook token, extract page info, exchange for
    long-lived token, detect linked Instagram, and store everything.
    """
    await wa.send_text(sender, "🔄 Validating your token, please wait...")

    try:
        async with httpx.AsyncClient(timeout=20) as client:

            # Step 1: Validate token is real
            me_resp = await client.get(
                f"{GRAPH_API}/me",
                params={"access_token": token, "fields": "id,name"},
            )
            if me_resp.status_code != 200:
                error_data = me_resp.json() if me_resp.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error", {}).get("message", "")
                logger.warning("Manual token validation failed for %s: %s", sender, error_msg or me_resp.text[:200])

                await wa.send_text(
                    sender,
                    "❌ *Invalid token.*\n\n"
                    "Make sure you copied the *full* token from Graph API Explorer "
                    "(it's a very long string starting with EAA...).\n\n"
                    "Paste the token again, or type *cancel* to exit.",
                )
                return

            me_data = me_resp.json()

            # Step 2: Exchange for long-lived token (60 days) if app credentials available
            long_token = token
            if FB_APP_ID and FB_APP_SECRET:
                ll_resp = await client.get(
                    f"{GRAPH_API}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": FB_APP_ID,
                        "client_secret": FB_APP_SECRET,
                        "fb_exchange_token": token,
                    },
                )
                if ll_resp.status_code == 200:
                    long_token = ll_resp.json().get("access_token", token)
                    logger.info("Long-lived token obtained for %s", sender)

            # Step 3: Get pages (works for user tokens; page tokens return empty)
            pages_resp = await client.get(
                f"{GRAPH_API}/me/accounts",
                params={
                    "access_token": long_token,
                    "fields": "id,name,access_token,instagram_business_account",
                },
            )

            pages = []
            if pages_resp.status_code == 200:
                pages = pages_resp.json().get("data", [])

            if pages:
                # User token — extract the first page's permanent page token
                page = pages[0]
                page_token = page.get("access_token", long_token)
                page_id = page.get("id", "")
                page_name = page.get("name", me_data.get("name", "Your Page"))
                ig_account = page.get("instagram_business_account", {}).get("id")
            else:
                # Already a page token — use as-is
                page_token = long_token
                page_id = me_data.get("id", "")
                page_name = me_data.get("name", "Your Page")
                ig_account = None

                # Try to find IG linked to this page
                ig_check = await client.get(
                    f"{GRAPH_API}/{page_id}",
                    params={"access_token": page_token,
                            "fields": "instagram_business_account"},
                )
                if ig_check.status_code == 200:
                    ig_account = ig_check.json().get(
                        "instagram_business_account", {}
                    ).get("id")

            # Step 4: Store Facebook
            db.save_platform_token(
                sender, "facebook", page_token, page_id,
                page_name=page_name, account_username=page_name,
            )

            # Step 5: Store Instagram if linked
            ig_connected = False
            ig_username = ""
            if ig_account:
                try:
                    ig_resp = await client.get(
                        f"{GRAPH_API}/{ig_account}",
                        params={"fields": "username,name", "access_token": page_token},
                    )
                    if ig_resp.status_code == 200:
                        ig_username = ig_resp.json().get("username", "")
                except Exception as e:
                    logger.warning("Failed to fetch IG username for %s: %s", sender, e)

                db.save_platform_token(
                    sender, "instagram", page_token, ig_account,
                    page_name=page_name, account_username=ig_username or page_name,
                )
                ig_connected = True

            # Step 6: Verify posting permission with a dry-run
            perm_ok = True
            perm_warning = ""
            try:
                perm_resp = await client.get(
                    f"{GRAPH_API}/{page_id}",
                    params={"access_token": page_token, "fields": "id,name"},
                )
                if perm_resp.status_code != 200:
                    perm_ok = False
                    perm_warning = (
                        "\n\n⚠️ *Warning:* Your token may lack posting permissions.\n"
                        "If posting fails, use *setup* → OAuth link (Option 1) instead — "
                        "it grants all required permissions automatically."
                    )
            except Exception:
                pass

            # Step 7: Confirm to user
            msg = f"✅ *Facebook connected!*\n\nPage: *{page_name}*\n"
            if ig_connected:
                ig_label = f"@{ig_username}" if ig_username else "Linked"
                msg += f"Instagram: *{ig_label}* (linked to your Page)\n"
            else:
                msg += "Instagram: Not linked to this Page\n"

            if pages and len(pages) > 1:
                other = ", ".join(p["name"] for p in pages[1:3])
                msg += f"\n_Other pages found: {other}_\n_(Currently using: {page_name})_"

            msg += perm_warning
            msg += "\n\nSend *post* to create your first post!"

            db.clear_conversation_state(sender)
            await wa.send_text(sender, msg)

    except httpx.TimeoutException:
        await wa.send_text(
            sender,
            "⏱️ Request timed out. Please paste the token again, or type *cancel* to exit.",
        )
    except Exception as e:
        logger.error("Manual token validation error for %s: %s", sender, e, exc_info=True)
        await wa.send_text(
            sender,
            "❌ Something went wrong. Please paste the token again, or type *cancel*.",
        )


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
    """Handle manual token setup, manual-choose state, and disconnect actions."""

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

    # --- MANUAL CHOOSE STATE (shown OAuth + waiting for "Connect Manually" button or token paste) ---
    if state == ConversationState.SETUP_MANUAL_CHOOSE:
        # Normalize: accept both button ID "connect_manually" and typed "connect manually"
        normalized = text.lower().strip().replace(" ", "_")

        if normalized == "connect_manually":
            await _send_manual_token_guide(sender)
            db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, {})
        elif _looks_like_token(text):
            # User skipped the guide and pasted a token directly — handle it
            db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, {})
            await _validate_and_store_manual_token(sender, text.strip(), db)
        else:
            # Re-show the options
            await wa.send_interactive_buttons(
                sender,
                "Tap the button below to connect manually, or tap the OAuth link sent earlier.\n\n"
                "_You can also paste a Facebook token directly here._",
                [{"id": "connect_manually", "title": "Connect Manually"}],
            )
        return

    # --- PLATFORM CHOICE (legacy manual-only path when OAuth not configured) ---
    if state == ConversationState.SETUP_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_text(sender, "Please choose Facebook or Instagram.")
            return

        data["platform"] = platform
        if platform == "facebook":
            db.set_conversation_state(sender, ConversationState.SETUP_FB_TOKEN, data)
            await _send_manual_token_guide(sender)
        elif platform == "instagram":
            db.set_conversation_state(sender, ConversationState.SETUP_IG_TOKEN, data)
            await wa.send_text(
                sender,
                "Instagram uses the same token as your Facebook Page.\n\n"
                "Follow the same guide to get your Facebook Page token — "
                "we'll automatically link your Instagram account.\n\n"
                "*Paste your Facebook Page token below:*",
            )

    # --- MANUAL FACEBOOK TOKEN ENTRY ---
    elif state == ConversationState.SETUP_FB_TOKEN:
        token = text.strip()
        if not _looks_like_token(token):
            await wa.send_text(
                sender,
                "That doesn't look like a valid token.\n\n"
                "The token is a very long string (100+ characters) starting with *EAA...*\n"
                "Please paste the full token, or type *cancel* to exit.",
            )
            return
        await _validate_and_store_manual_token(sender, token, db)

    # --- MANUAL INSTAGRAM TOKEN ENTRY (same as FB — page token covers both) ---
    elif state == ConversationState.SETUP_IG_TOKEN:
        token = text.strip()
        if not _looks_like_token(token):
            await wa.send_text(
                sender,
                "That doesn't look like a valid token. Please paste the full token.",
            )
            return
        await _validate_and_store_manual_token(sender, token, db)
