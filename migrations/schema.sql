-- ============================================================================
-- Multi-Platform Automation Bot — PostgreSQL Schema
-- Platforms: Facebook, Instagram (Graph API only — no browser automation)
-- Interface: WhatsApp Cloud API
-- Credits: 500/month, 5 per post, 3 per reply
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_versions (
    version     INT PRIMARY KEY,
    applied_at  TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
INSERT INTO schema_versions (version, description) VALUES (1, 'Initial API-only schema')
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

    -- Credits
    credits_remaining      INT DEFAULT 0,
    credits_used           INT DEFAULT 0,
    credits_reset_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    metadata               JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_active, subscription_expires);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- ============================================================================
-- USER PROFILES (content preferences)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    phone_number_id   VARCHAR(64) PRIMARY KEY REFERENCES users(phone_number_id) ON DELETE CASCADE,
    industry          TEXT[] DEFAULT '{}',
    skills            TEXT[] DEFAULT '{}',
    career_goals      TEXT[] DEFAULT '{}',
    tone              TEXT[] DEFAULT '{}',
    interests         TEXT[] DEFAULT '{}',
    content_themes    TEXT[] DEFAULT '{}',
    posting_frequency VARCHAR(32) DEFAULT 'daily',
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
    token_expires   TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (phone_number_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_tokens_user ON platform_tokens(phone_number_id, platform);

-- ============================================================================
-- CREDIT LEDGER (audit trail for every credit deduction)
-- ============================================================================
CREATE TABLE IF NOT EXISTS credit_ledger (
    id            SERIAL PRIMARY KEY,
    user_id       VARCHAR(64) REFERENCES users(phone_number_id) ON DELETE CASCADE,
    action        VARCHAR(50) NOT NULL,
    platform      VARCHAR(20) NOT NULL,
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
    discount_percent INT DEFAULT 100,
    max_uses         INT DEFAULT 1,
    current_uses     INT DEFAULT 0,
    active           BOOLEAN DEFAULT TRUE,
    expires_at       TIMESTAMP WITH TIME ZONE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

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
