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

    # Engagement
    AWAITING_REPLY_PLATFORM = "awaiting_reply_platform"

    # Credit pack purchase
    AWAITING_PACK_CHOICE = "awaiting_pack_choice"

    # Language selection
    AWAITING_LANGUAGE = "awaiting_language"

    # AI content generation
    AWAITING_AI_IMAGE_PROMPT = "awaiting_ai_image_prompt"

    # Avatar video — one-time setup
    AWAITING_AVATAR_PHOTO        = "awaiting_avatar_photo"         # user sends reference photo
    AWAITING_AVATAR_VOICE_SAMPLE = "awaiting_avatar_voice_sample"  # user sends 30-60s voice note

    # Avatar video — per-video generation
    AWAITING_AVATAR_SCRIPT = "awaiting_avatar_script"  # user types their spoken script
    AWAITING_AVATAR_STYLE  = "awaiting_avatar_style"   # user picks Professional/Warm/Luxury

    # Video command top-level menu
    AWAITING_VIDEO_MENU    = "awaiting_video_menu"      # user picks from video menu

    # Content Intelligence Pipeline — pillar setup
    AWAITING_PILLAR_MAIN   = "awaiting_pillar_main"    # user types main content pillar
    AWAITING_PILLAR_SUB1   = "awaiting_pillar_sub1"    # user types sub-pillar 1
    AWAITING_PILLAR_SUB2   = "awaiting_pillar_sub2"    # user types sub-pillar 2
    AWAITING_PILLAR_CONFIRM = "awaiting_pillar_confirm" # user confirms pillar setup

    # Content Intelligence Pipeline — idea mining
    AWAITING_IDEA_SOURCE   = "awaiting_idea_source"    # user sends URL or pastes text
    AWAITING_IDEA_CONFIRM  = "awaiting_idea_confirm"   # user reviews claims, confirms grade

    # Content Intelligence Pipeline — content expansion
    AWAITING_FORMAT_CHOICE = "awaiting_format_choice"  # user picks Reel/Carousel/Text/B-roll
    AWAITING_EXPAND_CONFIRM = "awaiting_expand_confirm" # user reviews expanded content

    # Content Intelligence Pipeline — production (Reel → avatar video)
    AWAITING_REEL_STYLE    = "awaiting_reel_style"     # user picks video style for Reel
