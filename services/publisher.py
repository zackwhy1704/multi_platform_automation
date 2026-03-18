"""
Direct publisher — posts to Facebook/Instagram via Graph API inline.

Replaces Celery dispatch for single-service Railway deployments where
no Redis or Celery worker is available. Falls back to Celery when
REDIS_URL is configured and reachable.
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
    """Post to a Facebook Page via Graph API (async, no Celery)."""
    token_data = db.get_platform_token(sender, "facebook")
    if not token_data or not token_data.get("access_token"):
        return {"success": False, "error": "No Facebook token. Send *setup* to connect."}

    access_token = token_data["access_token"]
    page_id = token_data.get("page_id")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Resolve page_id if missing
            if not page_id:
                resp = await client.get(
                    f"{GRAPH_API}/me/accounts",
                    params={"access_token": access_token},
                )
                pages = resp.json().get("data", []) if resp.status_code == 200 else []
                if not pages:
                    return {"success": False, "error": "No Facebook Pages found for this token."}
                page_id = pages[0]["id"]
                page_name = pages[0].get("name", "")
                db.save_platform_token(sender, "facebook", access_token, page_id, page_name=page_name)

            # Build request
            endpoint = f"{GRAPH_API}/{page_id}/feed"
            payload = {"message": caption, "access_token": access_token}

            if media_url:
                is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi"))
                if is_video:
                    endpoint = f"{GRAPH_API}/{page_id}/videos"
                    payload = {"file_url": media_url, "description": caption, "access_token": access_token}
                else:
                    endpoint = f"{GRAPH_API}/{page_id}/photos"
                    payload["url"] = media_url

            resp = await client.post(endpoint, data=payload)

            if resp.status_code != 200:
                error_data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                logger.error("Facebook post failed for %s: %s", sender, error_msg)
                return {"success": False, "error": error_msg}

            post_id = resp.json().get("id", "")
            db.log_automation_action(sender, "facebook", "post", 1)
            logger.info("Facebook post published for %s: %s", sender, post_id)
            return {"success": True, "post_id": post_id}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("Facebook publish error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": str(e)}


async def publish_to_instagram(
    db: BotDatabase, sender: str, caption: str, media_url: str | None = None
) -> dict:
    """Post to Instagram via Graph API (async, no Celery)."""
    token_data = db.get_platform_token(sender, "instagram")
    if not token_data or not token_data.get("access_token"):
        return {"success": False, "error": "No Instagram token. Send *setup* to connect."}

    access_token = token_data["access_token"]
    ig_account_id = token_data.get("page_id")

    if not media_url:
        return {"success": False, "error": "Instagram requires an image or video. Post cancelled."}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Resolve IG account ID if missing
            if not ig_account_id:
                resp = await client.get(
                    f"{GRAPH_API}/me/accounts",
                    params={"access_token": access_token, "fields": "id,instagram_business_account"},
                )
                pages = resp.json().get("data", []) if resp.status_code == 200 else []
                for page in pages:
                    ig = page.get("instagram_business_account", {}).get("id")
                    if ig:
                        ig_account_id = ig
                        break
                if not ig_account_id:
                    return {"success": False, "error": "No Instagram Business Account linked to your Page."}
                db.save_platform_token(sender, "instagram", access_token, ig_account_id)

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
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                return {"success": False, "error": error_msg}

            creation_id = resp.json().get("id")

            # Step 2: Wait for processing
            await asyncio.sleep(5)

            # Step 3: Publish
            pub_resp = await client.post(
                f"{GRAPH_API}/{ig_account_id}/media_publish",
                data={"creation_id": creation_id, "access_token": access_token},
            )
            if pub_resp.status_code != 200:
                error_data = pub_resp.json() if "application/json" in pub_resp.headers.get("content-type", "") else {}
                error_msg = error_data.get("error", {}).get("message", pub_resp.text[:200])
                return {"success": False, "error": error_msg}

            media_id = pub_resp.json().get("id", "")
            db.log_automation_action(sender, "instagram", "post", 1)
            logger.info("Instagram post published for %s: %s", sender, media_id)
            return {"success": True, "media_id": media_id}

    except httpx.TimeoutException:
        return {"success": False, "error": "Request timed out. Please try again."}
    except Exception as e:
        logger.error("Instagram publish error for %s: %s", sender, e, exc_info=True)
        return {"success": False, "error": str(e)}
