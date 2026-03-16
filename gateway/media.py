"""
Media handling — download from WhatsApp Cloud API, serve locally.

WhatsApp media flow:
  1. User sends image/video → webhook contains media ID
  2. GET /v21.0/{media-id} → returns download URL
  3. GET download URL (with auth header) → binary file
  4. Save locally and serve via /media/{filename} endpoint

For production: replace local storage with S3/CDN.
"""

import os
import uuid
import logging
from typing import Optional

import httpx

from shared.config import WHATSAPP_TOKEN

logger = logging.getLogger(__name__)

MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "media_files")
os.makedirs(MEDIA_DIR, exist_ok=True)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


async def download_whatsapp_media(media_id: str) -> Optional[dict]:
    """
    Download media from WhatsApp Cloud API.

    Returns: {"file_path": "/abs/path", "filename": "uuid.ext", "mime_type": "image/jpeg"}
    or None on failure.
    """
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get the download URL
            resp = await client.get(f"{GRAPH_API_BASE}/{media_id}", headers=headers)
            if resp.status_code != 200:
                logger.error("Failed to get media URL for %s: %s", media_id, resp.text)
                return None

            media_info = resp.json()
            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")

            if not download_url:
                logger.error("No download URL in media response: %s", media_info)
                return None

            # Step 2: Download the actual file
            file_resp = await client.get(download_url, headers=headers)
            if file_resp.status_code != 200:
                logger.error("Failed to download media: %s", file_resp.status_code)
                return None

            # Determine extension from mime type
            ext = _mime_to_ext(mime_type)
            filename = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(MEDIA_DIR, filename)

            with open(file_path, "wb") as f:
                f.write(file_resp.content)

            logger.info("Downloaded media: %s (%s, %d bytes)", filename, mime_type, len(file_resp.content))

            return {
                "file_path": file_path,
                "filename": filename,
                "mime_type": mime_type,
            }

    except Exception as e:
        logger.error("Error downloading media %s: %s", media_id, e)
        return None


def get_media_public_url(filename: str, base_url: str) -> str:
    """Get the publicly accessible URL for a media file."""
    return f"{base_url}/media/{filename}"


def _mime_to_ext(mime_type: str) -> str:
    """Convert MIME type to file extension."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/3gpp": ".3gp",
        "video/quicktime": ".mov",
        "audio/aac": ".aac",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "application/pdf": ".pdf",
    }
    return mapping.get(mime_type, ".bin")


def is_image(mime_type: str) -> bool:
    return mime_type.startswith("image/")


def is_video(mime_type: str) -> bool:
    return mime_type.startswith("video/")
