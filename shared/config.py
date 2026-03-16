"""
Shared configuration loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Database ---
# Railway provides DATABASE_URL, parse it if available
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL:
    # Parse railway DATABASE_URL: postgresql://user:password@host:port/database
    from urllib.parse import urlparse
    db_uri = urlparse(DATABASE_URL)
    DATABASE_HOST = db_uri.hostname or "localhost"
    DATABASE_PORT = db_uri.port or 5432
    DATABASE_NAME = db_uri.path.lstrip("/") or "multi_platform_bot"
    DATABASE_USER = db_uri.username or "postgres"
    DATABASE_PASSWORD = db_uri.password or ""
else:
    # Local development or explicit env vars
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
STRIPE_PRICE_ID_STARTER = os.getenv("STRIPE_PRICE_ID_STARTER", "")
STRIPE_PRICE_ID_PRO = os.getenv("STRIPE_PRICE_ID_PRO", "")
STRIPE_PRICE_ID_BUSINESS = os.getenv("STRIPE_PRICE_ID_BUSINESS", "")
# Credit pack one-time price IDs
STRIPE_PRICE_ID_PACK_100 = os.getenv("STRIPE_PRICE_ID_PACK_100", "")
STRIPE_PRICE_ID_PACK_500 = os.getenv("STRIPE_PRICE_ID_PACK_500", "")
STRIPE_PRICE_ID_PACK_1500 = os.getenv("STRIPE_PRICE_ID_PACK_1500", "")
STRIPE_PRICE_ID_PACK_5000 = os.getenv("STRIPE_PRICE_ID_PACK_5000", "")
# Legacy (single price)
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")

# --- Payment Server ---
PAYMENT_SERVER_URL = os.getenv("PAYMENT_SERVER_URL", "http://localhost:5000")

# --- AI (Anthropic Claude — text generation) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")

# --- AI (OpenAI — image generation via gpt-image-1) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# --- AI (Kling — video generation) ---
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "")

# --- Credits ---
MONTHLY_CREDITS = int(os.getenv("MONTHLY_CREDITS", 500))
FREE_SIGNUP_CREDITS = int(os.getenv("FREE_SIGNUP_CREDITS", 30))

# --- Facebook / Instagram Graph API ---
FB_APP_ID = os.getenv("FB_APP_ID", "")
FB_APP_SECRET = os.getenv("FB_APP_SECRET", "")

# --- OAuth ---
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# --- Pexels (stock images — free fallback) ---
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# --- Admin ---
ADMIN_PHONE_NUMBERS = [
    p.strip() for p in os.getenv("ADMIN_PHONE_NUMBERS", "").split(",") if p.strip()
]

# --- Platforms ---
PLATFORMS = ("facebook", "instagram")
