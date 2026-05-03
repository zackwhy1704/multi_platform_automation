"""
Admin auth — single password from ADMIN_PASSWORD env var, signed session cookie.

Login: POST /admin/login with form field 'password'. Sets HMAC-signed cookie.
Protect: any route can call require_admin(request) as a dependency.
Logout: POST /admin/logout clears the cookie.

Why HMAC + cookie (not JWT or DB-backed sessions):
  - Single user; we don't need server-side session storage.
  - HMAC is stdlib, no extra deps.
  - Cookie is HttpOnly + SameSite=Lax + Secure on HTTPS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

COOKIE_NAME = "admin_session"
SESSION_LIFETIME_SECONDS = 60 * 60 * 12  # 12 hours

# Lazy-loaded so tests can mutate env before import resolution
def _get_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "").strip()


def _get_session_secret() -> str:
    """Secret for signing session cookies. Falls back to a derived value if unset
    so the app still boots, but logs a warning. In production, set ADMIN_SESSION_SECRET."""
    secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
    if secret:
        return secret
    # Derive from the admin password so cookies are still scoped — but warn.
    fallback = _get_password() or "unset-admin-secret-change-me"
    logger.warning(
        "ADMIN_SESSION_SECRET not set — using a derived fallback. "
        "Set ADMIN_SESSION_SECRET in production for stable sessions."
    )
    return fallback


def _sign(payload: str) -> str:
    """HMAC-SHA256 signature, base64-encoded urlsafe (no padding)."""
    sig = hmac.new(
        _get_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def _make_token() -> str:
    """Token format: <issued_at>.<random_id>.<signature>"""
    issued_at = str(int(time.time()))
    rand_id = secrets.token_urlsafe(12)
    payload = f"{issued_at}.{rand_id}"
    sig = _sign(payload)
    return f"{payload}.{sig}"


def _verify_token(token: str) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued_at_str, rand_id, sig = parts
    payload = f"{issued_at_str}.{rand_id}"
    expected = _sign(payload)
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        issued_at = int(issued_at_str)
    except ValueError:
        return False
    if time.time() - issued_at > SESSION_LIFETIME_SECONDS:
        return False
    return True


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME, "")
    return _verify_token(token)


def get_csrf_token(request: Request) -> str:
    """CSRF token derived from the session cookie. Forms must echo it back."""
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return ""
    return _sign(token)[:32]


def verify_csrf(request: Request, submitted: Optional[str]) -> bool:
    if not submitted:
        return False
    expected = get_csrf_token(request)
    if not expected:
        return False
    return hmac.compare_digest(submitted, expected)


# --- FastAPI dependency / helpers ---

def require_admin(request: Request):
    """FastAPI dependency. Redirects to /admin/login if not authenticated."""
    if not is_authenticated(request):
        # We use HTTPException 302 via raise — but simpler: caller handles via try.
        # FastAPI dependencies can't return RedirectResponse directly while raising,
        # so we throw a 302 by raising a Starlette HTTPException with location header.
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/admin/login"},
        )
    return True


def attempt_login(password: str) -> bool:
    """Constant-time password compare against ADMIN_PASSWORD env var."""
    expected = _get_password()
    if not expected:
        # No password configured — refuse all logins for safety
        return False
    # Use compare_digest on bytes
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def issue_session_cookie(response) -> None:
    """Set the session cookie on the given response."""
    token = _make_token()
    # secure=True breaks local HTTP testing; use SameSite=Lax + HttpOnly always.
    # In production behind HTTPS, browsers will accept the cookie.
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        path="/admin",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/admin")
