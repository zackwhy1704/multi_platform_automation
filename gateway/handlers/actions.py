from __future__ import annotations

"""
Content creation and engagement handlers.
Facebook + Instagram only (Graph API). Freemium: credits-based.

Posting flow:
  1. User sends "post" → choose platform (FB/IG)
  2. Choose content type:
     - "My Photo/Video" → user sends media → caption (write or AI) → preview → confirm  (5 credits)
     - "AI Image"       → AI generates image (gpt-image-1) + caption → preview → confirm (30 credits)
     - "AI Video"       → AI generates video (Kling AI) + caption → preview → confirm    (100 credits)
     - "Stock Image"    → Pexels stock image + AI caption → preview → confirm             (5 credits)
     - "Text Only"      → write text or AI generate → preview → confirm (FB only)         (3 credits)
  3. Preview with approve/edit/cancel buttons
  4. On approve → publish to platform

Weekly auto-post flow:
  1. User sends "auto" → choose platform
  2. Choose how many posts (3/5/7)
  3. Choose content type for batch
  4. AI generates all posts → preview each → approve all / edit / cancel
  5. On approve → schedule posts across the week
"""

import logging
from datetime import datetime, timedelta
from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost, ACTION_COSTS
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}

# Map post_type → credit action name
POST_TYPE_ACTIONS = {
    "own_media": "own_media_post",
    "ai_image": "ai_image_post",
    "ai_video": "ai_video_post",
    "ai_generated": "stock_image_post",  # legacy name — uses Pexels stock
    "stock_image": "stock_image_post",
    "text_only": "text_post",
}


async def _check_credits(db: BotDatabase, sender: str, action: str) -> bool:
    """Check if user has enough credits. Prompts upgrade if not."""
    cm = CreditManager(db)
    if not cm.has_enough(sender, action):
        balance = cm.get_balance(sender)
        cost = get_action_cost(action)
        await wa.send_text(
            sender,
            f"Not enough credits. This costs *{cost}* credits but you have *{balance}*.\n\n"
            "Ways to get more credits:\n"
            "  *subscribe* — Upgrade your plan\n"
            "  *buy* — Purchase credit packs\n"
            "  *referral* — Share your code, earn 50 credits per friend\n\n"
            "Send *credits* for your full balance breakdown.",
        )
        return False
    return True


# ===========================================================================
# POST COMMAND — entry point
# ===========================================================================

async def handle_post(db: BotDatabase, sender: str, text: str):
    # Check minimum credits (text_post = 3, cheapest option)
    cm = CreditManager(db)
    if cm.get_balance(sender) < ACTION_COSTS["text_post"]:
        await wa.send_text(
            sender,
            f"You need at least *{ACTION_COSTS['text_post']}* credits to create a post.\n\n"
            "Send *buy* for credit packs or *subscribe* for a plan.",
        )
        return

    # Check if any platform is connected
    fb_token = db.get_platform_token(sender, "facebook")
    ig_token = db.get_platform_token(sender, "instagram")

    if not fb_token and not ig_token:
        await wa.send_text(
            sender,
            "You haven't connected any platform yet.\n\n"
            "Send *setup* to connect your Facebook or Instagram first.",
        )
        return

    # If only one platform is connected, skip platform selection
    if fb_token and not ig_token:
        data = {"platform": "facebook"}
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_TYPE, data)
        await _send_content_type_options(sender, "facebook")
        return
    elif ig_token and not fb_token:
        data = {"platform": "instagram"}
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_TYPE, data)
        await _send_content_type_options(sender, "instagram")
        return

    # Both connected — ask which platform
    await wa.send_interactive_buttons(
        sender,
        "Which platform do you want to post on?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {})


async def _send_content_type_options(sender: str, platform: str):
    """Send content type selection as interactive list."""
    rows = [
        {"id": "own_media", "title": "My Photo/Video", "description": f"Send your own media ({ACTION_COSTS['own_media_post']} credits)"},
        {"id": "ai_image", "title": "AI Image", "description": f"AI generates a custom image ({ACTION_COSTS['ai_image_post']} credits)"},
        {"id": "ai_video", "title": "AI Video", "description": f"AI generates a short video ({ACTION_COSTS['ai_video_post']} credits)"},
        {"id": "stock_image", "title": "Stock Image", "description": f"Find a stock photo + AI caption ({ACTION_COSTS['stock_image_post']} credits)"},
    ]
    # Text-only is only available on Facebook (Instagram requires media)
    if platform == "facebook":
        rows.append({"id": "text_only", "title": "Text Only", "description": f"Text post, no media ({ACTION_COSTS['text_post']} credits)"})

    await wa.send_interactive_list(
        sender,
        f"What type of *{PLATFORM_LABELS[platform]}* post do you want to create?",
        "Choose Type",
        [{"title": "Content Types", "rows": rows}],
    )


# ===========================================================================
# POST FLOW — state handlers
# ===========================================================================

async def handle_post_step(db: BotDatabase, sender: str, text: str,
                           state: ConversationState, data: dict,
                           media_info: dict = None):
    """Handle all post creation states. media_info is set when user sends a photo/video."""

    # --- PLATFORM SELECTION ---
    if state == ConversationState.AWAITING_POST_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_interactive_buttons(
                sender,
                "Please tap one of the buttons below:",
                [
                    {"id": "facebook", "title": "Facebook"},
                    {"id": "instagram", "title": "Instagram"},
                ],
            )
            return

        token = db.get_platform_token(sender, platform)
        if not token:
            await wa.send_text(
                sender,
                f"You haven't connected {PLATFORM_LABELS[platform]} yet.\n"
                "Send *setup* to connect it first.",
            )
            db.clear_conversation_state(sender)
            return

        data["platform"] = platform
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_TYPE, data)
        await _send_content_type_options(sender, platform)

    # --- CONTENT TYPE SELECTION ---
    elif state == ConversationState.AWAITING_POST_TYPE:
        choice = text.lower().replace(" ", "_")
        platform = data.get("platform", "facebook")

        if choice == "own_media":
            data["post_type"] = "own_media"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_MEDIA, data)
            await wa.send_text(
                sender,
                "Send me your *photo or video* now.\n\n"
                "Just attach it directly in this chat — I'll use it for your post.",
            )

        elif choice == "ai_image":
            if not await _check_credits(db, sender, "ai_image_post"):
                db.clear_conversation_state(sender)
                return
            data["post_type"] = "ai_image"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_text(
                sender,
                "What should the AI image be *about*?\n\n"
                "Give me a topic or describe the image you want.\n\n"
                "_e.g. \"Happy team celebrating a milestone\", \"Fresh coffee and pastries\"_\n\n"
                "Or type *auto* and I'll create something based on your business profile.",
            )

        elif choice == "ai_video":
            if not await _check_credits(db, sender, "ai_video_post"):
                db.clear_conversation_state(sender)
                return
            data["post_type"] = "ai_video"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_text(
                sender,
                "What should the AI video be *about*?\n\n"
                "Describe the scene or concept for a 5-second video.\n\n"
                "_e.g. \"Product reveal with smooth camera movement\", \"Funny office moment\"_\n\n"
                "Or type *auto* and I'll create something based on your profile.",
            )

        elif choice in ("ai_generated", "stock_image"):
            data["post_type"] = "stock_image"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
            await wa.send_text(
                sender,
                "What should the post be *about*?\n\n"
                "Give me a topic and I'll find a matching stock photo + generate the caption.\n\n"
                "_e.g. \"New product launch\", \"Behind the scenes\", \"Customer testimonial\"_\n\n"
                "Or type *auto* and I'll choose a topic based on your business profile.",
            )

        elif choice == "text_only" and platform == "facebook":
            data["post_type"] = "text_only"
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONTENT, data)
            await wa.send_text(
                sender,
                f"Write your {PLATFORM_LABELS[platform]} post below.\n\n"
                "Or type *ai* to have AI generate one for you.",
            )

        else:
            await _send_content_type_options(sender, platform)

    # --- WAITING FOR MEDIA (photo/video) ---
    elif state == ConversationState.AWAITING_POST_MEDIA:
        if not media_info:
            await wa.send_text(
                sender,
                "Please send a *photo or video* — I'm waiting for your media.\n\n"
                "Or type *cancel* to go back.",
            )
            return

        data["media_filename"] = media_info["filename"]
        data["media_mime"] = media_info["mime_type"]
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)

        from gateway.media import is_video
        media_type = "video" if is_video(media_info["mime_type"]) else "photo"
        await wa.send_text(
            sender,
            f"Got your {media_type}!\n\n"
            "Now write a *caption* for it.\n\n"
            "Or type *ai* and I'll generate one based on your business profile.",
        )

    # --- CAPTION / CONTENT ---
    elif state == ConversationState.AWAITING_POST_CAPTION:
        platform = data.get("platform", "facebook")
        post_type = data.get("post_type", "own_media")

        if post_type == "ai_image":
            topic = None if text.lower() == "auto" else text.strip()
            await wa.send_text(sender, "Generating your AI image + caption... this may take a moment.")

            profile = db.get_user_profile(sender)
            if not profile:
                await wa.send_text(sender, "Profile not found. Send *start* to set up.")
                db.clear_conversation_state(sender)
                return

            # Generate AI image
            from services.ai.image_generator import generate_image, build_image_prompt
            content_style = profile.get("content_style", "mixed")
            visual_style = profile.get("visual_style", "photorealistic")
            image_prompt = build_image_prompt(profile, content_style, visual_style, topic, platform)
            image_url = generate_image(image_prompt)

            if not image_url:
                await wa.send_text(sender, "Image generation failed. Please try again or choose a different content type.")
                db.clear_conversation_state(sender)
                return

            # Generate caption
            from services.ai.ai_service import generate_post
            caption = generate_post(platform, profile, topic=topic)
            if not caption:
                caption = "Check out our latest creation!"

            data["caption"] = caption
            data["ai_image_url"] = image_url
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
            await _send_preview(sender, data)

        elif post_type == "ai_video":
            topic = None if text.lower() == "auto" else text.strip()
            await wa.send_text(sender, "Generating your AI video + caption... this takes 1-3 minutes.")

            profile = db.get_user_profile(sender)
            if not profile:
                await wa.send_text(sender, "Profile not found. Send *start* to set up.")
                db.clear_conversation_state(sender)
                return

            # Generate AI video
            from services.ai.video_generator import generate_video, build_video_prompt
            content_style = profile.get("content_style", "mixed")
            visual_style = profile.get("visual_style", "photorealistic")
            video_prompt = build_video_prompt(profile, content_style, visual_style, topic, platform)
            video_result = await generate_video(video_prompt)

            if not video_result or not video_result.get("url"):
                await wa.send_text(sender, "Video generation failed. Please try again or choose a different content type.")
                db.clear_conversation_state(sender)
                return

            # Generate caption
            from services.ai.ai_service import generate_post
            caption = generate_post(platform, profile, topic=topic)
            if not caption:
                caption = "Watch our latest video!"

            data["caption"] = caption
            data["ai_video_url"] = video_result["url"]
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
            await _send_preview(sender, data)

        elif post_type == "stock_image":
            topic = None if text.lower() == "auto" else text.strip()
            await wa.send_text(sender, "Finding a stock image + generating caption...")

            profile = db.get_user_profile(sender)
            if not profile:
                await wa.send_text(sender, "Profile not found. Send *start* to set up.")
                db.clear_conversation_state(sender)
                return

            from services.ai.ai_service import generate_post, generate_image_search_query, fetch_stock_image

            caption = generate_post(platform, profile, topic=topic)
            if not caption:
                caption = f"Check out what's new! #{'#'.join(profile.get('industry', ['business']))}"

            search_query = generate_image_search_query(profile, topic=topic)
            stock = await fetch_stock_image(search_query)

            data["caption"] = caption
            if stock:
                data["stock_image_url"] = stock["url"]
                data["stock_photographer"] = stock.get("photographer", "")

            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
            await _send_preview(sender, data)

        else:
            # own_media — user writing caption
            use_ai = text.lower().strip() == "ai"

            if use_ai:
                await wa.send_text(sender, "Generating caption...")
                profile = db.get_user_profile(sender)
                from services.ai.ai_service import generate_caption_for_media
                from gateway.media import is_video

                media_type = "video" if is_video(data.get("media_mime", "")) else "photo"
                caption = generate_caption_for_media(platform, profile or {}, media_type=media_type)
                if not caption:
                    caption = "Check out our latest update!"
            else:
                caption = text.strip()

            data["caption"] = caption
            db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
            await _send_preview(sender, data)

    # --- TEXT-ONLY CONTENT ---
    elif state == ConversationState.AWAITING_POST_CONTENT:
        platform = data.get("platform", "facebook")
        use_ai = text.lower().strip() == "ai"

        if use_ai:
            await wa.send_text(sender, "Generating post...")
            profile = db.get_user_profile(sender)
            from services.ai.ai_service import generate_post
            caption = generate_post(platform, profile or {})
            if not caption:
                caption = "Exciting things happening at our business!"
        else:
            caption = text.strip()

        data["caption"] = caption
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONFIRM, data)
        await _send_preview(sender, data)

    # --- PREVIEW CONFIRMATION ---
    elif state == ConversationState.AWAITING_POST_CONFIRM:
        choice = text.lower().strip()

        if choice in ("approve", "yes", "publish", "post"):
            await _publish_post(db, sender, data)

        elif choice in ("edit", "change"):
            post_type = data.get("post_type", "text_only")
            if post_type == "own_media":
                db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
                await wa.send_text(sender, "Write a new caption (or type *ai* to generate one):")
            else:
                db.set_conversation_state(sender, ConversationState.AWAITING_POST_CAPTION, data)
                await wa.send_text(sender, "Give me a new topic or write the caption directly:")

        elif choice in ("cancel", "no"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Post cancelled. No credits deducted.\n\nSend *post* to start again.")

        else:
            await wa.send_interactive_buttons(
                sender,
                "Would you like to publish this post?",
                [
                    {"id": "approve", "title": "Publish Now"},
                    {"id": "edit", "title": "Edit Caption"},
                    {"id": "cancel", "title": "Cancel"},
                ],
            )

    # --- SCHEDULE TIME ---
    elif state == ConversationState.AWAITING_SCHEDULE_TIME:
        platform = data.get("platform", "facebook")
        post_type = data.get("post_type", "text_only")
        action = POST_TYPE_ACTIONS.get(post_type, "scheduled_post")
        # Use scheduled variant if available
        scheduled_action = f"scheduled_{action.replace('_post', '')}" if action.endswith("_post") else action

        try:
            scheduled_at = datetime.fromisoformat(text.strip())
        except ValueError:
            await wa.send_text(
                sender,
                "Please enter a valid date/time in ISO format:\n"
                "e.g. 2026-03-15T09:00",
            )
            return

        db.clear_conversation_state(sender)
        cm = CreditManager(db)
        if not cm.deduct(sender, scheduled_action, platform):
            await wa.send_text(sender, "Insufficient credits.")
            return

        media_url = _resolve_media_url(data)
        db.save_scheduled_content(sender, platform, data.get("caption", ""), scheduled_at, media_url=media_url)
        cost = get_action_cost(scheduled_action)
        await wa.send_text(
            sender,
            f"Post scheduled for {PLATFORM_LABELS[platform]} at "
            f"{scheduled_at.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Credits deducted: *{cost}*",
        )


# ===========================================================================
# PREVIEW
# ===========================================================================

async def _send_preview(sender: str, data: dict):
    """Send a preview of the post with approve/edit/cancel buttons.

    Sends the actual image/video in WhatsApp so user can see what will be posted.
    """
    platform = data.get("platform", "facebook")
    caption = data.get("caption", "")
    post_type = data.get("post_type", "text_only")
    action = POST_TYPE_ACTIONS.get(post_type, "post")
    cost = get_action_cost(action)

    preview_header = f"*Preview — {PLATFORM_LABELS[platform]} Post*\n*Cost: {cost} credits*"

    # Send the actual media preview in WhatsApp
    media_url = _resolve_media_url(data)
    media_sent = False

    if media_url:
        from gateway.media import is_video as _is_video
        mime = data.get("media_mime", "")
        is_vid = _is_video(mime) if mime else any(
            media_url.lower().endswith(ext) for ext in (".mp4", ".mov", ".3gp", ".avi")
        )

        if is_vid:
            media_sent = await wa.send_video(sender, media_url, caption=preview_header)
        else:
            media_sent = await wa.send_image(sender, media_url, caption=preview_header)

    if not media_sent:
        # Fallback: text-only preview (no media, or media send failed)
        lines = [preview_header, ""]
        if post_type == "own_media" and data.get("media_filename"):
            from gateway.media import is_video
            media_type = "Video" if is_video(data.get("media_mime", "")) else "Photo"
            lines.append(f"Media: {media_type} attached (preview not available)")
        elif not media_url:
            lines.append("Media: None (text-only)")
        else:
            lines.append("Media: Attached (preview failed to load)")
        lines.append("")
        await wa.send_text(sender, "\n".join(lines))

    # Always send caption as separate text for readability
    caption_text = f"*Caption:*\n{caption[:500]}"
    if len(caption) > 500:
        caption_text += "...(truncated)"
    await wa.send_text(sender, caption_text)

    await wa.send_interactive_buttons(
        sender,
        "Ready to publish?",
        [
            {"id": "approve", "title": "Publish Now"},
            {"id": "edit", "title": "Edit Caption"},
            {"id": "cancel", "title": "Cancel"},
        ],
    )


# ===========================================================================
# PUBLISH
# ===========================================================================

def _resolve_media_url(data: dict) -> str | None:
    """Get the media URL from data dict based on post_type."""
    post_type = data.get("post_type", "text_only")

    if post_type == "own_media" and data.get("media_filename"):
        from shared.config import PUBLIC_BASE_URL
        from gateway.media import get_media_public_url
        if PUBLIC_BASE_URL:
            return get_media_public_url(data["media_filename"], PUBLIC_BASE_URL)
    elif post_type == "ai_image" and data.get("ai_image_url"):
        return data["ai_image_url"]
    elif post_type == "ai_video" and data.get("ai_video_url"):
        return data["ai_video_url"]
    elif post_type == "stock_image" and data.get("stock_image_url"):
        return data["stock_image_url"]

    return None


async def _publish_post(db: BotDatabase, sender: str, data: dict):
    """Deduct credits and publish to the platform directly via Graph API."""
    platform = data.get("platform", "facebook")
    caption = data.get("caption", "")
    post_type = data.get("post_type", "text_only")
    action = POST_TYPE_ACTIONS.get(post_type, "post")

    db.clear_conversation_state(sender)

    # Deduct credits
    cm = CreditManager(db)
    if not cm.deduct(sender, action, platform):
        await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
        return

    media_url = _resolve_media_url(data)

    await wa.send_text(sender, f"Publishing to {PLATFORM_LABELS[platform]}...")

    # Publish directly via Graph API (no Celery/Redis required)
    from services.publisher import publish_to_facebook, publish_to_instagram

    if platform == "facebook":
        result = await publish_to_facebook(db, sender, caption, media_url)
    else:
        result = await publish_to_instagram(db, sender, caption, media_url)

    cost = get_action_cost(action)
    balance = cm.get_balance(sender)

    if result.get("success"):
        await wa.send_text(
            sender,
            f"✅ *Published to {PLATFORM_LABELS[platform]}!*\n\n"
            f"{caption[:100]}{'...' if len(caption) > 100 else ''}\n\n"
            f"Credits used: *{cost}* | Remaining: *{balance}*",
        )
    else:
        # Refund credits on failure
        db.execute_query(
            "UPDATE users SET credits_remaining = credits_remaining + %s, "
            "credits_used = GREATEST(credits_used - %s, 0) WHERE phone_number_id = %s",
            (cost, cost, sender),
        )
        balance = cm.get_balance(sender)
        error = result.get("error", "Unknown error")
        await wa.send_text(
            sender,
            f"❌ *Publishing failed:* {error}\n\n"
            f"Your *{cost} credits* have been refunded. Remaining: *{balance}*\n\n"
            f"Send *post* to try again.",
        )


# ===========================================================================
# WEEKLY AUTO-POST
# ===========================================================================

async def handle_auto(db: BotDatabase, sender: str, text: str):
    """Entry point for weekly auto-post generation."""
    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    if balance < ACTION_COSTS["text_post"]:
        await wa.send_text(
            sender,
            f"You need at least *{ACTION_COSTS['text_post']}* credits to use auto-post.\n\n"
            "Send *buy* for credit packs or *subscribe* for a plan.",
        )
        return

    fb_token = db.get_platform_token(sender, "facebook")
    ig_token = db.get_platform_token(sender, "instagram")

    if not fb_token and not ig_token:
        await wa.send_text(sender, "Connect a platform first. Send *setup*.")
        return

    if fb_token and not ig_token:
        data = {"platform": "facebook"}
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT, data)
        await _send_auto_count_options(sender)
        return
    elif ig_token and not fb_token:
        data = {"platform": "instagram"}
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT, data)
        await _send_auto_count_options(sender)
        return

    await wa.send_interactive_buttons(
        sender,
        "Auto-post for which platform?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_PLATFORM, {})


async def _send_auto_count_options(sender: str):
    await wa.send_interactive_buttons(
        sender,
        "How many posts for this week?",
        [
            {"id": "3", "title": "3 Posts"},
            {"id": "5", "title": "5 Posts"},
            {"id": "7", "title": "7 Posts (Daily)"},
        ],
    )


async def handle_auto_step(db: BotDatabase, sender: str, text: str,
                            state: ConversationState, data: dict, **kwargs):
    """Handle weekly auto-post states."""

    # --- PLATFORM ---
    if state == ConversationState.AWAITING_AUTO_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_interactive_buttons(
                sender,
                "Please tap one of the buttons below:",
                [
                    {"id": "facebook", "title": "Facebook"},
                    {"id": "instagram", "title": "Instagram"},
                ],
            )
            return
        data["platform"] = platform
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_COUNT, data)
        await _send_auto_count_options(sender)

    # --- COUNT ---
    elif state == ConversationState.AWAITING_AUTO_COUNT:
        try:
            count = int(text.strip())
        except ValueError:
            count = 0
        if count not in (3, 5, 7):
            await _send_auto_count_options(sender)
            return
        data["count"] = count
        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_TYPE, data)

        rows = [
            {"id": "stock_image", "title": "Stock Images", "description": f"{ACTION_COSTS['stock_image_post']} credits each"},
            {"id": "ai_image", "title": "AI Images", "description": f"{ACTION_COSTS['ai_image_post']} credits each"},
            {"id": "ai_video", "title": "AI Videos", "description": f"{ACTION_COSTS['ai_video_post']} credits each"},
        ]
        if data.get("platform") == "facebook":
            rows.append({"id": "text_only", "title": "Text Only", "description": f"{ACTION_COSTS['text_post']} credits each"})

        total_stock = count * ACTION_COSTS["stock_image_post"]
        total_ai_img = count * ACTION_COSTS["ai_image_post"]
        total_ai_vid = count * ACTION_COSTS["ai_video_post"]

        await wa.send_interactive_list(
            sender,
            f"What type of content for your *{count} posts*?\n\n"
            f"Estimated totals:\n"
            f"  Stock images: {total_stock} credits\n"
            f"  AI images: {total_ai_img} credits\n"
            f"  AI videos: {total_ai_vid} credits",
            "Choose Type",
            [{"title": "Content Types", "rows": rows}],
        )

    # --- TYPE ---
    elif state == ConversationState.AWAITING_AUTO_TYPE:
        content_type = text.lower().replace(" ", "_")
        valid_types = {"stock_image", "ai_image", "ai_video", "text_only"}
        if content_type not in valid_types:
            # Re-send the content type list
            rows = [
                {"id": "stock_image", "title": "Stock Images", "description": f"{ACTION_COSTS['stock_image_post']} credits each"},
                {"id": "ai_image", "title": "AI Images", "description": f"{ACTION_COSTS['ai_image_post']} credits each"},
                {"id": "ai_video", "title": "AI Videos", "description": f"{ACTION_COSTS['ai_video_post']} credits each"},
            ]
            if data.get("platform") == "facebook":
                rows.append({"id": "text_only", "title": "Text Only", "description": f"{ACTION_COSTS['text_post']} credits each"})
            await wa.send_interactive_list(
                sender,
                "Please choose a content type from the list:",
                "Choose Type",
                [{"title": "Content Types", "rows": rows}],
            )
            return

        count = data.get("count", 3)
        action = POST_TYPE_ACTIONS.get(content_type, "stock_image_post")
        total_cost = count * get_action_cost(action)

        cm = CreditManager(db)
        balance = cm.get_balance(sender)
        if balance < total_cost:
            await wa.send_text(
                sender,
                f"You need *{total_cost}* credits for {count} {content_type.replace('_', ' ')} posts "
                f"but you have *{balance}*.\n\n"
                "Choose fewer posts or a cheaper type. Send *buy* for credit packs.",
            )
            return

        data["content_type"] = content_type
        data["total_cost"] = total_cost

        await wa.send_text(
            sender,
            f"Generating *{count} {content_type.replace('_', ' ')} posts* for "
            f"{PLATFORM_LABELS[data.get('platform', 'facebook')]}...\n\n"
            f"Total cost: *{total_cost} credits*\n"
            f"This may take a minute.",
        )

        # Generate all posts
        platform = data.get("platform", "facebook")
        profile = db.get_user_profile(sender)
        if not profile:
            await wa.send_text(sender, "Profile not found. Send *start* to set up.")
            db.clear_conversation_state(sender)
            return

        posts = await _generate_batch_posts(profile, platform, content_type, count)
        data["posts"] = posts

        # Send preview of all posts
        for i, post in enumerate(posts, 1):
            preview = f"*Post {i}/{count}*\n"
            if post.get("media_type"):
                preview += f"Media: {post['media_type']}\n"
            preview += f"\n{post.get('caption', '')[:300]}"
            if len(post.get("caption", "")) > 300:
                preview += "..."
            await wa.send_text(sender, preview)

        db.set_conversation_state(sender, ConversationState.AWAITING_AUTO_CONFIRM, data)
        await wa.send_interactive_buttons(
            sender,
            f"*{count} posts ready!* Total: *{total_cost} credits*\n\n"
            "Posts will be scheduled evenly across the next 7 days.",
            [
                {"id": "approve_all", "title": "Schedule All"},
                {"id": "cancel", "title": "Cancel"},
            ],
        )

    # --- CONFIRM ---
    elif state == ConversationState.AWAITING_AUTO_CONFIRM:
        choice = text.lower().strip()

        if choice in ("approve_all", "approve", "yes", "schedule"):
            await _schedule_batch_posts(db, sender, data)
        elif choice in ("cancel", "no"):
            db.clear_conversation_state(sender)
            await wa.send_text(sender, "Auto-post cancelled. No credits deducted.\n\nSend *auto* to try again.")
        else:
            await wa.send_interactive_buttons(
                sender,
                "Schedule all posts or cancel?",
                [
                    {"id": "approve_all", "title": "Schedule All"},
                    {"id": "cancel", "title": "Cancel"},
                ],
            )


async def _generate_batch_posts(profile: dict, platform: str, content_type: str, count: int) -> list:
    """Generate a batch of posts for auto-post."""
    from services.ai.ai_service import generate_post, generate_image_search_query, fetch_stock_image

    content_style = profile.get("content_style", "mixed")
    visual_style = profile.get("visual_style", "photorealistic")
    posts = []

    for i in range(count):
        post = {"index": i}

        # Generate caption with varied topics
        caption = generate_post(platform, profile)
        post["caption"] = caption or f"Post {i + 1} for the week!"

        if content_type == "stock_image":
            query = generate_image_search_query(profile)
            stock = await fetch_stock_image(query)
            if stock:
                post["media_url"] = stock["url"]
                post["media_type"] = "Stock photo"
            else:
                post["media_type"] = "No image found"

        elif content_type == "ai_image":
            from services.ai.image_generator import generate_image, build_image_prompt
            prompt = build_image_prompt(profile, content_style, visual_style, platform=platform)
            url = generate_image(prompt)
            if url:
                post["media_url"] = url
                post["media_type"] = "AI image"
            else:
                post["media_type"] = "Image generation failed"

        elif content_type == "ai_video":
            from services.ai.video_generator import generate_video, build_video_prompt
            prompt = build_video_prompt(profile, content_style, visual_style, platform=platform)
            result = await generate_video(prompt)
            if result and result.get("url"):
                post["media_url"] = result["url"]
                post["media_type"] = "AI video"
            else:
                post["media_type"] = "Video generation failed"

        elif content_type == "text_only":
            post["media_type"] = "Text only"

        posts.append(post)

    return posts


async def _schedule_batch_posts(db: BotDatabase, sender: str, data: dict):
    """Deduct credits and schedule all batch posts across the week."""
    platform = data.get("platform", "facebook")
    content_type = data.get("content_type", "stock_image")
    posts = data.get("posts", [])
    action = POST_TYPE_ACTIONS.get(content_type, "stock_image_post")

    cm = CreditManager(db)
    total_cost = data.get("total_cost", 0)

    # Verify credits one more time
    if cm.get_balance(sender) < total_cost:
        await wa.send_text(sender, "Insufficient credits. Send *buy* for credit packs.")
        db.clear_conversation_state(sender)
        return

    # Schedule posts evenly across 7 days starting tomorrow 9 AM
    now = datetime.now()
    base_time = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    interval_days = 7 / len(posts) if posts else 1

    scheduled_count = 0
    for i, post in enumerate(posts):
        scheduled_at = base_time + timedelta(days=int(i * interval_days))
        media_url = post.get("media_url")

        # Deduct credits for each post
        if not cm.deduct(sender, action, platform):
            await wa.send_text(
                sender,
                f"Ran out of credits after scheduling {scheduled_count} posts.",
            )
            break

        db.save_scheduled_content(sender, platform, post.get("caption", ""), scheduled_at, media_url=media_url)
        scheduled_count += 1

    db.clear_conversation_state(sender)
    balance = cm.get_balance(sender)
    await wa.send_text(
        sender,
        f"*{scheduled_count} posts scheduled!*\n\n"
        f"Platform: {PLATFORM_LABELS[platform]}\n"
        f"Schedule: Next 7 days starting tomorrow at 9 AM\n"
        f"Credits used: *{scheduled_count * get_action_cost(action)}* | Remaining: *{balance}*\n\n"
        "Posts will be published automatically at the scheduled times.",
    )


# ===========================================================================
# SCHEDULE & REPLY (unchanged)
# ===========================================================================

async def handle_schedule(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "scheduled_post"):
        return
    await wa.send_interactive_buttons(
        sender,
        "Schedule a post for which platform?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {"scheduling": True})


async def handle_reply(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "comment_reply"):
        return
    await wa.send_interactive_buttons(
        sender,
        "Auto-reply to comments on which platform?",
        [
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_REPLY_PLATFORM, {})


async def handle_reply_step(db: BotDatabase, sender: str, text: str,
                            state: ConversationState, data: dict, **kwargs):
    platform = text.lower()
    if platform not in PLATFORM_LABELS:
        await wa.send_interactive_buttons(
            sender,
            "Please tap one of the buttons below:",
            [
                {"id": "facebook", "title": "Facebook"},
                {"id": "instagram", "title": "Instagram"},
            ],
        )
        return
    db.clear_conversation_state(sender)
    cm = CreditManager(db)
    if not cm.deduct(sender, "comment_reply", platform):
        await wa.send_text(sender, "Insufficient credits.")
        return
    await wa.send_text(sender, f"Starting auto-reply on {PLATFORM_LABELS[platform]}...")
    from workers.celery_app import celery_app
    celery_app.send_task(
        f"services.{platform}.tasks.reply_task",
        args=[sender],
        queue=f"{platform}_engagement",
    )


async def handle_stats(db: BotDatabase, sender: str, text: str):
    lines = ["*Your Automation Stats*\n"]
    for platform, label in PLATFORM_LABELS.items():
        stats = db.get_user_stats(sender, platform)
        if stats["posts_created"] or stats["comments_made"]:
            lines.append(f"*{label}:*")
            lines.append(f"  Posts: {stats['posts_created']}")
            lines.append(f"  Replies: {stats['comments_made']}")
            if stats["last_active"]:
                lines.append(f"  Last active: {str(stats['last_active'])[:10]}")
            lines.append("")
    if len(lines) == 1:
        lines.append("No activity yet. Send *post* to get started!")
    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    lines.append(f"\n*Credits remaining:* {balance}")
    await wa.send_text(sender, "\n".join(lines))
