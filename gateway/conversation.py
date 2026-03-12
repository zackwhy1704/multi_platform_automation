"""
Conversation state machine for WhatsApp multi-step flows.

States:
  IDLE                  → default, waiting for commands
  ONBOARDING_INDUSTRY   → collecting industry info
  ONBOARDING_SKILLS     → collecting skills
  ONBOARDING_GOALS      → collecting career goals
  ONBOARDING_TONE       → collecting tone preference
  SETUP_PLATFORM        → choosing which platform to set up
  SETUP_CREDENTIALS     → collecting platform login credentials
  SETUP_EMAIL           → collecting email for platform
  SETUP_PASSWORD        → collecting password for platform
  AWAITING_POST_CONTENT → user is writing a post
  AWAITING_POST_PLATFORM→ user is choosing which platform to post to
  AWAITING_SCHEDULE_TIME→ user is choosing schedule time
"""

from enum import Enum


class ConversationState(str, Enum):
    IDLE = "idle"

    # Onboarding
    ONBOARDING_INDUSTRY = "onboarding_industry"
    ONBOARDING_SKILLS = "onboarding_skills"
    ONBOARDING_GOALS = "onboarding_goals"
    ONBOARDING_TONE = "onboarding_tone"

    # Platform setup
    SETUP_PLATFORM = "setup_platform"
    SETUP_EMAIL = "setup_email"
    SETUP_PASSWORD = "setup_password"
    SETUP_FB_TOKEN = "setup_fb_token"
    SETUP_IG_TOKEN = "setup_ig_token"

    # Content creation
    AWAITING_POST_PLATFORM = "awaiting_post_platform"
    AWAITING_POST_CONTENT = "awaiting_post_content"
    AWAITING_SCHEDULE_TIME = "awaiting_schedule_time"

    # Engagement
    AWAITING_REPLY_PLATFORM = "awaiting_reply_platform"
