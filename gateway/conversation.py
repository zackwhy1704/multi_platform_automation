"""
Conversation state machine for WhatsApp multi-step flows.
API-only: Facebook + Instagram. No password collection flows.
"""

from enum import Enum


class ConversationState(str, Enum):
    IDLE = "idle"

    # Onboarding
    ONBOARDING_INDUSTRY = "onboarding_industry"
    ONBOARDING_SKILLS = "onboarding_skills"
    ONBOARDING_GOALS = "onboarding_goals"
    ONBOARDING_TONE = "onboarding_tone"

    # Platform setup (OAuth tokens only)
    SETUP_PLATFORM = "setup_platform"
    SETUP_FB_TOKEN = "setup_fb_token"
    SETUP_IG_TOKEN = "setup_ig_token"

    # Content creation
    AWAITING_POST_PLATFORM = "awaiting_post_platform"
    AWAITING_POST_CONTENT = "awaiting_post_content"
    AWAITING_SCHEDULE_TIME = "awaiting_schedule_time"

    # Engagement
    AWAITING_REPLY_PLATFORM = "awaiting_reply_platform"
