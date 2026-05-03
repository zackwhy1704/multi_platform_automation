"""
Admin panel FastAPI router — mounted under /admin in gateway/app.py.

Layout:
  /admin/login           - login form
  /admin/logout          - clear session
  /admin                 - dashboard
  /admin/users           - users list
  /admin/users/{id}      - user detail
  /admin/users/{id}/...  - actions on a user
  /admin/messages        - global message log
  /admin/activity        - activity feed
  /admin/revenue         - subscription / revenue snapshot
  /admin/audit           - admin action log
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from gateway.admin import auth, pages, actions
from gateway.admin.auth import require_admin
from gateway.admin.templates import login_page

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str = ""):
    if auth.is_authenticated(request):
        return RedirectResponse("/admin", status_code=302)
    return HTMLResponse(login_page(error=error))


@router.post("/login")
async def login_submit(request: Request, password: str = Form("")):
    if not auth.attempt_login(password):
        # Return rendered login page with error
        return HTMLResponse(login_page(error="Incorrect password."), status_code=401)
    response = RedirectResponse("/admin", status_code=302)
    auth.issue_session_cookie(response)
    return response


@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/admin/login", status_code=302)
    auth.clear_session_cookie(response)
    return response


# --------------------------------------------------------------------------
# Dashboard / read-only pages
# --------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(pages.render_dashboard(request))


@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    q: str = Query("", alias="q"),
    filter: str = Query("all"),
    page: int = Query(1, ge=1),
    _: bool = Depends(require_admin),
):
    return HTMLResponse(pages.render_users_list(request, search=q, filter_kind=filter, page=page))


@router.get("/users/{phone_number_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    phone_number_id: str,
    flash: str = "",
    _: bool = Depends(require_admin),
):
    return HTMLResponse(pages.render_user_detail(request, phone_number_id, flash=flash))


@router.get("/messages", response_class=HTMLResponse)
async def messages(
    request: Request,
    direction: str = Query("all"),
    q: str = Query(""),
    _: bool = Depends(require_admin),
):
    return HTMLResponse(pages.render_messages(request, direction=direction, search=q))


@router.get("/activity", response_class=HTMLResponse)
async def activity(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(pages.render_activity(request))


@router.get("/revenue", response_class=HTMLResponse)
async def revenue(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(pages.render_revenue(request))


@router.get("/audit", response_class=HTMLResponse)
async def audit_log(request: Request, _: bool = Depends(require_admin)):
    return HTMLResponse(pages.render_audit(request))


# --------------------------------------------------------------------------
# Action routes (state-changing, all require CSRF)
# --------------------------------------------------------------------------

def _check_csrf(request: Request, csrf: str):
    if not auth.verify_csrf(request, csrf):
        raise HTTPException(status_code=400, detail="CSRF token mismatch")


@router.post("/users/{phone_number_id}/gift_credits")
async def action_gift_credits(
    request: Request,
    phone_number_id: str,
    amount: int = Form(...),
    reason: str = Form("admin_gift"),
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.gift_credits(request, phone_number_id, amount, reason)
    return RedirectResponse(
        f"/admin/users/{phone_number_id}?flash={flash}", status_code=302,
    )


@router.post("/users/{phone_number_id}/reset_state")
async def action_reset_state(
    request: Request,
    phone_number_id: str,
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.reset_state(request, phone_number_id)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/send_message")
async def action_send_message(
    request: Request,
    phone_number_id: str,
    body: str = Form(...),
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.send_message(request, phone_number_id, body)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/ban")
async def action_ban(
    request: Request,
    phone_number_id: str,
    reason: str = Form(""),
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.ban_user(request, phone_number_id, reason)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/unban")
async def action_unban(
    request: Request,
    phone_number_id: str,
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.unban_user(request, phone_number_id)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/refund")
async def action_refund(
    request: Request,
    phone_number_id: str,
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.refund_subscription(request, phone_number_id)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/cancel_sub")
async def action_cancel_sub(
    request: Request,
    phone_number_id: str,
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.cancel_subscription(request, phone_number_id)
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)


@router.post("/users/{phone_number_id}/edit_profile")
async def action_edit_profile(
    request: Request,
    phone_number_id: str,
    industry: str = Form(""),
    offerings: str = Form(""),
    business_goals: str = Form(""),
    tone: str = Form(""),
    content_style: str = Form(""),
    visual_style: str = Form(""),
    platform: str = Form(""),
    csrf: str = Form(""),
    _: bool = Depends(require_admin),
):
    _check_csrf(request, csrf)
    flash = await actions.edit_profile(
        request, phone_number_id,
        {
            "industry": industry, "offerings": offerings,
            "business_goals": business_goals, "tone": tone,
            "content_style": content_style, "visual_style": visual_style,
            "platform": platform,
        },
    )
    return RedirectResponse(f"/admin/users/{phone_number_id}?flash={flash}", status_code=302)
