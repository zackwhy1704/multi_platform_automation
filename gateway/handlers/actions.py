"""
Content creation and engagement handlers.
Facebook + Instagram only (Graph API). Freemium: credits-based, no subscription required.
"""

import logging
from datetime import datetime
from shared.database import BotDatabase
from shared.credits import CreditManager, get_action_cost
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram"}


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
            "  *subscribe* — 500 credits/month\n"
            "  *referral* — Share your code, earn 50 credits per friend\n\n"
            "Send *credits* for your full balance breakdown.",
        )
        return False
    return True


async def handle_post(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "post"):
        return
    await wa.send_interactive_buttons(sender, "Which platform do you want to post on?",
        [{"id": "facebook", "title": "Facebook"}, {"id": "instagram", "title": "Instagram"}])
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {})


async def handle_post_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    if state == ConversationState.AWAITING_POST_PLATFORM:
        platform = text.lower()
        if platform not in PLATFORM_LABELS:
            await wa.send_text(sender, "Please choose Facebook or Instagram.")
            return
        token = db.get_platform_token(sender, platform)
        if not token:
            await wa.send_text(sender, f"You haven't connected your {PLATFORM_LABELS[platform]} account yet.\nSend *setup* to connect it first.")
            db.clear_conversation_state(sender)
            return
        data["platform"] = platform
        db.set_conversation_state(sender, ConversationState.AWAITING_POST_CONTENT, data)
        await wa.send_text(sender, f"Write your {PLATFORM_LABELS[platform]} post below.\n\nOr type *ai* to have AI generate one for you.")

    elif state == ConversationState.AWAITING_POST_CONTENT:
        platform = data.get("platform", "facebook")
        content = text.strip()
        use_ai = content.lower() == "ai"
        db.clear_conversation_state(sender)

        cm = CreditManager(db)
        if not cm.deduct(sender, "post", platform):
            await wa.send_text(sender, "Insufficient credits. Send *credits* for details.")
            return

        from workers.celery_app import celery_app
        if use_ai:
            await wa.send_text(sender, f"Generating AI content for {PLATFORM_LABELS[platform]}...")
            celery_app.send_task(f"services.{platform}.tasks.ai_post_task", args=[sender], queue=f"{platform}_posting")
        else:
            await wa.send_text(sender, f"Publishing to {PLATFORM_LABELS[platform]}...")
            celery_app.send_task(f"services.{platform}.tasks.post_task", args=[sender, content], queue=f"{platform}_posting")

    elif state == ConversationState.AWAITING_SCHEDULE_TIME:
        platform = data.get("platform", "facebook")
        content = data.get("content", "")
        try:
            scheduled_at = datetime.fromisoformat(text.strip())
        except ValueError:
            await wa.send_text(sender, "Please enter a valid date/time in ISO format:\ne.g. 2026-03-15T09:00")
            return
        db.clear_conversation_state(sender)
        cm = CreditManager(db)
        if not cm.deduct(sender, "scheduled_post", platform):
            await wa.send_text(sender, "Insufficient credits.")
            return
        db.save_scheduled_content(sender, platform, content, scheduled_at)
        await wa.send_text(sender, f"Post scheduled for {PLATFORM_LABELS[platform]} at {scheduled_at.strftime('%Y-%m-%d %H:%M')}.\nCredits deducted: *{get_action_cost('scheduled_post')}*")


async def handle_schedule(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "scheduled_post"):
        return
    await wa.send_interactive_buttons(sender, "Schedule a post for which platform?",
        [{"id": "facebook", "title": "Facebook"}, {"id": "instagram", "title": "Instagram"}])
    db.set_conversation_state(sender, ConversationState.AWAITING_POST_PLATFORM, {"scheduling": True})


async def handle_reply(db: BotDatabase, sender: str, text: str):
    if not await _check_credits(db, sender, "comment_reply"):
        return
    await wa.send_interactive_buttons(sender, "Auto-reply to comments on which platform?",
        [{"id": "facebook", "title": "Facebook"}, {"id": "instagram", "title": "Instagram"}])
    db.set_conversation_state(sender, ConversationState.AWAITING_REPLY_PLATFORM, {})


async def handle_reply_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    platform = text.lower()
    if platform not in PLATFORM_LABELS:
        await wa.send_text(sender, "Please choose Facebook or Instagram.")
        return
    db.clear_conversation_state(sender)
    cm = CreditManager(db)
    if not cm.deduct(sender, "comment_reply", platform):
        await wa.send_text(sender, "Insufficient credits.")
        return
    await wa.send_text(sender, f"Starting auto-reply on {PLATFORM_LABELS[platform]}...")
    from workers.celery_app import celery_app
    celery_app.send_task(f"services.{platform}.tasks.reply_task", args=[sender], queue=f"{platform}_engagement")


async def handle_stats(db: BotDatabase, sender: str, text: str):
    lines = ["*Your Automation Stats*\n"]
    for platform, label in PLATFORM_LABELS.items():
        stats = db.get_user_stats(sender, platform)
        if stats["posts_created"] or stats["comments_made"]:
            lines.append(f"*{label}:*")
            lines.append(f"  Posts: {stats['posts_created']}")
            lines.append(f"  Replies: {stats['comments_made']}")
            if stats["last_active"]:
                lines.append(f"  Last active: {stats['last_active'][:10]}")
            lines.append("")
    if len(lines) == 1:
        lines.append("No activity yet. Send *post* to get started!")
    cm = CreditManager(db)
    balance = cm.get_balance(sender)
    lines.append(f"\n*Credits remaining:* {balance}")
    await wa.send_text(sender, "\n".join(lines))
