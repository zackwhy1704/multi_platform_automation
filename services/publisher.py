"""
Post For Me publisher — posts to Facebook/Instagram via postforme.dev API.

No Facebook App Review required. Each customer connects their own social
accounts through Post For Me's hosted OAuth page, then we store their
Post For Me profile key and use it to publish on their behalf.

Docs: https://api.postforme.dev/docs
"""

import logging
import httpx
from shared.config import POSTFORME_API_KEY
from shared.database import BotDatabase

logger = logging.getLogger(__name__)

PFM_BASE = "https://api.postforme.dev/v1"
PFM_HEADERS = {"Authorization": f"Bearer {POSTFORME_API_KEY}", "Content-Type": "application/json"}

PLATFORM_MAP = {
    "facebook": "facebook",
    "instagram": "instagram",
}


def _pfm_headers():
    return {"Authorization": f"Bearer {POSTFORME_API_KEY}", "Content-Type": "application/json"}


async def publish_post(
    db: BotDatabase,
    sender: str,
    platform: str,
    caption: str,
    media_url: str | None = None,
) -> dict:
    """Publish a post via Post For Me API.

    Looks up the user's Post For Me profile key stored during setup,
    then posts to the specified platform.
    """
    token_data = db.get_platform_token(sender, platform)
    if not token_data:
        return {
            "success": False,
            "error": f"No {platform.title()} account connected. Send *setup* to connect.",
        }

    pfm_profile_key = token_data.get("pfm_profile_key")
    if not pfm_profile_key:
        return {
            "success": False,
            "error": (
                f"Your {platform.title()} account needs to be reconnected via Post For Me.\n\n"
                "Send *setup* and use the *Connect* link to reconnect."
            ),
        }

    if not POSTFORME_API_KEY:
        return {"success": False, "error": "Post For Me API key not configured. Contact support."}

    # Build post payload
    payload = {
        "profileKey": pfm_profile_key,
        "platforms": [PLATFORM_MAP[platform]],
        "text": caption,
    }

    if media_url:
        is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi", ".webm"))
        payload["media"] = [{"url": media_url, "type": "video" if is_video else "image"}]

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{PFM_BASE}/posts",
                json=payload,
                headers=_pfm_headers(),
            )

            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code in (200, 201):
                post_id = data.get("id") or data.get("postId", "")
                db.log_automation_action(sender, platform, "post", 1)
                logger.info("Post For Me: published %s post for %s: %s", platform, sender, post_id)
                return {"success": True, "post_id": post_id}

            error_msg = data.get("message") or data.get("error") or resp.text[:200]
            logger.error("Post For Me publish failed for %s: %s %s", sender, resp.status_code, error_msg)
            return {"success": False, "error": _friendly_pfm_error(resp.status_code, error_msg)}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("Post For Me publish error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": "Unexpected error. Please try again."}


def _friendly_pfm_error(status: int, msg: str) -> str:
    """Convert Post For Me error responses to user-friendly messages."""
    msg_lower = msg.lower()

    if status == 401 or "unauthorized" in msg_lower or "api key" in msg_lower:
        return "Service authentication error. Please contact support."

    if status == 403 or "profile" in msg_lower and "not found" in msg_lower:
        return (
            "Your account connection has expired.\n\n"
            "Send *setup* and reconnect via the link provided."
        )

    if "media" in msg_lower or "url" in msg_lower:
        return (
            "Could not process the image/video. "
            "Please try again or use a different image."
        )

    if status == 429:
        return "Too many posts. Please wait a few minutes and try again."

    return msg


# ---------------------------------------------------------------------------
# Profile management helpers (called from settings/setup flow)
# ---------------------------------------------------------------------------

async def create_pfm_profile(user_label: str) -> dict:
    """Create a new Post For Me profile for a user.

    Returns {"success": True, "profile_key": "...", "connect_url": "..."} or
            {"success": False, "error": "..."}
    """
    if not POSTFORME_API_KEY:
        return {"success": False, "error": "POSTFORME_API_KEY not configured"}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{PFM_BASE}/profiles",
                json={"label": user_label},
                headers=_pfm_headers(),
            )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code in (200, 201):
                profile_key = data.get("key") or data.get("profileKey") or data.get("id", "")
                connect_url = data.get("connectUrl") or data.get("connect_url") or (
                    f"https://app.postforme.dev/connect?profileKey={profile_key}" if profile_key else ""
                )
                return {"success": True, "profile_key": profile_key, "connect_url": connect_url}

            error_msg = data.get("message") or data.get("error") or resp.text[:200]
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error("create_pfm_profile error: %s", e)
        return {"success": False, "error": str(e)}


async def get_pfm_profile_platforms(profile_key: str) -> list[str]:
    """Return list of platforms the user has connected in Post For Me."""
    if not POSTFORME_API_KEY or not profile_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{PFM_BASE}/profiles/{profile_key}",
                headers=_pfm_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                accounts = data.get("accounts") or data.get("connectedAccounts") or []
                return [a.get("platform", "").lower() for a in accounts if a.get("platform")]
    except Exception as e:
        logger.warning("get_pfm_profile_platforms error: %s", e)
    return []


# Backwards-compatible wrappers so actions.py imports still work
async def publish_to_facebook(db: BotDatabase, sender: str, caption: str, media_url: str | None = None) -> dict:
    return await publish_post(db, sender, "facebook", caption, media_url)


async def publish_to_instagram(db: BotDatabase, sender: str, caption: str, media_url: str | None = None) -> dict:
    return await publish_post(db, sender, "instagram", caption, media_url)
