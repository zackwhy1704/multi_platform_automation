-- ============================================================================
-- Migration 002 — Admin Panel Support
-- Adds: message logging, admin audit trail, banned flag on users
-- Idempotent — safe to run multiple times.
-- ============================================================================

INSERT INTO schema_versions (version, description)
VALUES (3, 'Admin panel: message_log, admin_audit, users.banned')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- MESSAGE LOG — every inbound and outbound WhatsApp message
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_log (
    id              BIGSERIAL PRIMARY KEY,
    phone_number_id VARCHAR(64) NOT NULL,
    direction       VARCHAR(8) NOT NULL CHECK (direction IN ('in', 'out')),
    msg_type        VARCHAR(32) NOT NULL,        -- text, interactive, image, video, button_reply, list_reply, document, system
    text_body       TEXT,                         -- the rendered text (caption for media, body for interactive)
    wa_message_id   VARCHAR(255),                 -- WhatsApp message id when available
    metadata        JSONB DEFAULT '{}'::jsonb,    -- raw payload bits, button ids, media ids, etc.
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_message_log_user_time
    ON message_log(phone_number_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_time
    ON message_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_direction
    ON message_log(direction, created_at DESC);

-- ============================================================================
-- ADMIN AUDIT — every action taken from the admin panel
-- ============================================================================
CREATE TABLE IF NOT EXISTS admin_audit (
    id              BIGSERIAL PRIMARY KEY,
    actor           VARCHAR(64) NOT NULL DEFAULT 'admin',  -- always 'admin' for now (single password)
    action          VARCHAR(64) NOT NULL,                  -- e.g. gift_credits, reset_state, ban, refund
    target_user     VARCHAR(64),                            -- phone_number_id of affected user (if any)
    detail          JSONB DEFAULT '{}'::jsonb,
    ip_address      VARCHAR(64),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_time ON admin_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_target ON admin_audit(target_user, created_at DESC);

-- ============================================================================
-- USERS — banned flag (so admin can block a user from using the bot)
-- ============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_reason TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned) WHERE banned = TRUE;
