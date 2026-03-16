# Production Deployment Guide

## Prerequisites
- Docker Desktop installed and running
- All `.env` variables configured (see `.env` file)
- Stripe webhook URL configured: `https://your-domain/stripe/webhook`
- ngrok account with fixed domain or CLI installed

## Architecture

```
Internet → ngrok (HTTPS) → Caddy (HTTP) → Gateway + Payment + Workers
                                ↓
                        PostgreSQL + Redis
```

## Services

| Service | Port | Purpose |
|---------|------|---------|
| **gateway** | 8000 | WhatsApp webhook receiver + message router |
| **payment** | 5000 | Stripe payment webhooks + checkout redirects |
| **caddy** | 80 | Reverse proxy (HTTP-only, ngrok terminates TLS) |
| **db** | 5432 | PostgreSQL database |
| **redis** | 6379 | Celery message broker |
| **worker-facebook** | - | Facebook/Instagram posting tasks |
| **worker-instagram** | - | Instagram-specific tasks |
| **worker-notifications** | - | WhatsApp notification sending |

## Environment Variables

All critical variables are in `.env`:

```bash
# Payment flow
PAYMENT_SERVER_URL=https://your-domain.com
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# WhatsApp
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_VERIFY_TOKEN=...

# AI Services
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
KLING_ACCESS_KEY=...
KLING_SECRET_KEY=...

# Platforms
FB_APP_ID=...
FB_APP_SECRET=...

# Celery (MUST be false in production)
CELERY_ALWAYS_EAGER=false
```

## Deployment

### 1. Start Docker Services

```bash
cd ~/multi_platform_automation
docker compose up -d --build
```

**Verify all services are healthy:**
```bash
docker compose ps
```

Expected output:
```
NAME                    STATUS
db                      healthy
redis                   healthy
gateway                 running
payment                 running
caddy                   running
worker-facebook         running
worker-instagram        running
worker-notifications    running
```

### 2. Start ngrok Tunnel

In a new terminal:
```bash
ngrok http 80 --domain=charity-unappointed-fred.ngrok-free.dev
```

This tunnel maps:
- `https://charity-unappointed-fred.ngrok-free.dev` → localhost:80 (Caddy)
- Caddy routes to internal services (gateway:8000, payment:5000, etc.)

### 3. Verify Setup

Check Stripe webhook endpoint:
- Go to https://dashboard.stripe.com/webhooks
- Verify endpoint URL is: `https://your-domain/stripe/webhook`
- Check that events are being received

Check WhatsApp webhook:
- Go to https://developers.facebook.com/
- Select your app → WhatsApp → API Setup
- Verify webhook URL is: `https://your-domain/webhook`
- Verify verify token matches `WHATSAPP_VERIFY_TOKEN` in `.env`

## Monitoring

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f gateway
docker compose logs -f payment
docker compose logs -f worker-notifications
```

### Health Checks

```bash
# Gateway health
curl https://your-domain/health/gateway

# Payment health
curl https://your-domain/health/payment
```

## Production Features

✅ **Payments:**
- Stripe subscriptions (Starter/Pro/Business)
- One-time credit packs (100/500/1500/5000)
- Automatic credit reset on monthly renewal
- Promo code support (Stripe + in-app)
- Adaptive pricing (USD → SGD/MYR auto-conversion)

✅ **User Management:**
- Freemium model (30 free credits on signup)
- Referral system (50 credits per referral)
- Subscription management via Stripe Customer Portal

✅ **Content Automation:**
- Facebook + Instagram posting (Graph API)
- AI-powered captions (Claude)
- AI-generated images (OpenAI gpt-image-1)
- AI-generated videos (Kling AI)
- Stock images (Pexels)
- Comment auto-reply

✅ **Infrastructure:**
- PostgreSQL database with persistent storage
- Redis for task queue (Celery)
- Async workers for posting + notifications
- Persistent media storage (volume mount)
- Automatic service restart on failure

## Troubleshooting

### "Payment redirects to localhost"
❌ **Problem:** `PAYMENT_SERVER_URL=http://localhost:5000`
✅ **Solution:** Update to `PAYMENT_SERVER_URL=https://your-domain.com` in `.env`, then `docker compose restart gateway`

### "Tasks not running (always synchronous)"
❌ **Problem:** `CELERY_ALWAYS_EAGER=true`
✅ **Solution:** Set to `CELERY_ALWAYS_EAGER=false` in `.env`, then `docker compose restart` workers

### "Webhook events not received"
✅ **Check:** Stripe Dashboard → Webhooks → click endpoint → view recent events
✅ **Check:** Is ngrok tunnel running?
✅ **Check:** Does Stripe URL match `https://your-domain/stripe/webhook`?

### "Media files lost after restart"
✅ **Status:** Fixed! Media volume persists across restarts
✅ **Location:** `media_data` Docker volume (mounted at `/app/media_files` in gateway)

### "Can't reach payment server from gateway"
✅ **Why:** Docker internal networking
✅ **Status:** Caddy routes `/payment/*` and `/stripe/webhook` to `payment:5000` automatically
✅ **Verify:** `docker compose exec gateway curl http://payment:5000/health`

## Cleanup

Stop all services:
```bash
docker compose down
```

Remove all data:
```bash
docker compose down -v
```

## Notes

- Database migrations run automatically when db container starts
- First request to each service may be slow (Python startup)
- WhatsApp messages are processed asynchronously via Celery workers
- Media files are stored in Docker volume (not ephemeral)
- All timestamps are in UTC (see code: `timezone = "UTC"` in celery_app.py)
