# Production Deployment Checklist

## Pre-Deployment (DO THIS FIRST)

- [x] Docker Desktop installed and running
- [ ] All `.env` variables filled in correctly
- [ ] `PAYMENT_SERVER_URL` set to your public domain (NOT localhost)
- [ ] `CELERY_ALWAYS_EAGER=false` (for async workers)
- [ ] `STRIPE_SECRET_KEY` is production key (sk_live_...)
- [ ] `STRIPE_WEBHOOK_SECRET` matches Stripe Dashboard (whsec_...)
- [ ] `ANTHROPIC_API_KEY` set
- [ ] `OPENAI_API_KEY` set
- [ ] `KLING_ACCESS_KEY` and `KLING_SECRET_KEY` set
- [ ] `FB_APP_ID` and `FB_APP_SECRET` set
- [ ] `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` set

## Infrastructure Setup

- [ ] Run `docker compose up -d --build` (takes 2-3 min on first run)
- [ ] Run `docker compose ps` and verify all services are healthy
- [ ] Wait for database to be healthy: `docker compose logs db | grep "ready to accept"`
- [ ] Start ngrok tunnel: `ngrok http 80 --domain=charity-unappointed-fred.ngrok-free.dev`
- [ ] Verify ngrok is running: should show green "Online"

## Stripe Configuration

- [ ] Go to https://dashboard.stripe.com/webhooks
- [ ] Verify webhook endpoint URL: `https://charity-unappointed-fred.ngrok-free.dev/stripe/webhook`
- [ ] Check recent events tab — should show "Test Webhook" with status 200 OK
- [ ] Verify events enabled:
  - [x] `checkout.session.completed` (subscriptions + credit packs)
  - [x] `customer.subscription.updated` (renewals + cancellations)
  - [x] `customer.subscription.deleted` (cancellation)
  - [x] `invoice.paid` (monthly renewal)
  - [x] `invoice.payment_failed` (payment retry)

## WhatsApp Cloud API Setup

- [ ] Go to https://developers.facebook.com/ → Your App → WhatsApp → API Setup
- [ ] Verify webhook URL: `https://charity-unappointed-fred.ngrok-free.dev/webhook`
- [ ] Verify verify token matches `WHATSAPP_VERIFY_TOKEN` in `.env`
- [ ] Enable webhook fields:
  - [x] `messages` (incoming messages)
  - [x] `message_status` (delivery status)

## Facebook OAuth Setup

- [ ] Go to https://developers.facebook.com/ → Your App → Settings → Basic
- [ ] Verify `FB_APP_ID` and `FB_APP_SECRET` match `.env`
- [ ] Go to Products → Facebook Login → Settings
- [ ] In "Redirect URI Whitelist" add: `https://your-domain/auth/callback`
- [ ] Verify Instagram Graph API is enabled in app

## Production Testing

### Test WhatsApp Connection
```bash
# Send a test message to your WhatsApp number
# Bot should:
# 1. Receive message
# 2. Mark as read
# 3. Send help menu
# 4. Appear in logs: docker compose logs -f gateway
```

### Test Payment Flow (Stripe Test Mode)
1. In Stripe Dashboard, switch to **Test mode**
2. Use test card: `4242 4242 4242 4242` (any expiry, any CVC)
3. Send `*subscribe` to WhatsApp
4. Click "Starter" plan
5. Go to Stripe checkout, enter test card
6. After payment:
   - [ ] Success page loads
   - [ ] User gets WhatsApp notification: "Your subscription is ACTIVE"
   - [ ] User can send `*credits` and see balance: 500
   - [ ] Check Stripe Dashboard → Customers → user appears with subscription
   - [ ] Check `docker compose logs payment` for webhook event

### Test Credit Pack Purchase
1. Send `*buy` to WhatsApp
2. Select "100 credits" pack
3. Complete payment with test card
4. After payment:
   - [ ] Success page loads
   - [ ] User gets WhatsApp notification: "100 credits added"
   - [ ] User balance increases by 100

### Test Subscription Cancellation
1. Send `*cancel` to WhatsApp
2. User gets Stripe Customer Portal link
3. Click "Cancel plan"
4. After cancellation:
   - [ ] User gets WhatsApp: "Subscription Cancelled... Access continues until [date]"
   - [ ] Stripe shows subscription status: `active` → `cancel_at_period_end`
   - [ ] After period end, status becomes `cancelled`

### Test OAuth/Platform Setup
1. Send `*setup` to WhatsApp
2. Choose Facebook or Instagram
3. Complete OAuth flow
4. Should return to WhatsApp with confirmation

### Test Content Creation
1. Send `*post` to WhatsApp
2. Go through posting flow
3. Post to Facebook/Instagram
4. Verify post appears on platform
5. Check `docker compose logs worker-facebook` for task execution

### Test AI Features
1. Send `*auto` and complete auto-post setup
2. Choose AI-generated images
3. Posts should have AI captions + generated images
4. Check `docker compose logs -f gateway` for Claude API calls

## Monitoring & Maintenance

### Health Checks
```bash
# Check all services
docker compose ps

# Check logs
docker compose logs -f gateway
docker compose logs -f payment
docker compose logs -f worker-notifications

# Check database
docker compose exec db psql -U postgres -d multi_platform_bot -c "SELECT COUNT(*) FROM users;"
```

### Backup Database
```bash
docker compose exec db pg_dump -U postgres -d multi_platform_bot > backup.sql
```

### Database Access
```bash
docker compose exec db psql -U postgres -d multi_platform_bot
```

### Redis Cache (if needed)
```bash
docker compose exec redis redis-cli PING
```

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "Payment redirects to localhost:5000" | Update `PAYMENT_SERVER_URL` in `.env` → `docker compose restart gateway` |
| "Tasks run synchronously, no workers active" | Set `CELERY_ALWAYS_EAGER=false` in `.env` → `docker compose restart` |
| "Stripe webhook not receiving events" | Check ngrok is running, verify URL in dashboard, check `docker compose logs payment` |
| "WhatsApp webhook not receiving messages" | Verify URL in Meta dashboard matches ngrok, verify verify token matches `.env` |
| "Media files lost after restart" | Use `docker compose down` (not `docker compose kill`) to preserve volumes |
| "Database connection refused" | Check `docker compose logs db` for startup errors, verify db is healthy |

## Rollback Procedure

If something breaks:

```bash
# Stop services but keep data
docker compose down

# View logs to diagnose
docker compose logs --tail=100

# Restart
docker compose up -d
```

Or rollback git:
```bash
git log --oneline
git revert <commit-hash>
git push
```

## Post-Deployment

- [ ] Enable Stripe production mode (not test mode)
- [ ] Monitor for errors: `docker compose logs -f`
- [ ] Test full payment flow with real card (small amount)
- [ ] Set up log aggregation (optional: ELK, DataDog, etc.)
- [ ] Set up alerts for Stripe payment failures
- [ ] Document any custom configuration changes
- [ ] Share deployment runbook with team

## Support

See `PRODUCTION.md` for detailed architecture and troubleshooting guide.

Questions? Check logs:
```bash
docker compose logs -f [service-name]
```
