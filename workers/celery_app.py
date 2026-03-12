"""
Celery application configuration for multi-platform automation.
Facebook + Instagram only (Graph API). No browser automation.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from celery import Celery
from kombu import Queue, Exchange

celery_app = Celery(
    "multi_platform_automation",
    include=[
        "services.facebook.tasks",
        "services.instagram.tasks",
        "workers.notification",
    ],
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app.conf.broker_url = REDIS_URL
celery_app.conf.result_backend = REDIS_URL

# --- Exchanges ---
facebook_exchange = Exchange("facebook", type="direct")
instagram_exchange = Exchange("instagram", type="direct")
notifications_exchange = Exchange("notifications", type="direct")

# --- Queues (per-platform, per-action) ---
celery_app.conf.task_queues = (
    # Facebook
    Queue("facebook_posting", facebook_exchange, routing_key="facebook.posting", queue_arguments={"x-max-priority": 10}),
    Queue("facebook_engagement", facebook_exchange, routing_key="facebook.engagement", queue_arguments={"x-max-priority": 5}),
    # Instagram
    Queue("instagram_posting", instagram_exchange, routing_key="instagram.posting", queue_arguments={"x-max-priority": 10}),
    Queue("instagram_engagement", instagram_exchange, routing_key="instagram.engagement", queue_arguments={"x-max-priority": 5}),
    # Notifications
    Queue("notifications", notifications_exchange, routing_key="notifications.send", queue_arguments={"x-max-priority": 8}),
)

# --- Task routing ---
celery_app.conf.task_routes = {
    # Facebook
    "services.facebook.tasks.post_task": {"queue": "facebook_posting"},
    "services.facebook.tasks.ai_post_task": {"queue": "facebook_posting"},
    "services.facebook.tasks.reply_task": {"queue": "facebook_engagement"},
    # Instagram
    "services.instagram.tasks.post_task": {"queue": "instagram_posting"},
    "services.instagram.tasks.ai_post_task": {"queue": "instagram_posting"},
    "services.instagram.tasks.reply_task": {"queue": "instagram_engagement"},
    # Notifications
    "workers.notification.send_whatsapp_notification": {"queue": "notifications"},
}

# --- Worker config ---
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.worker_max_tasks_per_child = 50
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True

# --- Timeouts ---
celery_app.conf.task_time_limit = 600       # 10 min hard limit
celery_app.conf.task_soft_time_limit = 540  # 9 min soft limit

# --- Serialization ---
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
celery_app.conf.result_expires = 3600

# --- Retry ---
celery_app.conf.task_default_retry_delay = 60
celery_app.conf.task_max_retries = 3

# --- Logging ---
celery_app.conf.worker_log_format = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"

# --- Testing ---
celery_app.conf.task_always_eager = os.getenv("CELERY_ALWAYS_EAGER", "False").lower() == "true"
