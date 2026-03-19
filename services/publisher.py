"""
Post For Me publisher — posts to Facebook/Instagram via postforme.dev API.

No Facebook App Review required. Each customer connects their own social
accounts through Post For Me's OAuth URL. We store their social account IDs
and use them to publish on their behalf.

API Docs: https://api.postforme.dev/docs

Flow:
  1. generate_auth_url(sender) → returns OAuth URL, pass to user
  2. User completes OAuth → Post For Me fires social.account.created webhook
  3. Webhook handler stores social account ID mapped to sender phone
  4. publish_post(sender, platform, caption, media_url) uses stored account ID
"""

import logging
import httpx
from shared.config import POSTFORME_API_KEY
from shared.database import BotDatabase

logger = logging.getLogger(__name__)

PFM_BASE = "https://api.postforme.dev/v1"


def _headers():
    return {"Authorization": f"Bearer {POSTFORME_API_KEY}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Connection / Setup
# ---------------------------------------------------------------------------

async def generate_auth_url(sender: str, platform: str = "facebook") -> dict:
    """Generate a Post For Me OAuth URL for the user to connect their account.

    Uses external_id=sender so the webhook can map back to this user.
    Returns {"success": True, "url": "https://..."} or {"success": False, "error": "..."}
    """
    if not POSTFORME_API_KEY:
        return {"success": False, "error": "POSTFORME_API_KEY not configured"}

    payload = {
        "platform": platform,
        "external_id": sender,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{PFM_BASE}/social-accounts/auth-url", json=payload, headers=_headers())
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

            if r.status_code in (200, 201):
                return {"success": True, "url": data.get("url", "")}

            err = data.get("message") or data.get("error") or r.text[:200]
            logger.error("PFM auth-url failed: %s %s", r.status_code, err)
            return {"success": False, "error": err}

    except Exception as e:
        logger.error("generate_auth_url error: %s", e)
        return {"success": False, "error": str(e)}


async def get_connected_accounts(sender: str) -> list[dict]:
    """Return all Post For Me social accounts with external_id matching sender."""
    if not POSTFORME_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{PFM_BASE}/social-accounts",
                params={"external_id": sender, "limit": 10},
                headers=_headers(),
            )
            if r.status_code == 200:
                return r.json().get("data", [])
    except Exception as e:
        logger.warning("get_connected_accounts error: %s", e)
    return []


async def store_accounts_for_sender(db: BotDatabase, sender: str, accounts: list[dict]):
    """Store Post For Me social account IDs in the database for a sender."""
    for acc in accounts:
        platform = acc.get("platform", "").lower()
        account_id = acc.get("id", "")
        username = acc.get("username") or acc.get("name") or ""
        page_name = acc.get("name") or username

        if platform not in ("facebook", "instagram") or not account_id:
            continue

        db.save_platform_token(
            sender, platform, account_id, account_id,
            page_name=page_name, account_username=username,
        )
        try:
            db.execute_query(
                "UPDATE platform_tokens SET pfm_profile_key = %s "
                "WHERE phone_number_id = %s AND platform = %s",
                (account_id, sender, platform),
            )
        except Exception as e:
            logger.warning("Could not write pfm_profile_key: %s", e)

        logger.info("Stored PFM account %s (%s) for %s", account_id, platform, sender)


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

async def publish_post(
    db: BotDatabase,
    sender: str,
    platform: str,
    caption: str,
    media_url: str | None = None,
) -> dict:
    """Publish a post via Post For Me API."""
    if not POSTFORME_API_KEY:
        return {"success": False, "error": "Post For Me API key not configured. Contact support."}

    token_data = db.get_platform_token(sender, platform)
    if not token_data:
        return {
            "success": False,
            "error": f"No {platform.title()} account connected. Send *setup* to connect.",
        }

    # pfm_profile_key stores the social account ID (e.g. "sa_xxx")
    account_id = token_data.get("pfm_profile_key") or token_data.get("access_token")
    if not account_id or account_id == "pending":
        return {
            "success": False,
            "error": (
                f"Your {platform.title()} account isn't fully connected yet.\n\n"
                "Send *setup* and complete the connection link."
            ),
        }

    payload = {
        "caption": caption,
        "social_accounts": [account_id],
    }

    if media_url:
        is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi", ".webm"))
        payload["media"] = [{"url": media_url}]

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{PFM_BASE}/social-posts", json=payload, headers=_headers())
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

            if r.status_code in (200, 201):
                post_id = data.get("id", "")
                db.log_automation_action(sender, platform, "post", 1)
                logger.info("PFM post created for %s (%s): %s", sender, platform, post_id)
                return {"success": True, "post_id": post_id}

            err = data.get("message") or data.get("error") or r.text[:200]
            logger.error("PFM post failed for %s: %s %s", sender, r.status_code, err)
            return {"success": False, "error": _friendly_error(r.status_code, err)}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("publish_post error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": "Unexpected error. Please try again."}


def _friendly_error(status: int, msg: str) -> str:
    msg_lower = msg.lower()
    if status == 401 or "unauthorized" in msg_lower:
        return "Service authentication error. Please contact support."
    if status == 403 or "not found" in msg_lower and "account" in msg_lower:
        return "Your account connection has expired. Send *setup* to reconnect."
    if "media" in msg_lower or "url" in msg_lower:
        return "Could not process the image/video. Please try again."
    if status == 429:
        return "Too many posts. Please wait a few minutes and try again."
    return msg


# ---------------------------------------------------------------------------
# Backwards-compatible wrappers (used by actions.py)
# ---------------------------------------------------------------------------

async def publish_to_facebook(db: BotDatabase, sender: str, caption: str, media_url: str | None = None) -> dict:
    return await publish_post(db, sender, "facebook", caption, media_url)


async def publish_to_instagram(db: BotDatabase, sender: str, caption: str, media_url: str | None = None) -> dict:
    return await publish_post(db, sender, "instagram", caption, media_url)
