# Production Setup Guide

This guide covers the three-step setup process for bringing your multi-platform automation bot to production:

1. **WhatsApp Business Setup** — Configure your business phone number and webhook
2. **Stripe Payment Setup** — Enable subscriptions and credit purchases
3. **Facebook/Instagram OAuth** — Let users connect their accounts to post

---

## **Overview: Customer Onboarding**

Your bot uses a **WhatsApp Business Number** that customers message directly. Here's the flow:

```
Customer messages +6580409026
     ↓
WhatsApp Cloud API sends webhook to your bot
     ↓
Bot receives message, processes command
     ↓
Bot responds via WhatsApp API
     ↓
Customer gets reply in WhatsApp
```

No test numbers needed for production. Customers simply save your business number and message it.

---

## **Setup Step 1: WhatsApp Business Account**

### Overview
You need a WhatsApp Business Account tied to a real phone number. Customers will save this number and message your bot.

### Process
1. **Go to Meta Business Manager** → https://business.facebook.com
2. **Create/Link WhatsApp Business Account**
   - Business Name: Your company name
   - Category: Software/App
3. **Verify Your Phone Number**
   - Add your business phone number (e.g., +6580409026)
   - Meta sends verification code (SMS/WhatsApp/call)
   - Enter code to verify
4. **Get IDs**
   - Copy Phone Number ID from account settings
   - Copy Business Account ID
   - (These are in your `.env` as `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_BUSINESS_ACCOUNT_ID`)
5. **Create System User for API Access**
   - Meta Business Manager → Users → System Users → Create
   - Generate access token with `whatsapp_business_messaging` permission
   - Copy token to `.env` as `WHATSAPP_TOKEN`
6. **Configure Meta Webhook**
   - Meta App Dashboard → WhatsApp → Configuration
   - **Callback URL**: `https://multiplatformautomation-production.up.railway.app/webhook`
   - **Verify Token**: (from `.env` `WHATSAPP_VERIFY_TOKEN`)
   - Subscribe to: `messages`, `message_echoes`, `message_template_status_update`
7. **Test Webhook**
   - Send message from your test number to your business number
   - Bot should respond automatically
   - Check Railway logs for incoming webhook

### Result
✓ Your WhatsApp business number is live
✓ Customers can find and message your number
✓ Webhook receives and responds to messages

---

## **Setup Step 2: Stripe Payment Configuration**

### Overview
Stripe handles all payment UI (checkout, customer portal, promo codes). Your bot only needs to:
1. Create checkout sessions (send customer to Stripe)
2. Receive webhook confirmation when payment succeeds
3. Grant credits to the user

### Process
1. **Verify Stripe Account** → https://dashboard.stripe.com
   - Copy Secret Key (starts with `sk_live_`)
   - Store in `.env` as `STRIPE_SECRET_KEY`
2. **Create/Verify Subscription Plans**
   - Stripe Dashboard → Products → Subscriptions
   - You should have: Starter ($5/mo), Pro ($15/mo), Business ($50/mo)
   - Copy each plan's Price ID (starts with `price_`)
   - Store in `.env` as `STRIPE_PRICE_ID_STARTER`, etc.
3. **Create/Verify Credit Packs**
   - Stripe Dashboard → Products → One-Time Purchases
   - You should have: 100, 500, 1500, 5000 credits
   - Copy each pack's Price ID
   - Store in `.env` as `STRIPE_PRICE_ID_PACK_100`, etc.
4. **Add Webhook Endpoint**
   - Stripe Dashboard → Developers → Webhooks
   - Add Endpoint: `https://multiplatformautomation-production.up.railway.app/stripe/webhook`
   - Subscribe to: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`
   - Copy Signing Secret (starts with `whsec_`)
   - Store in `.env` as `STRIPE_WEBHOOK_SECRET`
5. **Create Promo Codes (Optional)**
   - Stripe Dashboard → Products → Promotions
   - Create code: `CATALYX50` → 50 credits discount
   - (Your database already has `CATALYX50` and `ADMIN99`)
6. **Test Payment Flow**
   - Message bot: `/buy`
   - Click credit pack → Stripe checkout
   - Use test card: 4242 4242 4242 4242 | 12/25 | 123
   - After payment, check bot sends confirmation in WhatsApp
   - Check database: `SELECT credits_remaining FROM users;`

### Result
✓ Customers can purchase subscriptions/credits
✓ Payments are processed securely by Stripe
✓ Bot automatically grants credits on successful payment
✓ Customers see webhooks are confirmed (green checkmark in Stripe)

---

## **Setup Step 3: Facebook/Instagram OAuth**

### Overview
Users need to connect their Facebook/Instagram accounts so the bot can post on their behalf.

### Process
1. **Verify Meta App** → https://developers.facebook.com/apps/
   - Click your app
   - Settings → Basic → Copy App ID and App Secret
   - Store in `.env` as `FB_APP_ID` and `FB_APP_SECRET` ⚠️ **Keep secret private!**
2. **Configure OAuth Redirect**
   - Meta App → Settings → Basic
   - Add **App Domain**: `multiplatformautomation-production.up.railway.app`
   - Meta App → Products → Facebook Login → Settings
   - Add **Valid OAuth Redirect URI**: `https://multiplatformautomation-production.up.railway.app/auth/callback`
3. **Enable Required Products**
   - Meta App → Products
   - Add: **Facebook Login**
   - Add: **Facebook Graph API**
   - Add: **Instagram Graph API**
4. **Test OAuth Flow**
   - Message bot: `/setup`
   - Choose: Facebook or Instagram
   - Bot sends login link (directs to Meta)
   - You log in and approve permissions
   - Redirected to `/auth/callback` (bot stores token)
   - Check database: `SELECT * FROM platform_tokens;`
5. **Test Posting**
   - Message bot: `/post`
   - Choose platform (Facebook/Instagram)
   - Choose content type (photo/video/AI image)
   - Write caption
   - Confirm
   - Bot posts to your account ✓

### Result
✓ Users can authenticate their Facebook/Instagram accounts
✓ Bot can post on their behalf (requires `pages_manage_posts`, `instagram_content_publishing` permissions)
✓ Tokens are stored securely in PostgreSQL
✓ Tokens auto-refresh before expiration (60 days)

---

## **Customer Journey (End-to-End)**

```
1. Customer discovers your WhatsApp number (from marketing, QR code, etc.)
   ↓
2. Customer messages: /start
   ↓
3. Bot: "Welcome! Let's set up your profile" (onboarding)
   Customer: Answers industry, offerings, goals, tone, content style
   ↓
4. Bot: "Now connect your Facebook/Instagram" (/setup command)
   Customer: Clicks login link, approves permissions
   Bot: "Great! Now you can post"
   ↓
5. Customer: /post
   Bot: "What platform?" (Facebook/Instagram)
   Customer: Chooses platform
   Bot: "What type of content?" (Photo/Video/AI Image/Text)
   Customer: Chooses and uploads/generates content
   Bot: "Write a caption (or type 'ai' for auto-generate)"
   Customer: Writes caption
   Bot: "Preview: [image] [caption] [approve/edit/cancel]"
   Customer: Clicks approve
   Bot: Posts to customer's account ✓
   ↓
6. Customer: /subscribe (to get more features)
   Bot: "Choose plan" (Starter $5/mo, Pro $15/mo, Business $50/mo)
   Customer: Selects plan
   Bot: Sends Stripe checkout link
   Customer: Enters card (4242 4242 4242 4242 for test)
   Stripe: Processes payment
   Bot: "Subscription activated! You now have 500 credits/month"
   ↓
7. Customer uses features (posts, schedules, auto-replies, etc.)
   Bot: Deducts credits for each action
   Customer: /credits → "You have 475 credits remaining"
```

---

## **Environment Variables Checklist**

```bash
# WhatsApp (from Meta Business Manager)
WHATSAPP_PHONE_NUMBER_ID=         # From: Accounts → Phone Numbers
WHATSAPP_BUSINESS_ACCOUNT_ID=     # From: Account Settings
WHATSAPP_TOKEN=                   # From: System User → Generate Token
WHATSAPP_VERIFY_TOKEN=            # Any string (for webhook verification)
WHATSAPP_APP_SECRET=              # From: Meta App → Settings → Basic

# Stripe (from Stripe Dashboard)
STRIPE_SECRET_KEY=                # From: Developers → API Keys → Secret
STRIPE_WEBHOOK_SECRET=            # From: Developers → Webhooks → Signing Secret
STRIPE_PRICE_ID_STARTER=          # From: Products → Subscriptions → Price ID
STRIPE_PRICE_ID_PRO=              # From: Products → Subscriptions → Price ID
STRIPE_PRICE_ID_BUSINESS=         # From: Products → Subscriptions → Price ID
STRIPE_PRICE_ID_PACK_100=         # From: Products → One-Time → Price ID
STRIPE_PRICE_ID_PACK_500=         # From: Products → One-Time → Price ID
STRIPE_PRICE_ID_PACK_1500=        # From: Products → One-Time → Price ID
STRIPE_PRICE_ID_PACK_5000=        # From: Products → One-Time → Price ID

# Facebook/Instagram OAuth (from Meta App)
FB_APP_ID=                        # From: Settings → Basic → App ID
FB_APP_SECRET=                    # From: Settings → Basic → App Secret ⚠️ PRIVATE
OAUTH_REDIRECT_URI=               # https://[your_domain]/auth/callback

# Railway PostgreSQL
DATABASE_URL=                      # From: Railway → PostgreSQL → Connection String

# Other (already configured)
PUBLIC_BASE_URL=https://multiplatformautomation-production.up.railway.app
PAYMENT_SERVER_URL=https://multiplatformautomation-production.up.railway.app
```

---

## **Monitoring & Troubleshooting**

### Daily Checks
- **Railway Dashboard**: Check gateway and payment service logs for errors
- **Stripe Dashboard**: Check webhook success rate (should be 100%)
- **Meta Dashboard**: Check message quality/delivery rates

### Common Issues

**WhatsApp webhook not responding**
- Check Railway gateway is running: `curl https://[domain]/`
- Verify `WHATSAPP_VERIFY_TOKEN` matches Meta configuration
- Check logs for connection errors

**Payment not crediting**
- Check Stripe webhook endpoint shows green ✓ (event delivered)
- Check logs: `POST /stripe/webhook` returned 200
- Check database: `SELECT * FROM credit_ledger;` for transaction

**OAuth redirect loop**
- Verify `FB_APP_SECRET` is correct
- Verify `OAUTH_REDIRECT_URI` matches Meta App configuration
- Check logs for `OAuth error`

---

## **Next: Scale to 1000+ Users**

Once production is running:
1. **Monitor webhook latency** (should be <1s)
2. **Monitor database connections** (pool size is 10, max)
3. **Monitor Stripe rate limits** (very generous for your volume)
4. **Monitor costs**: Railway ($7/mo base), Stripe (2.9% + $0.30 per transaction)
5. **Plan infrastructure**: No scaling needed for 1000-10,000 users (single Railway app handles this easily)

---

**You're all set!** Customers can now:
- Message your WhatsApp number
- Create profiles via onboarding
- Connect Facebook/Instagram
- Post content (with AI generation if enabled)
- Subscribe for features
- Schedule posts, auto-reply, view analytics

Good luck! 🚀
