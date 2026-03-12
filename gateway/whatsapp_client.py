"""
WhatsApp Cloud API client wrapper using pywa.
Provides a simplified interface for sending messages to users.
"""

import logging
from typing import Optional

import httpx

from shared.config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TOKEN

logger = logging.getLogger(__name__)

BASE_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
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


async def mark_as_read(message_id: str) -> bool:
    """Mark a message as read (blue ticks)."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    return await _post(payload)


async def _post(payload: dict) -> bool:
    """Send a request to the WhatsApp Cloud API."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
            if resp.status_code != 200:
                logger.error("WhatsApp API error %s: %s", resp.status_code, resp.text)
                return False
            return True
    except Exception as e:
        logger.error("WhatsApp send failed: %s", e)
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
