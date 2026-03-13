"""
Shared configuration loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Database ---
DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", 5432))
DATABASE_NAME = os.getenv("DATABASE_NAME", "multi_platform_bot")
DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")

# --- Redis ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- WhatsApp Cloud API ---
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_verify_token")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")

# --- Stripe ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")

# --- Payment Server ---
PAYMENT_SERVER_URL = os.getenv("PAYMENT_SERVER_URL", "http://localhost:5000")

# --- AI (Anthropic) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")

# --- Credits ---
MONTHLY_CREDITS = int(os.getenv("MONTHLY_CREDITS", 500))
FREE_SIGNUP_CREDITS = int(os.getenv("FREE_SIGNUP_CREDITS", 30))
CREDIT_COST_POST = int(os.getenv("CREDIT_COST_POST", 5))
CREDIT_COST_REPLY = int(os.getenv("CREDIT_COST_REPLY", 3))

# --- Facebook / Instagram Graph API ---
FB_APP_ID = os.getenv("FB_APP_ID", "")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")

# --- Admin ---
ADMIN_PHONE_NUMBERS = [
    p.strip() for p in os.getenv("ADMIN_PHONE_NUMBERS", "").split(",") if p.strip()
]

# --- Platforms (API-only, no browser automation) ---
PLATFORMS = ("facebook", "instagram")
