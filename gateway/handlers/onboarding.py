"""
Onboarding and help handlers.
"""

import logging
from shared.database import BotDatabase
from gateway.conversation import ConversationState
from gateway import whatsapp_client as wa

logger = logging.getLogger(__name__)


async def handle_start(db: BotDatabase, sender: str, text: str):
    profile = db.get_user_profile(sender)
    if profile:
        await wa.send_text(sender, "Welcome back! You're already set up.\n\nSend *help* to see what I can do, or *credits* to check your balance.")
        return

    await wa.send_text(
        sender,
        "Welcome to *Multi-Platform Automation Bot*!\n\n"
        "I can automate your social media presence on:\n"
        "- Facebook (Pages)\n"
        "- Instagram (Business accounts)\n\n"
        "All actions use the official Meta Graph API — safe, no risk of account bans.\n\n"
        "Let's set up your profile first. This helps me generate better content for you.\n\n"
        "What *industry* are you in? (e.g. Tech, Marketing, Finance, Healthcare)",
    )
    db.set_conversation_state(sender, ConversationState.ONBOARDING_INDUSTRY, {})


async def handle_help(db: BotDatabase, sender: str, text: str):
    await wa.send_text(
        sender,
        "*Available Commands:*\n\n"
        "*Content*\n"
        "  post — Create and publish a post (5 credits)\n"
        "  schedule — Schedule a post for later (5 credits)\n"
        "  reply — Auto-reply to comments (3 credits)\n\n"
        "*Account*\n"
        "  credits — Check credit balance\n"
        "  stats — View automation statistics\n"
        "  setup — Connect Facebook / Instagram\n"
        "  settings — View/update your profile\n\n"
        "*Subscription*\n"
        "  subscribe — Subscribe or manage plan\n"
        "  cancel — Cancel subscription\n\n"
        "Send *cancel* at any time to exit a multi-step flow.",
    )


async def handle_onboarding_step(db: BotDatabase, sender: str, text: str, state: ConversationState, data: dict):
    if state == ConversationState.ONBOARDING_INDUSTRY:
        data["industry"] = [t.strip() for t in text.split(",")]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_SKILLS, data)
        await wa.send_text(sender, "Great! Now list your *key skills* (comma-separated).\ne.g. Python, Data Analysis, Project Management")

    elif state == ConversationState.ONBOARDING_SKILLS:
        data["skills"] = [t.strip() for t in text.split(",")]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_GOALS, data)
        await wa.send_text(sender, "What are your *content goals*? (comma-separated)\ne.g. Grow personal brand, Find new clients, Build community")

    elif state == ConversationState.ONBOARDING_GOALS:
        data["career_goals"] = [t.strip() for t in text.split(",")]
        db.set_conversation_state(sender, ConversationState.ONBOARDING_TONE, data)
        await wa.send_interactive_buttons(sender, "What *tone* should I use for your content?",
            [{"id": "professional", "title": "Professional"}, {"id": "casual", "title": "Casual"}, {"id": "thought_leader", "title": "Thought Leader"}])

    elif state == ConversationState.ONBOARDING_TONE:
        data["tone"] = [text.strip()]
        db.save_user_profile(sender, data)
        db.clear_conversation_state(sender)
        await wa.send_text(
            sender,
            "Profile saved!\n\n"
            "Next steps:\n"
            "1. Send *setup* to connect your Facebook / Instagram\n"
            "2. Send *subscribe* to activate your plan (500 credits/month)\n"
            "3. Send *post* to create your first post\n\n"
            "Send *help* anytime to see all commands.",
        )
