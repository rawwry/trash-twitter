"""Login, Logout und gefuehrte Ersteinrichtung."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ROLE_ADMIN, User
from ..security import (
    SESSION_COOKIE,
    LoginThrottle,
    authenticate,
    clear_session_cookie,
    client_ip,
    create_session,
    current_user,
    destroy_session,
    get_db,
    get_settings,
    password_problem,
    set_password,
    set_session_cookie,
)
from ..services import admin_log
from ..templating import redirect, render

router = APIRouter()
_throttle = LoginThrottle()


def safe_next(value: str | None) -> str:
    """Nur interne Ruecksprungziele - keine offene Weiterleitung nach aussen."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value or "\n" in value:
        return "/"
    return value[:1000]


@router.get("/login")
def login_form(request: Request, next: str = "", user: User | None = Depends(current_user)):
    if user:
        return redirect(request, safe_next(next))
    return render(request, "login.html", next=safe_next(next) if next else "")


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form(""),
          db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    result = authenticate(db, settings, _throttle, client_ip(request), username[:64], password[:256])
    if not result.user:
        return render(request, "login.html", status_code=401, error=result.error, username=username[:64],
                      next=safe_next(next) if next else "")
    token = create_session(db, settings, result.user)
    target = "/settings/konto?pflicht=1" if result.user.must_change_password else safe_next(next)
    response = redirect(request, target)
    set_session_cookie(response, request, settings, token)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    destroy_session(db, request.cookies.get(SESSION_COOKIE))
    response = redirect(request, "/login", toast="Abgemeldet. Bis bald!")
    clear_session_cookie(response, request)
    return response


# --- Ersteinrichtung ----------------------------------------------------------

def _setup_open(request: Request, db: Session) -> bool:
    return bool(request.app.state.setup_code) and not db.scalar(select(func.count()).select_from(User))


@router.get("/setup")
def setup_form(request: Request, db: Session = Depends(get_db)):
    if not _setup_open(request, db):
        return redirect(request, "/login")
    return render(request, "setup.html")


@router.post("/setup")
def setup(request: Request, code: str = Form(""), username: str = Form(""), password: str = Form(""),
          password2: str = Form(""), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    if not _setup_open(request, db):
        return redirect(request, "/login")
    username = username.strip()
    error = None
    if not hmac.compare_digest(code.strip().upper(), request.app.state.setup_code):
        error = "Der Einrichtungscode stimmt nicht. Du findest ihn im Protokoll des Add-ons."
    elif not username or len(username) > 64:
        error = "Bitte einen Benutzernamen (bis 64 Zeichen) angeben."
    elif password != password2:
        error = "Die beiden Passwörter stimmen nicht überein."
    else:
        error = password_problem(password)
    if error:
        return render(request, "setup.html", status_code=400, error=error, username=username)
    admin = User(username=username, role=ROLE_ADMIN)
    set_password(settings, admin, password, must_change=False)
    db.add(admin)
    db.flush()
    admin_log.record(db, admin, "setup_admin", admin.username, "Ersteinrichtung")
    db.commit()
    request.app.state.setup_code = None
    token = create_session(db, settings, admin)
    response = redirect(request, "/", toast="Willkommen! Du bist jetzt Admin.")
    set_session_cookie(response, request, settings, token)
    return response
