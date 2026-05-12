"""
Video / Content Intelligence Pipeline — WhatsApp flow handlers.

Single entry point: 'video' command.

State machine:
  - Fully set up (pillars + avatar) → show menu: New Idea / Update Pillars / Redo Voice
  - Pillars missing                 → pillar setup flow (3 steps)
  - Avatar missing                  → avatar setup flow (photo → voice clone)
  - After pillars: idea mining → grade → format choice → expand → produce

Sub-flows accessible from the menu:
  New Idea       → AWAITING_IDEA_SOURCE     (pillar-aware idea pipeline)
  Update Pillars → AWAITING_PILLAR_MAIN     (re-set pillars)
  Redo Voice     → AWAITING_AVATAR_VOICE_SAMPLE (re-clone voice)
"""

from __future__ import annotations

import asyncio
import logging

from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)


# ===========================================================================
# UNIFIED VIDEO ENTRY POINT
# ===========================================================================

async def handle_video(db: BotDatabase, sender: str, text: str):
    """
    Single entry for the 'video' command.
    Routes based on what the user has set up:
      - No pillars        → pillar setup (required first)
      - No avatar profile → avatar setup (photo + voice)
      - Fully set up      → show menu: New Idea / Update Pillars / Redo Voice
    """
    pillars = db.get_content_pillars(sender)
    avatar  = db.get_avatar_profile(sender) or {}
    has_photo = bool(avatar.get("profile_photo_url"))
    has_voice = avatar.get("voice_clone_status") == "ready"

    if not pillars:
        await wa.send_text(
            sender,
            "*Video Content Setup — Step 1* 🏛\n\n"
            "First, let's set your content pillars — the niche lens for all your videos.\n\n"
            "*Step 1 of 3 — Main Pillar*\n"
            "What is the core topic your content revolves around?\n\n"
            "_Examples: Real Estate, Insurance, Interior Design, Personal Finance_",
        )
        db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_MAIN,
                                   {"from_video_cmd": True})
        return

    if not has_photo or not has_voice:
        missing = []
        if not has_photo:
            missing.append("profile photo")
        if not has_voice:
            missing.append("voice clone")
        # Delegate to avatar setup
        from gateway.handlers.actions import handle_avatar_setup
        await handle_avatar_setup(db=db, sender=sender, text=text)
        return

    # Fully set up — show menu
    await wa.send_interactive_list(
        sender,
        f"*Video Content* 🎬\n\n"
        f"Niche: *{pillars['main_pillar']}* · {pillars['sub_pillar_1']} · {pillars['sub_pillar_2']}\n\n"
        "What would you like to do?",
        "Choose Option",
        [{
            "title": "Options",
            "rows": [
                {"id": "video_new_idea",      "title": "New Content Idea",
                 "description": "Mine a URL or text → grade → Reel/Post/Carousel"},
                {"id": "video_update_pillars", "title": "Update Content Pillars",
                 "description": "Change your niche focus"},
                {"id": "video_redo_voice",    "title": "Redo Voice Sample",
                 "description": "Re-clone your AI voice"},
            ],
        }],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_VIDEO_MENU, {})


# ===========================================================================
# PILLAR SETUP (called internally from video flow)
# ===========================================================================

async def _start_pillar_setup(sender: str, data: dict, db: BotDatabase):
    """Begin pillar setup. data should carry from_video_cmd=True if coming from video."""
    await wa.send_text(
        sender,
        "*Content Pillars Setup* 🏛\n\n"
        "Your content pillars define the niche lens for all your videos.\n\n"
        "*Step 1 of 3 — Main Pillar*\n"
        "What is the core topic your content revolves around?\n\n"
        "_Examples: Real Estate, Insurance, Interior Design, Personal Finance_",
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_MAIN, data)


async def handle_pillar_step(db: BotDatabase, sender: str, text: str,
                              state: ConversationState, data: dict, **kwargs):
    """Handle all pillar setup states."""
    text = text.strip()
    if not text or text.lower() in ("cancel", "exit"):
        db.clear_conversation_state(sender)
        await wa.send_text(sender, "Pillar setup cancelled.")
        return

    if state == ConversationState.AWAITING_PILLAR_MAIN:
        data["main_pillar"] = text
        db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_SUB1, data)
        await wa.send_text(
            sender,
            f"Main pillar set: *{text}*\n\n"
            "*Step 2 of 3 — Sub-Pillar 1*\n"
            "What is a specific sub-topic within your main pillar?\n\n"
            f"_Example for {text}: Market Trends_",
        )

    elif state == ConversationState.AWAITING_PILLAR_SUB1:
        data["sub_pillar_1"] = text
        db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_SUB2, data)
        await wa.send_text(
            sender,
            f"Sub-pillar 1: *{text}*\n\n"
            "*Step 3 of 3 — Sub-Pillar 2*\n"
            "What is another sub-topic you want to cover?\n\n"
            f"_Example: Buying Tips_",
        )

    elif state == ConversationState.AWAITING_PILLAR_SUB2:
        data["sub_pillar_2"] = text
        db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_CONFIRM, data)
        await wa.send_interactive_buttons(
            sender,
            f"*Your content pillars:*\n\n"
            f"  🎯 Main pillar: *{data['main_pillar']}*\n"
            f"  📌 Sub-pillar 1: *{data['sub_pillar_1']}*\n"
            f"  📌 Sub-pillar 2: *{data['sub_pillar_2']}*\n\n"
            "Confirm to save?",
            [
                {"id": "confirm_pillars", "title": "Save Pillars ✓"},
                {"id": "redo_pillars",    "title": "Start Over"},
            ],
        )

    elif state == ConversationState.AWAITING_PILLAR_CONFIRM:
        if text == "confirm_pillars":
            db.save_content_pillars(
                sender,
                main_pillar=data["main_pillar"],
                sub_pillar_1=data["sub_pillar_1"],
                sub_pillar_2=data["sub_pillar_2"],
            )
            db.clear_conversation_state(sender)
            await wa.send_text(
                sender,
                "✅ *Content pillars saved!*\n\n"
                f"  Main: {data['main_pillar']}\n"
                f"  Sub 1: {data['sub_pillar_1']}\n"
                f"  Sub 2: {data['sub_pillar_2']}\n\n"
                "Send *video* to create content.",
            )
        elif text == "redo_pillars":
            db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_MAIN,
                                       {"from_video_cmd": True})
            await wa.send_text(
                sender,
                "*Step 1 of 3 — Main Pillar*\n"
                "What is the core topic your content revolves around?",
            )
        else:
            await wa.send_interactive_buttons(
                sender,
                "Please tap a button to confirm or start over:",
                [
                    {"id": "confirm_pillars", "title": "Save Pillars ✓"},
                    {"id": "redo_pillars",    "title": "Start Over"},
                ],
            )


# ===========================================================================
# VIDEO MENU STATE HANDLER
# ===========================================================================

async def handle_video_menu_step(db: BotDatabase, sender: str, text: str,
                                  state: ConversationState, data: dict, **kwargs):
    """Handle the video menu selection."""
    if text == "video_new_idea":
        pillars = db.get_content_pillars(sender)
        await _start_idea_mining(db, sender, pillars)

    elif text == "video_update_pillars":
        existing = db.get_content_pillars(sender)
        await wa.send_text(
            sender,
            "*Update Content Pillars*\n\n"
            f"Current: *{existing['main_pillar']}* · {existing['sub_pillar_1']} · {existing['sub_pillar_2']}\n\n"
            "*Step 1 of 3 — New Main Pillar*\n"
            "What should the new main topic be?",
        )
        db.set_conversation_state(sender, ConversationState.AWAITING_PILLAR_MAIN,
                                   {"from_video_cmd": True})

    elif text == "video_redo_voice":
        from gateway.handlers.actions import _prompt_voice_sample
        await _prompt_voice_sample(sender)
        db.set_conversation_state(sender, ConversationState.AWAITING_AVATAR_VOICE_SAMPLE, {})

    else:
        await wa.send_interactive_list(
            sender,
            "Please select an option:",
            "Choose Option",
            [{
                "title": "Options",
                "rows": [
                    {"id": "video_new_idea",      "title": "New Content Idea",    "description": "Mine → grade → Reel/Post/Carousel"},
                    {"id": "video_update_pillars", "title": "Update Pillars",     "description": "Change your niche focus"},
                    {"id": "video_redo_voice",    "title": "Redo Voice Sample",  "description": "Re-clone your AI voice"},
                ],
            }],
        )


# ===========================================================================
# CONTENT IDEA PIPELINE — internal start
# ===========================================================================

async def _start_idea_mining(db: BotDatabase, sender: str, pillars: dict):
    """Begin idea mining flow (called from menu or direct entry)."""

    await wa.send_text(
        sender,
        f"*Content Intelligence* 💡\n\n"
        f"Your niche lens:\n"
        f"  Main: *{pillars['main_pillar']}*\n"
        f"  Sub 1: {pillars['sub_pillar_1']} | Sub 2: {pillars['sub_pillar_2']}\n\n"
        "Share your idea source:\n\n"
        "  📰 *Paste a URL* — I'll scrape the article\n"
        "  📝 *Paste text* — paste a summary, transcript, or any text\n\n"
        "_Type or paste below:_",
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_IDEA_SOURCE,
                               {"pillars": dict(pillars)})


# ===========================================================================
# CONTENT IDEA PIPELINE — state handlers
# ===========================================================================

async def handle_content_step(db: BotDatabase, sender: str, text: str,
                               state: ConversationState, data: dict, **kwargs):
    """Dispatch all content intelligence pipeline states."""

    if state == ConversationState.AWAITING_IDEA_SOURCE:
        await _handle_idea_source(db, sender, text, data)

    elif state == ConversationState.AWAITING_IDEA_CONFIRM:
        await _handle_idea_confirm(db, sender, text, data)

    elif state == ConversationState.AWAITING_FORMAT_CHOICE:
        await _handle_format_choice(db, sender, text, data)

    elif state == ConversationState.AWAITING_EXPAND_CONFIRM:
        await _handle_expand_confirm(db, sender, text, data)

    elif state == ConversationState.AWAITING_REEL_STYLE:
        await _handle_reel_style(db, sender, text, data)


# ---------------------------------------------------------------------------
# Stage 1 → 2: Mine and grade
# ---------------------------------------------------------------------------

async def _handle_idea_source(db: BotDatabase, sender: str, text: str, data: dict):
    text = text.strip()
    if not text:
        await wa.send_text(sender, "Please paste a URL or some text to analyse.")
        return

    pillars = data.get("pillars", {})
    is_url = text.startswith("http://") or text.startswith("https://")

    await wa.send_text(sender, "⏳ Analysing your idea... This takes about 15 seconds.")

    from services.ai.content_intelligence import scrape_url, extract_key_claims, grade_idea

    # Mine
    if is_url:
        raw_text = await scrape_url(text)
        if not raw_text:
            await wa.send_text(
                sender,
                "⚠️ I couldn't read that URL. Please paste the article text directly instead.",
            )
            return
        source_url = text
        source_text = raw_text
    else:
        source_url = None
        source_text = text

    # Extract claims
    claims = await asyncio.to_thread(extract_key_claims, source_text)
    if not claims:
        await wa.send_text(
            sender,
            "⚠️ Couldn't extract key points from that content. Try a longer or clearer text.",
        )
        return

    # Grade
    grade = await asyncio.to_thread(grade_idea, claims, pillars)

    # Save to DB
    profile = db.get_user_profile(sender) or {}
    idea_id = db.save_content_idea(
        sender,
        source_url=source_url,
        source_text=source_text[:1000],
        key_claims=claims,
        virality_score=grade["virality"],
        originality_score=grade["originality"],
        pillar_score=grade["pillar_alignment"],
        niche_angle=grade["niche_angle"],
        status="graded",
    )

    data["idea_id"] = idea_id
    data["claims"] = claims
    data["grade"] = grade
    db.set_conversation_state(sender, ConversationState.AWAITING_IDEA_CONFIRM, data)

    # Format grade report
    claims_preview = "\n".join(f"  • {c}" for c in claims[:4])
    v = grade["virality"]
    o = grade["originality"]
    p = grade["pillar_alignment"]
    bar = lambda n: "█" * n + "░" * (10 - n)

    await wa.send_text(
        sender,
        f"*Idea Analysis*\n\n"
        f"*Key points found:*\n{claims_preview}\n\n"
        f"*Scores:*\n"
        f"  Virality      {bar(v)} {v}/10\n"
        f"  Originality   {bar(o)} {o}/10\n"
        f"  Pillar fit    {bar(p)} {p}/10\n\n"
        f"*Niche angle:*\n_{grade['niche_angle']}_\n\n"
        f"_{grade['summary']}_",
    )

    await wa.send_interactive_buttons(
        sender,
        "Happy with this idea?",
        [
            {"id": "idea_expand",  "title": "Expand This ✓"},
            {"id": "idea_remine",  "title": "Try Another Idea"},
        ],
    )


# ---------------------------------------------------------------------------
# Stage 2 → 3: Idea confirmed → choose format
# ---------------------------------------------------------------------------

async def _handle_idea_confirm(db: BotDatabase, sender: str, text: str, data: dict):
    if text == "idea_remine":
        pillars = data.get("pillars", {})
        db.set_conversation_state(sender, ConversationState.AWAITING_IDEA_SOURCE,
                                   {"pillars": pillars})
        await wa.send_text(
            sender,
            "Send a new URL or paste new text to analyse:",
        )
        return

    if text != "idea_expand":
        await wa.send_interactive_buttons(
            sender,
            "Please tap a button:",
            [
                {"id": "idea_expand", "title": "Expand This ✓"},
                {"id": "idea_remine", "title": "Try Another Idea"},
            ],
        )
        return

    db.set_conversation_state(sender, ConversationState.AWAITING_FORMAT_CHOICE, data)
    await wa.send_interactive_list(
        sender,
        "Choose the content format to create:",
        "Select Format",
        [{
            "title": "Content Formats",
            "rows": [
                {"id": "fmt_reel",      "title": "Reel (Avatar Video)",
                 "description": "Talking-head video script → your face & voice"},
                {"id": "fmt_carousel",  "title": "Carousel Slides",
                 "description": "5-slide Instagram/Facebook carousel"},
                {"id": "fmt_text_post", "title": "Text Post",
                 "description": "Caption-style post with hashtags"},
                {"id": "fmt_broll",     "title": "B-Roll Script",
                 "description": "Voice-over script for footage-style video"},
            ],
        }],
    )


# ---------------------------------------------------------------------------
# Stage 3 → 4: Expand content
# ---------------------------------------------------------------------------

_FORMAT_MAP = {
    "fmt_reel":      "reel",
    "fmt_carousel":  "carousel",
    "fmt_text_post": "text_post",
    "fmt_broll":     "broll",
}

async def _handle_format_choice(db: BotDatabase, sender: str, text: str, data: dict):
    format_type = _FORMAT_MAP.get(text)
    if not format_type:
        await wa.send_interactive_list(
            sender,
            "Please select a format:",
            "Select Format",
            [{
                "title": "Content Formats",
                "rows": [
                    {"id": "fmt_reel",      "title": "Reel (Avatar Video)",
                     "description": "Talking-head video script"},
                    {"id": "fmt_carousel",  "title": "Carousel Slides",
                     "description": "5-slide carousel"},
                    {"id": "fmt_text_post", "title": "Text Post",
                     "description": "Caption with hashtags"},
                    {"id": "fmt_broll",     "title": "B-Roll Script",
                     "description": "Voice-over for footage"},
                ],
            }],
        )
        return

    data["format_type"] = format_type
    claims = data.get("claims", [])
    grade = data.get("grade", {})
    pillars = data.get("pillars", {})
    profile = db.get_user_profile(sender) or {}

    await wa.send_text(sender, "⏳ Generating your content...")

    from services.ai.content_intelligence import expand_content, FORMAT_LABELS
    expanded = await asyncio.to_thread(
        expand_content, claims, grade.get("niche_angle", ""), pillars, profile, format_type
    )

    if not expanded:
        await wa.send_text(
            sender,
            "⚠️ Content generation failed. Please try again.",
        )
        return

    # Save expanded format to DB
    idea_id = data.get("idea_id")
    if idea_id:
        existing_idea = db.get_content_idea(idea_id)
        existing_formats = dict(existing_idea.get("expanded_formats") or {}) if existing_idea else {}
        existing_formats[format_type] = expanded
        db.update_content_idea(idea_id, expanded_formats=existing_formats, status="expanded")

    data["expanded_content"] = expanded
    db.set_conversation_state(sender, ConversationState.AWAITING_EXPAND_CONFIRM, data)

    format_label = FORMAT_LABELS.get(format_type, format_type)
    preview = expanded[:800] + ("..." if len(expanded) > 800 else "")

    await wa.send_text(
        sender,
        f"*{format_label}*\n\n{preview}",
    )

    buttons = [
        {"id": "expand_approve", "title": "Use This ✓"},
        {"id": "expand_regen",   "title": "Regenerate"},
        {"id": "expand_format",  "title": "Change Format"},
    ]
    if format_type == "reel":
        await wa.send_interactive_buttons(
            sender,
            "Produce this as an avatar video?",
            buttons,
        )
    else:
        await wa.send_interactive_buttons(
            sender,
            "Use this content?",
            buttons,
        )


# ---------------------------------------------------------------------------
# Stage 4 → Final: Approve, regenerate, or produce
# ---------------------------------------------------------------------------

async def _handle_expand_confirm(db: BotDatabase, sender: str, text: str, data: dict):
    format_type = data.get("format_type")

    if text == "expand_regen":
        # Re-run expansion with same format
        await _handle_format_choice(db, sender, f"fmt_{format_type}" if format_type else "fmt_reel", data)
        return

    if text == "expand_format":
        # Go back to format selection
        db.set_conversation_state(sender, ConversationState.AWAITING_FORMAT_CHOICE, data)
        await wa.send_interactive_list(
            sender,
            "Choose a different format:",
            "Select Format",
            [{
                "title": "Content Formats",
                "rows": [
                    {"id": "fmt_reel",      "title": "Reel (Avatar Video)",   "description": "Talking-head video script"},
                    {"id": "fmt_carousel",  "title": "Carousel Slides",       "description": "5-slide carousel"},
                    {"id": "fmt_text_post", "title": "Text Post",             "description": "Caption with hashtags"},
                    {"id": "fmt_broll",     "title": "B-Roll Script",         "description": "Voice-over for footage"},
                ],
            }],
        )
        return

    if text != "expand_approve":
        from services.ai.content_intelligence import FORMAT_LABELS
        format_label = FORMAT_LABELS.get(format_type, format_type)
        await wa.send_interactive_buttons(
            sender,
            "What would you like to do?",
            [
                {"id": "expand_approve", "title": "Use This ✓"},
                {"id": "expand_regen",   "title": "Regenerate"},
                {"id": "expand_format",  "title": "Change Format"},
            ],
        )
        return

    # Approved — branch by format type
    if format_type == "reel":
        await _initiate_reel_production(db, sender, data)
    else:
        await _deliver_text_content(db, sender, data)


async def _deliver_text_content(db: BotDatabase, sender: str, data: dict):
    """Deliver carousel / text post / b-roll copy directly to the user."""
    db.clear_conversation_state(sender)
    from services.ai.content_intelligence import FORMAT_LABELS
    format_type = data.get("format_type", "")
    content = data.get("expanded_content", "")
    format_label = FORMAT_LABELS.get(format_type, format_type)

    await wa.send_text(
        sender,
        f"✅ *{format_label} ready!*\n\n"
        f"Copy it below:\n\n"
        f"---\n{content}\n---\n\n"
        "Send *post* to create a post with this content, or *video* to start a new idea.",
    )


# ---------------------------------------------------------------------------
# Stage 4b: Reel → Avatar Video production
# ---------------------------------------------------------------------------

async def _initiate_reel_production(db: BotDatabase, sender: str, data: dict):
    """Check avatar setup, refine script, then ask for video style."""
    from gateway.handlers.actions import handle_avatar_setup

    avatar = db.get_avatar_profile(sender) or {}
    has_photo = bool(avatar.get("profile_photo_url"))
    has_voice = avatar.get("voice_clone_status") == "ready"

    if not has_photo or not has_voice:
        missing = []
        if not has_photo:
            missing.append("profile photo")
        if not has_voice:
            missing.append("voice clone")
        db.clear_conversation_state(sender)
        await wa.send_text(
            sender,
            f"⚠️ To produce a Reel you need your avatar profile set up. Missing: {', '.join(missing)}.\n\n"
            "Send *video* to complete your avatar setup first.",
        )
        return

    from shared.credits import ACTION_COSTS
    from shared.credits import CreditManager
    cm = CreditManager(db)
    if not cm.has_enough(sender, "ai_video"):
        balance = cm.get_balance(sender)
        cost = ACTION_COSTS.get("ai_video", 30)
        db.clear_conversation_state(sender)
        await wa.send_text(
            sender,
            f"Not enough credits. Avatar video costs *{cost}* but you have *{balance}*.\n\n"
            "Send *buy* to top up.",
        )
        return

    # Refine the reel script for spoken delivery
    await wa.send_text(sender, "⏳ Refining script for video production...")
    pillars = data.get("pillars", {})
    profile = db.get_user_profile(sender) or {}
    draft_script = data.get("expanded_content", "")

    from services.ai.content_intelligence import refine_reel_script
    refined = await asyncio.to_thread(refine_reel_script, draft_script, pillars, profile)
    final_script = refined or draft_script

    cost = ACTION_COSTS.get("ai_video", 30)
    await wa.send_text(
        sender,
        f"*Final Script:*\n\n_{final_script}_\n\n"
        f"Cost: *{cost} credits*",
    )

    data["avatar_script"] = final_script
    db.set_conversation_state(sender, ConversationState.AWAITING_REEL_STYLE, data)

    await wa.send_interactive_list(
        sender,
        "Choose your video style:",
        "Select Style",
        [{
            "title": "Video Style",
            "rows": [
                {"id": "vstyle_professional", "title": "Professional",
                 "description": "Office setting, confident, 16:9"},
                {"id": "vstyle_warm",         "title": "Warm & Friendly",
                 "description": "Natural setting, approachable, 9:16"},
                {"id": "vstyle_luxury",       "title": "Luxury / Premium",
                 "description": "Cinematic, dramatic lighting, 9:16"},
            ],
        }],
    )


async def _handle_reel_style(db: BotDatabase, sender: str, text: str, data: dict):
    """Final step — deduct credits, generate TTS + avatar video."""
    import os
    style_map = {
        "vstyle_professional": "professional",
        "vstyle_warm":         "warm",
        "vstyle_luxury":       "luxury",
    }
    style = style_map.get(text.lower().strip())
    if not style:
        await wa.send_interactive_list(
            sender,
            "Please select a video style:",
            "Select Style",
            [{
                "title": "Video Style",
                "rows": [
                    {"id": "vstyle_professional", "title": "Professional",     "description": "Office setting, confident"},
                    {"id": "vstyle_warm",         "title": "Warm & Friendly",  "description": "Natural, approachable"},
                    {"id": "vstyle_luxury",       "title": "Luxury / Premium", "description": "Cinematic lighting"},
                ],
            }],
        )
        return

    db.clear_conversation_state(sender)

    cm = CreditManager(db)
    if not cm.deduct(sender, "ai_video", "ai"):
        await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
        return

    balance = cm.get_balance(sender)
    cost = get_action_cost("ai_video")
    await wa.send_text(
        sender,
        f"🎬 Generating your avatar video... This may take 3–5 minutes.\n"
        f"Credits used: *{cost}* | Remaining: *{balance}*",
    )

    avatar = db.get_avatar_profile(sender) or {}
    photo_url = avatar.get("profile_photo_url")
    voice_id  = avatar.get("voice_clone_id")
    script    = data.get("avatar_script", "")

    from services.ai.voice_generator import generate_speech
    from services.ai.video_generator import generate_avatar_video
    from shared.config import PUBLIC_BASE_URL, FAL_KEY
    from gateway.media import get_media_public_url
    import os as _os

    audio_path = await asyncio.to_thread(generate_speech, voice_id, script)
    if not audio_path:
        await wa.send_text(
            sender,
            "❌ Voice generation failed. Credits used.\n\nSend *video* to try again.",
        )
        return

    # Upload audio to fal.ai CDN — Railway filesystem is ephemeral
    try:
        import fal_client as _fal
        _os.environ["FAL_KEY"] = FAL_KEY
        audio_url = await asyncio.to_thread(_fal.upload_file, audio_path)
    except Exception as _e:
        logger.warning("fal.ai audio upload failed, falling back to local URL: %s", _e)
        audio_url = get_media_public_url(_os.path.basename(audio_path), PUBLIC_BASE_URL)

    try:
        result = await generate_avatar_video(photo_url, audio_url, style=style)
    except Exception as e:
        logger.error("Avatar video error for %s: %s", sender, e)
        result = None

    # Mark idea as produced
    idea_id = data.get("idea_id")
    if idea_id:
        db.update_content_idea(idea_id, status="produced")

    if result and result.get("url"):
        sent = await wa.send_video(sender, result["url"], caption="Here's your content Reel!")
        if not sent:
            await wa.send_text(sender, f"Your Reel is ready:\n{result['url']}")
    elif result and result.get("error") == "billing":
        cost = get_action_cost("ai_video")
        db.execute_query(
            "UPDATE users SET credits_remaining = credits_remaining + %s, "
            "credits_used = GREATEST(credits_used - %s, 0) WHERE phone_number_id = %s",
            (cost, cost, sender),
        )
        await wa.send_text(
            sender,
            "❌ *Video generation unavailable* — the video service account is out of credits.\n\n"
            f"Your *{cost} credits* have been refunded.\n\n"
            "Please contact support.",
        )
    else:
        await wa.send_text(
            sender,
            "❌ Video generation failed. Credits used.\n\nSend *video* to try again.",
        )
