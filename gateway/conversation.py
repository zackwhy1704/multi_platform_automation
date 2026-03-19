"""
Conversation state machine for WhatsApp multi-step flows.
API-only: Facebook + Instagram. Freemium with referrals.
"""

from enum import Enum


class ConversationState(str, Enum):
    IDLE = "idle"

    # Onboarding (enhanced: includes content + visual style)
    ONBOARDING_INDUSTRY = "onboarding_industry"
    ONBOARDING_OFFERINGS = "onboarding_offerings"
    ONBOARDING_GOALS = "onboarding_goals"
    ONBOARDING_TONE = "onboarding_tone"
    ONBOARDING_CONTENT_STYLE = "onboarding_content_style"
    ONBOARDING_VISUAL_STYLE = "onboarding_visual_style"
    ONBOARDING_PLATFORM = "onboarding_platform"

    # Promo / referral code entry
    AWAITING_PROMO_CODE = "awaiting_promo_code"

    # Platform setup (Post For Me OAuth flow)
    SETUP_PLATFORM = "setup_platform"
    SETUP_MANUAL_CHOOSE = "setup_manual_choose"   # shown OAuth URL, waiting for "Done"

    # Content creation — media-aware flow
    AWAITING_POST_PLATFORM = "awaiting_post_platform"
    AWAITING_POST_MEDIA = "awaiting_post_media"        # waiting for user to send photo/video
    AWAITING_POST_CAPTION = "awaiting_post_caption"    # write caption or type "ai"
    AWAITING_POST_CONFIRM = "awaiting_post_confirm"    # preview → approve/edit/cancel
    AWAITING_POST_CONTENT = "awaiting_post_content"    # text-only content
    AWAITING_SCHEDULE_TIME = "awaiting_schedule_time"

    # Weekly auto-post
    AWAITING_AUTO_PLATFORM = "awaiting_auto_platform"
    AWAITING_AUTO_COUNT = "awaiting_auto_count"        # how many posts (3/5/7/others)
    AWAITING_AUTO_COUNT_CUSTOM = "awaiting_auto_count_custom"  # user types custom number
    AWAITING_AUTO_TYPE = "awaiting_auto_type"          # content type for batch
    AWAITING_AUTO_TYPE_CUSTOM = "awaiting_auto_type_custom"    # user types custom content type
    AWAITING_AUTO_CONFIRM = "awaiting_auto_confirm"    # approve all / edit / cancel

    # Engagement
    AWAITING_REPLY_PLATFORM = "awaiting_reply_platform"

    # Credit pack purchase
    AWAITING_PACK_CHOICE = "awaiting_pack_choice"
