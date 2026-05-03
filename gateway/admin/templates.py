"""
Inline HTML templates for the admin panel.

No Jinja2 dependency — just Python f-strings inside helper functions.
Pages share a common layout() shell. CSS is inline + minimal.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Iterable, Optional


def esc(value) -> str:
    """HTML-escape a value, returning '' for None."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return html.escape(format_dt(value))
    return html.escape(str(value))


def format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def relative_time(dt: Optional[datetime]) -> str:
    """e.g. '3m ago', '2h ago', '5d ago'"""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


# --------------------------------------------------------------------------
# Layout shell
# --------------------------------------------------------------------------

CSS = """
:root {
  --bg: #0f1117;
  --panel: #181b23;
  --panel-2: #20242e;
  --border: #2a2f3a;
  --text: #e6e8ee;
  --muted: #8b94a7;
  --accent: #4f8cff;
  --accent-2: #7c5cff;
  --good: #3ec28b;
  --bad: #ff6b6b;
  --warn: #f5b74f;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px; line-height: 1.5; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.layout { display: flex; min-height: 100vh; }
.sidebar { width: 220px; background: var(--panel); border-right: 1px solid var(--border);
  padding: 20px 0; position: sticky; top: 0; height: 100vh; }
.brand { font-weight: 700; font-size: 16px; padding: 0 20px 20px;
  border-bottom: 1px solid var(--border); margin-bottom: 12px; }
.brand small { display: block; color: var(--muted); font-weight: 400; font-size: 11px; margin-top: 2px; }
.nav a { display: block; padding: 10px 20px; color: var(--text); border-left: 3px solid transparent; }
.nav a:hover { background: var(--panel-2); text-decoration: none; }
.nav a.active { background: var(--panel-2); border-left-color: var(--accent); }
.nav .group { padding: 16px 20px 6px; font-size: 11px; text-transform: uppercase;
  color: var(--muted); letter-spacing: 0.5px; }
.main { flex: 1; padding: 24px 32px; overflow-x: auto; }
.page-title { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; }
.page-title h1 { margin: 0; font-size: 22px; font-weight: 600; }
.page-title .subtitle { color: var(--muted); font-size: 13px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 24px; }
.kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; }
.kpi .label { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.5px; }
.kpi .value { font-size: 24px; font-weight: 600; margin-top: 4px; }
.kpi .delta { font-size: 12px; color: var(--good); margin-top: 2px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  margin-bottom: 24px; overflow: hidden; }
.card .card-head { padding: 14px 18px; border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center; }
.card .card-head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.card .card-body { padding: 18px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border);
  vertical-align: middle; }
th { background: var(--panel-2); color: var(--muted); font-weight: 500; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.4px; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--panel-2); }
.muted { color: var(--muted); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
  font-weight: 500; background: var(--panel-2); color: var(--muted); }
.badge.good { background: rgba(62, 194, 139, 0.15); color: var(--good); }
.badge.warn { background: rgba(245, 183, 79, 0.15); color: var(--warn); }
.badge.bad  { background: rgba(255, 107, 107, 0.15); color: var(--bad); }
.btn { display: inline-block; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--panel-2); color: var(--text); cursor: pointer; font-size: 13px;
  text-decoration: none; }
.btn:hover { background: #2a3040; text-decoration: none; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: white; }
.btn.primary:hover { background: #3a78f0; }
.btn.danger { background: rgba(255,107,107,0.15); border-color: var(--bad); color: var(--bad); }
.btn.danger:hover { background: rgba(255,107,107,0.25); }
.btn.small { padding: 5px 10px; font-size: 12px; }
input[type=text], input[type=password], input[type=number], textarea, select {
  background: var(--bg); border: 1px solid var(--border); color: var(--text);
  padding: 8px 12px; border-radius: 6px; font-size: 13px; width: 100%;
  font-family: inherit; }
textarea { min-height: 80px; resize: vertical; }
label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px;
  text-transform: uppercase; letter-spacing: 0.4px; }
.form-row { margin-bottom: 14px; }
.form-row.inline { display: flex; gap: 8px; align-items: end; }
.form-row.inline > * { flex: 1; }
.form-row.inline > .btn { flex: 0; }
.flex { display: flex; gap: 8px; align-items: center; }
.spread { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.search-bar { background: var(--panel); padding: 14px 18px; border-radius: 8px;
  border: 1px solid var(--border); margin-bottom: 16px; }
.search-bar form { display: flex; gap: 8px; }
.pagination { display: flex; gap: 8px; justify-content: center; margin-top: 20px; }
.alert { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px;
  border: 1px solid var(--border); }
.alert.good { background: rgba(62,194,139,0.1); border-color: var(--good); color: var(--good); }
.alert.bad { background: rgba(255,107,107,0.1); border-color: var(--bad); color: var(--bad); }
.alert.warn { background: rgba(245,183,79,0.1); border-color: var(--warn); color: var(--warn); }
pre.json { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px; font-size: 12px; overflow-x: auto; max-height: 400px; }
.msg-thread { display: flex; flex-direction: column; gap: 6px; }
.msg-bubble { max-width: 70%; padding: 8px 12px; border-radius: 10px; font-size: 13px;
  line-height: 1.4; word-wrap: break-word; }
.msg-bubble.in  { align-self: flex-start; background: var(--panel-2); }
.msg-bubble.out { align-self: flex-end;   background: rgba(79,140,255,0.18); }
.msg-meta { font-size: 10px; color: var(--muted); margin-top: 2px; }
.tag-row { display: flex; flex-wrap: wrap; gap: 4px; }
.tag-row .badge { font-size: 10px; }
"""


def layout(title: str, body: str, active_nav: str = "", flash: str = "") -> str:
    """Wrap page body in the standard admin shell."""
    nav_items = [
        ("dashboard", "/admin", "Dashboard"),
        ("users",     "/admin/users", "Users"),
        ("activity",  "/admin/activity", "Activity Feed"),
        ("messages",  "/admin/messages", "Messages"),
        ("revenue",   "/admin/revenue", "Revenue"),
        ("audit",     "/admin/audit", "Admin Audit"),
    ]
    nav_html = ""
    for key, href, label in nav_items:
        cls = " active" if key == active_nav else ""
        nav_html += f'<a class="{cls.strip()}" href="{href}">{label}</a>'

    flash_html = f'<div class="alert {flash.split("|", 1)[0]}">{esc(flash.split("|",1)[1] if "|" in flash else flash)}</div>' if flash else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Admin</title>
<style>{CSS}</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="brand">Catalyx Admin<small>WhatsApp Bot</small></div>
    <nav class="nav">
      <div class="group">Overview</div>
      {nav_html}
      <div class="group">Account</div>
      <a href="#" onclick="document.getElementById('logout-form').submit(); return false;">Logout</a>
    </nav>
    <form id="logout-form" method="post" action="/admin/logout" style="display:none"></form>
  </aside>
  <main class="main">
    {flash_html}
    {body}
  </main>
</div>
</body>
</html>"""


# --------------------------------------------------------------------------
# Login page
# --------------------------------------------------------------------------

def login_page(error: str = "") -> str:
    err_html = f'<div class="alert bad">{esc(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Login</title>
<style>{CSS}
.login-wrap {{ display: flex; min-height: 100vh; align-items: center; justify-content: center; }}
.login-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 32px; width: 360px; }}
.login-card h1 {{ margin: 0 0 6px 0; font-size: 22px; }}
.login-card .sub {{ color: var(--muted); margin-bottom: 24px; font-size: 13px; }}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-card">
    <h1>Admin Login</h1>
    <div class="sub">Enter your admin password</div>
    {err_html}
    <form method="post" action="/admin/login">
      <div class="form-row">
        <label>Password</label>
        <input type="password" name="password" autofocus required>
      </div>
      <button class="btn primary" style="width:100%" type="submit">Sign in</button>
    </form>
  </div>
</div>
</body>
</html>"""
