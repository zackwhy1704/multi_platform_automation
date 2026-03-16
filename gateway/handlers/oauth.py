"""
Facebook OAuth flow — one-click platform connection.

Instead of asking users to copy-paste tokens from developers.facebook.com,
we send them a link that opens Facebook Login in their browser.

Flow:
  1. User sends "setup" → bot sends OAuth link
  2. User clicks link → Facebook Login dialog → grants permissions
  3. Facebook redirects to /auth/callback with auth code
  4. We exchange code for user token → get page tokens (permanent!) → store
  5. Notify user on WhatsApp: "Connected!"

Permissions requested:
  - pages_manage_posts: Post to Facebook Pages
  - pages_read_engagement: Read comments for auto-reply
  - instagram_basic: Access IG business account info
  - instagram_content_publish: Publish to Instagram
  - pages_show_list: List user's pages
"""

import logging
from typing import Optional
from urllib.parse import urlencode

import httpx

from shared.config import FB_APP_ID, FB_APP_SECRET, OAUTH_REDIRECT_URI, PUBLIC_BASE_URL
from shared.database import BotDatabase
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

OAUTH_SCOPES = ",".join([
    "pages_manage_posts",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
])


def get_oauth_url(phone_number_id: str) -> Optional[str]:
    """Generate the Facebook Login URL for a user."""
    if not FB_APP_ID or not OAUTH_REDIRECT_URI:
        return None

    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "state": phone_number_id,  # pass phone ID to identify user on callback
        "scope": OAUTH_SCOPES,
        "response_type": "code",
    }
    return f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"


async def handle_oauth_callback(code: str, state: str, db: BotDatabase) -> dict:
    """
    Process the OAuth callback from Facebook.

    Args:
        code: Authorization code from Facebook
        state: phone_number_id of the user
        db: Database instance

    Returns:
        dict with status and message
    """
    phone = state
    if not phone:
        return {"error": "Missing user identifier"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: Exchange code for short-lived user token
            token_resp = await client.get(
                f"{GRAPH_API_BASE}/oauth/access_token",
                params={
                    "client_id": FB_APP_ID,
                    "redirect_uri": OAUTH_REDIRECT_URI,
                    "client_secret": FB_APP_SECRET,
                    "code": code,
                },
            )
            if token_resp.status_code != 200:
                logger.error("Token exchange failed: %s", token_resp.text)
                await wa.send_text(phone, "Failed to connect your Facebook account. Please try again with *setup*.")
                return {"error": "Token exchange failed"}

            short_token = token_resp.json().get("access_token")

            # Step 2: Exchange for long-lived user token (60 days)
            ll_resp = await client.get(
                f"{GRAPH_API_BASE}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": FB_APP_ID,
                    "client_secret": FB_APP_SECRET,
                    "fb_exchange_token": short_token,
                },
            )
            long_lived_token = short_token
            if ll_resp.status_code == 200:
                long_lived_token = ll_resp.json().get("access_token", short_token)

            # Step 3: Get user's pages (page tokens from long-lived user token are permanent!)
            pages_resp = await client.get(
                f"{GRAPH_API_BASE}/me/accounts",
                params={
                    "access_token": long_lived_token,
                    "fields": "id,name,access_token,instagram_business_account",
                },
            )
            if pages_resp.status_code != 200:
                logger.error("Failed to get pages: %s", pages_resp.text)
                await wa.send_text(phone, "Connected but couldn't find your Pages. Make sure you have a Facebook Page.")
                return {"error": "No pages found"}

            pages = pages_resp.json().get("data", [])
            if not pages:
                await wa.send_text(
                    phone,
                    "No Facebook Pages found on your account.\n\n"
                    "You need a Facebook Page to post. Create one at facebook.com, then try *setup* again.",
                )
                return {"error": "No pages"}

            # Step 4: Store tokens for each page
            page = pages[0]  # Use first page
            page_token = page.get("access_token")
            page_id = page.get("id")
            page_name = page.get("name", "Your Page")

            # Save Facebook token with page name for identification
            db.save_platform_token(phone, "facebook", page_token, page_id,
                                   page_name=page_name, account_username=page_name)

            # Step 5: Check for Instagram Business Account + fetch username
            ig_account = page.get("instagram_business_account", {}).get("id")
            ig_connected = False
            ig_username = ""
            if ig_account:
                # Fetch Instagram username for account identification
                ig_resp = await client.get(
                    f"{GRAPH_API_BASE}/{ig_account}",
                    params={"fields": "username,name", "access_token": page_token},
                )
                if ig_resp.status_code == 200:
                    ig_data = ig_resp.json()
                    ig_username = ig_data.get("username", "")

                db.save_platform_token(phone, "instagram", page_token, ig_account,
                                       page_name=page_name, account_username=ig_username or page_name)
                ig_connected = True

            # Step 6: Notify user on WhatsApp
            msg = f"*Facebook connected!*\n\nPage: *{page_name}*\n"
            if ig_connected:
                ig_label = f"@{ig_username}" if ig_username else "Connected"
                msg += f"Instagram: *{ig_label}* (linked to your Page)\n"
            else:
                msg += "Instagram: Not linked to this Page\n"

            if len(pages) > 1:
                other_pages = ", ".join(p["name"] for p in pages[1:4])
                msg += f"\nOther pages found: {other_pages}\n(Currently using: {page_name})"

            msg += "\n\nYou're all set! Send *post* to create your first post."
            msg += "\nSend *disconnect* anytime to switch to a different account."
            await wa.send_text(phone, msg)

            db.clear_conversation_state(phone)

            return {
                "success": True,
                "page_name": page_name,
                "ig_connected": ig_connected,
            }

    except Exception as e:
        logger.error("OAuth callback error for %s: %s", phone, e)
        await wa.send_text(phone, "Something went wrong connecting your account. Please try *setup* again.")
        return {"error": str(e)}


# HTML for the OAuth result page (shown in browser after callback)
OAUTH_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Connected!</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4;color:#166534;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p><strong>Account connected!</strong></p>
<p>Return to WhatsApp — you'll see a confirmation message.</p>
</div></body></html>"""

OAUTH_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Connection Failed</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fef2f2;color:#991b1b;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#10007;</h1>
<p><strong>Connection failed</strong></p>
<p>Return to WhatsApp and send <strong>setup</strong> to try again.</p>
</div></body></html>"""
