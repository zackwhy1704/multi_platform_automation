# Step 3: Facebook/Instagram OAuth Setup — Visual Guide

---

## **3.1 Open Meta App Dashboard**

**URL:** https://developers.facebook.com/apps/

**What you'll see:**
```
┌────────────────────────────────────────┐
│  Meta for Developers                   │
├────────────────────────────────────────┤
│                                        │
│  My Apps:                              │
│                                        │
│  ┌──────────────────────────────────┐  │
│  │ Your Meta App (WhatsApp)         │  │
│  │ ID: 1302403355286987             │  │
│  │ [Go to App Dashboard]  ← CLICK    │  │
│  └──────────────────────────────────┘  │
│                                        │
│  [+ Create App]                        │
│                                        │
└────────────────────────────────────────┘
```

**Step-by-step:**
1. Go to https://developers.facebook.com/apps/
2. Click your app (WhatsApp/Multi-Platform App)
3. You're now in the **App Dashboard**

---

## **3.2 Get Your App ID and Secret**

**Left sidebar → Settings → Basic**

**You'll see:**
```
┌────────────────────────────────────────┐
│  App Settings → Basic                  │
├────────────────────────────────────────┤
│                                        │
│  App Name: Your Meta App               │
│  App ID: 1302403355286987      [Copy] │
│              ↑                         │
│              Save this!                │
│                                        │
│  App Secret: ••••••••••••••••          │
│  [Show] [Reset] [Copy]  ← CLICK COPY  │
│              ↑                         │
│              Keep this secret!         │
│                                        │
│  App Domains:                          │
│  + multiplatformautomation...up.rail   │
│    way.app                             │
│                                        │
└────────────────────────────────────────┘
```

**Actions:**
1. Copy **App ID**:
   - Paste into `.env`:
     ```bash
     FB_APP_ID=1302403355286987
     ```
2. Copy **App Secret**:
   - Paste into `.env`:
     ```bash
     FB_APP_SECRET=54570218813b70985fbdfed4469598c9
     ```
   - ⚠️ **NEVER commit this to git!**

---

## **3.3 Verify App Domain**

**Same Settings → Basic page, scroll down:**

```
┌────────────────────────────────────────┐
│  App Domains                           │
├────────────────────────────────────────┤
│  + multiplatformautomation-production  │
│    .up.railway.app                     │
│                                        │
│  Privacy Policy URL (optional):        │
│  [________________________________________]│
│                                        │
│  User Data Deletion:                   │
│  (configure if needed)                 │
│                                        │
│  [Save Changes]                        │
│                                        │
└────────────────────────────────────────┘
```

**Check:**
- ✓ `multiplatformautomation-production.up.railway.app` is listed

**If not listed:**
- Click **[+ Add Domain]**
- Paste: `multiplatformautomation-production.up.railway.app`
- Click **[Save Changes]**

---

## **3.4 Add Facebook Login Product**

**Left sidebar → Products:**

```
┌────────────────────────────────────────┐
│  Products                              │
├────────────────────────────────────────┤
│                                        │
│  [+ Add Product]  ← CLICK              │
│                                        │
│  Current Products:                     │
│  ✓ WhatsApp Business Platform          │
│  ✓ Webhooks                            │
│  (others...)                           │
│                                        │
└────────────────────────────────────────┘
```

**Click [+ Add Product]:**

```
┌────────────────────────────────────────┐
│  Add a Product                         │
├────────────────────────────────────────┤
│                                        │
│  Search: [Facebook Login           ]   │
│         ↓                              │
│  ┌──────────────────────────────────┐  │
│  │ Facebook Login                   │  │
│  │ Enable secure, reliable login    │  │
│  │                                  │  │
│  │        [Set Up]  ← CLICK         │  │
│  └──────────────────────────────────┘  │
│                                        │
└────────────────────────────────────────┘
```

**Step-by-step:**
1. Type: `Facebook Login`
2. Click the **Facebook Login** card
3. Click **[Set Up]**

**You'll see:**
```
┌────────────────────────────────────────┐
│  Facebook Login Setup                  │
├────────────────────────────────────────┤
│                                        │
│  ✓ Set Up Facebook Login               │
│  ✓ Configure Redirect URIs             │
│  ✓ Request Permissions                 │
│  ✓ Submit for Review (optional)        │
│                                        │
│  Status: Ready to use ✓                │
│                                        │
│  [Next]  [Skip]                        │
│                                        │
└────────────────────────────────────────┘
```

Click **[Skip]** (we'll configure manually below)

---

## **3.5 Configure OAuth Redirect URI**

**URL:** https://developers.facebook.com/apps/[APP_ID]/fb-login/settings/

**Or navigate:**
- Left sidebar → **Products** → **Facebook Login** → **Settings**

**You'll see:**
```
┌────────────────────────────────────────┐
│  Facebook Login Settings               │
├────────────────────────────────────────┤
│                                        │
│  App Type: Business                    │
│  Display Name: Facebook Login          │
│                                        │
│  Valid OAuth Redirect URIs:            │
│  ┌────────────────────────────────────┐│
│  │ https://multiplatformautomation-  ││
│  │ production.up.railway.app/auth/   ││
│  │ callback                           ││
│  └────────────────────────────────────┘│
│                                        │
│  [+ Add URI]  [Remove]                 │
│                                        │
│  Enforce HTTPS: ☑                      │
│                                        │
│  [Save Changes]                        │
│                                        │
└────────────────────────────────────────┘
```

**If the redirect URI isn't there:**
1. Click **[+ Add URI]**
2. Paste:
   ```
   https://multiplatformautomation-production.up.railway.app/auth/callback
   ```
3. Click **[Save Changes]**

---

## **3.6 Add Instagram Graph API Product**

**Left sidebar → Products → [+ Add Product]:**

```
┌────────────────────────────────────────┐
│  Add a Product                         │
├────────────────────────────────────────┤
│                                        │
│  Search: [Instagram Graph API      ]   │
│         ↓                              │
│  ┌──────────────────────────────────┐  │
│  │ Instagram Graph API              │  │
│  │ Access Instagram's data via API  │  │
│  │                                  │  │
│  │        [Set Up]  ← CLICK         │  │
│  └──────────────────────────────────┘  │
│                                        │
└────────────────────────────────────────┘
```

**Step-by-step:**
1. Type: `Instagram Graph API`
2. Click the product card
3. Click **[Set Up]**

**Result:**
```
✓ Instagram Graph API added to your app
```

---

## **3.7 Add Facebook Graph API Product**

**Left sidebar → Products → [+ Add Product]:**

```
┌────────────────────────────────────────┐
│  Add a Product                         │
├────────────────────────────────────────┤
│                                        │
│  Search: [Facebook Graph API       ]   │
│         ↓                              │
│  ┌──────────────────────────────────┐  │
│  │ Facebook Graph API               │  │
│  │ Post to pages, read comments     │  │
│  │                                  │  │
│  │        [Set Up]  ← CLICK         │  │
│  └──────────────────────────────────┘  │
│                                        │
└────────────────────────────────────────┘
```

**Step-by-step:**
1. Type: `Facebook Graph API`
2. Click the product card
3. Click **[Set Up]**

**Result:**
```
✓ Facebook Graph API added to your app
```

---

## **3.8 Test OAuth Flow in WhatsApp**

**In your WhatsApp bot, send:**
```
You:   /setup
       ↓
Bot:   "Choose platform to connect:
        1️⃣  Facebook (for business pages)
        2️⃣  Instagram (for business profiles)"
       ↓
You:   Click "1️⃣  Facebook"
       ↓
Bot:   [Facebook Login Link]
       https://www.facebook.com/v18.0/dialog/oauth?
       client_id=1302403355286987
       &redirect_uri=https://...railway.app/auth/callback
       &scope=pages_manage_posts,pages_read_engagement,...
       ↓
You:   Click link
       ↓
Facebook Login Page:
       ┌──────────────────────────────────┐
       │  Your Meta App wants to...       │
       ├──────────────────────────────────┤
       │                                  │
       │  Log in as: Your Name            │
       │  [Not you? Change account]       │
       │                                  │
       │  This app wants access to:       │
       │  ☑ Manage your posts             │
       │  ☑ Read post comments            │
       │  ☑ Instagram Basic               │
       │  ☑ Instagram Publishing          │
       │                                  │
       │  [Continue]  [Not Now]           │
       │                                  │
       └──────────────────────────────────┘
       ↓
You:   Click [Continue]
       ↓
Facebook/Instagram Permissions:
       May ask to:
       - Select which pages/accounts
       - Confirm business account (for Instagram)
       ↓
You:   Approve all permissions
       ↓
Redirect:
       https://...railway.app/auth/callback?code=...&state=...
       ↓
Bot:   Exchanges code for access token
       Stores token in database
       ↓
Bot Sends WhatsApp:
       "✓ Facebook connected!
        You can now post to your page.
        Send /post to create content!"
```

---

## **3.9 Verify Token Stored**

**Check your database:**

**SQL Query (via Railway PostgreSQL):**
```sql
SELECT * FROM platform_tokens
WHERE phone_number_id = '[YOUR_NUMBER]'
AND platform = 'facebook';
```

**You should see:**
```
phone_number_id | platform | access_token | page_id | page_name | account_username | token_expires | created_at
6580409026      | facebook | EAAJ5ksaW... | 987654  | My Page   | (null)           | 2026-05-17    | 2026-03-17
```

**Meaning:**
- ✓ Access token stored (long string)
- ✓ Page ID captured
- ✓ Page name stored
- ✓ Token expires in 60 days

---

## **3.10 Test Posting to Facebook**

**In WhatsApp, send:**
```
You:   /post
       ↓
Bot:   "Choose platform:
        1️⃣  Facebook
        2️⃣  Instagram"
       ↓
You:   Click "1️⃣  Facebook"
       ↓
Bot:   "What would you like to post?
        1️⃣  My photo/video
        2️⃣  AI-generated image
        3️⃣  Stock image
        4️⃣  Text only"
       ↓
You:   Click "1️⃣  My photo/video"
       ↓
Bot:   "Send your photo or video"
       ↓
You:   Send a photo/video (or use an emoji)
       ↓
Bot:   "Write a caption (or type 'ai' for auto-generate)"
       ↓
You:   Type: "Check out this amazing content! 🚀"
       ↓
Bot:   "Preview:
        [Image]
        Caption: Check out this amazing content! 🚀

        [Approve] [Edit] [Cancel]"
       ↓
You:   Click [Approve]
       ↓
Bot:   Calls Facebook Graph API
       POST /me/feed?message=...&picture=...
       ↓
Facebook: Returns post ID
       ↓
Bot Sends WhatsApp:
       "✓ Posted to Facebook!
        Post ID: 123456789
        Credits remaining: 475"
       ↓
Your Facebook Page:
       [Image] Check out this amazing content! 🚀
       Posted 1 minute ago
```

---

## **3.11 Verify Post in Facebook**

**Check your Facebook page:**
1. Go to https://facebook.com → Your Page
2. Look for your new post (should be at top)
3. Verify image and caption are correct

**Check Railway logs:**
1. https://railway.app → gateway service → **Logs**
2. Look for:
   ```
   [INFO] Posted to facebook
   [INFO] Graph API returned post_id: 123456789
   ```

---

## **3.12 Test Instagram (Same Flow)**

**In WhatsApp, send:**
```
You:   /setup
       ↓
Bot:   "Choose platform:
        1️⃣  Facebook
        2️⃣  Instagram"
       ↓
You:   Click "2️⃣  Instagram"
       ↓
Instagram Login:
       ┌──────────────────────────────────┐
       │  Login to Instagram              │
       ├──────────────────────────────────┤
       │                                  │
       │  Username/Email: [____________] │
       │  Password:       [____________] │
       │                                  │
       │  [Log In]  [Cancel]              │
       │                                  │
       └──────────────────────────────────┘
       ↓
Instagram Permissions:
       "Your Meta App wants access to:
        - Post to your Instagram account
        - Read your comments
        [Continue]"
       ↓
Bot Stores Token
       ↓
Bot WhatsApp:
       "✓ Instagram connected!
        Make sure your account is a Business Account.
        Send /post to start!"
```

**Important:**
- ⚠️ Instagram requires **Business Account** (not Personal)
- If Personal: Settings → Professional Dashboard → Switch to Business
- Then re-authenticate

---

## **3.13 Monitor Active Connections**

**Check how many users have connected:**

**SQL Query:**
```sql
SELECT
  COUNT(DISTINCT phone_number_id) as total_users,
  SUM(CASE WHEN platform='facebook' THEN 1 ELSE 0 END) as fb_connected,
  SUM(CASE WHEN platform='instagram' THEN 1 ELSE 0 END) as ig_connected
FROM platform_tokens;
```

**Example result:**
```
total_users | fb_connected | ig_connected
5           | 3            | 4
```

Means: 5 users total, 3 with Facebook, 4 with Instagram

---

## **Summary: OAuth Setup Complete**

| Step | What | URL | Status |
|------|------|-----|--------|
| 1 | Got App ID & Secret | developers.facebook.com/apps | 1302403355286987 |
| 2 | Verified App Domain | Settings → Basic | ✓ Railway domain |
| 3 | Added Facebook Login | Products → [+ Add] | ✓ Configured |
| 4 | Set OAuth Redirect | FB Login → Settings | /auth/callback ✓ |
| 5 | Added Instagram API | Products → [+ Add] | ✓ Added |
| 6 | Added Facebook API | Products → [+ Add] | ✓ Added |
| 7 | Tested OAuth Flow | WhatsApp /setup | ✓ Token stored |
| 8 | Tested Posting | WhatsApp /post | ✓ Posted to page |
| 9 | Verified Post | Facebook page | ✓ Post visible |
| 10 | Tested Instagram | WhatsApp /setup | ✓ Connected |

---

## **Your .env Should Now Have**

```bash
FB_APP_ID=1302403355286987
FB_APP_SECRET=54570218813b70985fbdfed4469598c9
OAUTH_REDIRECT_URI=https://multiplatformautomation-production.up.railway.app/auth/callback
```

✅ **OAuth setup complete!**

---

## **All Done! 🎉**

Your bot is now fully configured:

```
✓ Step 1: WhatsApp Business Setup
  - Customers message: +6580409026
  - Bot receives and responds

✓ Step 2: Stripe Payment
  - /subscribe → Stripe checkout → Payment processed
  - /buy credits → Credit pack → Automatically granted

✓ Step 3: OAuth
  - /setup → User logs in → Bot can post
  - /post → Create content → Publish to Facebook/Instagram

Your bot is LIVE and READY for customers! 🚀
```

---

## **Next Steps**

1. Share your WhatsApp business number with customers
2. Monitor logs for errors (https://railway.app)
3. Monitor Stripe for payment issues
4. Track user growth in database
5. Scale as needed (no infrastructure changes needed for 10,000+ users)

**Enjoy!** 🎊
