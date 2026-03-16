"""
Facebook Celery tasks — Graph API-based.
Uses Page Access Token for posting and comment management.
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
    """Get Facebook access token and page ID."""
    token_data = db.get_platform_token(phone_number_id, "facebook")
    if not token_data or not token_data.get("access_token"):
        raise ValueError(f"No Facebook token for user {phone_number_id}")
    return token_data["access_token"], token_data.get("page_id")


def _resolve_page_id(access_token: str) -> str:
    """Get the first page ID associated with the token."""
    resp = requests.get(
        f"{GRAPH_API_BASE}/me/accounts",
        params={"access_token": access_token},
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("data", [])
    if not pages:
        raise ValueError("No Facebook Pages found for this token")
    return pages[0]["id"]


@celery_app.task(bind=True, name="services.facebook.tasks.post_task", max_retries=2)
def post_task(self, phone_number_id: str, content: str, media_url: str = None):
    """Post to a Facebook Page via Graph API."""
    try:
        access_token, page_id = _get_token(phone_number_id)

        if not page_id:
            page_id = _resolve_page_id(access_token)
            db.save_platform_token(phone_number_id, "facebook", access_token, page_id)

        _notify(phone_number_id, "Publishing to Facebook...")

        endpoint = f"{GRAPH_API_BASE}/{page_id}/feed"
        payload = {"message": content, "access_token": access_token}

        if media_url:
            # Detect video vs image by file extension
            is_video = any(media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi"))
            if is_video:
                endpoint = f"{GRAPH_API_BASE}/{page_id}/videos"
                payload["file_url"] = media_url
                payload["description"] = content
                payload.pop("message", None)
            else:
                endpoint = f"{GRAPH_API_BASE}/{page_id}/photos"
                payload["url"] = media_url

        resp = requests.post(endpoint, data=payload, timeout=30)
        resp.raise_for_status()
        post_id = resp.json().get("id", "")

        db.log_automation_action(phone_number_id, "facebook", "post", 1, session_id=self.request.id)
        _notify(phone_number_id, f"Facebook post published!\n\n{content[:100]}...")

        return {"success": True, "post_id": post_id, "task_id": self.request.id}

    except Exception as e:
        logger.error("Facebook post failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"Facebook post failed: {str(e)}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        return {"success": False, "error": str(e)}


@celery_app.task(bind=True, name="services.facebook.tasks.ai_post_task", max_retries=2)
def ai_post_task(self, phone_number_id: str):
    """Generate AI content and post to Facebook."""
    profile = db.get_user_profile(phone_number_id)
    if not profile:
        _notify(phone_number_id, "Profile not set up. Send *start* first.")
        return {"success": False, "error": "No profile"}

    from services.ai.ai_service import generate_post
    content = generate_post("facebook", profile)
    if not content:
        _notify(phone_number_id, "AI content generation failed.")
        return {"success": False, "error": "AI generation failed"}

    _notify(phone_number_id, f"*AI-Generated Post:*\n\n{content}\n\nPublishing now...")
    return post_task(phone_number_id, content)


@celery_app.task(bind=True, name="services.facebook.tasks.reply_task", max_retries=1)
def reply_task(self, phone_number_id: str, max_replies: int = 5):
    """Auto-reply to comments on recent Facebook Page posts."""
    try:
        access_token, page_id = _get_token(phone_number_id)

        if not page_id:
            page_id = _resolve_page_id(access_token)

        _notify(phone_number_id, "Scanning Facebook posts for comments...")

        # Get recent posts
        resp = requests.get(
            f"{GRAPH_API_BASE}/{page_id}/posts",
            params={"access_token": access_token, "limit": 5, "fields": "id,message,comments.limit(10){id,message,from}"},
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", [])

        replies_sent = 0
        from services.ai.ai_service import generate_reply

        profile = db.get_user_profile(phone_number_id)
        tone = ", ".join(profile.get("tone", ["professional"])) if profile else "professional"

        for post in posts:
            if replies_sent >= max_replies:
                break

            post_message = post.get("message", "")
            comments = post.get("comments", {}).get("data", [])

            for comment in comments:
                if replies_sent >= max_replies:
                    break

                comment_id = comment["id"]

                # Skip if already replied
                if db.has_engaged_post(phone_number_id, "facebook", comment_id):
                    continue

                reply_text = generate_reply("facebook", post_message, comment.get("message", ""), tone)
                if not reply_text:
                    continue

                # Post reply
                reply_resp = requests.post(
                    f"{GRAPH_API_BASE}/{comment_id}/comments",
                    data={"message": reply_text, "access_token": access_token},
                    timeout=15,
                )

                if reply_resp.status_code == 200:
                    db.mark_post_engaged(phone_number_id, "facebook", comment_id, "reply")
                    replies_sent += 1

        db.log_automation_action(phone_number_id, "facebook", "comment", replies_sent, session_id=self.request.id)
        _notify(phone_number_id, f"Facebook reply engagement complete!\nReplied to {replies_sent} comments.")

        return {"success": True, "replies_sent": replies_sent}

    except Exception as e:
        logger.error("Facebook reply task failed for %s: %s", phone_number_id, e)
        _notify(phone_number_id, f"Facebook reply failed: {str(e)}")
        return {"success": False, "error": str(e)}
