"""
Instagram Celery tasks — Graph API-based.
Uses Instagram Graph API for Business accounts (requires FB Page link).
Supports: publishing posts, replying to comments on own posts.
"""

import logging

import requests

from workers.celery_app import celery_app
from shared.database import BotDatabase

logger = logging.getLogger(__name__)
db = BotDatabase()

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def _notify(phone: str, msg: str):
    from workers.notification import send_whatsapp_notification
    send_whatsapp_notification.delay(phone, msg)


def _get_token(phone_number_id: str) -> tuple:
    """Get Instagram access token and IG business account ID."""
    token_data = db.get_platform_token(phone_number_id, "instagram")
    if not token_data or not token_data.get("access_token"):
        raise ValueError(f"No Instagram token for user {phone_number_id}")
    return token_data["access_token"], token_data.get("page_id")  # page_id stores IG business account ID


def _resolve_ig_account(access_token: str) -> str:
    """Resolve IG Business Account ID from the linked FB Page."""
    # Get pages
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={"access_token": access_token, "fields": "id,instagram_business_account"},
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", [])

    for page in pages:
        ig_account = page.get("instagram_business_account", {}).get("id")
        if ig_account:
            return ig_account

    raise ValueError("No Instagram Business Account found linked to your Facebook Pages")


@celery_app.task(bind=True, name="services.instagram.tasks.post_task", max_retries=2)
def post_task(self, phone_number_id: str, content: str, media_url: str = None, image_url: str = None):
    """
    Post to Instagram via Graph API.
    Instagram requires an image_url for feed posts.
    If no image is provided, creates a text-only story (or fails).
    media_url is the new parameter name; image_url is kept for backwards compatibility.
    """
    # Accept either parameter name
    image_url = media_url or image_url

    try:
        access_token, ig_account_id = _get_token(phone_number_id)

        if not ig_account_id:
            ig_account_id = _resolve_ig_account(access_token)
            db.save_platform_token(phone_number_id, "instagram", access_token, ig_account_id)

        _notify(phone_number_id, "Publishing to Instagram...")

        if not image_url:
            _notify(
                phone_number_id,
                "Instagram requires an image for feed posts. Please include an image URL next time.\n"
                "Post cancelled — your credits have not been deducted.",
            )
            # Refund credits
            db.execute_query(
                "UPDATE users SET credits_remaining = credits_remaining + 5, credits_used = credits_used - 5 WHERE phone_number_id = %s",
                (phone_number_id,),
            )
            return {"success": False, "error": "Image required for Instagram"}

        # Step 1: Create media container (image or video)
        is_video = any(image_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi"))
        container_data = {
            "caption": content,
            "access_token": access_token,
        }
        if is_video:
            container_data["media_type"] = "VIDEO"
            container_data["video_url"] = image_url
        else:
            container_data["image_url"] = image_url

        container_resp = requests.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media",
            data=container_data,
            timeout=30,
        )
        container_resp.raise_for_status()
        creation_id = container_resp.json().get("id")

        # Step 2: Publish the container
        import time
        time.sleep(5)  # Wait for processing

        publish_resp = requests.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            },
            timeout=30,
        )
        publish_resp.raise_for_status()
        media_id = publish_resp.json().get("id", "")

        db.log_automation_action(phone_number_id, "instagram", "post", 1, session_id=self.request.id)
        _notify(phone_number_id, f"Instagram post published!\n\n{content[:100]}...")

        return {"success": True, "media_id": media_id, "task_id": self.request.id}

    except Exception as e:
        logger.error("Instagram post failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"Instagram post failed: {str(e)}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        return {"success": False, "error": str(e)}


@celery_app.task(bind=True, name="services.instagram.tasks.ai_post_task", max_retries=2)
def ai_post_task(self, phone_number_id: str):
    """Generate AI caption for Instagram (image still required separately)."""
    profile = db.get_user_profile(phone_number_id)
    if not profile:
        _notify(phone_number_id, "Profile not set up. Send *start* first.")
        return {"success": False, "error": "No profile"}

    from services.ai.ai_service import generate_post
    content = generate_post("instagram", profile)
    if not content:
        _notify(phone_number_id, "AI content generation failed.")
        return {"success": False, "error": "AI generation failed"}

    _notify(
        phone_number_id,
        f"*AI-Generated Caption:*\n\n{content}\n\n"
        "Note: Instagram requires an image. Please send the image URL and I'll publish the post.",
    )
    return {"success": True, "caption": content}


@celery_app.task(bind=True, name="services.instagram.tasks.reply_task", max_retries=1)
def reply_task(self, phone_number_id: str, max_replies: int = 5):
    """Auto-reply to comments on recent Instagram posts."""
    try:
        access_token, ig_account_id = _get_token(phone_number_id)

        if not ig_account_id:
            ig_account_id = _resolve_ig_account(access_token)

        _notify(phone_number_id, "Scanning Instagram posts for comments...")

        # Get recent media
        resp = requests.get(
            f"{GRAPH_API_BASE}/{ig_account_id}/media",
            params={"access_token": access_token, "limit": 5, "fields": "id,caption,comments{id,text,from}"},
            timeout=15,
        )
        resp.raise_for_status()
        media_list = resp.json().get("data", [])

        replies_sent = 0
        from services.ai.ai_service import generate_reply

        profile = db.get_user_profile(phone_number_id)
        tone = ", ".join(profile.get("tone", ["professional"])) if profile else "professional"

        for media in media_list:
            if replies_sent >= max_replies:
                break

            caption = media.get("caption", "")
            comments = media.get("comments", {}).get("data", [])

            for comment in comments:
                if replies_sent >= max_replies:
                    break

                comment_id = comment["id"]

                if db.has_engaged_post(phone_number_id, "instagram", comment_id):
                    continue

                user_lang = db.get_display_language(phone_number_id)
                reply_text = generate_reply("instagram", caption, comment.get("text", ""), tone, language=user_lang)
                if not reply_text:
                    continue

                reply_resp = requests.post(
                    f"{GRAPH_API_BASE}/{comment_id}/replies",
                    data={"message": reply_text, "access_token": access_token},
                    timeout=15,
                )

                if reply_resp.status_code == 200:
                    db.mark_post_engaged(phone_number_id, "instagram", comment_id, "reply")
                    replies_sent += 1

        db.log_automation_action(phone_number_id, "instagram", "comment", replies_sent, session_id=self.request.id)
        _notify(phone_number_id, f"Instagram reply engagement complete!\nReplied to {replies_sent} comments.")

        return {"success": True, "replies_sent": replies_sent}

    except Exception as e:
        logger.error("Instagram reply task failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"Instagram reply failed: {str(e)}")
        return {"success": False, "error": str(e)}
