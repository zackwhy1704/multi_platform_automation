"""
WhatsApp Gateway — FastAPI application.
Receives Meta Cloud API webhooks and dispatches to conversation handlers.
Includes OAuth callback, media serving, payment redirect pages, and Stripe webhook.

This is the SINGLE deployed service on Railway — all routes live here.
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import stripe
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, FileResponse

from shared.config import (
    WHATSAPP_VERIFY_TOKEN,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    MONTHLY_CREDITS,
    PAYMENT_SERVER_URL,
    WHATSAPP_BOT_PHONE,
    FB_APP_ID,
    OAUTH_REDIRECT_URI,
    PUBLIC_BASE_URL,
)
from shared.database import BotDatabase
from shared.credits import CreditManager
from gateway.router import handle_incoming_message
from gateway.handlers.oauth import (
    handle_oauth_callback,
    OAUTH_SUCCESS_HTML,
    OAUTH_ERROR_HTML,
    OAUTH_DENIED_HTML,
    OAUTH_EXPIRED_HTML,
    _verify_state,
)
from gateway.media import MEDIA_DIR
from gateway import whatsapp_client as wa

logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

stripe.api_key = STRIPE_SECRET_KEY

db: BotDatabase = None


def _seed_defaults(database: BotDatabase):
    """Insert default promo codes if they don't exist yet (idempotent)."""
    defaults = [
        ("CATALYX50", 50, None),
        ("ADMIN99", 999999, None),
        ("FIRSTMONTHFREE", 1500, None),
    ]
    for code, credits, max_uses in defaults:
        try:
            database.execute_query(
                "INSERT INTO promo_codes (code, credits_granted, max_uses, active) "
                "VALUES (%s, %s, %s, TRUE) ON CONFLICT DO NOTHING",
                (code, credits, max_uses),
            )
        except Exception as e:
            logger.warning("Could not seed promo code %s: %s", code, e)


def _run_migrations(database: BotDatabase):
    """Run idempotent schema migrations on startup."""
    migrations = [
        # Add pfm_profile_key column if it doesn't exist (Post For Me integration)
        "ALTER TABLE platform_tokens ADD COLUMN IF NOT EXISTS pfm_profile_key VARCHAR(255)",
        # Add webhook_events table if missing
        "CREATE TABLE IF NOT EXISTS webhook_events (event_id VARCHAR(255) PRIMARY KEY, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP)",
    ]
    for sql in migrations:
        try:
            database.execute_query(sql)
        except Exception as e:
            logger.warning("Migration skipped: %s — %s", sql[:60], e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = BotDatabase()
    app.state.db = db
    logger.info("Gateway started — database pool ready")
    _run_migrations(db)
    _seed_defaults(db)
    yield
    db.close()
    logger.info("Gateway shutdown — pool closed")


app = FastAPI(title="Multi-Platform Automation Gateway", lifespan=lifespan)


@app.get("/")
async def health_check():
    """Health check endpoint for Railway."""
    return {"status": "ok", "service": "gateway"}


# =========================================================================
# WHATSAPP WEBHOOK
# =========================================================================

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification (GET challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    entry = body.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            for i, msg in enumerate(messages):
                sender = msg.get("from", "")
                contact_name = contacts[i]["profile"]["name"] if i < len(contacts) else ""

                await handle_incoming_message(
                    db=app.state.db,
                    sender=sender,
                    message=msg,
                    contact_name=contact_name,
                )

    return {"status": "ok"}


# =========================================================================
# FACEBOOK OAUTH — DEBUG + CALLBACK
# =========================================================================

@app.get("/auth/debug")
async def oauth_debug():
    """Debug endpoint: shows OAuth config and generates a test URL."""
    from gateway.handlers.oauth import get_oauth_url, OAUTH_SCOPES
    test_url = get_oauth_url("debug_test_user")
    return {
        "fb_app_id": FB_APP_ID or "(not set)",
        "redirect_uri": OAUTH_REDIRECT_URI or "(not set)",
        "scopes": OAUTH_SCOPES,
        "oauth_url": test_url or "(cannot generate — missing FB_APP_ID or OAUTH_REDIRECT_URI)",
        "public_base_url": PUBLIC_BASE_URL or "(not set)",
        "tip": "Open the oauth_url in a browser to test the Facebook Login flow.",
    }


@app.get("/auth/connect/{phone_id}")
async def connect_page(phone_id: str):
    """Self-service Facebook Login page using JS SDK.

    This bypasses the server-side OAuth flow entirely. The user logs in
    client-side, grants permissions, and we extract the Page Access Token
    via JS SDK — then POST it back to our server to store.
    """
    wa_url = f"https://wa.me/{WHATSAPP_BOT_PHONE}" if WHATSAPP_BOT_PHONE else "#"
    html = f"""<!DOCTYPE html>
<html><head>
<title>Connect Facebook</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;margin:0;padding:20px;background:#f8f9fa;
     display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#fff;border-radius:12px;padding:32px;max-width:420px;width:100%;
      box-shadow:0 2px 12px rgba(0,0,0,.1);text-align:center}}
h2{{margin:0 0 8px;color:#1a1a1a}}
.subtitle{{color:#666;margin-bottom:24px;font-size:14px}}
.btn{{display:inline-block;padding:14px 28px;border-radius:8px;font-size:16px;
     font-weight:600;text-decoration:none;border:none;cursor:pointer;width:100%;box-sizing:border-box}}
.btn-fb{{background:#1877F2;color:#fff;margin-bottom:12px}}
.btn-fb:hover{{background:#166FE5}}
.btn-wa{{background:#25D366;color:#fff;margin-top:16px}}
.btn-disabled{{background:#ccc;cursor:not-allowed}}
#status{{margin:16px 0;padding:12px;border-radius:8px;display:none;font-size:14px;text-align:left}}
.status-ok{{background:#f0fdf4;color:#166534;display:block!important}}
.status-err{{background:#fef2f2;color:#991b1b;display:block!important}}
.status-wait{{background:#eff6ff;color:#1e40af;display:block!important}}
.perms{{text-align:left;margin:16px 0;padding:12px;background:#f8f9fa;border-radius:8px;font-size:13px}}
.perms li{{margin:4px 0}}
</style>
</head><body>
<div class="card">
  <h2>Connect Your Facebook Page</h2>
  <p class="subtitle">Log in with Facebook to grant posting permissions</p>

  <div class="perms">
    <strong>Permissions requested:</strong>
    <ul>
      <li>Manage and publish posts to your Page</li>
      <li>Read Page engagement (for stats)</li>
      <li>Access linked Instagram account</li>
    </ul>
  </div>

  <button id="loginBtn" class="btn btn-fb" onclick="doLogin()">
    Log in with Facebook
  </button>

  <div id="status"></div>

  <a href="{wa_url}" id="waBtn" class="btn btn-wa" style="display:none">
    ↩ Back to WhatsApp
  </a>
</div>

<script>
const PHONE_ID = "{phone_id}";
const APP_ID = "{FB_APP_ID}";
const BASE_URL = "{PUBLIC_BASE_URL}";

// Load Facebook SDK
window.fbAsyncInit = function() {{
  FB.init({{
    appId: APP_ID,
    cookie: true,
    xfbml: false,
    version: 'v21.0'
  }});
}};
(function(d, s, id) {{
  var js, fjs = d.getElementsByTagName(s)[0];
  if (d.getElementById(id)) return;
  js = d.createElement(s); js.id = id;
  js.src = "https://connect.facebook.net/en_US/sdk.js";
  fjs.parentNode.insertBefore(js, fjs);
}}(document, 'script', 'facebook-jssdk'));

function setStatus(msg, cls) {{
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status-' + cls;
}}

function showWaBtn() {{
  document.getElementById('waBtn').style.display = 'inline-block';
}}

async function doLogin() {{
  const btn = document.getElementById('loginBtn');
  btn.classList.add('btn-disabled');
  btn.textContent = 'Connecting...';
  setStatus('Opening Facebook Login...', 'wait');

  FB.login(function(response) {{
    if (response.authResponse) {{
      const userToken = response.authResponse.accessToken;
      setStatus('Logged in! Fetching your Pages...', 'wait');
      fetchPages(userToken);
    }} else {{
      setStatus('Login cancelled or not fully authorized. Please try again and grant all permissions.', 'err');
      btn.classList.remove('btn-disabled');
      btn.textContent = 'Log in with Facebook';
    }}
  }}, {{
    scope: 'pages_manage_posts,pages_read_engagement,pages_show_list,instagram_basic,instagram_content_publish,public_profile',
    auth_type: 'rerequest'
  }});
}}

function fetchPages(userToken) {{
  FB.api('/me/accounts', {{
    fields: 'id,name,access_token,instagram_business_account',
    access_token: userToken
  }}, function(resp) {{
    if (resp.error) {{
      setStatus('Error fetching pages: ' + resp.error.message, 'err');
      showWaBtn();
      return;
    }}
    if (!resp.data || resp.data.length === 0) {{
      setStatus('No Facebook Pages found. You need a Facebook Page to use this bot. Create one at facebook.com.', 'err');
      showWaBtn();
      return;
    }}

    const page = resp.data[0];
    const pageToken = page.access_token;
    const pageId = page.id;
    const pageName = page.name;
    const igAccount = page.instagram_business_account ? page.instagram_business_account.id : null;

    setStatus('Found page: ' + pageName + '. Saving...', 'wait');
    saveToken(pageToken, pageId, pageName, igAccount, userToken);
  }});
}}

async function saveToken(pageToken, pageId, pageName, igAccount, userToken) {{
  try {{
    // Exchange for long-lived token server-side, then store
    const resp = await fetch(BASE_URL + '/auth/store-token', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        phone_id: PHONE_ID,
        page_token: pageToken,
        page_id: pageId,
        page_name: pageName,
        ig_account_id: igAccount,
        user_token: userToken
      }})
    }});

    const result = await resp.json();
    if (result.success) {{
      setStatus('✅ Connected! Page: ' + pageName +
        (result.ig_connected ? ' | Instagram: connected' : '') +
        '\\n\\nYou will receive a confirmation in WhatsApp.', 'ok');
    }} else {{
      setStatus('Error: ' + (result.error || 'Unknown error'), 'err');
    }}
  }} catch(e) {{
    setStatus('Network error: ' + e.message, 'err');
  }}
  showWaBtn();
}}
</script>
</body></html>"""
    return HTMLResponse(html)


@app.post("/auth/store-token")
async def store_token(request: Request):
    """Receive Page Access Token from the JS SDK login flow and store it."""
    import httpx as _httpx

    try:
        body = await request.json()
        phone_id = body.get("phone_id", "")
        page_token = body.get("page_token", "")
        page_id = body.get("page_id", "")
        page_name = body.get("page_name", "")
        ig_account_id = body.get("ig_account_id")
        user_token = body.get("user_token", "")

        if not phone_id or not page_token or not page_id:
            return {"success": False, "error": "Missing required fields"}

        db: BotDatabase = app.state.db

        # Exchange user token for long-lived, then get permanent page token
        final_page_token = page_token
        if user_token and FB_APP_ID:
            from shared.config import FB_APP_SECRET
            try:
                async with _httpx.AsyncClient(timeout=15) as client:
                    ll_resp = await client.get(
                        "https://graph.facebook.com/v21.0/oauth/access_token",
                        params={
                            "grant_type": "fb_exchange_token",
                            "client_id": FB_APP_ID,
                            "client_secret": FB_APP_SECRET,
                            "fb_exchange_token": user_token,
                        },
                    )
                    if ll_resp.status_code == 200:
                        ll_token = ll_resp.json().get("access_token", user_token)
                        pages_resp = await client.get(
                            "https://graph.facebook.com/v21.0/me/accounts",
                            params={
                                "access_token": ll_token,
                                "fields": "id,access_token",
                            },
                        )
                        if pages_resp.status_code == 200:
                            for p in pages_resp.json().get("data", []):
                                if p.get("id") == page_id:
                                    final_page_token = p.get("access_token", page_token)
                                    break
            except Exception as e:
                logger.warning("Long-lived token exchange failed: %s", e)

        # Store Facebook
        db.save_platform_token(phone_id, "facebook", final_page_token, page_id,
                               page_name=page_name, account_username=page_name)

        # Store Instagram if linked
        ig_connected = False
        if ig_account_id:
            try:
                async with _httpx.AsyncClient(timeout=10) as client:
                    ig_resp = await client.get(
                        f"https://graph.facebook.com/v21.0/{ig_account_id}",
                        params={"fields": "username,name", "access_token": final_page_token},
                    )
                    ig_username = ""
                    if ig_resp.status_code == 200:
                        ig_username = ig_resp.json().get("username", "")
                    db.save_platform_token(phone_id, "instagram", final_page_token, ig_account_id,
                                           page_name=page_name, account_username=ig_username or page_name)
                    ig_connected = True
            except Exception as e:
                logger.warning("IG account fetch failed: %s", e)
                db.save_platform_token(phone_id, "instagram", final_page_token, ig_account_id,
                                       page_name=page_name)
                ig_connected = True

        db.clear_conversation_state(phone_id)

        # Notify user on WhatsApp
        msg = f"✅ *Facebook connected!*\n\nPage: *{page_name}*"
        if ig_connected:
            msg += "\nInstagram: Connected"
        msg += "\n\nSend *post* to create your first post!"
        await wa.send_text(phone_id, msg)

        return {"success": True, "ig_connected": ig_connected}

    except Exception as e:
        logger.error("store-token error: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


@app.get("/auth/callback")
async def oauth_callback(request: Request):
    """Facebook OAuth callback — exchanges auth code for tokens."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    error_reason = request.query_params.get("error_reason", "")

    # User denied permissions
    if error == "access_denied" or error_reason == "user_denied":
        logger.info("OAuth: user denied permissions (state=%s)", state)
        # Try to notify user via WhatsApp
        if state:
            phone = _verify_state(state)
            if phone:
                await wa.send_text(phone,
                    "You didn't grant the required permissions.\n\n"
                    "The bot needs access to your Pages and Instagram to post on your behalf.\n"
                    "Send *setup* to try again — make sure to allow all permissions.")
        return HTMLResponse(OAUTH_DENIED_HTML)

    if error:
        logger.warning("OAuth error: %s — %s", error, request.query_params.get("error_description"))
        return HTMLResponse(OAUTH_ERROR_HTML)

    if not code or not state:
        return HTMLResponse(OAUTH_ERROR_HTML)

    # Verify state hasn't expired
    phone = _verify_state(state)
    if not phone:
        return HTMLResponse(OAUTH_EXPIRED_HTML)

    result = await handle_oauth_callback(code, state, app.state.db)
    if result.get("success"):
        return HTMLResponse(OAUTH_SUCCESS_HTML)

    # Show the actual error on the error page for debugging
    error_detail = result.get("error", "Unknown error")
    logger.error("OAuth callback failed: %s", error_detail)
    error_html = OAUTH_ERROR_HTML.replace(
        "Return to WhatsApp and send <strong>setup</strong> to try again.",
        f"Return to WhatsApp and send <strong>setup</strong> to try again."
        f"<br><br><small style='color:#666'>Error: {error_detail}</small>",
    )
    return HTMLResponse(error_html)


# =========================================================================
# POST FOR ME WEBHOOK — receives social.account.created events
# =========================================================================

@app.post("/pfm/webhook")
async def pfm_webhook(request: Request):
    """Post For Me webhook handler.

    Fires when a user completes OAuth and a social account is created.
    We use external_id (=sender phone) to map the account back to the user.
    """
    try:
        body = await request.json()
        event_type = body.get("event_type") or body.get("type", "")
        data = body.get("data") or body.get("account") or {}

        logger.info("PFM webhook: %s", event_type)

        if event_type == "social.account.created":
            account_id = data.get("id", "")
            platform = (data.get("platform") or "").lower()
            external_id = data.get("external_id") or data.get("externalId") or ""
            username = data.get("username") or data.get("name") or ""

            if external_id and account_id and platform in ("facebook", "instagram"):
                db_instance: BotDatabase = app.state.db

                db_instance.save_platform_token(
                    external_id, platform, account_id, account_id,
                    page_name=username, account_username=username,
                )
                try:
                    db_instance.execute_query(
                        "UPDATE platform_tokens SET pfm_profile_key = %s "
                        "WHERE phone_number_id = %s AND platform = %s",
                        (account_id, external_id, platform),
                    )
                except Exception as e:
                    logger.warning("pfm_webhook: could not write pfm_profile_key: %s", e)

                db_instance.clear_conversation_state(external_id)
                await wa.send_text(
                    external_id,
                    f"✅ *{platform.title()} connected!*\n\n"
                    f"Account: *{username or account_id}*\n\n"
                    "Send *post* to create your first post!",
                )
                logger.info("PFM: stored %s account %s for %s", platform, account_id, external_id)

    except Exception as e:
        logger.error("pfm_webhook error: %s", e, exc_info=True)

    return {"status": "ok"}


@app.get("/pfm/webhook")
async def pfm_webhook_ping():
    """Respond to Post For Me webhook URL verification ping."""
    return {"status": "ok"}


# =========================================================================
# MEDIA SERVING
# =========================================================================

@app.get("/media/{filename}")
async def serve_media(filename: str):
    """Serve downloaded media files (for Facebook/Instagram Graph API to access)."""
    file_path = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(file_path):
        return Response(status_code=404)
    return FileResponse(file_path)


# =========================================================================
# PAYMENT REDIRECT PAGES (Stripe Checkout redirects here)
# =========================================================================

def _wa_btn(label: str = "Return to WhatsApp") -> str:
    href = f"https://wa.me/{WHATSAPP_BOT_PHONE}" if WHATSAPP_BOT_PHONE else "https://wa.me/"
    return (
        f'<a href="{href}" style="display:inline-block;margin-top:24px;padding:14px 28px;'
        f'background:#25D366;color:#fff;text-decoration:none;border-radius:8px;'
        f'font-size:16px;font-weight:600;">&#x21A9; {label}</a>'
    )


_SUCCESS_HTML = f"""<!DOCTYPE html>
<html><head><title>Payment Successful</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#f0fdf4;color:#166534;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p><strong>Payment successful!</strong></p>
<p>Your subscription is being activated. You'll receive a confirmation message in WhatsApp shortly.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""

_CANCEL_HTML = f"""<!DOCTYPE html>
<html><head><title>Payment Cancelled</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#fefce8;color:#854d0e;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#8592;</h1>
<p>Payment cancelled. No charges were made.</p>
<p>Send <strong>subscribe</strong> in WhatsApp to try again.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""

_PORTAL_RETURN_HTML = f"""<!DOCTYPE html>
<html><head><title>Subscription Updated</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;
min-height:100vh;margin:0;background:#eff6ff;color:#1e40af;padding:20px;text-align:center}}
.card{{padding:40px;max-width:400px}}
h1{{font-size:48px;margin:0}}p{{font-size:18px;line-height:1.6}}
</style></head>
<body><div class="card">
<h1>&#10003;</h1>
<p>Subscription updated.</p>
{_wa_btn("Back to WhatsApp")}
</div></body></html>"""


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success():
    """Redirect page after Stripe Checkout. Activation happens via webhook."""
    return HTMLResponse(_SUCCESS_HTML)


@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel():
    """Redirect page when user cancels Stripe Checkout."""
    return HTMLResponse(_CANCEL_HTML)


@app.get("/payment/portal-return", response_class=HTMLResponse)
async def portal_return():
    """Return page after Stripe Customer Portal."""
    return HTMLResponse(_PORTAL_RETURN_HTML)


# =========================================================================
# STRIPE WEBHOOK — single source of truth for payment events
# =========================================================================

def _get_subscription_period_end(subscription) -> int | None:
    """Get current_period_end from Stripe subscription (handles old + new API)."""
    period_end = getattr(subscription, "current_period_end", None)
    if period_end is None:
        try:
            period_end = subscription["current_period_end"]
        except (KeyError, TypeError):
            pass
    if period_end is None:
        try:
            items = getattr(subscription, "items", None)
            if callable(items):
                items = items()
            item_list = getattr(items, "data", []) if items else []
            if item_list:
                period_end = getattr(item_list[0], "current_period_end", None)
        except (AttributeError, IndexError):
            pass
    return period_end


def _find_user_by_stripe(customer_id: str, subscription_id: str = None):
    """Find user by Stripe customer or subscription ID."""
    if subscription_id:
        row = db.execute_query(
            "SELECT phone_number_id FROM users WHERE stripe_subscription_id = %s",
            (subscription_id,), fetch="one",
        )
        if row:
            return row
    if customer_id:
        return db.execute_query(
            "SELECT phone_number_id FROM users WHERE stripe_customer_id = %s",
            (customer_id,), fetch="one",
        )
    return None


def _is_duplicate_event(event_id: str) -> bool:
    """Check if we've already processed this Stripe event (idempotency)."""
    try:
        existing = db.execute_query(
            "SELECT 1 FROM webhook_events WHERE event_id = %s", (event_id,), fetch="one"
        )
        if existing:
            return True
        db.execute_query(
            "INSERT INTO webhook_events (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (event_id,),
        )
        return False
    except Exception as e:
        # Table might not exist yet — log and proceed (non-blocking)
        logger.warning("Idempotency check failed (table may not exist): %s", e)
        return False


async def _notify_whatsapp(phone: str, msg: str):
    """Send WhatsApp notification directly (no Celery needed)."""
    try:
        await wa.send_text(phone, msg)
    except Exception as e:
        logger.error("Failed to notify %s: %s", phone, e)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except ValueError:
            logger.warning("Stripe webhook: invalid payload")
            return Response(status_code=400)
        except stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook: invalid signature")
            return Response(status_code=400)
    else:
        # No webhook secret configured — parse raw (dev/testing only)
        import json
        event = json.loads(payload)

    event_id = event.get("id", "")
    event_type = event.get("type", "") if isinstance(event, dict) else event["type"]
    logger.info("Stripe event: %s (id=%s)", event_type, event_id)

    # Idempotency: skip duplicate events
    if event_id and _is_duplicate_event(event_id):
        logger.info("Duplicate Stripe event skipped: %s", event_id)
        return {"status": "duplicate"}

    data_object = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data_object)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data_object)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data_object)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data_object)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data_object)

    return {"status": "success"}


async def _handle_checkout_completed(session):
    """Handle successful checkout — subscriptions OR one-time credit pack purchases."""
    try:
        customer_id = session.get("customer") if isinstance(session, dict) else getattr(session, "customer", None)
        subscription_id = session.get("subscription") if isinstance(session, dict) else getattr(session, "subscription", None)
        mode = session.get("mode") if isinstance(session, dict) else getattr(session, "mode", None)
        metadata = session.get("metadata", {}) if isinstance(session, dict) else getattr(session, "metadata", {})
        phone = (session.get("client_reference_id") if isinstance(session, dict) else getattr(session, "client_reference_id", None))
        if not phone:
            phone = metadata.get("phone_number_id") if isinstance(metadata, dict) else getattr(metadata, "phone_number_id", None)
        purchase_type = metadata.get("purchase_type", "") if isinstance(metadata, dict) else getattr(metadata, "purchase_type", "")

        if not phone:
            logger.warning("checkout.session.completed missing phone: %s",
                           session.get("id") if isinstance(session, dict) else getattr(session, "id", "?"))
            return

        if mode == "subscription" and subscription_id:
            days = 30
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                period_end = _get_subscription_period_end(sub)
                if period_end:
                    days = max(1, (datetime.fromtimestamp(period_end) - datetime.now()).days)
            except Exception:
                pass

            db.activate_subscription(phone, stripe_customer_id=customer_id,
                                     stripe_subscription_id=subscription_id, days=days)

            await _notify_whatsapp(
                phone,
                "Payment Successful!\n\n"
                f"Your subscription is ACTIVE with *{MONTHLY_CREDITS} credits*.\n\n"
                "Send *post* to start automating!",
            )

        elif mode == "payment" and purchase_type.startswith("pack_"):
            try:
                pack_credits = int(purchase_type.replace("pack_", ""))
            except ValueError:
                logger.error("Invalid pack purchase_type: %s", purchase_type)
                return

            if customer_id:
                db.execute_query(
                    "UPDATE users SET stripe_customer_id = COALESCE(stripe_customer_id, %s) WHERE phone_number_id = %s",
                    (customer_id, phone),
                )

            db.grant_credits(phone, pack_credits, reason=f"credit_pack_{pack_credits}")

            await _notify_whatsapp(
                phone,
                f"Payment Successful!\n\n"
                f"*{pack_credits:,} credits* have been added to your account.\n\n"
                "Send *credits* to check your balance.",
            )
        else:
            logger.warning("Unhandled checkout mode=%s for session %s", mode,
                           session.get("id") if isinstance(session, dict) else getattr(session, "id", "?"))

    except Exception as e:
        logger.error("Error in checkout.session.completed: %s", e, exc_info=True)


async def _handle_subscription_updated(subscription):
    """Handle subscription renewals and cancellations."""
    try:
        customer_id = getattr(subscription, "customer", None) or (subscription.get("customer") if isinstance(subscription, dict) else None)
        subscription_id = getattr(subscription, "id", None) or (subscription.get("id") if isinstance(subscription, dict) else None)
        cancel_at_period_end = getattr(subscription, "cancel_at_period_end", None)
        if cancel_at_period_end is None and isinstance(subscription, dict):
            cancel_at_period_end = subscription.get("cancel_at_period_end", False)
        status = getattr(subscription, "status", None) or (subscription.get("status") if isinstance(subscription, dict) else None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if cancel_at_period_end:
            period_end = _get_subscription_period_end(subscription)
            cancel_date = datetime.fromtimestamp(period_end).strftime("%B %d, %Y") if period_end else "your billing period end"

            await _notify_whatsapp(
                phone,
                f"Subscription Cancelled\n\n"
                f"Access continues until: {cancel_date}\n"
                "You won't be charged again.\n\n"
                "Send *subscribe* to resubscribe anytime.",
            )
        elif status == "active":
            cm = CreditManager(db)
            cm.reset_credits(phone, MONTHLY_CREDITS)
            await _notify_whatsapp(phone, f"Subscription renewed! Credits reset to *{MONTHLY_CREDITS}*.")

    except Exception as e:
        logger.error("Error in subscription.updated: %s", e, exc_info=True)


async def _handle_subscription_deleted(subscription):
    """Deactivate subscription."""
    try:
        customer_id = getattr(subscription, "customer", None) or (subscription.get("customer") if isinstance(subscription, dict) else None)
        subscription_id = getattr(subscription, "id", None) or (subscription.get("id") if isinstance(subscription, dict) else None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        db.deactivate_subscription(phone)
        await _notify_whatsapp(phone, "Subscription Ended\n\nYour free credits are still available.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in subscription.deleted: %s", e, exc_info=True)


async def _handle_payment_failed(invoice):
    """Notify user of failed payment."""
    try:
        customer_id = invoice.get("customer") if isinstance(invoice, dict) else getattr(invoice, "customer", None)
        subscription_id = invoice.get("subscription") if isinstance(invoice, dict) else getattr(invoice, "subscription", None)
        next_attempt = invoice.get("next_payment_attempt") if isinstance(invoice, dict) else getattr(invoice, "next_payment_attempt", None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]

        if next_attempt:
            retry_date = datetime.fromtimestamp(next_attempt).strftime("%B %d, %Y")
            await _notify_whatsapp(
                phone,
                f"Payment Failed\n\n"
                f"Please update your payment method.\n"
                f"Retry on: {retry_date}\n\n"
                "Send *cancel* to manage your subscription.",
            )
        else:
            db.deactivate_subscription(phone)
            await _notify_whatsapp(phone, "Subscription cancelled due to payment failure.\nSend *subscribe* to resubscribe.")

    except Exception as e:
        logger.error("Error in invoice.payment_failed: %s", e, exc_info=True)


async def _handle_invoice_paid(invoice):
    """Reset credits on successful invoice payment (subscription renewal)."""
    try:
        customer_id = invoice.get("customer") if isinstance(invoice, dict) else getattr(invoice, "customer", None)
        subscription_id = invoice.get("subscription") if isinstance(invoice, dict) else getattr(invoice, "subscription", None)

        user = _find_user_by_stripe(customer_id, subscription_id)
        if not user:
            return

        phone = user["phone_number_id"]
        cm = CreditManager(db)
        cm.reset_credits(phone, MONTHLY_CREDITS)
        logger.info("Credits reset for %s on invoice.paid", phone)

    except Exception as e:
        logger.error("Error in invoice.paid: %s", e, exc_info=True)


@app.get("/connect/{phone_id}", response_class=HTMLResponse)
async def connect_fallback(phone_id: str):
    """Fallback connection page — generates a fresh PFM OAuth link for stuck users."""
    from services.publisher import generate_auth_url
    wa_url = f"https://wa.me/{WHATSAPP_BOT_PHONE}" if WHATSAPP_BOT_PHONE else "https://wa.me/"

    result = await generate_auth_url(phone_id, "facebook")
    connect_url = result.get("url", "") if result.get("success") else ""

    if connect_url:
        connect_section = f"""
      <p class="subtitle">Tap the button below to connect your Facebook Page and Instagram account.</p>
      <a href="{connect_url}" class="btn btn-primary">Connect with Facebook</a>
      <p class="note">After connecting, return to WhatsApp and send <strong>done</strong> to confirm.</p>"""
    else:
        connect_section = """
      <p class="subtitle error">Could not generate a connection link right now. Please return to WhatsApp and try <strong>setup</strong> again in a moment.</p>"""

    html = f"""<!DOCTYPE html>
<html><head>
<title>Connect Your Account</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;
     min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#fff;border-radius:16px;padding:36px 28px;max-width:420px;width:100%;
      box-shadow:0 4px 24px rgba(0,0,0,.08);text-align:center}}
h1{{font-size:22px;font-weight:700;color:#0f172a;margin-bottom:8px}}
.subtitle{{color:#475569;font-size:15px;line-height:1.6;margin-bottom:24px}}
.error{{color:#dc2626}}
.btn{{display:block;padding:15px 20px;border-radius:10px;font-size:16px;font-weight:600;
     text-decoration:none;margin-bottom:12px}}
.btn-primary{{background:#1877F2;color:#fff}}
.btn-primary:hover{{background:#1664d8}}
.btn-wa{{background:#25D366;color:#fff;margin-top:8px}}
.note{{font-size:13px;color:#64748b;margin-top:16px;line-height:1.6}}
.steps{{text-align:left;background:#f8fafc;border-radius:10px;padding:16px;margin:20px 0;font-size:14px;color:#334155;line-height:2}}
.steps strong{{color:#1877F2}}
.divider{{border:none;border-top:1px solid #e2e8f0;margin:24px 0}}
</style>
</head><body>
<div class="card">
  <h1>Connect Facebook &amp; Instagram</h1>
  {connect_section}
  <hr class="divider">
  <div class="steps">
    <strong>Steps:</strong><br>
    1. Tap "Connect with Facebook"<br>
    2. Log in &amp; select your Page<br>
    3. Approve all permissions<br>
    4. Return here &amp; go back to WhatsApp<br>
    5. Send <strong>done</strong> in chat
  </div>
  <a href="{wa_url}" class="btn btn-wa">&#x21A9; Back to WhatsApp</a>
  <p class="note">If you're still stuck, send <strong>reset</strong> in WhatsApp to clear your session.</p>
</div>
</body></html>"""
    return HTMLResponse(html)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}


# =========================================================================
# GUIDE PAGES — step-by-step visual guides for manual token setup
# =========================================================================

_CONNECT_FACEBOOK_GUIDE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<title>Connect Facebook — Step by Step</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;padding:20px}}
.container{{max-width:640px;margin:0 auto}}
h1{{font-size:24px;font-weight:700;color:#1877f2;margin-bottom:6px}}
.subtitle{{color:#64748b;font-size:15px;margin-bottom:28px}}
.step{{background:#fff;border-radius:12px;padding:20px 20px 20px 16px;margin-bottom:16px;
       display:flex;gap:16px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e2e8f0}}
.step-num{{width:36px;height:36px;min-width:36px;background:#1877f2;color:#fff;
           border-radius:50%;display:flex;align-items:center;justify-content:center;
           font-weight:700;font-size:16px}}
.step-body h3{{font-size:16px;font-weight:600;margin-bottom:6px;color:#0f172a}}
.step-body p{{font-size:14px;line-height:1.6;color:#475569}}
.step-body .url{{display:inline-block;margin-top:8px;background:#eff6ff;border:1px solid #bfdbfe;
                  color:#1d4ed8;padding:8px 12px;border-radius:8px;font-size:13px;
                  word-break:break-all;text-decoration:none;font-weight:500}}
.ui-box{{background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;padding:10px 14px;
         margin-top:10px;font-size:13px;color:#334155;line-height:1.7}}
.ui-box .arrow{{color:#1877f2;font-weight:700}}
.badge{{display:inline-block;background:#dbeafe;color:#1e40af;padding:2px 8px;
        border-radius:4px;font-size:12px;font-weight:600;margin-left:4px}}
.note{{background:#fefce8;border:1px solid #fde047;border-radius:8px;padding:12px 14px;
       margin-top:10px;font-size:13px;color:#713f12}}
.highlight{{background:#fffbeb;border-left:3px solid #f59e0b;padding:4px 8px;border-radius:0 4px 4px 0;font-weight:600}}
.wa-btn{{display:block;text-align:center;margin-top:28px;padding:16px;background:#25D366;
         color:#fff;text-decoration:none;border-radius:12px;font-size:16px;font-weight:600}}
.done{{background:#f0fdf4;border:1px solid #86efac;border-radius:12px;padding:16px;
       text-align:center;margin-top:8px;color:#166534;font-size:15px}}
</style>
</head>
<body>
<div class="container">
  <h1>Connect Facebook &amp; Instagram</h1>
  <p class="subtitle">Follow these steps to get your Facebook Page token. Takes about 2 minutes.</p>

  <!-- Step 1 -->
  <div class="step">
    <div class="step-num">1</div>
    <div class="step-body">
      <h3>Open Graph API Explorer</h3>
      <p>Tap the link below to open Facebook's token tool. Log in with your Facebook account if prompted.</p>
      <a class="url" href="https://developers.facebook.com/tools/explorer/" target="_blank">
        developers.facebook.com/tools/explorer
      </a>
    </div>
  </div>

  <!-- Step 2 -->
  <div class="step">
    <div class="step-num">2</div>
    <div class="step-body">
      <h3>Select Your Facebook App</h3>
      <p>In the <strong>top-right corner</strong>, find the <strong>"Meta App"</strong> dropdown and select your app from the list.</p>
      <div class="ui-box">
        <span class="arrow">&#9654;</span> Top-right corner<br>
        <span class="arrow">&#9654;</span> Click <strong>"Meta App"</strong> dropdown<br>
        <span class="arrow">&#9654;</span> Select <strong>your app name</strong>
      </div>
      <div class="note">&#128161; Don't have an app? Create one free at developers.facebook.com/apps</div>
    </div>
  </div>

  <!-- Step 3 -->
  <div class="step">
    <div class="step-num">3</div>
    <div class="step-body">
      <h3>Generate Access Token</h3>
      <p>Click the blue <strong>"Generate Access Token"</strong> button. A Facebook Login dialog will appear.</p>
      <div class="ui-box">
        <span class="arrow">&#9654;</span> Click <strong style="color:#1877f2">"Generate Access Token"</strong> button<br>
        <span class="arrow">&#9654;</span> Click <strong>"Continue as [Your Name]"</strong><br>
        <span class="arrow">&#9654;</span> Click <strong>"OK"</strong> or <strong>"Done"</strong>
      </div>
    </div>
  </div>

  <!-- Step 4 -->
  <div class="step">
    <div class="step-num">4</div>
    <div class="step-body">
      <h3>Add Required Permissions</h3>
      <p>Before generating, make sure these permissions are selected:</p>
      <div class="ui-box">
        &#10003; <strong>pages_show_list</strong><br>
        &#10003; <strong>pages_read_engagement</strong><br>
        &#10003; <strong>pages_manage_posts</strong><br>
        &#10003; <strong>instagram_basic</strong> (if you have Instagram)<br>
        &#10003; <strong>instagram_content_publish</strong> (if you have Instagram)
      </div>
      <div class="note">&#9888;&#65039; If you don't see these permissions, click <strong>"Add a Permission"</strong> to add them.</div>
    </div>
  </div>

  <!-- Step 5 -->
  <div class="step">
    <div class="step-num">5</div>
    <div class="step-body">
      <h3>Copy the Access Token</h3>
      <p>After clicking OK, you'll see a long token in the <strong>Access Token</strong> field at the top of the page.</p>
      <div class="ui-box">
        <span class="arrow">&#9654;</span> Find the <strong>Access Token</strong> field (top of page)<br>
        <span class="arrow">&#9654;</span> Click the token field to <strong>select all</strong><br>
        <span class="arrow">&#9654;</span> <strong>Copy</strong> the full token<br><br>
        <span class="highlight">Looks like: EAAl7fPZB... (100+ characters)</span>
      </div>
    </div>
  </div>

  <!-- Step 6 -->
  <div class="step">
    <div class="step-num">6</div>
    <div class="step-body">
      <h3>Paste the Token in WhatsApp</h3>
      <p>Return to your WhatsApp chat with the bot and paste the token. We'll handle the rest automatically — page detection, Instagram linking, and token renewal.</p>
    </div>
  </div>

  <div class="done">
    &#127881; That's it! Paste the token in WhatsApp and your Facebook &amp; Instagram will be connected.
  </div>

  <a class="wa-btn" href="https://wa.me/{WHATSAPP_BOT_PHONE or ''}">
    &#x21A9; Back to WhatsApp
  </a>
</div>
</body>
</html>"""


_PRIVACY_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<title>Privacy Policy — Catalyx AI</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;
     margin:40px auto;padding:0 20px;color:#1e293b;line-height:1.7}}
h1{{font-size:28px;font-weight:700;margin-bottom:4px}}
.updated{{color:#64748b;font-size:14px;margin-bottom:32px}}
h2{{font-size:18px;font-weight:600;margin:28px 0 8px}}
p,li{{font-size:15px;color:#334155}}
ul{{padding-left:20px}}
a{{color:#1877f2}}
</style>
</head>
<body>
<h1>Privacy Policy</h1>
<p class="updated">Last updated: March 2026</p>

<p>Catalyx AI ("we", "our", or "us") operates a WhatsApp-based social media automation service.
This policy explains what data we collect, how we use it, and your rights.</p>

<h2>1. Data We Collect</h2>
<ul>
  <li><strong>WhatsApp identity:</strong> Your WhatsApp phone number and display name, used to identify your account.</li>
  <li><strong>Business profile:</strong> Industry, goals, tone preferences, and visual style — used to generate relevant content.</li>
  <li><strong>Facebook &amp; Instagram tokens:</strong> Page Access Tokens used to publish posts and read engagement on your behalf.</li>
  <li><strong>Message content:</strong> Text and media you send us while creating posts.</li>
  <li><strong>Payment info:</strong> Processed by Stripe; we store only your Stripe customer ID, not card details.</li>
</ul>

<h2>2. How We Use Your Data</h2>
<ul>
  <li>Publish posts to your Facebook Pages and Instagram accounts at your instruction.</li>
  <li>Generate AI content personalised to your business profile.</li>
  <li>Manage your subscription and credit balance.</li>
  <li>Send you service notifications via WhatsApp.</li>
</ul>

<h2>3. Data Sharing</h2>
<p>We do not sell your data. We share data only with:</p>
<ul>
  <li><strong>Meta (Facebook/Instagram)</strong> — to publish posts via the Graph API.</li>
  <li><strong>Anthropic</strong> — for AI content generation (no personal data included in prompts).</li>
  <li><strong>Stripe</strong> — for payment processing.</li>
</ul>

<h2>4. Data Retention</h2>
<p>Your data is retained while your account is active. You can disconnect your Facebook/Instagram account at any time by sending <em>disconnect</em> to the bot. To delete your account entirely, contact us.</p>

<h2>5. Security</h2>
<p>Tokens are stored encrypted at rest. We use HTTPS for all API communication. CSRF protection is applied to all OAuth flows.</p>

<h2>6. Your Rights</h2>
<p>You may request access to, correction of, or deletion of your personal data at any time by contacting us via WhatsApp or email.</p>

<h2>7. Contact</h2>
<p>Questions? Send <em>help</em> in WhatsApp or email us at privacy@catalyxai.com.</p>
</body>
</html>"""


@app.get("/guide/connect-facebook", response_class=HTMLResponse)
async def guide_connect_facebook():
    """Step-by-step visual guide for manually connecting Facebook via Graph API Explorer."""
    return HTMLResponse(_CONNECT_FACEBOOK_GUIDE_HTML)


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Privacy policy page — required for Facebook App Review."""
    return HTMLResponse(_PRIVACY_HTML)
