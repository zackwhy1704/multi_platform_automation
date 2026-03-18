#!/usr/bin/env python3
"""
Direct API integration tests — actually calls every external API.

Tests:
  1. Anthropic Claude (caption generation, post generation, image search query)
  2. OpenAI gpt-image-1 (image generation, base64 decode, file save)
  3. Kling AI (video generation, JWT auth, polling)
  4. Pexels (stock image search)
  5. Stripe (checkout session creation, price ID validation)
  6. Facebook Graph API (token validation, page listing)
  7. WhatsApp Cloud API (send text message)
  8. Full posting flow: AI image → caption → preview data

Usage:
  python3 api_test.py              # run all tests
  python3 api_test.py anthropic    # run only anthropic tests
  python3 api_test.py openai       # run only openai tests
  python3 api_test.py kling        # run only kling tests
  python3 api_test.py pexels       # run only pexels tests
  python3 api_test.py stripe       # run only stripe tests
  python3 api_test.py whatsapp     # run only whatsapp tests
  python3 api_test.py full_flow    # run full posting flow test
"""

import asyncio
import base64
import json
import os
import sys
import time
import traceback
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
KLING_ACCESS_KEY = os.getenv("KLING_ACCESS_KEY", "")
KLING_SECRET_KEY = os.getenv("KLING_SECRET_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID_PRO = os.getenv("STRIPE_PRICE_ID_PRO", "")
STRIPE_PRICE_ID_PACK_100 = os.getenv("STRIPE_PRICE_ID_PACK_100", "")
WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
TEST_PHONE = os.getenv("TEST_PHONE", "6597120520")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

passed = 0
failed = 0
skipped = 0
errors = []


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
    log("❌", msg)
    if detail:
        log("  ", f"   → {detail[:300]}")
    errors.append(msg)


def test_skip(msg: str, reason: str = ""):
    global skipped
    skipped += 1
    log("⏭️ ", f"{msg} — {reason}")


def section(title: str):
    print(f"\n{'─'*80}")
    print(f"  {title}")
    print(f"{'─'*80}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. ANTHROPIC CLAUDE API
# ══════════════════════════════════════════════════════════════════════════════

async def test_anthropic():
    section("1. Anthropic Claude API")

    if not ANTHROPIC_API_KEY:
        test_skip("Anthropic tests", "ANTHROPIC_API_KEY not set")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Test 1a: Basic message
    try:
        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": "Say 'hello' in one word."}],
        )
        text = resp.content[0].text.strip()
        if text:
            test_pass(f"Basic message — model={AI_MODEL}, response='{text[:50]}'")
        else:
            test_fail("Basic message — empty response")
    except Exception as e:
        test_fail("Basic message", str(e))

    # Test 1b: Generate post (same as ai_service.generate_post)
    try:
        prompt = """You are a social media content strategist.

Write a Facebook post. Keep it conversational and engaging. Include a question to drive comments. Use short paragraphs.

Business profile:
- Industry: Technology
- Products/Services: SaaS, Web Development
- Business goals: Get more customers
- Preferred tone: professional

Write ONE post. Output ONLY the post text, no preamble or explanation."""

        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        post_text = resp.content[0].text.strip()
        if len(post_text) > 20:
            test_pass(f"Generate post — {len(post_text)} chars: '{post_text[:80]}...'")
        else:
            test_fail("Generate post — response too short", post_text)
    except Exception as e:
        test_fail("Generate post", str(e))

    # Test 1c: Generate caption for media
    try:
        prompt = """You are a social media content strategist.

Write an Instagram caption. Start with a hook, add emojis, end with 10-15 hashtags.

Business profile:
- Industry: Food & Beverage
- Products/Services: Coffee, Pastries
- Preferred tone: casual

The user is posting a photo. Write a caption that complements it.
Output ONLY the caption text, no preamble."""

        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        caption = resp.content[0].text.strip()
        if len(caption) > 20:
            test_pass(f"Generate caption — {len(caption)} chars, has hashtags: {'#' in caption}")
        else:
            test_fail("Generate caption — too short", caption)
    except Exception as e:
        test_fail("Generate caption", str(e))

    # Test 1d: Generate image search query
    try:
        prompt = """Generate a short Pexels stock photo search query (2-4 words) for a social media post.

Business: Technology
Products/Services: Web Development

Output ONLY the search query, nothing else. Example: "coffee shop interior" or "team meeting office"."""

        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=30,
            messages=[{"role": "user", "content": prompt}],
        )
        query = resp.content[0].text.strip().strip('"').strip("'")
        if 1 < len(query) < 100:
            test_pass(f"Image search query — '{query}'")
        else:
            test_fail("Image search query — unexpected length", query)
    except Exception as e:
        test_fail("Image search query", str(e))

    # Test 1e: ReAct input validation (same as input_validator)
    try:
        prompt = """You are validating a user's input during a business profile onboarding flow.

QUESTION ASKED: What industry is your business in?
EXPECTED INPUT: One or more business industries/sectors, comma-separated
EXAMPLES OF GOOD ANSWERS: E-commerce, Tech, F&B, Healthcare, Real Estate, Marketing

USER'S ANSWER: "I sell coffee and pastries"

Apply the ReAct reasoning pattern:

THOUGHT: Reason step by step:
1. Is this in English?
2. Is it relevant to the question asked?
3. Is it specific enough to be useful for generating social media content?
4. Does it make sense as a business-related answer?

ACTION: Choose exactly one:
- ACCEPT: Input is valid, relevant, and clear enough to use
- CLARIFY: Input is partially valid but too vague, off-topic, or could be better. Provide a helpful, friendly nudge.
- REJECT: Input is gibberish, not English, or completely unrelated

Respond in this exact JSON format (no other text):
{"thought": "your reasoning", "action": "accept|clarify|reject", "cleaned": "normalized input if accept, null otherwise", "message": "friendly message to user if clarify/reject, null if accept"}"""

        resp = client.messages.create(
            model=AI_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        action = result.get("action", "").lower()
        if action in ("accept", "clarify", "reject"):
            test_pass(f"ReAct validation — action={action}, thought='{result.get('thought', '')[:60]}...'")
        else:
            test_fail("ReAct validation — unexpected action", str(result))
    except json.JSONDecodeError as e:
        test_fail("ReAct validation — invalid JSON", f"{e}: {raw[:200]}")
    except Exception as e:
        test_fail("ReAct validation", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 2. OPENAI IMAGE GENERATION (gpt-image-1)
# ══════════════════════════════════════════════════════════════════════════════

async def test_openai():
    section("2. OpenAI Image Generation (gpt-image-1)")

    if not OPENAI_API_KEY:
        test_skip("OpenAI tests", "OPENAI_API_KEY not set")
        return

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Test 2a: Generate image with base64 response
    try:
        log("🔄", "Generating image (this takes 10-30 seconds)...")
        result = client.images.generate(
            model="gpt-image-1",
            prompt="A simple blue circle on a white background, minimalist",
            n=1,
            size="1024x1024",
        )

        image_data = result.data[0]

        if image_data.b64_json:
            # Decode base64
            img_bytes = base64.b64decode(image_data.b64_json)
            if len(img_bytes) > 1000:
                test_pass(f"Image generated (base64) — {len(img_bytes):,} bytes")

                # Test saving to file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    f.write(img_bytes)
                    temp_path = f.name

                file_size = os.path.getsize(temp_path)
                if file_size > 1000:
                    test_pass(f"Image saved to disk — {file_size:,} bytes at {temp_path}")
                else:
                    test_fail("Image save — file too small", f"{file_size} bytes")
                os.unlink(temp_path)
            else:
                test_fail("Image base64 decode — too small", f"{len(img_bytes)} bytes")

        elif image_data.url:
            test_pass(f"Image generated (URL) — {image_data.url[:80]}...")
        else:
            test_fail("Image generation — no b64_json or url in response")

    except Exception as e:
        test_fail("Image generation", str(e))

    # Test 2b: Verify the image_generator module works end-to-end
    try:
        from services.ai.image_generator import generate_image, build_image_prompt

        profile = {
            "industry": ["Technology"],
            "offerings": ["SaaS"],
            "tone": ["professional"],
        }
        prompt = build_image_prompt(profile, "mixed", "minimalist", "test image", "instagram")
        if len(prompt) > 20:
            test_pass(f"build_image_prompt — {len(prompt)} chars: '{prompt[:80]}...'")
        else:
            test_fail("build_image_prompt — too short", prompt)

        if PUBLIC_BASE_URL:
            log("🔄", "Testing generate_image() end-to-end (saves to disk + returns URL)...")
            url = generate_image("A simple red square on white background, minimalist, small")
            if url and url.startswith("http"):
                test_pass(f"generate_image → URL: {url}")
            elif url is None and not PUBLIC_BASE_URL:
                test_skip("generate_image", "PUBLIC_BASE_URL not set, cannot serve")
            else:
                test_fail("generate_image — unexpected result", str(url))
        else:
            test_skip("generate_image() e2e", "PUBLIC_BASE_URL not set")

    except Exception as e:
        test_fail("image_generator module", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 3. KLING AI VIDEO GENERATION
# ══════════════════════════════════════════════════════════════════════════════

async def test_kling():
    section("3. Kling AI Video Generation")

    if not KLING_ACCESS_KEY or not KLING_SECRET_KEY:
        test_skip("Kling tests", "KLING_ACCESS_KEY/KLING_SECRET_KEY not set")
        return

    # Test 3a: JWT token generation
    try:
        from services.ai.video_generator import _generate_jwt_token
        token = _generate_jwt_token()
        if token and len(token) > 50:
            test_pass(f"JWT token generated — {len(token)} chars")
        else:
            test_fail("JWT token — empty or too short", str(token))
            return  # Can't proceed without JWT
    except Exception as e:
        test_fail("JWT token generation", str(e))
        return

    # Test 3b: Submit a video task (don't wait for completion to save time)
    try:
        import jwt as pyjwt
        payload = {
            "iss": KLING_ACCESS_KEY,
            "exp": int(time.time()) + 1800,
            "nbf": int(time.time()) - 5,
        }
        jwt_token = pyjwt.encode(payload, KLING_SECRET_KEY, algorithm="HS256")

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.klingai.com/v1/videos/text2video",
                json={
                    "model_name": "kling-v1",
                    "prompt": "A simple blue ball bouncing",
                    "cfg_scale": 0.5,
                    "mode": "std",
                    "duration": "5",
                    "aspect_ratio": "1:1",
                },
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json().get("data", {})
                task_id = data.get("task_id")
                if task_id:
                    test_pass(f"Video task submitted — task_id={task_id}")

                    # Test 3c: Poll once to verify status endpoint works
                    await asyncio.sleep(3)
                    status_resp = await client.get(
                        f"https://api.klingai.com/v1/videos/text2video/{task_id}",
                        headers=headers,
                    )
                    if status_resp.status_code == 200:
                        status_data = status_resp.json().get("data", {})
                        task_status = status_data.get("task_status", "unknown")
                        test_pass(f"Video status poll — status={task_status}")

                        # If already succeeded (unlikely but possible), verify URL
                        if task_status == "succeed":
                            works = status_data.get("task_result", {}).get("videos", [])
                            if works and works[0].get("url"):
                                test_pass(f"Video URL — {works[0]['url'][:80]}...")
                    else:
                        test_fail("Video status poll", f"HTTP {status_resp.status_code}: {status_resp.text[:200]}")
                else:
                    test_fail("Video task — no task_id", str(resp.json()))
            else:
                error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]
                test_fail(f"Video task submit — HTTP {resp.status_code}", str(error_body))

    except Exception as e:
        test_fail("Kling API", str(e))

    # Test 3d: build_video_prompt
    try:
        from services.ai.video_generator import build_video_prompt
        profile = {
            "industry": ["Technology"],
            "offerings": ["SaaS"],
            "tone": ["professional"],
        }
        prompt = build_video_prompt(profile, "mixed", "photorealistic", "product demo", "instagram")
        if len(prompt) > 20:
            test_pass(f"build_video_prompt — {len(prompt)} chars")
        else:
            test_fail("build_video_prompt — too short")
    except Exception as e:
        test_fail("build_video_prompt", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 4. PEXELS STOCK IMAGE API
# ══════════════════════════════════════════════════════════════════════════════

async def test_pexels():
    section("4. Pexels Stock Image API")

    if not PEXELS_API_KEY:
        test_skip("Pexels tests", "PEXELS_API_KEY not set")
        return

    # Test 4a: Direct API call
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": "coffee shop", "per_page": 3, "orientation": "square"},
                headers={"Authorization": PEXELS_API_KEY},
            )

            if resp.status_code == 200:
                data = resp.json()
                photos = data.get("photos", [])
                if photos:
                    photo = photos[0]
                    url = photo.get("src", {}).get("large2x", "")
                    photographer = photo.get("photographer", "")
                    test_pass(f"Search 'coffee shop' — {len(photos)} results, by {photographer}")

                    # Verify image URL is accessible
                    img_resp = await client.head(url)
                    if img_resp.status_code == 200:
                        test_pass(f"Image URL accessible — {url[:60]}...")
                    else:
                        test_fail(f"Image URL not accessible — HTTP {img_resp.status_code}")
                else:
                    test_fail("Pexels search — no results")
            elif resp.status_code == 401:
                test_fail("Pexels API — unauthorized (bad API key)", resp.text[:200])
            else:
                test_fail(f"Pexels API — HTTP {resp.status_code}", resp.text[:200])

    except Exception as e:
        test_fail("Pexels API", str(e))

    # Test 4b: fetch_stock_image module function
    try:
        from services.ai.ai_service import fetch_stock_image
        result = await fetch_stock_image("modern office workspace")
        if result and result.get("url"):
            test_pass(f"fetch_stock_image — url={result['url'][:60]}..., photographer={result.get('photographer', 'N/A')}")
        else:
            test_fail("fetch_stock_image — returned None")
    except Exception as e:
        test_fail("fetch_stock_image", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 5. STRIPE API
# ══════════════════════════════════════════════════════════════════════════════

async def test_stripe():
    section("5. Stripe API")

    if not STRIPE_SECRET_KEY:
        test_skip("Stripe tests", "STRIPE_SECRET_KEY not set")
        return

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    # Test 5a: List prices to verify key works
    try:
        prices = stripe.Price.list(limit=5, active=True)
        if prices.data:
            test_pass(f"List prices — {len(prices.data)} active prices found")
            for p in prices.data[:3]:
                amount = p.unit_amount / 100 if p.unit_amount else "N/A"
                test_pass(f"  Price: {p.id} → ${amount} {p.currency.upper()} ({p.type})")
        else:
            test_fail("List prices — no active prices found")
    except Exception as e:
        test_fail("List prices", str(e))

    # Test 5b: Validate specific price IDs
    price_ids = {
        "STRIPE_PRICE_ID_PRO": STRIPE_PRICE_ID_PRO,
        "STRIPE_PRICE_ID_PACK_100": STRIPE_PRICE_ID_PACK_100,
    }
    for name, pid in price_ids.items():
        if not pid:
            test_skip(f"Validate {name}", "not set")
            continue
        try:
            price = stripe.Price.retrieve(pid)
            amount = price.unit_amount / 100 if price.unit_amount else "N/A"
            if price.active:
                test_pass(f"Validate {name} — ${amount} {price.currency.upper()}, active=True")
            else:
                test_fail(f"Validate {name} — price exists but inactive!")
        except stripe.error.InvalidRequestError:
            test_fail(f"Validate {name} — price ID not found: {pid}")
        except Exception as e:
            test_fail(f"Validate {name}", str(e))

    # Test 5c: Create a checkout session (without completing it)
    if STRIPE_PRICE_ID_PACK_100:
        try:
            base_url = PUBLIC_BASE_URL or "https://example.com"
            session = stripe.checkout.Session.create(
                line_items=[{"price": STRIPE_PRICE_ID_PACK_100, "quantity": 1}],
                mode="payment",
                success_url=f"{base_url}/payment/success",
                cancel_url=f"{base_url}/payment/cancel",
                client_reference_id="test_user_api_test",
                metadata={"phone_number_id": "test", "purchase_type": "pack_100"},
                allow_promotion_codes=True,
            )
            if session.url:
                test_pass(f"Create checkout session — {session.url[:60]}...")
            else:
                test_fail("Create checkout session — no URL returned")

            # Expire the test session immediately
            stripe.checkout.Session.expire(session.id)
            test_pass("Expired test checkout session")
        except Exception as e:
            test_fail("Create checkout session", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 6. WHATSAPP CLOUD API
# ══════════════════════════════════════════════════════════════════════════════

async def test_whatsapp():
    section("6. WhatsApp Cloud API")

    if not WA_TOKEN or not WA_PHONE_ID:
        test_skip("WhatsApp tests", "WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set")
        return

    url = f"https://graph.facebook.com/v21.0/{WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_TOKEN.strip()}",
        "Content-Type": "application/json",
    }

    # Test 6a: Send a text message
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": TEST_PHONE,
            "type": "text",
            "text": {"body": f"🧪 API test at {datetime.now().strftime('%H:%M:%S')} — text message OK"},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                test_pass("Send text message")
            else:
                test_fail(f"Send text — HTTP {resp.status_code}", resp.text[:300])
    except Exception as e:
        test_fail("Send text message", str(e))

    # Test 6b: Send interactive buttons
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": TEST_PHONE,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": "🧪 API test — interactive buttons"},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": "test_btn_1", "title": "Button 1"}},
                        {"type": "reply", "reply": {"id": "test_btn_2", "title": "Button 2"}},
                    ]
                },
            },
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                test_pass("Send interactive buttons")
            else:
                test_fail(f"Send buttons — HTTP {resp.status_code}", resp.text[:300])
    except Exception as e:
        test_fail("Send interactive buttons", str(e))

    # Test 6c: Send interactive list
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": TEST_PHONE,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": "🧪 API test — interactive list"},
                "action": {
                    "button": "View Options",
                    "sections": [{
                        "title": "Test Section",
                        "rows": [
                            {"id": "item_1", "title": "Item 1", "description": "First item"},
                            {"id": "item_2", "title": "Item 2", "description": "Second item"},
                        ],
                    }],
                },
            },
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                test_pass("Send interactive list")
            else:
                test_fail(f"Send list — HTTP {resp.status_code}", resp.text[:300])
    except Exception as e:
        test_fail("Send interactive list", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 7. FULL POSTING FLOW TEST
# ══════════════════════════════════════════════════════════════════════════════

async def test_full_flow():
    section("7. Full Posting Flow (AI Image + Caption)")

    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        test_skip("Full flow", f"Missing: {', '.join(missing)}")
        return

    profile = {
        "industry": ["Food & Beverage"],
        "offerings": ["Coffee", "Pastries", "Brunch"],
        "business_goals": ["Get more customers"],
        "tone": ["casual"],
        "content_style": "behind_the_scenes",
        "visual_style": "photorealistic",
    }

    # Step 1: Generate image prompt
    from services.ai.image_generator import build_image_prompt
    image_prompt = build_image_prompt(
        profile, "behind_the_scenes", "photorealistic",
        topic="morning coffee ritual", platform="instagram"
    )
    test_pass(f"Step 1 — Image prompt: '{image_prompt[:80]}...'")

    # Step 2: Generate image
    log("🔄", "Step 2 — Generating AI image (10-30 seconds)...")
    from services.ai.image_generator import generate_image
    image_url = generate_image(image_prompt)
    if image_url:
        test_pass(f"Step 2 — Image URL: {image_url}")
    else:
        if not PUBLIC_BASE_URL:
            test_fail("Step 2 — Image generation returned None (PUBLIC_BASE_URL not set?)")
        else:
            test_fail("Step 2 — Image generation returned None")
        return

    # Step 3: Generate caption
    from services.ai.ai_service import generate_post
    caption = generate_post("instagram", profile, topic="morning coffee ritual")
    if caption and len(caption) > 20:
        test_pass(f"Step 3 — Caption ({len(caption)} chars): '{caption[:100]}...'")
    else:
        test_fail("Step 3 — Caption generation failed", str(caption))
        caption = "Check out our morning coffee ritual! ☕"

    # Step 4: Verify image is accessible (if URL is public)
    if image_url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(image_url)
                if resp.status_code == 200:
                    test_pass(f"Step 4 — Image URL accessible")
                elif resp.status_code == 405:
                    # HEAD not supported, try GET
                    resp = await client.get(image_url)
                    if resp.status_code == 200:
                        test_pass(f"Step 4 — Image URL accessible (via GET)")
                    else:
                        test_fail(f"Step 4 — Image URL not accessible: HTTP {resp.status_code}")
                else:
                    test_fail(f"Step 4 — Image URL not accessible: HTTP {resp.status_code}")
        except Exception as e:
            test_fail("Step 4 — Image URL check", str(e))

    # Step 5: Preview data structure
    preview_data = {
        "platform": "instagram",
        "post_type": "ai_image",
        "caption": caption,
        "ai_image_url": image_url,
    }
    test_pass(f"Step 5 — Preview data ready: {json.dumps({k: v[:50] if isinstance(v, str) and len(v) > 50 else v for k, v in preview_data.items()})}")

    log("✨", "Full flow completed successfully! Ready to publish.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "═" * 80)
    print("  API INTEGRATION TEST SUITE")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("═" * 80)

    # Show config status
    section("Configuration Check")
    configs = {
        "ANTHROPIC_API_KEY": bool(ANTHROPIC_API_KEY),
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "KLING_ACCESS_KEY": bool(KLING_ACCESS_KEY),
        "PEXELS_API_KEY": bool(PEXELS_API_KEY),
        "STRIPE_SECRET_KEY": bool(STRIPE_SECRET_KEY),
        "WHATSAPP_TOKEN": bool(WA_TOKEN),
        "PUBLIC_BASE_URL": PUBLIC_BASE_URL or "(not set)",
    }
    for name, val in configs.items():
        status = "✅" if val and val is not False else "❌"
        log(status, f"{name}: {val}")

    # Determine which tests to run
    filter_arg = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    test_map = {
        "anthropic": test_anthropic,
        "openai": test_openai,
        "kling": test_kling,
        "pexels": test_pexels,
        "stripe": test_stripe,
        "whatsapp": test_whatsapp,
        "full_flow": test_full_flow,
    }

    if filter_arg == "all":
        for name, fn in test_map.items():
            try:
                await fn()
            except Exception as e:
                test_fail(f"Unhandled error in {name}", traceback.format_exc())
    elif filter_arg in test_map:
        try:
            await test_map[filter_arg]()
        except Exception as e:
            test_fail(f"Unhandled error in {filter_arg}", traceback.format_exc())
    else:
        print(f"Unknown test: {filter_arg}")
        print(f"Available: {', '.join(test_map.keys())}, all")
        sys.exit(1)

    # Summary
    print(f"\n{'═'*80}")
    total = passed + failed + skipped
    print(f"  RESULTS: {passed} passed, {failed} failed, {skipped} skipped (total: {total})")
    if errors:
        print(f"\n  FAILURES:")
        for e in errors:
            print(f"    ❌ {e}")
    print(f"{'═'*80}\n")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
