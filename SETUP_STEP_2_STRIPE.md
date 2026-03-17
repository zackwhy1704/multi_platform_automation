# Step 2: Stripe Payment Setup — Visual Guide

---

## **2.1 Open Stripe Dashboard**

**URL:** https://dashboard.stripe.com

**What you'll see:**
```
┌──────────────────────────────────────────┐
│  Stripe Dashboard                        │
├──────────────────────────────────────────┤
│                                          │
│  Left Sidebar:                           │
│  ├─ Home                                 │
│  ├─ Payments                             │
│  ├─ Billing                              │
│  ├─ Connect                              │
│  ├─ Developers ─────────────┐            │
│  │  ├─ API Keys            │ EXPAND      │
│  │  ├─ Webhooks            │            │
│  │  └─ Logs                │            │
│  └─                         │            │
│                             └→ Click     │
│                                          │
└──────────────────────────────────────────┘
```

**Step-by-step:**
1. Go to https://dashboard.stripe.com
2. Log in with your Stripe account
3. Make sure you're in **LIVE MODE** (top right toggle, not Test Mode)

---

## **2.2 Get Your API Secret Key**

**URL:** https://dashboard.stripe.com/apikeys

**You'll see:**
```
┌────────────────────────────────────────┐
│  API Keys                              │
├────────────────────────────────────────┤
│                                        │
│  Publishable Key:                      │
│  pk_live_5lIvCFuKu7mq2...   [Copy]    │
│                                        │
│  Secret Key:                           │
│  sk_live_51T0HnjGKa28ddRD...  [Copy]  │
│  ⚠️  Keep this secret! Never share     │
│                                        │
└────────────────────────────────────────┘
```

**Action:**
- Find the **Secret Key** (starts with `sk_live_`)
- Click **[Copy]** button
- Paste into `.env`:
  ```bash
  STRIPE_SECRET_KEY=sk_live_51T0HnjGKa28ddRD...
  ```

---

## **2.3 Check Your Subscription Plans**

**URL:** https://dashboard.stripe.com/products

**You'll see:**
```
┌─────────────────────────────────────────┐
│  Products                               │
├─────────────────────────────────────────┤
│                                         │
│  Filter: [All ▼] [Recurring ▼]         │
│                                         │
│  Products:                              │
│  ├─ Starter Plan        [Plan Details] │
│  │  Price: $5/month                    │
│  │  Price ID: price_1TBZ...            │
│  │                                     │
│  ├─ Pro Plan            [Plan Details] │
│  │  Price: $15/month                   │
│  │  Price ID: price_1TBZ...            │
│  │                                     │
│  └─ Business Plan       [Plan Details] │
│     Price: $50/month                   │
│     Price ID: price_1TBZ...            │
│                                         │
└─────────────────────────────────────────┘
```

**For each plan, click it and you'll see:**
```
┌──────────────────────────────────────┐
│  Starter Plan                        │
├──────────────────────────────────────┤
│                                      │
│  Description:                        │
│  100 credits per month               │
│                                      │
│  Pricing:                            │
│  Monthly: $5.00 USD                  │
│                                      │
│  Price ID:                           │
│  price_1TBZ2mGKa28ddRDdayjCWe95     │
│                          ↑           │
│                    Copy this!        │
│                                      │
└──────────────────────────────────────┘
```

**Action for each plan:**
- Click on the plan name
- Copy the **Price ID** (long string starting with `price_`)
- Update your `.env`:
  ```bash
  STRIPE_PRICE_ID_STARTER=price_1TBZ2mGKa28ddRDdayjCWe95
  STRIPE_PRICE_ID_PRO=price_1TBZ31GKa28ddRDdWTAt6Tgo
  STRIPE_PRICE_ID_BUSINESS=price_1TBZ6WGKa28ddRDdA5D5Dnij
  ```

---

## **2.4 Check Your Credit Packs (One-Time Purchases)**

**Same URL:** https://dashboard.stripe.com/products

**You'll see credit pack products:**
```
┌─────────────────────────────────────────┐
│  Products (Filter: One-Time ▼)          │
├─────────────────────────────────────────┤
│                                         │
│  ├─ 100 Credits          [Details]     │
│  │  Price: $5.00         price_1TBZ... │
│  │                                     │
│  ├─ 500 Credits          [Details]     │
│  │  Price: $20.00        price_1TBZ... │
│  │                                     │
│  ├─ 1500 Credits         [Details]     │
│  │  Price: $50.00        price_1TBZ... │
│  │                                     │
│  └─ 5000 Credits         [Details]     │
│     Price: $150.00       price_1TBZ... │
│                                         │
└─────────────────────────────────────────┘
```

**Action:**
- Click each product
- Copy the **Price ID**
- Update `.env`:
  ```bash
  STRIPE_PRICE_ID_PACK_100=price_1TBZ6wGKa28ddRDdAZSI7fjR
  STRIPE_PRICE_ID_PACK_500=price_1TBZ7XGKa28ddRDdzRXB8wzK
  STRIPE_PRICE_ID_PACK_1500=price_1TBZ8SGKa28ddRDdHHDVWRmm
  STRIPE_PRICE_ID_PACK_5000=price_1TBZ8nGKa28ddRDdgAgfDeaj
  ```

---

## **2.5 Set Up Webhook Endpoint**

**URL:** https://dashboard.stripe.com/webhooks

**You'll see:**
```
┌────────────────────────────────────────┐
│  Webhooks                              │
├────────────────────────────────────────┤
│                                        │
│  [+ Add Endpoint]  ← CLICK             │
│                                        │
│  Endpoints:                            │
│  (any existing webhooks)               │
│                                        │
└────────────────────────────────────────┘
```

**Click [+ Add Endpoint]:**
```
┌──────────────────────────────────────────┐
│  Add an Endpoint                         │
├──────────────────────────────────────────┤
│                                          │
│  Endpoint URL:                           │
│  ┌────────────────────────────────────┐  │
│  │https://multiplatformautomation-    │  │
│  │production.up.railway.app/stripe/   │  │
│  │webhook                             │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Description (optional):                 │
│  ┌────────────────────────────────────┐  │
│  │Multi-Platform Bot Payments         │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Select events to send:                  │
│  ☑ checkout.session.completed          │
│  ☑ customer.subscription.updated       │
│  ☑ customer.subscription.deleted       │
│  ☑ invoice.payment_failed              │
│  ☑ invoice.paid                        │
│                                          │
│  [Create Endpoint]                      │
│                                          │
└──────────────────────────────────────────┘
```

**Step-by-step:**
1. **Endpoint URL**: Paste:
   ```
   https://multiplatformautomation-production.up.railway.app/stripe/webhook
   ```
2. **Description**: `Multi-Platform Bot Payments` (optional)
3. **Events**: Check these boxes:
   - ✓ `checkout.session.completed`
   - ✓ `customer.subscription.updated`
   - ✓ `customer.subscription.deleted`
   - ✓ `invoice.payment_failed`
   - ✓ `invoice.paid`
4. Click **[Create Endpoint]**

---

## **2.6 Get Your Webhook Signing Secret**

**After creating endpoint, you'll see:**
```
┌──────────────────────────────────────────┐
│  Webhook Endpoint Created!               │
├──────────────────────────────────────────┤
│                                          │
│  Endpoint: ...stripe/webhook             │
│  Status: Active ✓                        │
│                                          │
│  Signing Secret:                         │
│  whsec_sYT9mIazfR9ztDrZFKvFP2SE...      │
│                                          │
│  ⚠️  This is secret! Keep it private     │
│      Never commit to git                 │
│                                          │
│  [Copy]  [Reveal] [Delete]              │
│                                          │
└──────────────────────────────────────────┘
```

**Action:**
- Click **[Copy]** or **[Reveal]** to see the full key
- Copy the **Signing Secret** (starts with `whsec_`)
- Paste into `.env`:
  ```bash
  STRIPE_WEBHOOK_SECRET=whsec_sYT9mIazfR9ztDrZFKvFP2SE...
  ```

---

## **2.7 Verify Webhook is Receiving Events**

**Stay on same page, scroll down:**
```
┌──────────────────────────────────────────┐
│  Endpoint Details                        │
├──────────────────────────────────────────┤
│                                          │
│  Events (last 24 hours):                 │
│                                          │
│  Event                   Time     Status │
│  checkout.session.completed  15:32  ✓   │
│  invoice.paid              15:31  ✓    │
│  customer.subscription...  15:30  ✓    │
│                                          │
│  (Each event shows response code)        │
│                                          │
│  Status: All webhooks successful ✓      │
│                                          │
└──────────────────────────────────────────┘
```

**What to look for:**
- Green ✓ checkmarks next to events = webhook delivered successfully
- If you see ✗ or red status = check Railway logs for errors

---

## **2.8 Test Payment Flow**

**In WhatsApp, send your bot:**
```
You:   /buy
       ↓
Bot:   "Choose credit pack:
        1️⃣  100 credits - $5
        2️⃣  500 credits - $20
        3️⃣  1500 credits - $50
        4️⃣  5000 credits - $150"
       ↓
You:   Click "100 credits"
       ↓
Bot:   [Stripe Checkout Link]
       https://checkout.stripe.com/pay/cs_...
       ↓
You:   Click link
       ↓
Stripe Checkout:
       ┌──────────────────────────────────┐
       │  Payment Details                 │
       ├──────────────────────────────────┤
       │                                  │
       │  100 Credits       $5.00         │
       │                                  │
       │  Email: you@example.com          │
       │  Card:  [4242424242424242      ] │
       │  Exp:   [12/25]  CVC: [123    ] │
       │                                  │
       │  [Pay Now]  [Cancel]             │
       │                                  │
       └──────────────────────────────────┘
       ↓
You:   Enter test card: 4242 4242 4242 4242
       Exp: 12/25 (any future date)
       CVC: 123
       Click [Pay Now]
       ↓
Stripe: "Payment successful!"
       Redirect to /payment/success
       ↓
Bot:    Sends WhatsApp confirmation:
        "✓ Payment received!
        Your credits: 100
        Enjoy! 🎉"
       ↓
Database: credit_ledger updated
```

**Verify in Railway:**
1. Go to https://railway.app
2. Click **payment** service
3. **Logs** tab
4. Look for:
   ```
   [INFO] Stripe event: checkout.session.completed
   [INFO] Granted 100 credits to user 6580409026
   ```

---

## **2.9 Create Promo Codes (Optional)**

**URL:** https://dashboard.stripe.com/coupons

**You'll see:**
```
┌──────────────────────────────────────────┐
│  Promotions → Coupons                    │
├──────────────────────────────────────────┤
│                                          │
│  [+ Create Coupon]  ← CLICK              │
│                                          │
│  Existing Coupons:                       │
│  (any you've created before)             │
│                                          │
└──────────────────────────────────────────┘
```

**Click [+ Create Coupon]:**
```
┌──────────────────────────────────────────┐
│  Create Coupon                           │
├──────────────────────────────────────────┤
│                                          │
│  Discount Type:                          │
│  ○ Percentage discount                   │
│  ● Fixed amount  ← SELECT                │
│                                          │
│  Amount:                                 │
│  [$5.00] [USD]                           │
│                                          │
│  Duration:                               │
│  ○ Repeating (limited time)              │
│  ● Forever                               │
│                                          │
│  Restrictions:                           │
│  ○ Apply to all products/prices          │
│  ● Applies to: [Select products ▼]      │
│                                          │
│  [Create Coupon]                         │
│                                          │
└──────────────────────────────────────────┘
```

**After coupon, create Promotion Code:**
```
┌──────────────────────────────────────────┐
│  Add Promotion Code                      │
├──────────────────────────────────────────┤
│                                          │
│  Promotion Code:                         │
│  [CATALYX50]                             │
│                                          │
│  Select Coupon: [Select ▼]              │
│  (select the coupon you just created)    │
│                                          │
│  Active: ☑                               │
│                                          │
│  Restrictions:                           │
│  Max redemptions: (leave blank)          │
│  Expiration: Never                       │
│                                          │
│  [Create]                                │
│                                          │
└──────────────────────────────────────────┘
```

---

## **2.10 Test Promo Code During Checkout**

**During Stripe Checkout:**
```
┌──────────────────────────────────────────┐
│  Payment Details                         │
├──────────────────────────────────────────┤
│                                          │
│  100 Credits          $5.00              │
│                                          │
│  [Promo Code ▼]  ← CLICK TO ENTER CODE  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │Enter promo code                    │  │
│  │[CATALYX50                        ] │  │
│  │                                    │  │
│  │Discount (−$5.00)    −$5.00        │  │
│  │Total                 $0.00         │  │
│  └────────────────────────────────────┘  │
│                                          │
│  [Pay Now]                               │
│                                          │
└──────────────────────────────────────────┘
```

---

## **Summary: Stripe Setup Complete**

| Step | What | URL | Status |
|------|------|-----|--------|
| 1 | Got API Secret Key | dashboard.stripe.com/apikeys | sk_live_... |
| 2 | Verified Subscription Plans | dashboard.stripe.com/products | 3 plans found |
| 3 | Verified Credit Packs | dashboard.stripe.com/products | 4 packs found |
| 4 | Created Webhook Endpoint | dashboard.stripe.com/webhooks | Active ✓ |
| 5 | Got Webhook Secret | Same page | whsec_... |
| 6 | Tested Payment Flow | WhatsApp → /buy | ✓ Payment succeeded |
| 7 | Verified Bot Credits | Database | Credits added |
| 8 | Created Promo Code | dashboard.stripe.com/coupons | CATALYX50 |
| 9 | Tested Promo Code | Stripe Checkout | Discount applied |

---

## **Your .env Should Now Have**

```bash
STRIPE_SECRET_KEY=sk_live_51T0HnjGKa28ddRD...
STRIPE_WEBHOOK_SECRET=whsec_sYT9mIazfR9ztDr...
STRIPE_PRICE_ID_STARTER=price_1TBZ2mGKa28ddRDdayjCWe95
STRIPE_PRICE_ID_PRO=price_1TBZ31GKa28ddRDdWTAt6Tgo
STRIPE_PRICE_ID_BUSINESS=price_1TBZ6WGKa28ddRDdA5D5Dnij
STRIPE_PRICE_ID_PACK_100=price_1TBZ6wGKa28ddRDdAZSI7fjR
STRIPE_PRICE_ID_PACK_500=price_1TBZ7XGKa28ddRDdzRXB8wzK
STRIPE_PRICE_ID_PACK_1500=price_1TBZ8SGKa28ddRDdHHDVWRmm
STRIPE_PRICE_ID_PACK_5000=price_1TBZ8nGKa28ddRDdgAgfDeaj
PAYMENT_SERVER_URL=https://multiplatformautomation-production.up.railway.app
```

✅ **Stripe setup complete!**

**Next:** [Step 3: Facebook/Instagram OAuth Setup](./SETUP_STEP_3_OAUTH.md)
