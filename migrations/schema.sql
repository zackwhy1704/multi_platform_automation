-- ============================================================================
-- Multi-Platform Automation Bot — PostgreSQL Schema
-- Platforms: Facebook, Instagram (Graph API only — no browser automation)
-- Interface: WhatsApp Cloud API
-- Freemium: 30 free credits on signup, 500 credits/month for subscribers
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_versions (
    version     INT PRIMARY KEY,
    applied_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
INSERT INTO schema_versions (version, description) VALUES (2, 'Freemium model with referrals')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- USERS (keyed by WhatsApp phone_number_id)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    phone_number_id        VARCHAR(64) PRIMARY KEY,
    phone_number           VARCHAR(32),
    display_name           VARCHAR(255),
    created_at             TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen              TIMESTAMP WITH TIME ZONE,

    -- Subscription
    subscription_active    BOOLEAN DEFAULT FALSE,
    subscription_expires   TIMESTAMP WITH TIME ZONE,
    stripe_customer_id     VARCHAR(255) UNIQUE,
    stripe_subscription_id VARCHAR(255) UNIQUE,

    -- Credits (new users get 100 free credits)
    credits_remaining      INT DEFAULT 100,
    credits_used           INT DEFAULT 0,
    credits_reset_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Referral
    referral_code          VARCHAR(32) UNIQUE,
    referred_by            VARCHAR(64),

    metadata               JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_active, subscription_expires);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code) WHERE referral_code IS NOT NULL;

-- ============================================================================
-- USER PROFILES (content preferences — business-focused)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    phone_number_id   VARCHAR(64) PRIMARY KEY REFERENCES users(phone_number_id) ON DELETE CASCADE,
    industry          TEXT[] DEFAULT '{}',
    offerings         TEXT[] DEFAULT '{}',
    business_goals    TEXT[] DEFAULT '{}',
    tone              TEXT[] DEFAULT '{}',
    content_style     VARCHAR(50) DEFAULT '',
    visual_style      VARCHAR(50) DEFAULT '',
    platform          VARCHAR(20),
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- PLATFORM TOKENS (OAuth tokens for Facebook / Instagram Graph API)
-- No passwords stored — tokens only, revocable from Meta at any time.
-- ============================================================================
CREATE TABLE IF NOT EXISTS platform_tokens (
    id              SERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    platform        VARCHAR(20) NOT NULL CHECK (platform IN ('facebook', 'instagram')),
    access_token    TEXT NOT NULL,
    page_id         VARCHAR(128),
    page_name       VARCHAR(255),
    account_username VARCHAR(255),
    token_expires   TIMESTAMP WITH TIME ZONE,
    pfm_profile_key VARCHAR(255),  -- Post For Me profile key (replaces Graph API token)
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phone_number_id, platform)
);

-- Add pfm_profile_key column to existing installations
ALTER TABLE platform_tokens ADD COLUMN IF NOT EXISTS pfm_profile_key VARCHAR(255);

-- Add display_language column to users (default English)
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_language VARCHAR(5) DEFAULT 'en';

CREATE INDEX IF NOT EXISTS idx_tokens_user ON platform_tokens(phone_number_id, platform);

-- ============================================================================
-- CREDIT LEDGER (audit trail for every credit transaction)
-- ============================================================================
CREATE TABLE IF NOT EXISTS credit_ledger (
    id            SERIAL PRIMARY KEY,
    user_id       VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    action        VARCHAR(50) NOT NULL,
    platform      VARCHAR(20),
    credits_spent INT NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_user ON credit_ledger(user_id, created_at DESC);

-- ============================================================================
-- AUTOMATION STATS
-- ============================================================================
CREATE TABLE IF NOT EXISTS automation_stats (
    id              SERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    platform        VARCHAR(20) NOT NULL,
    action_type     VARCHAR(50) NOT NULL,
    action_count    INT DEFAULT 1,
    session_id      VARCHAR(255),
    metadata        JSONB,
    performed_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stats_user ON automation_stats(phone_number_id, performed_at DESC);

-- ============================================================================
-- PROMO CODES
-- ============================================================================
CREATE TABLE IF NOT EXISTS promo_codes (
    code             VARCHAR(64) PRIMARY KEY,
    credits_granted  INT DEFAULT 50,
    max_uses         INT,
    current_uses     INT DEFAULT 0,
    active           BOOLEAN DEFAULT TRUE,
    expires_at       TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Default promo codes
INSERT INTO promo_codes (code, credits_granted, max_uses, active)
VALUES ('CATALYX50', 50, NULL, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO promo_codes (code, credits_granted, max_uses, active)
VALUES ('ADMIN99', 999999, NULL, TRUE)
ON CONFLICT DO NOTHING;

-- First month Pro free: grants 1,500 credits (equivalent to one Pro month)
INSERT INTO promo_codes (code, credits_granted, max_uses, active)
VALUES ('FIRSTMONTHFREE', 1500, NULL, TRUE)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- PROMO CODE USAGE (track which users used which codes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS promo_usage (
    id              SERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    code            VARCHAR(64) NOT NULL,
    credits_granted INT NOT NULL,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phone_number_id, code)
);

-- ============================================================================
-- REFERRAL TRACKING
-- ============================================================================
CREATE TABLE IF NOT EXISTS referrals (
    id                  SERIAL PRIMARY KEY,
    referrer_id         VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    referred_id         VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    referrer_credits    INT DEFAULT 50,
    referred_credits    INT DEFAULT 50,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (referred_id)
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);

-- ============================================================================
-- ENGAGED POSTS (deduplication — prevent replying to same comment twice)
-- ============================================================================
CREATE TABLE IF NOT EXISTS engaged_posts (
    id              SERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    platform        VARCHAR(20) NOT NULL,
    post_id         VARCHAR(512) NOT NULL,
    engagement_type VARCHAR(20) DEFAULT 'reply',
    engaged_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phone_number_id, platform, post_id)
);

-- ============================================================================
-- CONVERSATION STATE (WhatsApp multi-step flows)
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversation_state (
    phone_number_id VARCHAR(64) PRIMARY KEY REFERENCES users(phone_number_id) ON DELETE CASCADE,
    state           VARCHAR(128) NOT NULL,
    data            JSONB DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- SCHEDULED CONTENT
-- ============================================================================
CREATE TABLE IF NOT EXISTS scheduled_content (
    id              SERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    platform        VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    media_url       TEXT,
    scheduled_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'posted', 'failed', 'cancelled')),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scheduled_pending ON scheduled_content(status, scheduled_at) WHERE status = 'pending';

-- ============================================================================
-- WEBHOOK EVENTS (idempotency — prevent processing same Stripe event twice)
-- ============================================================================
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id    VARCHAR(255) PRIMARY KEY,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Auto-cleanup: events older than 30 days can be purged
CREATE INDEX IF NOT EXISTS idx_webhook_events_date ON webhook_events(processed_at);

-- ============================================================================
-- MESSAGE LOG (admin panel — every inbound and outbound WhatsApp message)
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_log (
    id              BIGSERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) NOT NULL,
    direction       VARCHAR(8) NOT NULL CHECK (direction IN ('in', 'out')),
    msg_type        VARCHAR(32) NOT NULL,
    text_body       TEXT,
    wa_message_id   VARCHAR(255),
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_message_log_user_time
    ON message_log(phone_number_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_time
    ON message_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_direction
    ON message_log(direction, created_at DESC);

-- ============================================================================
-- ADMIN AUDIT (admin panel — track every admin action)
-- ============================================================================
CREATE TABLE IF NOT EXISTS admin_audit (
    id              BIGSERIAL PRIMARY KEY,
    actor           VARCHAR(64) NOT NULL DEFAULT 'admin',
    action          VARCHAR(64) NOT NULL,
    target_user     VARCHAR(64),
    detail          JSONB DEFAULT '{}'::jsonb,
    ip_address      VARCHAR(64),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit(target_user, created_at DESC);

-- ============================================================================
-- USERS — admin panel additions (banned flag)
-- ============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned) WHERE banned = TRUE;
