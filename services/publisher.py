"""
Post For Me publisher — posts to Facebook/Instagram via postforme.dev API.

No Facebook App Review required. Each customer connects their own social
accounts through Post For Me's OAuth URL. We store their spc_xxx account IDs
and use them to publish on their behalf.

API Docs: https://api.postforme.dev/docs

Key behaviours:
- Media on Railway's filesystem is uploaded to PFM storage (Railway is ephemeral)
- External URLs (Pexels, etc.) are passed directly
- placement is set correctly: timeline / reels / stories
- Post results are polled to confirm publish and return the Facebook/IG URL
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from typing import Optional

import httpx

from shared.config import POSTFORME_API_KEY, PUBLIC_BASE_URL
from shared.database import BotDatabase

logger = logging.getLogger(__name__)

PFM_BASE = "https://api.postforme.dev/v1"

# Media files stored locally on Railway
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media_files")


def _headers():
    return {"Authorization": f"Bearer {POSTFORME_API_KEY}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Media upload to PFM storage
# ---------------------------------------------------------------------------

def _is_railway_url(url: str) -> bool:
    """Return True if this URL points to our own Railway media endpoint."""
    return bool(PUBLIC_BASE_URL and url.startswith(PUBLIC_BASE_URL + "/media/"))


def _local_path_from_url(url: str) -> Optional[str]:
    """Convert a Railway /media/filename URL to its local file path."""
    if not _is_railway_url(url):
        return None
    filename = url.split("/media/")[-1]
    path = os.path.join(MEDIA_DIR, filename)
    return path if os.path.exists(path) else None


async def upload_media_to_pfm(file_path: str) -> Optional[str]:
    """Upload a local file to Post For Me storage. Returns public media_url or None."""
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    filename = os.path.basename(file_path)

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            # Step 1: Get signed upload URL
            r = await c.post(
                f"{PFM_BASE}/media/create-upload-url",
                json={"content_type": mime, "filename": filename},
                headers=_headers(),
            )
            if r.status_code not in (200, 201):
                logger.error("PFM upload-url failed: %s %s", r.status_code, r.text[:200])
                return None

            data = r.json()
            upload_url = data.get("upload_url")
            media_url = data.get("media_url")

            if not upload_url or not media_url:
                logger.error("PFM upload-url missing fields: %s", data)
                return None

            # Step 2: PUT file to signed URL
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            up = await c.put(upload_url, content=file_bytes, headers={"Content-Type": mime})
            if up.status_code not in (200, 201):
                logger.error("PFM media PUT failed: %s", up.status_code)
                return None

            logger.info("PFM media uploaded: %s → %s", filename, media_url[:60])
            return media_url

    except Exception as e:
        logger.error("upload_media_to_pfm error: %s", e)
        return None


async def resolve_media_url(original_url: str) -> Optional[str]:
    """
    Resolve a media URL to one that Post For Me can fetch.
    - Railway /media/ URLs: upload the local file to PFM storage
    - Everything else: return as-is (Pexels, external CDNs, etc.)
    """
    if not original_url:
        return None

    local_path = _local_path_from_url(original_url)
    if local_path:
        logger.info("Uploading local file to PFM: %s", local_path)
        uploaded = await upload_media_to_pfm(local_path)
        if uploaded:
            return uploaded
        logger.warning("PFM upload failed for %s, trying Railway URL directly", local_path)

    return original_url


# ---------------------------------------------------------------------------
# Determine placement from media URL
# ---------------------------------------------------------------------------

def _is_video(url: str) -> bool:
    return any(url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi", ".webm"))


def _get_placement(media_url: Optional[str], post_type: str = "timeline") -> str:
    """Return PFM placement value. Videos default to reels if no explicit type."""
    if post_type in ("reels", "stories"):
        return post_type
    if media_url and _is_video(media_url):
        return "reels"
    return "timeline"


# ---------------------------------------------------------------------------
# Connection / Setup
# ---------------------------------------------------------------------------

async def generate_auth_url(sender: str, platform: str = "facebook") -> dict:
    """Generate a Post For Me OAuth URL for the user to connect their account."""
    if not POSTFORME_API_KEY:
        return {"success": False, "error": "POSTFORME_API_KEY not configured"}

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{PFM_BASE}/social-accounts/auth-url",
                json={"platform": platform, "external_id": sender},
                headers=_headers(),
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code in (200, 201):
                return {"success": True, "url": data.get("url", "")}
            err = data.get("message") or data.get("error") or r.text[:200]
            return {"success": False, "error": err}
    except Exception as e:
        logger.error("generate_auth_url error: %s", e)
        return {"success": False, "error": str(e)}


async def get_connected_accounts(sender: str) -> list:
    """Return connected Post For Me social accounts with external_id matching sender."""
    if not POSTFORME_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{PFM_BASE}/social-accounts",
                params={"external_id": sender, "limit": 10, "status": "connected"},
                headers=_headers(),
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                # Filter defensively in case the API ignores the status param
                return [a for a in data if a.get("status", "connected") == "connected"]
    except Exception as e:
        logger.warning("get_connected_accounts error: %s", e)
    return []


async def store_accounts_for_sender(db: BotDatabase, sender: str, accounts: list):
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
            pfm_profile_key=account_id,
        )

        logger.info("Stored PFM account %s (%s) for %s", account_id, platform, sender)


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

async def publish_post(
    db: BotDatabase,
    sender: str,
    platform: str,
    caption: str,
    media_url: Optional[str] = None,
    post_type: str = "timeline",
) -> dict:
    """Publish a post via Post For Me API.

    post_type: "timeline" | "reels" | "stories"
    Returns {"success": True, "post_id": "sp_xxx", "url": "https://facebook.com/..."}
         or {"success": False, "error": "..."}
    """
    if not POSTFORME_API_KEY:
        return {"success": False, "error": "Post For Me API key not configured. Contact support."}

    token_data = db.get_platform_token(sender, platform)
    if not token_data:
        return {
            "success": False,
            "error": f"No {platform.title()} account connected. Send *setup* to connect.",
        }

    account_id = token_data.get("pfm_profile_key") or token_data.get("access_token")
    if not account_id or account_id in ("pending", "__pfm__"):
        return {
            "success": False,
            "error": (
                f"Your {platform.title()} account isn't fully connected yet.\n\n"
                "Send *setup* and complete the connection."
            ),
        }

    # Resolve media — upload Railway files to PFM storage
    resolved_media_url = None
    if media_url:
        resolved_media_url = await resolve_media_url(media_url)
        if not resolved_media_url:
            return {"success": False, "error": "Could not process media file. Please try again."}

    # Determine placement
    placement = _get_placement(resolved_media_url, post_type)

    # Build payload
    payload = {
        "caption": caption,
        "social_accounts": [account_id],
        "platform_configurations": {
            platform: {"placement": placement},
        },
    }
    if resolved_media_url:
        payload["media"] = [{"url": resolved_media_url}]

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{PFM_BASE}/social-posts", json=payload, headers=_headers())
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

            if r.status_code not in (200, 201):
                err = data.get("message") or data.get("error") or r.text[:200]
                if isinstance(err, list):
                    err = "; ".join(str(e) for e in err)
                logger.error("PFM post failed for %s: %s %s", sender, r.status_code, err)
                return {"success": False, "error": _friendly_error(r.status_code, str(err))}

            post_id = data.get("id", "")
            db.log_automation_action(sender, platform, "post", 1)
            logger.info("PFM post created for %s (%s): %s placement=%s", sender, platform, post_id, placement)

            # Poll for result (up to 60s for videos/reels, 30s for images)
            max_wait = 60 if resolved_media_url and _is_video(resolved_media_url) else 30
            post_url, post_failed = await _poll_post_result(c, post_id, max_wait)

            if post_failed:
                return {"success": False, "error": "Post was rejected by the platform. Check your account permissions and try again."}

            return {"success": True, "post_id": post_id, "url": post_url}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("publish_post error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": "Unexpected error. Please try again."}


async def _poll_post_result(client: httpx.AsyncClient, post_id: str, max_wait: int = 30) -> tuple[Optional[str], bool]:
    """Poll /v1/social-post-results until published or timeout.

    Returns (post_url, failed):
      - ("https://...", False) on success
      - (None, False) on timeout (still processing)
      - (None, True) on explicit platform failure
    """
    interval = 5
    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            r = await client.get(
                f"{PFM_BASE}/social-post-results",
                params={"post_id": post_id},
                headers=_headers(),
            )
            results = r.json().get("data", []) if r.status_code == 200 else []
            if results:
                result = results[0]
                if result.get("success"):
                    pd = result.get("platform_data") or {}
                    url = pd.get("url") or pd.get("id") or ""
                    logger.info("PFM post %s published: %s", post_id, url)
                    return url, False
                elif result.get("success") is False:
                    err = result.get("error")
                    logger.warning("PFM post %s failed at platform level: %s", post_id, err)
                    return None, True
        except Exception as e:
            logger.warning("poll_post_result error: %s", e)

    logger.info("PFM post %s still processing after %ds", post_id, max_wait)
    return None, False


def _friendly_error(status: int, msg: str) -> str:
    msg_lower = msg.lower()
    if status in (401, 403) or "unauthorized" in msg_lower or "forbidden" in msg_lower:
        return "Service authentication error. Contact support."
    if status == 404 or "not found" in msg_lower:
        return "Your account connection could not be found. Send *setup* to reconnect."
    if "not owned by user" in msg_lower or (status == 400 and "invalid social accounts" in msg_lower):
        return "Your account connection has expired. Send *setup* to reconnect."
    if "media" in msg_lower or "url" in msg_lower:
        return "Could not process the image/video. Please try a different file."
    if status == 429:
        return "Too many posts. Please wait a few minutes and try again."
    return msg


# ---------------------------------------------------------------------------
# Backwards-compatible wrappers (used by actions.py)
# ---------------------------------------------------------------------------

async def publish_to_facebook(
    db: BotDatabase, sender: str, caption: str, media_url: Optional[str] = None
) -> dict:
    return await publish_post(db, sender, "facebook", caption, media_url)


async def publish_to_instagram(
    db: BotDatabase, sender: str, caption: str, media_url: Optional[str] = None
) -> dict:
    return await publish_post(db, sender, "instagram", caption, media_url)
