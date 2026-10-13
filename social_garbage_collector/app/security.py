"""Zentrale Sicherheit: Passwoerter, Sitzungen, CSRF, Rechtepruefung.

Rechte werden NUR hier geprueft, ueber wiederverwendbare Abhaengigkeiten:

    require_user   - eingeloggt (sonst Weiterleitung zum Login)
    require_admin  - eingeloggter, aktiver Admin (sonst neutrale 404)

Admin-Routen haengen am Router mit dependencies=[Depends(require_admin)],
nicht an einzelnen Routen. So kann keine Route die Pruefung "vergessen".
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Iterator

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import ROLE_ADMIN, User, UserSession, utcnow

SESSION_COOKIE = "sgc_session"
CSRF_COOKIE = "sgc_csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
MIN_PASSWORD_LENGTH = 5

_hasher = PasswordHasher()
# Fuer unbekannte Benutzernamen trotzdem einmal argon2 rechnen, damit man an
# der Antwortzeit nicht erkennt, ob es den Namen gibt.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


# --------------------------------------------------------------------------
# Passwoerter
# --------------------------------------------------------------------------

def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, plaintext: str) -> bool:
    try:
        return _hasher.verify(password_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_password(length: int = 10) -> str:
    """Zufaelliges Passwort ohne leicht verwechselbare Zeichen (0/O, 1/l/I).

    10 Zeichen aus ~60 Symbolen (~59 Bit) - gut abtippbar und fuer ein
    Anfangspasswort, das ohnehin geaendert werden muss, mehr als genug.
    """
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI") + "-_!?#+"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def password_problem(plaintext: str) -> str | None:
    """Deutsche Fehlermeldung, falls das Passwort zu schwach ist, sonst None."""
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        return f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein."
    if len(plaintext) > 256:
        return "Das Passwort ist zu lang (hoechstens 256 Zeichen)."
    return None


def set_password(settings: Settings, user: User, plaintext: str, *, must_change: bool) -> None:
    """DIE eine Stelle, an der Passwoerter gesetzt werden.

    Gespeichert wird nur der argon2-Hash - niemand kann Passwoerter einsehen,
    auch kein Admin. Klartext wird nirgends geloggt.
    """
    user.password_hash = hash_password(plaintext)
    user.must_change_password = must_change
    user.failed_logins = 0
    user.locked_until = None


def find_user_by_name(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))


def count_active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == ROLE_ADMIN, User.is_active.is_(True))
    ) or 0


# --------------------------------------------------------------------------
# Login-Bremse (Rate-Limit)
# --------------------------------------------------------------------------

class LoginThrottle:
    """Zaehlt Fehlversuche pro IP im Speicher.

    Zusaetzlich sperrt authenticate() das betroffene Konto selbst
    (users.locked_until). Beides zusammen bremst Raten von aussen und
    gezieltes Durchprobieren eines Kontos.
    """

    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, window: float) -> deque[float]:
        q = self._fails[ip]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        return q

    def blocked(self, ip: str, settings: Settings) -> bool:
        window = settings.login_lock_minutes * 60
        # Pro IP etwas grosszuegiger als pro Konto: mehrere Freunde koennen
        # hinter derselben IP sitzen (Ingress, gleiches WLAN).
        return len(self._prune(ip, window)) >= settings.login_max_attempts * 3

    def fail(self, ip: str) -> None:
        self._fails[ip].append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


class LoginResult:
    def __init__(self, user: User | None = None, error: str | None = None) -> None:
        self.user = user
        self.error = error


GENERIC_LOGIN_ERROR = "Benutzername oder Passwort ist falsch."


def authenticate(db: Session, settings: Settings, throttle: LoginThrottle, ip: str,
                 username: str, password: str) -> LoginResult:
    lock_msg = f"Zu viele Fehlversuche. Bitte in {settings.login_lock_minutes} Minuten erneut versuchen."
    if throttle.blocked(ip, settings):
        return LoginResult(error=lock_msg)

    user = find_user_by_name(db, username) if username else None
    if user is None:
        verify_password(_DUMMY_HASH, password)
        throttle.fail(ip)
        return LoginResult(error=GENERIC_LOGIN_ERROR)

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        throttle.fail(ip)
        return LoginResult(error=lock_msg)

    if not verify_password(user.password_hash, password):
        throttle.fail(ip)
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
        db.commit()
        return LoginResult(error=GENERIC_LOGIN_ERROR)

    if not user.is_active:
        # Erst NACH richtigem Passwort verraten, dass das Konto deaktiviert ist.
        return LoginResult(error="Dieses Konto ist deaktiviert. Wende dich an den Admin.")

    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    throttle.reset(ip)
    return LoginResult(user=user)


# --------------------------------------------------------------------------
# Sitzungen
# --------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(db: Session, settings: Settings, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(UserSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_hours),
    ))
    # Bei der Gelegenheit abgelaufene Sitzungen wegraeumen.
    db.execute(delete(UserSession).where(UserSession.expires_at < now))
    db.commit()
    return token


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))
        db.commit()


def destroy_user_sessions(db: Session, user_id: int, keep_token: str | None = None) -> None:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_token:
        stmt = stmt.where(UserSession.token_hash != _hash_token(keep_token))
    db.execute(stmt)


def set_session_cookie(response, request: Request, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=settings.session_hours * 3600,
        httponly=True, samesite="lax", secure=settings.cookie_secure,
        path=cookie_path(request),
    )


def clear_session_cookie(response, request: Request) -> None:
    response.delete_cookie(SESSION_COOKIE, path=cookie_path(request))


def cookie_path(request: Request) -> str:
    # Unter Ingress nur fuer den eigenen Pfad, nicht fuer ganz Home Assistant.
    return (request.scope.get("root_path") or "") + "/"


# --------------------------------------------------------------------------
# Abhaengigkeiten fuer die Routen
# --------------------------------------------------------------------------

def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.SessionLocal()
    # Fuer render(): Zaehler wie "Neu fuer dich" ohne zweite DB-Sitzung.
    request.state.db = db
    try:
        yield db
    finally:
        db.close()


def load_session(request: Request, db: Session = Depends(get_db)) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = db.get(UserSession, _hash_token(token))
    if sess is None:
        return None
    if sess.expires_at < utcnow() or not sess.user.is_active:
        db.delete(sess)
        db.commit()
        return None
    request.state.user = sess.user
    request.state.csrf_token = sess.csrf_token
    return sess


def current_user(sess: UserSession | None = Depends(load_session)) -> User | None:
    return sess.user if sess else None


class LoginRequired(Exception):
    """Wird in main.py in eine Weiterleitung zum Login uebersetzt."""


class PasswordChangeRequired(Exception):
    """Wird in main.py in eine Weiterleitung zur Passwortaenderung uebersetzt."""


def require_user_allow_pw_change(user: User | None = Depends(current_user)) -> User:
    """Eingeloggt - auch wenn das Passwort noch geaendert werden muss."""
    if user is None:
        raise LoginRequired()
    return user


def require_user(user: User = Depends(require_user_allow_pw_change)) -> User:
    """Eingeloggt und Passwort bereits selbst gesetzt."""
    if user.must_change_password:
        raise PasswordChangeRequired()
    return user


def require_admin(user: User | None = Depends(current_user)) -> User:
    """Nur aktive Admins. Alle anderen - auch nicht eingeloggte - bekommen
    eine neutrale 404, damit nicht einmal die Existenz der Seite auffaellt."""
    if user is None or not user.is_admin:
        raise HTTPException(status_code=404)
    if user.must_change_password:
        raise PasswordChangeRequired()
    return user


async def csrf_protect(request: Request, sess: UserSession | None = Depends(load_session)) -> None:
    """CSRF-Schutz fuer ALLE schreibenden Anfragen (global in main.py).

    Erwartet wird das Token im Formularfeld csrf_token oder im Header
    X-CSRF-Token (htmx setzt ihn global, siehe base.html). Eingeloggt gilt
    das Token der Sitzung, sonst das aus dem Cookie sgc_csrf.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = sess.csrf_token if sess else request.cookies.get(CSRF_COOKIE)
    sent = request.headers.get(CSRF_HEADER)
    if not sent:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            sent = form.get(CSRF_FIELD)
    if not expected or not sent or not hmac.compare_digest(str(sent), str(expected)):
        raise HTTPException(status_code=403, detail="Sicherheits-Token fehlt oder ist abgelaufen. Bitte die Seite neu laden.")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unbekannt"
