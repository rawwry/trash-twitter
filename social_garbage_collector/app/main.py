"""Einstiegspunkt: baut die FastAPI-App zusammen.

    uvicorn app.main:app           (im Add-on, Einstellungen aus der Umgebung)
    create_app(Settings(...))      (in den Tests, mit eigenem Datenordner)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.exceptions import HTTPException

from . import APP_NAME, VERSION
from .config import Settings, prepare_storage
from .db import backup_database, init_db, make_engine, make_sessionmaker
from .models import ROLE_ADMIN, User
from .routers import account, admin, api, auth, collage, comments, gallery, generator, help, ideas, imports, lists, palette, persons, posts, research, saved, tagrules
from .routers import settings as settings_router
from .security import (
    CSRF_COOKIE,
    LoginRequired,
    PasswordChangeRequired,
    cookie_path,
    csrf_protect,
    set_password,
)
from .services import accounts, admin_log, dates, media, ocr, shots
from .templating import redirect, render, root_path

log = logging.getLogger("sgc")

BACKUP_INTERVAL_S = 24 * 3600


class IngressMiddleware:
    """Home-Assistant-Ingress: der Supervisor reicht Anfragen ohne Praefix
    durch und nennt den Praefix im Header X-Ingress-Path. Wir setzen ihn als
    root_path, damit alle Links (url()) und Cookies (Pfad) stimmen."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            for name, value in scope.get("headers", []):
                if name == b"x-ingress-path":
                    path = value.decode("latin-1").rstrip("/")
                    if path.startswith("/api/hassio_ingress/"):
                        scope["root_path"] = path
                    break
        await self.app(scope, receive, send)


def _remove_password_copies(settings: Settings) -> None:
    """Bis 0.8 gab es eine Testfunktion, mit der Admins Passwoerter einsehen
    konnten (verschluesselte Kopien + Schluesseldatei). Seit 0.9 entfernt: die
    Spalte loescht die Migration, hier verschwindet der Schluessel."""
    key = settings.base_path / "secrets" / "fernet.key"
    try:
        if key.exists():
            key.unlink()
            log.info("Schluessel der entfernten Passwort-Anzeige geloescht.")
        if key.parent.exists() and not any(key.parent.iterdir()):
            key.parent.rmdir()
    except OSError as exc:
        log.warning("Alte Schluesseldatei nicht loeschbar: %s", exc)


def _emergency_reset(db, settings: Settings) -> None:
    """Notfall: niemand kommt mehr rein (Passwort vergessen, Konto gesperrt).

    Add-on-Optionen: reset_password: true, admin_username = Konto, admin_password
    = neues Passwort. Beim Start bekommt das Konto dieses Passwort, wird
    entsperrt, aktiviert und ist Admin. Gibt es den Namen nicht, wird er als
    Admin angelegt. Danach unbedingt reset_password wieder ausschalten.
    """
    name = (settings.admin_username or "").strip() or "admin"
    if len(settings.admin_password or "") < 5:
        log.error("NOTFALL-RESET: admin_password fehlt oder ist kuerzer als 5 Zeichen - nichts geaendert.")
        return
    user = db.scalar(select(User).where(func.lower(User.username) == name.lower()))
    created = user is None
    if created:
        user = User(username=name, role=ROLE_ADMIN)
        db.add(user)
    user.role, user.is_active = ROLE_ADMIN, True
    set_password(settings, user, settings.admin_password, must_change=True)  # entsperrt auch
    db.flush()
    admin_log.record(db, None, "password_reset", user.username, "Notfall-Reset ueber Add-on-Option")
    db.commit()
    log.warning("=" * 64)
    log.warning("NOTFALL-RESET: Konto '%s' %s. Anmelden mit dem Passwort aus den Add-on-Optionen,",
                user.username, "angelegt" if created else "zurueckgesetzt und entsperrt")
    log.warning("danach ein eigenes Passwort vergeben. JETZT 'reset_password' wieder AUSSCHALTEN")
    log.warning("und 'admin_password' leeren - sonst passiert das bei jedem Neustart.")
    log.warning("=" * 64)


def _bootstrap_admin(app: FastAPI, settings: Settings) -> None:
    """Erster Admin: per Add-on-Option, sonst gefuehrte Ersteinrichtung.

    Es gibt KEIN eingebautes Standardpasswort. Ohne Option wird ein
    Einrichtungscode erzeugt und nur ins Add-on-Protokoll geschrieben. Wer
    /setup aufruft, braucht diesen Code - so kann sich niemand aus dem
    Netz zuerst zum Admin machen.
    """
    with app.state.SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)):
            app.state.setup_code = None
            if settings.reset_password:
                _emergency_reset(db, settings)
            admins = list(db.scalars(select(User.username).where(User.role == ROLE_ADMIN, User.is_active.is_(True))))
            log.info("Admin-Konten: %s", ", ".join(admins) or "keins aktiv")
            return
        if settings.admin_password:
            admin = User(username=settings.admin_username.strip() or "admin", role=ROLE_ADMIN)
            # Das Passwort steht im Klartext in den Add-on-Optionen -> beim
            # ersten Login aendern lassen.
            set_password(settings, admin, settings.admin_password, must_change=True)
            db.add(admin)
            db.flush()
            admin_log.record(db, None, "setup_admin", admin.username, "aus Add-on-Option")
            db.commit()
            log.info("Admin '%s' aus der Add-on-Option angelegt. Passwort beim ersten Login aendern.", admin.username)
            app.state.setup_code = None
            return
        code = secrets.token_hex(4).upper()
        app.state.setup_code = code
        log.warning("=" * 64)
        log.warning("ERSTEINRICHTUNG: Noch kein Benutzer vorhanden.")
        log.warning("Oeffne die Oberflaeche und gib diesen Einrichtungscode ein: %s", code)
        log.warning("=" * 64)


async def _backup_loop(settings: Settings) -> None:
    while True:
        try:
            await asyncio.to_thread(backup_database, settings.db_path, settings.backup_dir, settings.backup_keep)
        except Exception:
            log.exception("Sicherung fehlgeschlagen")
        await asyncio.sleep(BACKUP_INTERVAL_S)


def _close_request_db(request: Request) -> None:
    """⚠️ 0.16: Die DB-Sitzung der Anfrage am Ende IMMER schliessen.

    get_db() schliesst sie zwar - aber bei einem Fehler (404, 403, 500) schon
    VOR dem Fehler-Handler. Der rendert die Fehlerseite und fragt dabei erneut
    die Datenbank (Benutzer, Zaehler) -> neue Verbindung, die niemand mehr
    zurueckgab. Nach 15 solchen Seiten war der Verbindungs-Pool leer und jede
    weitere Anfrage endete nach 30 s in Fehler 500."""
    db = getattr(request.state, "db", None)
    if db is not None:
        try:
            db.close()
        except Exception:  # pragma: no cover
            log.warning("DB-Sitzung liess sich nicht schliessen", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_storage(settings)
        engine = make_engine(settings.db_path)
        init_db(engine)
        app.state.engine = engine
        app.state.SessionLocal = make_sessionmaker(engine)
        with app.state.SessionLocal() as db:
            _remove_password_copies(settings)  # 0.9: Passwort-Anzeige entfernt - Reste loeschen
            shots.backfill(db, settings)
            shots.convert_existing(db, settings)
            accounts.backfill(db)  # 0.6: Postings ohne Account (alte Daten) zuordnen
            ocr.reflow_existing(db)  # 0.6.2: zerhackte OCR-Zeilen zu Absaetzen
            dates.backfill_from_ids(db)  # 0.6.3: fehlendes Datum aus der Beitrags-ID
            media.backfill_thumbs(db, settings)  # 0.11: Vorschaubilder fuer gesicherte Bilder
        _bootstrap_admin(app, settings)

        tasks: list[asyncio.Task] = []
        app.state.worker = None
        if settings.worker_enabled:
            from .services.capture import CaptureWorker

            app.state.worker = CaptureWorker(settings, app.state.SessionLocal)
            await app.state.worker.start()
            tasks.append(asyncio.create_task(_backup_loop(settings), name="sgc-backup"))
        log.info("%s %s bereit. Daten: %s", APP_NAME, VERSION, settings.base_path)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            if app.state.worker:
                await app.state.worker.stop()
            engine.dispose()

    app = FastAPI(
        title=APP_NAME,
        version=VERSION,
        lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,  # keine oeffentliche API-Doku
        dependencies=[Depends(csrf_protect)],
    )
    app.state.settings = settings
    app.state.setup_code = None

    @app.middleware("http")
    async def csrf_cookie_and_setup(request: Request, call_next):
        # Token fuer Formulare ohne Login (Login, Ersteinrichtung).
        anon = request.cookies.get(CSRF_COOKIE)
        fresh = None
        if not anon:
            anon = fresh = secrets.token_urlsafe(32)
        request.state.anon_csrf = anon
        request.state.user = None
        request.state.csrf_token = ""

        # Solange niemand existiert, fuehren alle Wege zur Ersteinrichtung.
        path = request.url.path
        if (app.state.setup_code and not path.startswith(("/setup", "/static", "/health", "/manifest"))):
            response = redirect(request, "/setup")
        else:
            try:
                response = await call_next(request)
            finally:
                _close_request_db(request)

        if fresh:
            response.set_cookie(CSRF_COOKIE, fresh, httponly=True, samesite="strict",
                                secure=settings.cookie_secure, path=cookie_path(request))
        # Sicherheits-Header. Kein X-Frame-Options: DENY, sonst geht das
        # HA-Ingress-Panel (iframe, gleicher Ursprung) nicht.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        return response

    # --- Fehlerbehandlung ---------------------------------------------------
    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        # Nach dem Login zurueck dorthin, wo man hinwollte (z. B. /teilen?url=...).
        target = "/login"
        if request.method == "GET" and request.url.path not in ("/", "/login"):
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            target += "?" + urlencode({"next": path})
        return redirect(request, target)

    @app.exception_handler(PasswordChangeRequired)
    async def _pw_change(request: Request, _exc: PasswordChangeRequired):
        return redirect(request, "/settings/konto?pflicht=1")

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        messages = {
            403: exc.detail if isinstance(exc.detail, str) and exc.detail != "Forbidden" else "Keine Berechtigung.",
            404: "Diese Seite gibt es nicht.",
            405: "Diese Aktion ist hier nicht möglich.",
        }
        msg = messages.get(exc.status_code, "Da ist etwas schiefgelaufen.")
        if request.headers.get("hx-request"):
            return HTMLResponse(f'<div class="flash flash-error">{msg}</div>', status_code=exc.status_code)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": msg}, status_code=exc.status_code)
        try:
            return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=msg)
        finally:
            _close_request_db(request)

    @app.exception_handler(Exception)
    async def _server_error(request: Request, exc: Exception):
        """Unerwarteter Fehler: verstaendliche Seite statt "Internal Server Error".
        Der vollstaendige Fehler steht im Add-on-Protokoll."""
        from sqlalchemy.exc import OperationalError

        busy = isinstance(exc, OperationalError) and "locked" in str(exc).lower()
        log.error("Fehler bei %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        code = 503 if busy else 500
        msg = ("Die Datenbank war gerade beschäftigt – bitte in ein paar Sekunden noch einmal versuchen."
               if busy else "Da ist etwas schiefgelaufen. Bitte noch einmal versuchen – der Fehler steht im Add-on-Protokoll.")
        if request.headers.get("hx-request"):
            return HTMLResponse(f'<div class="flash flash-error">{msg}</div>', status_code=code,
                                headers={"HX-Reswap": "none",
                                         "HX-Trigger": json.dumps({"toast": {"message": msg, "kind": "error"}})})
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": msg}, status_code=code)
        try:
            return render(request, "error.html", status_code=code, code=code, message=msg, retry=True)
        except Exception:  # pragma: no cover - auch das Rendern kann scheitern (z. B. DB weg)
            return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>Fehler</title><p>{msg}</p>", status_code=code)
        finally:
            _close_request_db(request)

    # --- Routen ---------------------------------------------------------------
    @app.get("/health", include_in_schema=False)
    async def health() -> Response:
        return JSONResponse({"status": "ok", "version": VERSION})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest(request: Request) -> Response:
        """PWA-Manifest: App-Icon, Vollbild am Handy und Teilen-Ziel (Android)."""
        base = root_path(request)
        icon = lambda name, size, purpose: {  # noqa: E731
            "src": f"{base}/static/brand/{name}?v={VERSION}", "sizes": f"{size}x{size}",
            "type": "image/png", "purpose": purpose}
        data = {
            "name": APP_NAME,
            "short_name": APP_NAME,
            "description": "Quellenarchiv für öffentliche Postings von X und Bluesky",
            "lang": "de",
            "start_url": f"{base}/",
            "scope": f"{base}/",
            "display": "standalone",
            "background_color": "#16181c",
            "theme_color": "#16181c",
            "icons": [icon("icon-192.png", 192, "any"), icon("icon-512.png", 512, "any"),
                      icon("icon-maskable-192.png", 192, "maskable"), icon("icon-maskable-512.png", 512, "maskable")],
            "share_target": {"action": f"{base}/teilen", "method": "GET",
                             "params": {"title": "title", "text": "text", "url": "url"}},
            "shortcuts": [
                {"name": "Personen", "url": f"{base}/personen"},
                {"name": "Suchgenerator", "url": f"{base}/generator"},
            ],
        }
        return JSONResponse(data, media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    for router in (auth.router, account.router, settings_router.router, posts.router, persons.router,
                   imports.router, lists.router, gallery.router, generator.router, admin.router,
                   api.router, help.router, ideas.router, research.router, comments.router, tagrules.router, collage.router, palette.router, saved.router):
        app.include_router(router)

    # Ingress ganz aussen, damit root_path schon bei allem anderen gesetzt ist.
    app.add_middleware(IngressMiddleware)
    return app


def _configure_logging() -> None:
    import os

    level = os.environ.get("SGC_LOG_LEVEL", "info").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# Nur fuer uvicorn app.main:app. Die Tests rufen create_app() selbst auf.
_configure_logging()
app = create_app()

__all__ = ["app", "create_app", "root_path"]
