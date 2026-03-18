"""
Direct publisher — posts to Facebook/Instagram via Graph API inline.

Replaces Celery dispatch for single-service Railway deployments where
no Redis or Celery worker is available.

Facebook posting requires a Page Access Token with pages_manage_posts permission.
The old publish_actions permission was deprecated in 2018.
"""

import asyncio
import logging

import httpx

from shared.database import BotDatabase

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.facebook.com/v21.0"


async def _get_page_token(client: httpx.AsyncClient, stored_token: str, page_id: str) -> tuple[str, str]:
    """
    Ensure we have a valid Page Access Token (not a User Access Token).

    If the stored token is a User token, fetches the Page token from /me/accounts.
    Returns (page_token, page_id).
    """
    # Check if stored token is already a Page token by trying /me
    # Page tokens return the page info; User tokens return user info
    me_resp = await client.get(
        f"{GRAPH_API}/me",
        params={"access_token": stored_token, "fields": "id,name"},
    )

    if me_resp.status_code == 200:
        me_data = me_resp.json()
        me_id = me_data.get("id", "")

        # If me_id matches page_id, this IS a page token — good
        if me_id == page_id:
            return stored_token, page_id

        # Otherwise it's a User token — get the Page token
        pages_resp = await client.get(
            f"{GRAPH_API}/me/accounts",
            params={"access_token": stored_token, "fields": "id,name,access_token"},
        )

        if pages_resp.status_code == 200:
            pages = pages_resp.json().get("data", [])

            # Find the matching page
            for page in pages:
                if page.get("id") == page_id:
                    page_token = page.get("access_token", stored_token)
                    logger.info("Resolved Page token for page %s", page_id)
                    return page_token, page_id

            # If page_id not in list, use first page
            if pages:
                page = pages[0]
                page_token = page.get("access_token", stored_token)
                resolved_id = page.get("id", page_id)
                logger.info("Using first page %s (requested %s)", resolved_id, page_id)
                return page_token, resolved_id

    # Fallback: use stored token as-is
    return stored_token, page_id


async def publish_to_facebook(
    db: BotDatabase, sender: str, caption: str, media_url: str | None = None
) -> dict:
    """Post to a Facebook Page via Graph API (async, no Celery).

    Uses Page Access Token and modern endpoints:
    - Text: /{page_id}/feed (requires pages_manage_posts)
    - Photo: /{page_id}/photos (requires pages_manage_posts)
    - Video: /{page_id}/videos (requires pages_manage_posts)
    """
    token_data = db.get_platform_token(sender, "facebook")
    if not token_data or not token_data.get("access_token"):
        return {"success": False, "error": "No Facebook token. Send *setup* to connect."}

    stored_token = token_data["access_token"]
    page_id = token_data.get("page_id")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Always resolve to a proper Page Access Token
            access_token, page_id = await _get_page_token(client, stored_token, page_id or "")

            if not page_id:
                return {"success": False, "error": "No Facebook Page found. Send *setup* to reconnect."}

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
                    # Photo post — use /photos endpoint
                    endpoint = f"{GRAPH_API}/{page_id}/photos"
                    payload = {
                        "url": media_url,
                        "message": caption,
                        "access_token": access_token,
                    }
            else:
                # Text-only post
                endpoint = f"{GRAPH_API}/{page_id}/feed"
                payload = {
                    "message": caption,
                    "access_token": access_token,
                }

            resp = await client.post(endpoint, data=payload)

            if resp.status_code != 200:
                error_data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                error_code = error_data.get("error", {}).get("code", 0)
                error_subcode = error_data.get("error", {}).get("error_subcode", 0)

                logger.error("Facebook post failed for %s: code=%s subcode=%s msg=%s",
                             sender, error_code, error_subcode, error_msg)

                # Provide actionable error messages
                if error_code == 200 or "publish_actions" in error_msg.lower():
                    return {
                        "success": False,
                        "error": (
                            "Your Facebook token doesn't have posting permission.\n\n"
                            "Send *setup* to reconnect — make sure to grant "
                            "*all permissions* when Facebook asks."
                        ),
                    }
                elif error_code == 190:
                    return {
                        "success": False,
                        "error": "Your Facebook token has expired. Send *setup* to reconnect.",
                    }

                return {"success": False, "error": error_msg}

            post_id = resp.json().get("id", resp.json().get("post_id", ""))
            db.log_automation_action(sender, "facebook", "post", 1)

            # Update stored token if we resolved a better one
            if access_token != stored_token:
                db.save_platform_token(sender, "facebook", access_token, page_id,
                                       page_name=token_data.get("page_name", ""))

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
    """Post to Instagram via Graph API (async, no Celery).

    Instagram posting flow:
    1. Create media container (image_url or video_url)
    2. Wait for processing
    3. Publish the container

    Requires: instagram_basic, instagram_content_publish, pages_read_engagement
    """
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
                error_code = error_data.get("error", {}).get("code", 0)

                if error_code == 190:
                    return {"success": False, "error": "Token expired. Send *setup* to reconnect."}

                return {"success": False, "error": error_msg}

            creation_id = resp.json().get("id")

            # Step 2: Poll for processing (videos take longer)
            max_wait = 60 if is_video else 15
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
                        return {"success": False, "error": "Instagram media processing failed."}
                    # IN_PROGRESS — continue polling

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
