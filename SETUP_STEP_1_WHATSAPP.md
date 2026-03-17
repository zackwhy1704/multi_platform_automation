# Step 1: WhatsApp Business Setup — Visual Guide

---

## **1.1 Open Meta Business Manager**

**URL:** https://business.facebook.com

**What you'll see:**
```
┌─────────────────────────────────────────────────────────┐
│  Meta Business Manager                          [👤]    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Left Sidebar:                                          │
│  ├─ Home                                                │
│  ├─ Accounts ──────────┐ ← CLICK HERE                   │
│  ├─ Catalogs          │                                 │
│  ├─ Audiences         │                                 │
│  └─ Integrations      │                                 │
│                       └─→ WhatsApp Accounts            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Step-by-step:**
1. Go to https://business.facebook.com
2. Log in with your Facebook account
3. Left sidebar → **Accounts** → **WhatsApp Accounts**

---

## **1.2 Create or Link WhatsApp Business Account**

**You should see:**
```
┌──────────────────────────────────────┐
│  WhatsApp Accounts                   │
├──────────────────────────────────────┤
│                                      │
│  [+ Create WhatsApp Business Acct]  │
│                                      │
│  OR                                  │
│                                      │
│  [Link Existing Account]             │
│                                      │
└──────────────────────────────────────┘
```

**If creating new:**
- Click **Create WhatsApp Business Account**
- Fill in:
  - **Business Name**: `Catalyx Bot` (or your name)
  - **Category**: Select "Software/App"
- Click **Create**

**If linking existing:**
- Click **Link Existing Account**
- Select your WhatsApp Business Account from dropdown

---

## **1.3 Verify Your Phone Number**

**URL:** https://business.facebook.com/wa/manage/

**After account is created, you'll see:**
```
┌──────────────────────────────────────────────┐
│  Catalyx Bot (WhatsApp Business Account)    │
├──────────────────────────────────────────────┤
│                                              │
│  Account Settings                            │
│  ├─ Phone Numbers ←─────────────┐           │
│  ├─ Quality                      │ CLICK     │
│  └─ Settings                     │           │
│                                  │           │
│  [+ Add Phone Number] ←──────────┘           │
│                                              │
└──────────────────────────────────────────────┘
```

**Step-by-step:**
1. Click **Phone Numbers** in left sidebar
2. Click **[+ Add Phone Number]**
3. Enter your phone number in format: **+6580409026**
   ```
   Country Code: +65
   Area Code: (blank if none)
   Phone Number: 80409026
   ```
4. Click **Next**

---

## **1.4 Verify Code**

**Meta will send verification code via:**
- SMS
- Phone call
- WhatsApp message

**You'll see:**
```
┌──────────────────────────────────┐
│  Verify Your Phone Number        │
├──────────────────────────────────┤
│                                  │
│  We sent a code to +6580409026  │
│                                  │
│  How did you want to receive it? │
│  ○ SMS                           │
│  ○ Phone Call                    │
│  ○ WhatsApp                      │
│                                  │
│  [Enter Code Here]               │
│  [Verify]                        │
│                                  │
└──────────────────────────────────┘
```

**Step-by-step:**
1. Choose how to receive code (SMS is fastest)
2. Check your phone for the 6-digit code
3. Enter code in the field
4. Click **Verify**

**Status should now show:** ✓ **Verified**

---

## **1.5 Get Your Phone Number ID**

**Back in the same Phone Numbers section, you'll see:**
```
┌────────────────────────────────────────────┐
│  Phone Numbers                             │
├────────────────────────────────────────────┤
│                                            │
│  +6580409026                              │
│  ├─ Phone Number ID: 953624217844398 ←┐   │
│  ├─ Status: Verified ✓                  │ COPY THIS
│  ├─ Quality: HIGH                       │
│  └─ [Manage]                            │
│                                            │
└────────────────────────────────────────────┘
```

**Action:**
- Look for **Phone Number ID** (long number like `953624217844398`)
- Click copy icon or select and copy
- Paste into your `.env` file:
  ```bash
  WHATSAPP_PHONE_NUMBER_ID=953624217844398
  ```

---

## **1.6 Get Your Business Account ID**

**URL:** https://business.facebook.com/settings/

**Navigate to:**
```
┌──────────────────────────────────────────┐
│  Business Settings                       │
├──────────────────────────────────────────┤
│                                          │
│  Left Sidebar:                           │
│  ├─ Business Info                        │
│  ├─ Brand Safety                         │
│  ├─ Security                             │
│  └─ Account Info ←────────────── CLICK   │
│                                          │
└──────────────────────────────────────────┘
```

**You'll see:**
```
┌─────────────────────────────────────┐
│  Account Information                │
├─────────────────────────────────────┤
│                                     │
│  Business Name: Catalyx Bot         │
│  Business ID: 1254604036115997 ←┐   │
│  Time Zone: Asia/Singapore          │ COPY THIS
│  Currency: SGD                      │
│                                     │
└─────────────────────────────────────┘
```

**Action:**
- Copy **Business ID**
- Paste into `.env`:
  ```bash
  WHATSAPP_BUSINESS_ACCOUNT_ID=1254604036115997
  ```

---

## **1.7 Create System User for API Access**

**URL:** https://business.facebook.com/settings/system-users/

**You'll see:**
```
┌──────────────────────────────────────┐
│  System Users                        │
├──────────────────────────────────────┤
│                                      │
│  [+ Create System User]  ← CLICK     │
│                                      │
│  Existing Users:                     │
│  (if any)                            │
│                                      │
└──────────────────────────────────────┘
```

**Step-by-step:**
1. Click **[+ Create System User]**
2. Fill in:
   - **Name**: `WhatsApp Bot API`
   - **Role**: Select **Admin**
3. Click **Create System User**

**Result:**
```
┌──────────────────────────────────────┐
│  System User Created!                │
├──────────────────────────────────────┤
│                                      │
│  Name: WhatsApp Bot API              │
│  ID: 11234567890123456               │
│  Role: Admin                         │
│                                      │
│  [Generate Tokens]  ← CLICK NEXT     │
│  [Manage Assets]                     │
│  [Delete User]                       │
│                                      │
└──────────────────────────────────────┘
```

---

## **1.8 Generate Access Token**

**Click** **[Generate Tokens]** in the System User you just created

**You'll see:**
```
┌─────────────────────────────────────────┐
│  Generate Token                         │
├─────────────────────────────────────────┤
│                                         │
│  System User: WhatsApp Bot API          │
│                                         │
│  App: [Select Your App ▼]               │
│        ↓ Choose: "Your Meta App"        │
│                                         │
│  Permissions:                           │
│  ☑ whatsapp_business_messaging ✓       │
│  ☑ whatsapp_business_account_mgmt ✓    │
│  ☐ (other permissions)                  │
│                                         │
│  Token Expires: [Never ▼] or longest    │
│                                         │
│  [Generate Token]  ← CLICK              │
│                                         │
└─────────────────────────────────────────┘
```

**Step-by-step:**
1. **App dropdown**: Select your Meta app (WhatsApp/Multi-Platform App)
2. **Permissions**: Check these boxes:
   - ✓ `whatsapp_business_messaging`
   - ✓ `whatsapp_business_account_management`
3. **Token Expiration**: Select `Never` if available, otherwise longest option
4. Click **[Generate Token]**

**⚠️ IMPORTANT:**
```
┌────────────────────────────────────────┐
│  Your Token Has Been Generated!        │
├────────────────────────────────────────┤
│                                        │
│  EAASgh2lYncsBQZCum1DjFEVeYZAK...     │
│                                        │
│  ⚠️  Copy this now! You won't see it   │
│      again. Keep it private!           │
│                                        │
│  [Copy]  [Close]                      │
│                                        │
└────────────────────────────────────────┘
```

**Action:**
- Click **[Copy]** immediately
- Paste into `.env`:
  ```bash
  WHATSAPP_TOKEN=EAASgh2lYncsBQZCum1DjFEVeYZAK...
  ```

---

## **1.9 Configure Meta Webhook**

**URL:** https://developers.facebook.com/apps/

**Navigate to:**
```
┌────────────────────────────────────────┐
│  Meta App Dashboard                    │
├────────────────────────────────────────┤
│                                        │
│  Your Meta App (or create if needed)   │
│  ↓                                     │
│  Products (left sidebar)               │
│  ├─ Messenger                          │
│  ├─ WhatsApp ←─────────────── CLICK    │
│  └─ (other products)                   │
│                                        │
└────────────────────────────────────────┘
```

**Under WhatsApp, click:**
```
┌────────────────────────────────────────┐
│  WhatsApp                              │
├────────────────────────────────────────┤
│                                        │
│  Configuration  ←─────────────── CLICK │
│                                        │
│  Getting Started                       │
│  Settings                              │
│  API Reference                         │
│                                        │
└────────────────────────────────────────┘
```

---

## **1.10 Add Webhook Endpoint**

**In Configuration section, you'll see:**
```
┌──────────────────────────────────────────┐
│  Webhooks                                │
├──────────────────────────────────────────┤
│                                          │
│  Webhook URL:                            │
│  ┌────────────────────────────────────┐  │
│  │https://multiplatformautomation-    │  │
│  │production.up.railway.app/webhook   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Verify Token:                           │
│  ┌────────────────────────────────────┐  │
│  │catalyx_bot_2026                    │  │
│  └────────────────────────────────────┘  │
│                                          │
│  [Save]  [Edit]                         │
│                                          │
└──────────────────────────────────────────┘
```

**Step-by-step:**
1. **Callback URL field**: Paste:
   ```
   https://multiplatformautomation-production.up.railway.app/webhook
   ```
2. **Verify Token field**: Paste:
   ```
   catalyx_bot_2026
   ```
3. Click **[Save]** or **[Verify and Save]**

**Expected result:**
```
┌──────────────────────────────────────┐
│  ✓ Webhook Verified!                 │
├──────────────────────────────────────┤
│                                      │
│  Your webhook is responding and      │
│  valid. Ready to receive messages!   │
│                                      │
└──────────────────────────────────────┘
```

---

## **1.11 Subscribe to Webhook Events**

**Below Webhook URL/Token, you'll see:**
```
┌─────────────────────────────────────────┐
│  Subscribe to Webhook Fields            │
├─────────────────────────────────────────┤
│                                         │
│  ☑ messages ✓                          │
│  ☑ message_echoes ✓                    │
│  ☑ message_template_status_update ✓    │
│  ☑ message_template_quality_update     │
│  ☐ (other fields)                      │
│                                         │
│  [Save]                                │
│                                         │
└─────────────────────────────────────────┘
```

**Action:**
- Check these boxes:
  - ✓ `messages` (receive incoming messages)
  - ✓ `message_echoes` (confirm sent messages)
  - ✓ `message_template_status_update`
- Click **[Save]**

---

## **1.12 Test the Webhook**

**Send a test message:**

```
Your Phone → WhatsApp → Find your business number
                        ↓
                   Send: /start
                        ↓
Your Bot (Railway) ← Receives webhook
                   → Responds automatically
                        ↓
Your Phone → Receives bot response
```

**To verify:**
1. Save your WhatsApp business number in your phone
2. Message it: `/start`
3. You should get a bot response within 2 seconds
4. Check Railway logs: Go to https://railway.app → gateway service → **Logs**
   - Look for: `POST /webhook` with status 200

**Success looks like:**
```
[2026-03-17 15:30:45 INFO] gateway.app: Webhook received from 6580409026
[2026-03-17 15:30:45 INFO] gateway.router: User created: 6580409026
[2026-03-17 15:30:46 INFO] shared.database: Message stored
[2026-03-17 15:30:46 INFO] gateway.whatsapp_client: Sent response to 6580409026
```

---

## **Summary: What You've Done**

| Step | What | Where | Status |
|------|------|-------|--------|
| 1 | Created WhatsApp Business Account | Meta Business Manager | ✓ |
| 2 | Verified your phone number | Phone Numbers section | ✓ Verified |
| 3 | Got Phone Number ID | Platform Tokens | 953624217844398 |
| 4 | Got Business Account ID | Account Settings | 1254604036115997 |
| 5 | Created System User | System Users | WhatsApp Bot API |
| 6 | Generated Access Token | System User Tokens | EAASgh2... (in .env) |
| 7 | Configured Webhook URL | Meta App → WhatsApp | https://railway.app/webhook |
| 8 | Set Verify Token | Meta App → WhatsApp | catalyx_bot_2026 |
| 9 | Subscribed to Events | Meta App → WhatsApp | messages, message_echoes, etc. |
| 10 | Tested Webhook | Send /start message | ✓ Got response |

---

## **Your .env Should Now Have**

```bash
WHATSAPP_PHONE_NUMBER_ID=953624217844398
WHATSAPP_BUSINESS_ACCOUNT_ID=1254604036115997
WHATSAPP_TOKEN=EAASgh2lYncsBQZCum1DjFEVeYZAK...
WHATSAPP_VERIFY_TOKEN=catalyx_bot_2026
WHATSAPP_APP_SECRET=(from Meta App Settings)
```

✅ **WhatsApp setup complete!**

**Next:** [Step 2: Stripe Payment Setup](./SETUP_STEP_2_STRIPE.md)
