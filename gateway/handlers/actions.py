"""
Content creation and engagement handlers.
Handles: post, schedule, reply, stats commands.
"""

import logging
from datetime import datetime

from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}


async def _check_subscription(db: BotDatabase, sender: str) -> bool:
    """Check if user has active subscription. Sends message if not."""
    if not db.is_subscription_active(sender):
        await wa.send_text(
            sender,
            "You need an active subscription to use this feature.\n"
            "Send *subscribe* to get started (500 credits/month).",
        )
        return False
    return True


async def _check_credits(db: BotDatabase, sender: str, action: str) -> bool:
    """Check if user has enough credits. Sends message if not."""
    cm = CreditManager(db)
    if not cm.has_enough(sender, action):
        balance = cm.get_balance(sender)
        cost = get_action_cost(action)
        await wa.send_text(
            sender,
            f"Insufficient credits. This action costs *{cost}* credits but you have *{balance}* remaining.\n\n"
            "Your credits reset on your next billing cycle. Send *credits* for details.",
        )
        return False
    return True


# =========================================================================
# POST
# =========================================================================

async def handle_post(db: BotDatabase, sender: str, text: str):
    """Start the post creation flow: choose platform → write content → publish."""
    if not await _check_subscription(db, sender):
        return
    if not await _check_credits(db, sender, "post"):
        return

    await wa.send_interactive_buttons(
        sender,
        "Which platform do you want to post on?",
        [
            {"id": "linkedin", "title": "LinkedIn"},
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {})


async def handle_post_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    """Process post creation steps."""

    if state == ConversationState.AWAITING_POST_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_text(sender, "Please choose LinkedIn, Facebook, or Instagram.")
            return

        # Check platform credentials
        creds = db.get_platform_credentials(sender, platform)
        token = db.get_platform_token(sender, platform)
        if not creds and not token:
            await wa.send_text(
                sender,
                f"You haven't connected your {PLATFORM_LABELS[platform]} account yet.\n"
                "Send *setup* to connect it first.",
            )
            db.clear_conversation_state(sender)
            return

        data["platform"] = platform
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONTENT, data)
        await wa.send_text(
            sender,
            f"Write your {PLATFORM_LABELS[platform]} post below.\n\n"
            "Or type *ai* to have AI generate one for you.",
        )

    elif state == ConversationState.AWAITING_POST_CONTENT:
        platform = data.get("platform", "linkedin")
        content = text.strip()
        use_ai = content.lower() == "ai"

        db.clear_conversation_state(sender)

        # Deduct credits
        cm = CreditManager(db)
        if not cm.deduct(sender, "post", platform):
            await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
            return

        if use_ai:
            await wa.send_text(sender, f"Generating AI content for {PLATFORM_LABELS[platform]}...")
            # Dispatch to AI content generation + posting task
            from workers.celery_app import celery_app
            celery_app.send_task(
                f"services.{platform}.tasks.ai_post_task",
                args=[sender],
                queue=f"{platform}_posting",
            )
        else:
            await wa.send_text(sender, f"Publishing to {PLATFORM_LABELS[platform]}...")
            from workers.celery_app import celery_app
            celery_app.send_task(
                f"services.{platform}.tasks.post_task",
                args=[sender, content],
                queue=f"{platform}_posting",
            )

    elif state == ConversationState.AWAITING_SCHEDULE_TIME:
        platform = data.get("platform", "linkedin")
        content = data.get("content", "")

        try:
            scheduled_at = datetime.fromisoformat(text.strip())
        except ValueError:
            await wa.send_text(sender, "Please enter a valid date/time in ISO format:\ne.g. 2026-03-15T09:00")
            return

        db.clear_conversation_state(sender)

        # Deduct credits
        cm = CreditManager(db)
        if not cm.deduct(sender, "scheduled_post", platform):
            await wa.send_text(sender, "Insufficient credits.")
            return

        db.save_scheduled_content(sender, platform, content, scheduled_at)
        await wa.send_text(
            sender,
            f"Post scheduled for {PLATFORM_LABELS[platform]} at {scheduled_at.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Credits deducted: *{get_action_cost('scheduled_post')}*",
        )


# =========================================================================
# SCHEDULE
# =========================================================================

async def handle_schedule(db: BotDatabase, sender: str, text: str):
    """Start the schedule flow: platform → content → time."""
    if not await _check_subscription(db, sender):
        return
    if not await _check_credits(db, sender, "scheduled_post"):
        return

    await wa.send_interactive_buttons(
        sender,
        "Schedule a post for which platform?",
        [
            {"id": "linkedin", "title": "LinkedIn"},
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {"scheduling": True})


# =========================================================================
# REPLY (comment replies)
# =========================================================================

async def handle_reply(db: BotDatabase, sender: str, text: str):
    """Start auto-reply flow: choose platform → dispatch task."""
    if not await _check_subscription(db, sender):
        return
    if not await _check_credits(db, sender, "comment_reply"):
        return

    await wa.send_interactive_buttons(
        sender,
        "Auto-reply to comments on which platform?",
        [
            {"id": "linkedin", "title": "LinkedIn"},
            {"id": "facebook", "title": "Facebook"},
            {"id": "instagram", "title": "Instagram"},
        ],
    )
    db.set_conversation_state(sender, ConversationState.AWAITING_REPLY_PLATFORM, {})


async def handle_reply_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    """Process reply platform selection."""
    platform = text.lower()
    if platform not in PLATFORM_LABELS:
        await wa.send_text(sender, "Please choose LinkedIn, Facebook, or Instagram.")
        return

    db.clear_conversation_state(sender)

    # Deduct credits
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


# =========================================================================
# STATS
# =========================================================================

async def handle_stats(db: BotDatabase, sender: str, text: str):
    """Show user stats across all platforms."""
    lines = ["*Your Automation Stats*\n"]

    for platform in ("linkedin", "facebook", "instagram"):
        stats = db.get_user_stats(sender, platform)
        if stats["posts_created"] or stats["likes_given"] or stats["comments_made"]:
            lines.append(f"*{PLATFORM_LABELS[platform]}:*")
            lines.append(f"  Posts: {stats['posts_created']}")
            lines.append(f"  Likes: {stats['likes_given']}")
            lines.append(f"  Comments: {stats['comments_made']}")
            lines.append(f"  Connections: {stats['connections_sent']}")
            if stats["last_active"]:
                lines.append(f"  Last active: {stats['last_active'][:10]}")
            lines.append("")

    if len(lines) == 1:
        lines.append("No activity yet. Send *post* to get started!")

    cm = CreditManager(db)
    summary = cm.get_usage_summary(sender)
    lines.append(f"*Credits:* {summary['credits_remaining']}/{summary['credits_total']} remaining")

    await wa.send_text(sender, "\n".join(lines))
