"""
Admin page renderers — pure functions that return HTML strings.

Each function takes the FastAPI Request (to access app.state.db and to compute
the CSRF token), reads from queries.py, renders via templates.py, and returns
a string ready to be wrapped in an HTMLResponse.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urlencode

from fastapi import Request

from gateway.admin import queries as Q
from gateway.admin.auth import get_csrf_token
from gateway.admin.templates import (
    layout,
    esc,
    format_dt,
    relative_time,
)


def _db(request: Request):
    return request.app.state.db


# ============================================================================
# Dashboard
# ============================================================================

def render_dashboard(request: Request) -> str:
    k = Q.get_kpis(_db(request))
    feed = Q.get_activity_feed(_db(request), limit=20)

    kpi_cards = [
        ("Total Users",        k["total_users"],         f'+{k["new_today"]} today'),
        ("Active Subscribers", k["active_subs"],         f'{k["active_subs"]}/{max(k["total_users"],1)} subs'),
        ("Free Users",         k["free_users"],          ""),
        ("New (7d)",           k["new_7d"],              f'{k["new_30d"]} in 30d'),
        ("Messages Today",     k["messages_today"],
            f'{k["msgs_in_today"]} in / {k["msgs_out_today"]} out'),
        ("Credits Used (Today)", k["credits_used_today"],
            f'{k["credits_used_30d"]} in 30d'),
        ("Active Convos",      k["active_conversations"], "in last 15m"),
        ("Banned",             k["banned_users"],         ""),
    ]

    cards_html = ""
    for label, value, delta in kpi_cards:
        cards_html += f"""
        <div class="kpi">
          <div class="label">{esc(label)}</div>
          <div class="value">{esc(value)}</div>
          {f'<div class="delta">{esc(delta)}</div>' if delta else ''}
        </div>
        """

    feed_rows = ""
    for ev in feed:
        kind = ev.get("kind") or ""
        user = ev.get("user_id") or ""
        name = ev.get("display_name") or ""
        when = ev.get("at")
        detail = ev.get("detail") or {}
        label_map = {
            "signup":  ("New signup", "good"),
            "action":  (f'{detail.get("action_type", "action")} on {detail.get("platform", "?")}', ""),
            "credits": (f'{detail.get("action", "credits")} ({detail.get("spent", 0)})', ""),
        }
        label, badge_cls = label_map.get(kind, (kind, ""))
        feed_rows += f"""
        <tr>
          <td><span class="badge {badge_cls}">{esc(kind)}</span></td>
          <td>{esc(label)}</td>
          <td><a href="/admin/users/{esc(user)}">{esc(name or user)}</a></td>
          <td class="muted" title="{esc(format_dt(when))}">{esc(relative_time(when))}</td>
        </tr>
        """

    body = f"""
    <div class="page-title">
      <div>
        <h1>Dashboard</h1>
        <div class="subtitle">Snapshot of your bot right now.</div>
      </div>
    </div>

    <div class="kpi-grid">{cards_html}</div>

    <div class="card">
      <div class="card-head">
        <h2>Recent activity</h2>
        <a class="btn small" href="/admin/activity">See all →</a>
      </div>
      <table>
        <thead>
          <tr><th>Kind</th><th>Event</th><th>User</th><th>When</th></tr>
        </thead>
        <tbody>{feed_rows or '<tr><td colspan="4" class="muted">No activity yet.</td></tr>'}</tbody>
      </table>
    </div>
    """
    return layout("Dashboard", body, active_nav="dashboard")


# ============================================================================
# Users list
# ============================================================================

def render_users_list(
    request: Request,
    search: str = "",
    filter_kind: str = "all",
    page: int = 1,
) -> str:
    per_page = 25
    rows, total = Q.list_users(_db(request), search=search, filter_kind=filter_kind, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)

    filter_options = [
        ("all", "All"),
        ("subscribers", "Subscribers"),
        ("free", "Free"),
        ("low_credits", "Low credits"),
        ("banned", "Banned"),
    ]
    filter_html = "".join(
        f'<option value="{esc(k)}"{" selected" if k==filter_kind else ""}>{esc(v)}</option>'
        for k, v in filter_options
    )

    rows_html = ""
    for r in rows:
        sub_badge = (
            '<span class="badge good">Active</span>' if r.get("subscription_active")
            else '<span class="badge">Free</span>'
        )
        if r.get("banned"):
            sub_badge = '<span class="badge bad">Banned</span>'
        rows_html += f"""
        <tr>
          <td><a href="/admin/users/{esc(r['phone_number_id'])}">{esc(r.get('display_name') or '(unnamed)')}</a></td>
          <td class="muted">{esc(r.get('phone_number') or r['phone_number_id'])}</td>
          <td>{sub_badge}</td>
          <td>{esc(r.get('credits_remaining') or 0)}</td>
          <td class="muted" title="{esc(format_dt(r.get('last_seen')))}">{esc(relative_time(r.get('last_seen')))}</td>
          <td class="muted" title="{esc(format_dt(r.get('created_at')))}">{esc(relative_time(r.get('created_at')))}</td>
        </tr>
        """

    # Pagination links preserve current filter/search
    def page_link(p: int, label: str) -> str:
        params = {"page": p}
        if search:
            params["q"] = search
        if filter_kind != "all":
            params["filter"] = filter_kind
        return f'<a class="btn small" href="/admin/users?{urlencode(params)}">{esc(label)}</a>'

    pagination = ""
    if total_pages > 1:
        prev_btn = page_link(page - 1, "← Prev") if page > 1 else '<span class="btn small muted" style="opacity:0.5">← Prev</span>'
        next_btn = page_link(page + 1, "Next →") if page < total_pages else '<span class="btn small muted" style="opacity:0.5">Next →</span>'
        pagination = f'<div class="pagination">{prev_btn}<span class="muted" style="padding:8px">Page {page} of {total_pages} • {total} users</span>{next_btn}</div>'

    body = f"""
    <div class="page-title">
      <div>
        <h1>Users</h1>
        <div class="subtitle">{esc(total)} total</div>
      </div>
    </div>

    <div class="search-bar">
      <form method="get" action="/admin/users">
        <input type="text" name="q" value="{esc(search)}" placeholder="Search by phone, name, or referral code">
        <select name="filter" style="max-width:160px">{filter_html}</select>
        <button class="btn primary" type="submit">Search</button>
      </form>
    </div>

    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Name</th><th>Phone</th><th>Status</th><th>Credits</th>
            <th>Last seen</th><th>Joined</th>
          </tr>
        </thead>
        <tbody>{rows_html or '<tr><td colspan="6" class="muted">No users match.</td></tr>'}</tbody>
      </table>
    </div>
    {pagination}
    """
    return layout("Users", body, active_nav="users")


# ============================================================================
# User detail
# ============================================================================

def render_user_detail(request: Request, phone_number_id: str, flash: str = "") -> str:
    csrf = get_csrf_token(request)
    data = Q.get_user_detail(_db(request), phone_number_id)
    if data is None:
        return layout(
            "User not found",
            f'<div class="alert bad">No user with phone_number_id <code>{esc(phone_number_id)}</code></div>'
            '<a class="btn" href="/admin/users">← Back to users</a>',
            active_nav="users",
            flash=flash,
        )

    u = data["user"]
    profile = data["profile"] or {}
    platforms = data["platforms"]
    ledger = data["ledger"]
    posts = data["posts"]
    scheduled = data["scheduled"]
    conv = data["conversation"]
    referrals = data["referral_count"]

    messages = Q.get_messages_for_user(_db(request), phone_number_id, limit=80)

    # Status badges
    if u.get("banned"):
        status_badge = '<span class="badge bad">Banned</span>'
    elif u.get("subscription_active"):
        status_badge = '<span class="badge good">Active subscriber</span>'
    else:
        status_badge = '<span class="badge">Free</span>'

    # ----- Header -----
    header = f"""
    <div class="page-title">
      <div>
        <h1>{esc(u.get('display_name') or '(unnamed)')}</h1>
        <div class="subtitle">{esc(u.get('phone_number') or u['phone_number_id'])} • Joined {esc(format_dt(u.get('created_at')))}</div>
      </div>
      <div>{status_badge}</div>
    </div>
    """

    # ----- KPI strip -----
    kpis = f"""
    <div class="kpi-grid">
      <div class="kpi"><div class="label">Credits remaining</div><div class="value">{esc(u.get('credits_remaining') or 0)}</div></div>
      <div class="kpi"><div class="label">Credits used</div><div class="value">{esc(u.get('credits_used') or 0)}</div></div>
      <div class="kpi"><div class="label">Referrals made</div><div class="value">{esc(referrals)}</div></div>
      <div class="kpi"><div class="label">Last seen</div><div class="value" style="font-size:16px">{esc(relative_time(u.get('last_seen')))}</div></div>
    </div>
    """

    # ----- Actions -----
    danger_action = ""
    if u.get("banned"):
        danger_action = f"""
        <form method="post" action="/admin/users/{esc(phone_number_id)}/unban" style="display:inline">
          <input type="hidden" name="csrf" value="{esc(csrf)}">
          <button class="btn" type="submit">Unban user</button>
        </form>
        """
    else:
        danger_action = f"""
        <form method="post" action="/admin/users/{esc(phone_number_id)}/ban" style="display:inline"
              onsubmit="return confirm('Ban this user? They will be silently dropped on next message.');">
          <input type="hidden" name="csrf" value="{esc(csrf)}">
          <input type="text" name="reason" placeholder="Reason (optional)" style="width:200px;display:inline-block;margin-right:8px">
          <button class="btn danger" type="submit">Ban user</button>
        </form>
        """

    sub_action = ""
    if u.get("stripe_subscription_id"):
        sub_action = f"""
        <form method="post" action="/admin/users/{esc(phone_number_id)}/cancel_sub" style="display:inline"
              onsubmit="return confirm('Cancel this subscription at period end?');">
          <input type="hidden" name="csrf" value="{esc(csrf)}">
          <button class="btn danger" type="submit">Cancel subscription</button>
        </form>
        <form method="post" action="/admin/users/{esc(phone_number_id)}/refund" style="display:inline"
              onsubmit="return confirm('Refund the most recent payment for this customer?');">
          <input type="hidden" name="csrf" value="{esc(csrf)}">
          <button class="btn danger" type="submit">Refund last payment</button>
        </form>
        """

    actions_card = f"""
    <div class="card">
      <div class="card-head"><h2>Admin actions</h2></div>
      <div class="card-body">
        <div class="form-row">
          <label>Gift credits</label>
          <form method="post" action="/admin/users/{esc(phone_number_id)}/gift_credits" class="form-row inline">
            <input type="hidden" name="csrf" value="{esc(csrf)}">
            <input type="number" name="amount" min="1" max="100000" placeholder="Amount" required>
            <input type="text" name="reason" value="admin_gift" placeholder="Reason">
            <button class="btn primary small" type="submit">Gift</button>
          </form>
        </div>

        <div class="form-row">
          <label>Send manual WhatsApp message</label>
          <form method="post" action="/admin/users/{esc(phone_number_id)}/send_message">
            <input type="hidden" name="csrf" value="{esc(csrf)}">
            <textarea name="body" placeholder="Message body" required></textarea>
            <button class="btn primary small" type="submit" style="margin-top:8px">Send</button>
          </form>
        </div>

        <div class="form-row">
          <label>Reset conversation state</label>
          <form method="post" action="/admin/users/{esc(phone_number_id)}/reset_state" style="display:inline"
                onsubmit="return confirm('Clear this user\\'s conversation state?');">
            <input type="hidden" name="csrf" value="{esc(csrf)}">
            <button class="btn" type="submit">Reset state</button>
          </form>
          <span class="muted" style="margin-left:8px">Useful when a user gets stuck mid-flow.</span>
        </div>

        <div class="form-row">
          <label>Subscription</label>
          {sub_action or '<span class="muted">No active Stripe subscription.</span>'}
        </div>

        <div class="form-row">
          <label>Moderation</label>
          {danger_action}
          { f'<div class="muted" style="margin-top:6px">Banned reason: <code>{esc(u.get("banned_reason") or "—")}</code> at {esc(format_dt(u.get("banned_at")))}</div>' if u.get("banned") else "" }
        </div>
      </div>
    </div>
    """

    # ----- Profile card (editable) -----
    def _arr(v):
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v or ""

    profile_card = f"""
    <div class="card">
      <div class="card-head"><h2>Profile</h2></div>
      <div class="card-body">
        <form method="post" action="/admin/users/{esc(phone_number_id)}/edit_profile">
          <input type="hidden" name="csrf" value="{esc(csrf)}">
          <div class="form-row"><label>Industry (comma-separated)</label>
            <input type="text" name="industry" value="{esc(_arr(profile.get('industry')))}"></div>
          <div class="form-row"><label>Offerings</label>
            <input type="text" name="offerings" value="{esc(_arr(profile.get('offerings')))}"></div>
          <div class="form-row"><label>Business goals</label>
            <input type="text" name="business_goals" value="{esc(_arr(profile.get('business_goals')))}"></div>
          <div class="form-row"><label>Tone</label>
            <input type="text" name="tone" value="{esc(_arr(profile.get('tone')))}"></div>
          <div class="form-row inline">
            <div><label>Content style</label>
              <input type="text" name="content_style" value="{esc(profile.get('content_style') or '')}"></div>
            <div><label>Visual style</label>
              <input type="text" name="visual_style" value="{esc(profile.get('visual_style') or '')}"></div>
            <div><label>Platform</label>
              <input type="text" name="platform" value="{esc(profile.get('platform') or '')}"></div>
          </div>
          <button class="btn primary small" type="submit">Save profile</button>
        </form>
      </div>
    </div>
    """

    # ----- Connected platforms -----
    plat_rows = ""
    for p in platforms:
        plat_rows += f"""
        <tr>
          <td><span class="badge">{esc(p.get('platform'))}</span></td>
          <td>{esc(p.get('page_name') or p.get('account_username') or p.get('page_id') or '—')}</td>
          <td class="muted">{esc(p.get('page_id') or '')}</td>
          <td class="muted">{esc(format_dt(p.get('created_at')))}</td>
        </tr>
        """
    platforms_card = f"""
    <div class="card">
      <div class="card-head"><h2>Connected platforms</h2></div>
      <table>
        <thead><tr><th>Platform</th><th>Page</th><th>ID</th><th>Connected</th></tr></thead>
        <tbody>{plat_rows or '<tr><td colspan="4" class="muted">None connected.</td></tr>'}</tbody>
      </table>
    </div>
    """

    # ----- Message thread -----
    msg_html = ""
    # display chronologically (oldest first)
    for m in reversed(messages):
        cls = "in" if m.get("direction") == "in" else "out"
        body_text = m.get("text_body") or f'[{m.get("msg_type")}]'
        msg_html += f"""
        <div class="msg-bubble {cls}">
          {esc(body_text)}
          <div class="msg-meta">{esc(m.get('msg_type'))} • {esc(relative_time(m.get('created_at')))}</div>
        </div>
        """
    messages_card = f"""
    <div class="card">
      <div class="card-head"><h2>Conversation ({len(messages)} most recent)</h2></div>
      <div class="card-body">
        <div class="msg-thread">{msg_html or '<span class="muted">No messages yet.</span>'}</div>
      </div>
    </div>
    """

    # ----- Credit ledger -----
    led_rows = ""
    for l in ledger[:20]:
        spent = l.get("credits_spent") or 0
        sign = "good" if spent < 0 else ""
        led_rows += f"""
        <tr>
          <td>{esc(l.get('action'))}</td>
          <td class="muted">{esc(l.get('platform') or '')}</td>
          <td><span class="badge {sign}">{esc(spent)}</span></td>
          <td class="muted">{esc(format_dt(l.get('created_at')))}</td>
        </tr>
        """
    ledger_card = f"""
    <div class="card">
      <div class="card-head"><h2>Credit ledger (last 20)</h2></div>
      <table>
        <thead><tr><th>Action</th><th>Platform</th><th>Δ Credits</th><th>When</th></tr></thead>
        <tbody>{led_rows or '<tr><td colspan="4" class="muted">No ledger entries.</td></tr>'}</tbody>
      </table>
    </div>
    """

    # ----- Posts / actions -----
    post_rows = ""
    for p in posts[:20]:
        post_rows += f"""
        <tr>
          <td><span class="badge">{esc(p.get('platform'))}</span></td>
          <td>{esc(p.get('action_type'))}</td>
          <td>{esc(p.get('action_count') or 1)}</td>
          <td class="muted">{esc(format_dt(p.get('performed_at')))}</td>
        </tr>
        """
    posts_card = f"""
    <div class="card">
      <div class="card-head"><h2>Recent automation actions</h2></div>
      <table>
        <thead><tr><th>Platform</th><th>Action</th><th>Count</th><th>When</th></tr></thead>
        <tbody>{post_rows or '<tr><td colspan="4" class="muted">No actions yet.</td></tr>'}</tbody>
      </table>
    </div>
    """

    # ----- Conversation state debug -----
    conv_html = "<span class='muted'>Idle.</span>"
    if conv:
        try:
            conv_data = json.dumps(conv.get("data") or {}, indent=2, default=str)
        except Exception:
            conv_data = str(conv.get("data"))
        conv_html = f"""
          <div class="muted" style="margin-bottom:8px">Updated {esc(relative_time(conv.get('updated_at')))} • State: <code>{esc(conv.get('state'))}</code></div>
          <pre class="json">{esc(conv_data)}</pre>
        """
    conv_card = f"""
    <div class="card">
      <div class="card-head"><h2>Conversation state</h2></div>
      <div class="card-body">{conv_html}</div>
    </div>
    """

    body = f"""
    <a class="btn small" href="/admin/users">← All users</a>
    <div style="height:12px"></div>
    {header}
    {kpis}
    {actions_card}
    {messages_card}
    {profile_card}
    {platforms_card}
    {ledger_card}
    {posts_card}
    {conv_card}
    """
    return layout(u.get('display_name') or phone_number_id, body, active_nav="users", flash=flash)


# ============================================================================
# Global messages
# ============================================================================

def render_messages(request: Request, direction: str = "all", search: str = "") -> str:
    rows = Q.get_recent_messages(_db(request), direction=direction, search=search, limit=200)

    dir_options = [("all", "All"), ("in", "Inbound only"), ("out", "Outbound only")]
    dir_html = "".join(
        f'<option value="{esc(k)}"{" selected" if k==direction else ""}>{esc(v)}</option>'
        for k, v in dir_options
    )

    rows_html = ""
    for m in rows:
        cls = "good" if m.get("direction") == "in" else ""
        rows_html += f"""
        <tr>
          <td><span class="badge {cls}">{esc(m.get('direction'))}</span></td>
          <td><a href="/admin/users/{esc(m['phone_number_id'])}">{esc(m.get('display_name') or m['phone_number_id'])}</a></td>
          <td><span class="badge">{esc(m.get('msg_type'))}</span></td>
          <td>{esc((m.get('text_body') or '')[:140])}</td>
          <td class="muted" title="{esc(format_dt(m.get('created_at')))}">{esc(relative_time(m.get('created_at')))}</td>
        </tr>
        """

    body = f"""
    <div class="page-title">
      <div><h1>Messages</h1>
      <div class="subtitle">Live feed of every inbound and outbound WhatsApp message.</div></div>
    </div>
    <div class="search-bar">
      <form method="get" action="/admin/messages">
        <input type="text" name="q" value="{esc(search)}" placeholder="Search message text or phone">
        <select name="direction" style="max-width:160px">{dir_html}</select>
        <button class="btn primary" type="submit">Filter</button>
      </form>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>Dir</th><th>User</th><th>Type</th><th>Text</th><th>When</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="5" class="muted">No messages yet — they will appear here as the bot is used.</td></tr>'}</tbody>
      </table>
    </div>
    """
    return layout("Messages", body, active_nav="messages")


# ============================================================================
# Activity feed
# ============================================================================

def render_activity(request: Request) -> str:
    feed = Q.get_activity_feed(_db(request), limit=100)
    rows_html = ""
    for ev in feed:
        kind = ev.get("kind") or ""
        user = ev.get("user_id") or ""
        name = ev.get("display_name") or ""
        when = ev.get("at")
        detail = ev.get("detail") or {}
        if kind == "signup":
            evt = "Signed up"
        elif kind == "action":
            evt = f'{detail.get("action_type", "action")} on {detail.get("platform", "?")}'
        elif kind == "credits":
            spent = detail.get("spent", 0)
            verb = "Granted" if spent < 0 else "Spent"
            evt = f'{verb} {abs(spent)} credits ({detail.get("action", "")})'
        else:
            evt = kind
        rows_html += f"""
        <tr>
          <td><span class="badge">{esc(kind)}</span></td>
          <td>{esc(evt)}</td>
          <td><a href="/admin/users/{esc(user)}">{esc(name or user)}</a></td>
          <td class="muted" title="{esc(format_dt(when))}">{esc(relative_time(when))}</td>
        </tr>
        """
    body = f"""
    <div class="page-title"><div><h1>Activity feed</h1>
      <div class="subtitle">Signups, posts, and credit movements across all users.</div></div></div>
    <div class="card">
      <table>
        <thead><tr><th>Kind</th><th>Event</th><th>User</th><th>When</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="4" class="muted">No activity yet.</td></tr>'}</tbody>
      </table>
    </div>
    """
    return layout("Activity", body, active_nav="activity")


# ============================================================================
# Revenue
# ============================================================================

def render_revenue(request: Request) -> str:
    r = Q.get_revenue_summary(_db(request))
    rows_html = ""
    for s in r["subs_recent"]:
        active = "good" if s.get("subscription_active") else ""
        rows_html += f"""
        <tr>
          <td><a href="/admin/users/{esc(s['phone_number_id'])}">{esc(s.get('display_name') or s['phone_number_id'])}</a></td>
          <td><span class="badge {active}">{esc('Active' if s.get('subscription_active') else 'Inactive')}</span></td>
          <td class="muted">{esc(s.get('stripe_customer_id') or '—')}</td>
          <td class="muted">{esc(format_dt(s.get('subscription_expires')))}</td>
          <td class="muted">{esc(format_dt(s.get('updated_at')))}</td>
        </tr>
        """
    body = f"""
    <div class="page-title"><div><h1>Revenue</h1>
      <div class="subtitle">Local snapshot — Stripe Dashboard is the source of truth.</div></div></div>
    <div class="kpi-grid">
      <div class="kpi"><div class="label">Active subscribers</div><div class="value">{esc(r['active_subs'])}</div></div>
      <div class="kpi"><div class="label">Customers in Stripe</div><div class="value">{esc(r['subs_with_stripe_id'])}</div></div>
    </div>
    <div class="card">
      <div class="card-head">
        <h2>Recent subscriptions</h2>
        <a class="btn small" href="https://dashboard.stripe.com/subscriptions" target="_blank">Open Stripe ↗</a>
      </div>
      <table>
        <thead><tr><th>User</th><th>Status</th><th>Stripe customer</th><th>Renews</th><th>Updated</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="5" class="muted">No subscriptions yet.</td></tr>'}</tbody>
      </table>
    </div>
    """
    return layout("Revenue", body, active_nav="revenue")


# ============================================================================
# Audit log
# ============================================================================

def render_audit(request: Request) -> str:
    rows = Q.get_admin_audit(_db(request), limit=200)
    rows_html = ""
    for r in rows:
        try:
            detail_str = json.dumps(r.get("detail") or {}, default=str)
        except Exception:
            detail_str = str(r.get("detail"))
        target = r.get("target_user")
        target_html = f'<a href="/admin/users/{esc(target)}">{esc(target)}</a>' if target else '<span class="muted">—</span>'
        rows_html += f"""
        <tr>
          <td><span class="badge">{esc(r.get('action'))}</span></td>
          <td>{target_html}</td>
          <td class="muted">{esc(detail_str[:140])}</td>
          <td class="muted">{esc(r.get('ip_address') or '')}</td>
          <td class="muted" title="{esc(format_dt(r.get('created_at')))}">{esc(relative_time(r.get('created_at')))}</td>
        </tr>
        """
    body = f"""
    <div class="page-title"><div><h1>Admin audit</h1>
      <div class="subtitle">Every action you take from this panel is logged here.</div></div></div>
    <div class="card">
      <table>
        <thead><tr><th>Action</th><th>Target</th><th>Detail</th><th>IP</th><th>When</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="5" class="muted">No admin actions logged yet.</td></tr>'}</tbody>
      </table>
    </div>
    """
    return layout("Audit", body, active_nav="audit")
