"""
WhatsApp Cloud API client wrapper using pywa.
Provides a simplified interface for sending messages to users.
"""

import logging
from typing import Optional

import httpx

from shared.config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TOKEN

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"


def _get_url() -> str:
    """Build messages URL using current config (not stale module-level value)."""
    from shared.config import WHATSAPP_PHONE_NUMBER_ID as _phone_id
    return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{_phone_id}/messages"


def _get_headers() -> dict:
    """Build auth headers using current config (not stale module-level value)."""
    from shared.config import WHATSAPP_TOKEN as _token
    return {
        "Authorization": f"Bearer {_token.strip()}",
        "Content-Type": "application/json",
    }


async def send_text(to: str, body: str) -> bool:
    """Send a plain text message to a WhatsApp number."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    return await _post(payload)


async def send_interactive_buttons(to: str, body: str, buttons: list[dict]) -> bool:
    """
    Send an interactive button message (max 3 buttons).

    buttons: [{"id": "btn_1", "title": "Option 1"}, ...]
    """
    btn_rows = [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}} for b in buttons[:3]]
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": btn_rows},
        },
    }
    return await _post(payload)


async def send_interactive_list(to: str, body: str, button_text: str, sections: list[dict]) -> bool:
    """
    Send an interactive list message.

    sections: [{"title": "Section", "rows": [{"id": "row1", "title": "Item", "description": "..."}]}]
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body},
            "action": {"button": button_text[:20], "sections": sections},
        },
    }
    return await _post(payload)


async def upload_media(file_path: str, mime_type: str) -> Optional[str]:
    """Upload a local file to WhatsApp Media API. Returns media_id or None.

    Uploaded media IDs are valid for 30 days and render instantly (no URL fetch lag).
    """
    from shared.config import WHATSAPP_PHONE_NUMBER_ID as _phone_id
    from shared.config import WHATSAPP_TOKEN as _token
    import os

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{_phone_id}/media"
    headers = {"Authorization": f"Bearer {_token.strip()}"}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, mime_type)}
                data = {"messaging_product": "whatsapp", "type": mime_type}
                resp = await client.post(url, headers=headers, files=files, data=data)

            if resp.status_code == 200:
                media_id = resp.json().get("id")
                logger.info("Uploaded media to WhatsApp: %s", media_id)
                return media_id

            logger.error("WhatsApp media upload failed %s: %s", resp.status_code, resp.text[:200])
            return None
    except Exception as e:
        logger.error("upload_media error: %s", e)
        return None


async def send_image(to: str, image_url: str, caption: str = "",
                     file_path: str = "", mime_type: str = "") -> bool:
    """Send an image. Prefers direct upload (file_path) over URL for instant rendering."""
    media_id = None
    if file_path and mime_type:
        media_id = await upload_media(file_path, mime_type)

    if media_id:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id},
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
    if caption:
        payload["image"]["caption"] = caption[:1024]
    return await _post(payload)


async def send_video(to: str, video_url: str, caption: str = "",
                     file_path: str = "", mime_type: str = "") -> bool:
    """Send a video. Prefers direct upload (file_path) over URL for instant rendering."""
    media_id = None
    if file_path and mime_type:
        media_id = await upload_media(file_path, mime_type)

    if media_id:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "video",
            "video": {"id": media_id},
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "video",
            "video": {"link": video_url},
        }
    if caption:
        payload["video"]["caption"] = caption[:1024]
    return await _post(payload)


async def mark_as_read(message_id: str) -> bool:
    """Mark a message as read (blue ticks)."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    return await _post(payload)


async def _post(payload: dict) -> bool:
    """Send a request to the WhatsApp Cloud API with one retry on 5xx."""
    url = _get_url()
    headers = _get_headers()
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return True
                if resp.status_code >= 500 and attempt == 0:
                    logger.warning("WhatsApp API %s (attempt 1), retrying...", resp.status_code)
                    continue
                logger.error("WhatsApp API error %s: %s", resp.status_code, resp.text[:300])
                return False
        except Exception as e:
            if attempt == 0:
                logger.warning("WhatsApp send error (attempt 1), retrying: %s", e)
                continue
            logger.error("WhatsApp send failed: %s", e)
            return False
    return False


def send_text_sync(to: str, body: str) -> bool:
    """Synchronous wrapper for use in Celery tasks."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, send_text(to, body)).result()
        return loop.run_until_complete(send_text(to, body))
    except RuntimeError:
        return asyncio.run(send_text(to, body))
