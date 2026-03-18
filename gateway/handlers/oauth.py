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

import hashlib
import hmac
import logging
import time
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

# CSRF state signing — prevents forged callbacks
def _sign_state(phone_number_id: str) -> str:
    """Create HMAC-signed state param: phone_id.timestamp.signature"""
    ts = str(int(time.time()))
    payload = f"{phone_number_id}.{ts}"
    secret = (FB_APP_SECRET or "fallback-secret").encode()
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def _verify_state(state: str) -> Optional[str]:
    """Verify signed state param. Returns phone_number_id or None."""
    parts = state.split(".")
    if len(parts) == 3:
        phone_id, ts, sig = parts
        payload = f"{phone_id}.{ts}"
        secret = (FB_APP_SECRET or "fallback-secret").encode()
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(sig, expected):
            # Reject if older than 10 minutes
            try:
                if abs(time.time() - int(ts)) > 600:
                    logger.warning("OAuth state expired: %s", state)
                    return None
            except ValueError:
                return None
            return phone_id
    # Fallback: accept raw phone_number_id for backward compat
    if parts[0].isdigit() and len(parts) == 1:
        return state
    return None


def get_oauth_url(phone_number_id: str) -> Optional[str]:
    """Generate the Facebook Login URL for a user."""
    if not FB_APP_ID or not OAUTH_REDIRECT_URI:
        return None

    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "state": _sign_state(phone_number_id),
        "scope": OAUTH_SCOPES,
        "response_type": "code",
    }
    return f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"


async def handle_oauth_callback(code: str, state: str, db: BotDatabase) -> dict:
    """
    Process the OAuth callback from Facebook with comprehensive error handling.

    Returns:
        dict with status and message
    """
    # Verify CSRF state
    phone = _verify_state(state)
    if not phone:
        logger.warning("OAuth callback with invalid/expired state: %s", state)
        return {"error": "Invalid or expired link. Please send *setup* in WhatsApp to get a new link."}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
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
                error_data = token_resp.json() if token_resp.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error", {}).get("message", token_resp.text)
                error_code = error_data.get("error", {}).get("code", 0)

                logger.error("Token exchange failed (HTTP %s, code %s): %s",
                             token_resp.status_code, error_code, error_msg)

                # Specific error messages for common failures
                if "redirect_uri" in error_msg.lower() or error_code == 191:
                    user_msg = "Connection failed — redirect URL mismatch. Please contact support."
                elif "code has been used" in error_msg.lower() or "code has expired" in error_msg.lower():
                    user_msg = "That link has expired. Send *setup* to get a fresh link."
                elif error_code == 190:
                    user_msg = "Authentication expired. Send *setup* to try again."
                else:
                    user_msg = "Failed to connect your Facebook account. Send *setup* to try again."

                await wa.send_text(phone, user_msg)
                return {"error": f"Token exchange failed: {error_msg}"}

            token_data = token_resp.json()
            short_token = token_data.get("access_token", "")

            if not short_token:
                logger.error("Token exchange returned empty access_token")
                await wa.send_text(phone, "Facebook returned an empty token. Send *setup* to try again.")
                return {"error": "Empty access token"}

            # Step 2: Exchange for long-lived user token (60 days)
            long_lived_token = short_token
            ll_resp = await client.get(
                f"{GRAPH_API_BASE}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": FB_APP_ID,
                    "client_secret": FB_APP_SECRET,
                    "fb_exchange_token": short_token,
                },
            )
            if ll_resp.status_code == 200:
                ll_data = ll_resp.json()
                long_lived_token = ll_data.get("access_token", short_token)
                logger.info("Long-lived token obtained for %s (expires_in: %s)",
                            phone, ll_data.get("expires_in", "unknown"))
            else:
                logger.warning("Long-lived token exchange failed for %s (HTTP %s): %s — using short-lived token",
                               phone, ll_resp.status_code, ll_resp.text[:200])

            # Step 3: Validate token with a test API call
            me_resp = await client.get(
                f"{GRAPH_API_BASE}/me",
                params={"access_token": long_lived_token, "fields": "id,name"},
            )
            if me_resp.status_code != 200:
                logger.error("Token validation failed for %s: %s", phone, me_resp.text[:200])
                await wa.send_text(phone, "Your Facebook token is invalid. Send *setup* to try again.")
                return {"error": "Token validation failed"}

            # Step 4: Get user's pages
            pages_resp = await client.get(
                f"{GRAPH_API_BASE}/me/accounts",
                params={
                    "access_token": long_lived_token,
                    "fields": "id,name,access_token,instagram_business_account",
                },
            )

            if pages_resp.status_code != 200:
                error_data = pages_resp.json() if pages_resp.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error", {}).get("message", "")
                logger.error("Failed to get pages for %s: %s", phone, error_msg or pages_resp.text[:200])

                if "permission" in error_msg.lower():
                    await wa.send_text(phone,
                        "Connected but missing permissions.\n\n"
                        "When connecting, make sure to grant all requested permissions "
                        "(Pages, Instagram, posting).\n\nSend *setup* to try again.")
                else:
                    await wa.send_text(phone,
                        "Connected but couldn't find your Pages.\n"
                        "Make sure you have a Facebook Page.\n\nSend *setup* to try again.")
                return {"error": "No pages found"}

            pages = pages_resp.json().get("data", [])
            if not pages:
                await wa.send_text(
                    phone,
                    "No Facebook Pages found on your account.\n\n"
                    "You need a Facebook Page to post. Create one at facebook.com, then send *setup* again.",
                )
                return {"error": "No pages"}

            # Step 5: Validate page token before storing
            page = pages[0]
            page_token = page.get("access_token")
            page_id = page.get("id")
            page_name = page.get("name", "Your Page")

            # Validate page token works
            page_test = await client.get(
                f"{GRAPH_API_BASE}/{page_id}",
                params={"access_token": page_token, "fields": "id,name"},
            )
            if page_test.status_code != 200:
                logger.error("Page token validation failed for page %s: %s", page_id, page_test.text[:200])
                await wa.send_text(phone,
                    "Connected but your Page token is invalid.\n"
                    "This can happen if the app doesn't have full Page permissions.\n\n"
                    "Send *setup* to try again and grant all permissions.")
                return {"error": "Page token invalid"}

            # Store Facebook token
            db.save_platform_token(phone, "facebook", page_token, page_id,
                                   page_name=page_name, account_username=page_name)

            # Step 6: Check for Instagram Business Account
            ig_account = page.get("instagram_business_account", {}).get("id")
            ig_connected = False
            ig_username = ""
            if ig_account:
                try:
                    ig_resp = await client.get(
                        f"{GRAPH_API_BASE}/{ig_account}",
                        params={"fields": "username,name", "access_token": page_token},
                    )
                    if ig_resp.status_code == 200:
                        ig_data = ig_resp.json()
                        ig_username = ig_data.get("username", "")
                except Exception as ig_err:
                    logger.warning("Failed to fetch IG username for %s: %s", phone, ig_err)

                # Save Instagram even if username fetch failed
                db.save_platform_token(phone, "instagram", page_token, ig_account,
                                       page_name=page_name, account_username=ig_username or page_name)
                ig_connected = True

            # Step 7: Notify user on WhatsApp
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

    except httpx.TimeoutException:
        logger.error("OAuth callback timed out for %s", phone)
        await wa.send_text(phone,
            "Connection timed out — Facebook took too long to respond.\n"
            "Send *setup* to try again.")
        return {"error": "Timeout"}

    except httpx.ConnectError:
        logger.error("OAuth callback connection error for %s", phone)
        await wa.send_text(phone,
            "Couldn't reach Facebook servers.\n"
            "Send *setup* to try again in a moment.")
        return {"error": "Connection error"}

    except Exception as e:
        logger.error("OAuth callback error for %s: %s", phone, e, exc_info=True)
        await wa.send_text(phone, "Something went wrong connecting your account. Send *setup* to try again.")
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

OAUTH_DENIED_HTML = """<!DOCTYPE html>
<html><head><title>Permission Denied</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fefce8;color:#854d0e;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#8592;</h1>
<p><strong>Permission not granted</strong></p>
<p>You need to grant all requested permissions for the bot to work.</p>
<p>Return to WhatsApp and send <strong>setup</strong> to try again.</p>
</div></body></html>"""

OAUTH_EXPIRED_HTML = """<!DOCTYPE html>
<html><head><title>Link Expired</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fefce8;color:#854d0e;padding:20px;text-align:center}
.card{padding:40px;max-width:400px}
h1{font-size:48px;margin:0}p{font-size:18px;line-height:1.6}
</style></head>
<body><div class="card">
<h1>&#8635;</h1>
<p><strong>This link has expired</strong></p>
<p>Return to WhatsApp and send <strong>setup</strong> to get a new link.</p>
</div></body></html>"""
