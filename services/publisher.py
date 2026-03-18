"""
Direct publisher — posts to Facebook/Instagram via Graph API inline.

Facebook posting requires a Page Access Token with:
  - pages_manage_posts
  - pages_read_engagement

The token stored during setup (OAuth or manual) should already be a
Page Access Token extracted from /me/accounts.
"""

import asyncio
import logging

import httpx

from shared.database import BotDatabase

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.facebook.com/v21.0"


async def publish_to_facebook(
    db: BotDatabase, sender: str, caption: str, media_url: str | None = None
) -> dict:
    """Post to a Facebook Page via Graph API.

    Endpoints:
    - Text:  POST /{page_id}/feed      → pages_manage_posts
    - Photo: POST /{page_id}/photos    → pages_manage_posts + pages_read_engagement
    - Video: POST /{page_id}/videos    → pages_manage_posts + pages_read_engagement
    """
    token_data = db.get_platform_token(sender, "facebook")
    if not token_data or not token_data.get("access_token"):
        return {"success": False, "error": "No Facebook token. Send *setup* to connect."}

    access_token = token_data["access_token"]
    page_id = token_data.get("page_id")

    if not page_id:
        return {"success": False, "error": "No Facebook Page ID stored. Send *setup* to reconnect."}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Build request based on content type
            if media_url:
                is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi"))

                if is_video:
                    endpoint = f"{GRAPH_API}/{page_id}/videos"
                    payload = {
                        "file_url": media_url,
                        "description": caption,
                        "access_token": access_token,
                    }
                else:
                    endpoint = f"{GRAPH_API}/{page_id}/photos"
                    payload = {
                        "url": media_url,
                        "message": caption,
                        "access_token": access_token,
                    }
            else:
                endpoint = f"{GRAPH_API}/{page_id}/feed"
                payload = {
                    "message": caption,
                    "access_token": access_token,
                }

            resp = await client.post(endpoint, data=payload)

            if resp.status_code != 200:
                error_data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                fb_error = error_data.get("error", {})
                error_msg = fb_error.get("message", resp.text[:200])
                error_code = fb_error.get("code", 0)

                logger.error("Facebook post failed for %s: code=%s msg=%s",
                             sender, error_code, error_msg)

                return {"success": False, "error": _friendly_fb_error(error_code, error_msg)}

            post_id = resp.json().get("id", resp.json().get("post_id", ""))
            db.log_automation_action(sender, "facebook", "post", 1)
            logger.info("Facebook post published for %s: %s", sender, post_id)
            return {"success": True, "post_id": post_id}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("Facebook publish error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": str(e)}


def _friendly_fb_error(code: int, msg: str) -> str:
    """Convert Facebook error codes to user-friendly messages."""
    msg_lower = msg.lower()

    if code == 190 or "expired" in msg_lower:
        return "Your Facebook token has expired. Send *setup* to reconnect."

    if code == 200 or "publish_actions" in msg_lower:
        return (
            "Missing *pages_manage_posts* permission.\n\n"
            "Send *setup* and use the *OAuth link* (Option 1) to reconnect — "
            "it automatically requests all required permissions."
        )

    if code == 283 or "pages_read_engagement" in msg_lower:
        return (
            "Missing *pages_read_engagement* permission.\n\n"
            "Send *setup* and use the *OAuth link* (Option 1) to reconnect — "
            "it automatically requests all required permissions."
        )

    if code == 368 or "temporarily blocked" in msg_lower:
        return "Facebook has temporarily blocked posting. Try again in a few hours."

    if "url" in msg_lower and ("not accessible" in msg_lower or "could not download" in msg_lower):
        return (
            "Facebook couldn't download the image/video. "
            "The file may have expired. Please try again with a new upload."
        )

    return msg


async def publish_to_instagram(
    db: BotDatabase, sender: str, caption: str, media_url: str | None = None
) -> dict:
    """Post to Instagram via Graph API.

    Flow: create container → poll status → publish.
    Requires: instagram_basic, instagram_content_publish, pages_read_engagement
    """
    token_data = db.get_platform_token(sender, "instagram")
    if not token_data or not token_data.get("access_token"):
        return {"success": False, "error": "No Instagram token. Send *setup* to connect."}

    access_token = token_data["access_token"]
    ig_account_id = token_data.get("page_id")

    if not media_url:
        return {"success": False, "error": "Instagram requires an image or video. Post cancelled."}

    if not ig_account_id:
        return {"success": False, "error": "No Instagram account ID. Send *setup* to reconnect."}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Step 1: Create media container
            is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi"))
            container_data = {"caption": caption, "access_token": access_token}
            if is_video:
                container_data["media_type"] = "VIDEO"
                container_data["video_url"] = media_url
            else:
                container_data["image_url"] = media_url

            resp = await client.post(f"{GRAPH_API}/{ig_account_id}/media", data=container_data)
            if resp.status_code != 200:
                error_data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                fb_error = error_data.get("error", {})
                error_msg = fb_error.get("message", resp.text[:200])
                error_code = fb_error.get("code", 0)
                return {"success": False, "error": _friendly_fb_error(error_code, error_msg)}

            creation_id = resp.json().get("id")

            # Step 2: Poll for processing completion
            max_wait = 60 if is_video else 20
            poll_interval = 5
            for _ in range(max_wait // poll_interval):
                await asyncio.sleep(poll_interval)

                status_resp = await client.get(
                    f"{GRAPH_API}/{creation_id}",
                    params={"fields": "status_code", "access_token": access_token},
                )
                if status_resp.status_code == 200:
                    status = status_resp.json().get("status_code")
                    if status == "FINISHED":
                        break
                    elif status == "ERROR":
                        return {"success": False, "error": "Instagram media processing failed. Try a different image/video."}

            # Step 3: Publish
            pub_resp = await client.post(
                f"{GRAPH_API}/{ig_account_id}/media_publish",
                data={"creation_id": creation_id, "access_token": access_token},
            )
            if pub_resp.status_code != 200:
                error_data = pub_resp.json() if "application/json" in pub_resp.headers.get("content-type", "") else {}
                fb_error = error_data.get("error", {})
                error_msg = fb_error.get("message", pub_resp.text[:200])
                error_code = fb_error.get("code", 0)
                return {"success": False, "error": _friendly_fb_error(error_code, error_msg)}

            media_id = pub_resp.json().get("id", "")
            db.log_automation_action(sender, "instagram", "post", 1)
            logger.info("Instagram post published for %s: %s", sender, media_id)
            return {"success": True, "media_id": media_id}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("Instagram publish error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": str(e)}
