"""Admin panel for the WhatsApp bot.

Single-password protected web UI for monitoring users, conversations,
revenue, and taking moderation actions. All routes are mounted under /admin.
"""
from gateway.admin.router import router  # noqa: F401
