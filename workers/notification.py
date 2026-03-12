"""
WhatsApp notification task — lightweight Celery task for sending messages.
"""

import logging
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.notification.send_whatsapp_notification")
def send_whatsapp_notification(phone_number: str, message: str):
    """Send a WhatsApp message from a Celery worker."""
    from gateway.whatsapp_client import send_text_sync

    try:
        success = send_text_sync(phone_number, message)
        if success:
            logger.info("Notification sent to %s", phone_number)
        else:
            logger.error("Failed to send notification to %s", phone_number)
    except Exception as e:
        logger.error("Notification error for %s: %s", phone_number, e)
