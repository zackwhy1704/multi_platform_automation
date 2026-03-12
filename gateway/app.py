"""
WhatsApp Gateway — FastAPI application.
Receives Meta Cloud API webhooks and dispatches to conversation handlers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from shared.config import WHATSAPP_VERIFY_TOKEN
from shared.database import BotDatabase
from gateway.router import handle_incoming_message

logging.basicConfig(level=logging.INFO, format="[%(asctime)s %(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

db: BotDatabase = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = BotDatabase()
    app.state.db = db
    logger.info("Gateway started — database pool ready")
    yield
    db.close()
    logger.info("Gateway shutdown — pool closed")


app = FastAPI(title="Multi-Platform Automation Gateway", lifespan=lifespan)


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification (GET challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    # Meta sends notifications with this structure
    entry = body.get("entry", [])
    for e in entry:
        changes = e.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            for i, msg in enumerate(messages):
                sender = msg.get("from", "")
                contact_name = contacts[i]["profile"]["name"] if i < len(contacts) else ""

                await handle_incoming_message(
                    db=app.state.db,
                    sender=sender,
                    message=msg,
                    contact_name=contact_name,
                )

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}
