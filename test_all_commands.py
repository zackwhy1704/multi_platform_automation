#!/usr/bin/env python3
"""
Comprehensive command test suite — auto-discovers ALL commands from the router.

This script imports the COMMANDS dict directly from the router, so it
automatically picks up new commands without manual updates.

For each command it:
  1. Clears conversation state
  2. Sends the command via webhook
  3. Verifies HTTP 200 response
  4. Checks that the expected conversation state was set (where applicable)
  5. Tests multi-step flows (buy → pack select, setup → platform select, etc.)

Usage:
  python3 test_all_commands.py
"""

import os
import sys
import json
import asyncio
import hashlib
import hmac
import traceback
from datetime import datetime

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://multiplatformautomation-production.up.railway.app")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "953624217844398")
WA_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:uTKZlJFIYxDAQorHavWTlbsEaXugFBMx@turntable.proxy.rlwy.net:34828/railway")
TEST_PHONE = os.getenv("TEST_PHONE", "6597120520")

passed = 0
failed = 0
errors = []

# ── Auto-discover commands from router ────────────────────────────────────────

# Add project root to path so we can import gateway modules
sys.path.insert(0, os.path.dirname(__file__))

from gateway.router import COMMANDS, STATE_HANDLERS

ALL_COMMANDS = list(COMMANDS.keys())


# ── Expected states after each command ────────────────────────────────────────
# Maps command → expected conversation state after sending it.
# None means state should be idle/cleared (no state set).
# Commands not listed here default to "any state is ok as long as HTTP 200".

EXPECTED_STATES = {
    "post": "awaiting_post_media",
    "schedule": "awaiting_post_platform",
    "reply": "awaiting_reply_platform",
    "buy": "awaiting_pack_choice",
    "subscribe": "awaiting_pack_choice",
    "setup": "setup_platform",
    "language": "awaiting_language",
    "ai image": "awaiting_ai_image_prompt",
    "ai video": "awaiting_ai_video_prompt",
    "disconnect": "setup_platform",
    # These commands don't set state (respond and stay idle)
    "help": None,
    "start": None,
    "stats": None,
    "credits": None,
    "cancel subscription": None,
    "reset": None,
    "settings": None,
    "referral": None,
}

# ── Multi-step flow tests ─────────────────────────────────────────────────────
# Each flow is a list of steps: (message_type, message_data, expected_state_after)

MULTI_STEP_FLOWS = {
    "buy → select pack": [
        ("text", "buy", "awaiting_pack_choice"),
        ("list_reply", {"id": "pack_100", "title": "100 credits"}, None),  # checkout created, state cleared
    ],
    "setup → select instagram": [
        ("text", "setup", "setup_platform"),
        ("button_reply", {"id": "setup_instagram", "title": "Instagram"}, "setup_manual_choose"),
    ],
    "setup → select facebook": [
        ("text", "setup", "setup_platform"),
        ("button_reply", {"id": "setup_facebook", "title": "Facebook"}, "setup_manual_choose"),
    ],
    "ai image → enter prompt": [
        ("text", "ai image", "awaiting_ai_image_prompt"),
        # Don't actually generate (costs credits) — just verify state was set
    ],
    "ai video → enter prompt → select length": [
        ("text", "ai video", "awaiting_ai_video_prompt"),
        ("text", "a beautiful sunset over the ocean", "awaiting_ai_video_length"),
        # Don't select length (would cost 30 credits)
    ],
    "language → select english": [
        ("text", "language", "awaiting_language"),
        ("button_reply", {"id": "lang_en", "title": "English"}, None),
    ],
    "subscribe → select plan": [
        ("text", "subscribe", "awaiting_pack_choice"),
        ("list_reply", {"id": "plan_pro", "title": "Pro"}, None),  # checkout created
    ],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {level} {msg}")


def test_pass(msg: str):
    global passed
    passed += 1
    log("✅", msg)


def test_fail(msg: str, detail: str = ""):
    global failed
    failed += 1
    errors.append(msg)
    log("❌", msg)
    if detail:
        log("  ", f"→ {detail}")


def _sign(payload_str: str) -> str:
    return "sha256=" + hmac.new(
        WA_APP_SECRET.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()


def _make_webhook(msg_body: dict, msg_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "0",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": WA_PHONE_ID},
                    "contacts": [{"profile": {"name": "Test"}, "wa_id": TEST_PHONE}],
                    "messages": [{
                        **msg_body,
                        "from": TEST_PHONE,
                        "id": msg_id,
                        "timestamp": str(int(datetime.now().timestamp())),
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _make_text_msg(text: str) -> dict:
    return {"type": "text", "text": {"body": text}}


def _make_button_reply(button: dict) -> dict:
    return {
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": button},
    }


def _make_list_reply(item: dict) -> dict:
    return {
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": item},
    }


async def _post_webhook(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    body = json.dumps(payload)
    return await client.post(
        f"{BASE_URL}/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body),
        },
    )


def _clear_state():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("DELETE FROM conversation_state WHERE phone_number_id = %s", (TEST_PHONE,))
    conn.commit()
    conn.close()


def _get_state() -> dict | None:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute(
        "SELECT state, data FROM conversation_state WHERE phone_number_id = %s",
        (TEST_PHONE,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def _seed_user():
    """Ensure test user exists with profile and FB token so all commands work."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    # Ensure user exists
    cur.execute(
        """INSERT INTO users (phone_number_id, display_name, credits_remaining, credits_used)
           VALUES (%s, 'Test User', 500, 0)
           ON CONFLICT (phone_number_id) DO UPDATE SET credits_remaining = GREATEST(users.credits_remaining, 100)""",
        (TEST_PHONE,),
    )
    # Ensure profile exists
    cur.execute(
        """INSERT INTO user_profiles (phone_number_id, industry, offerings, business_goals, tone, platform)
           VALUES (%s, '["tech"]', '["software"]', '["brand_awareness"]', '["professional"]', 'both')
           ON CONFLICT (phone_number_id) DO NOTHING""",
        (TEST_PHONE,),
    )
    # Ensure FB token exists (so post/disconnect/etc. work)
    cur.execute(
        """INSERT INTO platform_tokens (phone_number_id, platform, access_token, page_id, page_name, pfm_profile_key)
           VALUES (%s, 'facebook', 'test_token', 'test_page', 'Test Page', 'spc_test')
           ON CONFLICT (phone_number_id, platform) DO NOTHING""",
        (TEST_PHONE,),
    )
    conn.commit()
    conn.close()


# ── Test: All commands smoke test ─────────────────────────────────────────────

async def test_all_commands_smoke(client: httpx.AsyncClient):
    """Send every command from COMMANDS dict, verify HTTP 200 and expected state."""
    print(f"\n{'─'*80}")
    print(f"  SMOKE TEST: All {len(ALL_COMMANDS)} commands")
    print(f"  Commands: {', '.join(ALL_COMMANDS)}")
    print(f"{'─'*80}\n")

    for i, cmd in enumerate(ALL_COMMANDS):
        _clear_state()
        await asyncio.sleep(0.5)

        msg = _make_text_msg(cmd)
        payload = _make_webhook(msg, f"smoke_{i:03d}_{cmd.replace(' ', '_')}")
        resp = await _post_webhook(client, payload)

        if resp.status_code != 200:
            test_fail(f"Command '{cmd}' → HTTP {resp.status_code}", resp.text[:200])
            continue

        await asyncio.sleep(2.0)  # Wait for async processing

        # Check state
        state_row = _get_state()
        actual_state = state_row["state"] if state_row else None

        expected = EXPECTED_STATES.get(cmd, "SKIP")

        if expected == "SKIP":
            # Command not in expected map — just check HTTP 200
            test_pass(f"Command '{cmd}' → HTTP 200 ✓ (state: {actual_state or 'idle'})")
        elif expected is None:
            # Should NOT set state
            if actual_state is None or actual_state == "idle":
                test_pass(f"Command '{cmd}' → HTTP 200 ✓, state cleared ✓")
            else:
                test_fail(f"Command '{cmd}' → expected idle state, got '{actual_state}'")
        else:
            # Should set specific state
            if actual_state == expected:
                test_pass(f"Command '{cmd}' → HTTP 200 ✓, state '{expected}' ✓")
            else:
                test_fail(
                    f"Command '{cmd}' → expected state '{expected}', got '{actual_state or 'idle'}'",
                )

    _clear_state()


# ── Test: Multi-step flows ────────────────────────────────────────────────────

async def test_multi_step_flows(client: httpx.AsyncClient):
    """Test multi-step command flows to verify full user journeys."""
    print(f"\n{'─'*80}")
    print(f"  MULTI-STEP FLOW TESTS: {len(MULTI_STEP_FLOWS)} flows")
    print(f"{'─'*80}\n")

    for flow_name, steps in MULTI_STEP_FLOWS.items():
        _clear_state()
        await asyncio.sleep(0.5)

        flow_ok = True
        for step_i, step in enumerate(steps):
            msg_type, msg_data, expected_state = step

            if msg_type == "text":
                msg = _make_text_msg(msg_data)
            elif msg_type == "button_reply":
                msg = _make_button_reply(msg_data)
            elif msg_type == "list_reply":
                msg = _make_list_reply(msg_data)
            else:
                test_fail(f"Flow '{flow_name}' step {step_i}: unknown msg_type '{msg_type}'")
                flow_ok = False
                break

            payload = _make_webhook(msg, f"flow_{flow_name.replace(' ', '_')}_{step_i:02d}")
            resp = await _post_webhook(client, payload)

            if resp.status_code != 200:
                test_fail(
                    f"Flow '{flow_name}' step {step_i} → HTTP {resp.status_code}",
                    resp.text[:200],
                )
                flow_ok = False
                break

            await asyncio.sleep(2.5)

            # Check state
            state_row = _get_state()
            actual_state = state_row["state"] if state_row else None

            if expected_state is None:
                if actual_state is not None and actual_state != "idle":
                    test_fail(
                        f"Flow '{flow_name}' step {step_i}: expected idle, got '{actual_state}'",
                    )
                    flow_ok = False
                    break
            else:
                if actual_state != expected_state:
                    test_fail(
                        f"Flow '{flow_name}' step {step_i}: expected '{expected_state}', got '{actual_state or 'idle'}'",
                    )
                    flow_ok = False
                    break

        if flow_ok:
            test_pass(f"Flow '{flow_name}' → all {len(steps)} steps passed ✓")

        _clear_state()


# ── Test: State handler coverage ──────────────────────────────────────────────

async def test_state_handler_coverage(client: httpx.AsyncClient):
    """Verify that every conversation state has a handler registered."""
    print(f"\n{'─'*80}")
    print(f"  STATE HANDLER COVERAGE CHECK")
    print(f"{'─'*80}\n")

    from gateway.conversation import ConversationState

    all_states = [s for s in ConversationState if s != ConversationState.IDLE]
    handled_states = set(STATE_HANDLERS.keys())

    for state in all_states:
        if state in handled_states:
            test_pass(f"State '{state.value}' has handler ✓")
        else:
            test_fail(f"State '{state.value}' has NO handler registered!")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "═" * 80)
    print("  COMPREHENSIVE COMMAND TEST SUITE (Auto-Discovered)")
    print("═" * 80)
    print(f"  Target:     {BASE_URL}")
    print(f"  Phone:      {TEST_PHONE}")
    print(f"  Commands:   {len(ALL_COMMANDS)} discovered from router")
    print(f"  Flows:      {len(MULTI_STEP_FLOWS)} multi-step flows")
    print(f"  DB:         {DATABASE_URL.split('@')[1][:40] if DATABASE_URL else 'NOT SET'}...")
    print("═" * 80)

    if not WA_APP_SECRET:
        print("\n  ❌ WHATSAPP_APP_SECRET not set — cannot sign webhooks. Aborting.")
        sys.exit(1)

    if not DATABASE_URL:
        print("\n  ❌ DATABASE_URL not set — cannot verify states. Aborting.")
        sys.exit(1)

    # Seed test user
    try:
        _seed_user()
        print(f"\n  ℹ️  Test user seeded: {TEST_PHONE}")
    except Exception as e:
        print(f"\n  ⚠️  Could not seed test user: {e}")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # 1. Smoke test all commands
        await test_all_commands_smoke(client)

        # 2. Multi-step flow tests
        await test_multi_step_flows(client)

        # 3. State handler coverage
        await test_state_handler_coverage(client)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print(f"  RESULTS:  {passed} passed  |  {failed} failed  |  {passed + failed} total")
    print("═" * 80)

    if errors:
        print(f"\n  FAILURES:")
        for e in errors:
            print(f"    ❌ {e}")

    print()
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
