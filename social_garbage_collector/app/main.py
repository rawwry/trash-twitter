"""Einstiegspunkt: baut die FastAPI-App zusammen.

    uvicorn app.main:app           (im Add-on, Einstellungen aus der Umgebung)
    create_app(Settings(...))      (in den Tests, mit eigenem Datenordner)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from starlette.exceptions import HTTPException

from . import APP_NAME, VERSION
from .config import Settings, prepare_storage
from .db import backup_database, init_db, make_engine, make_sessionmaker
from .models import ROLE_ADMIN, User
from .routers import account, admin, auth, gallery, generator, imports, lists, persons, posts
from .routers import settings as settings_router
from .security import (
    CSRF_COOKIE,
    LoginRequired,
    LoginThrottle,
    PasswordChangeRequired,
    cookie_path,
    csrf_protect,
    set_password,
)
from .services import accounts, admin_log, dates, ocr, shots
from .templating import redirect, render, root_path

log = logging.getLogger("sgc")

BACKUP_INTERVAL_S = 24 * 3600
MAX_REQUEST_BYTES = 105 * 1024 * 1024


class RequestSizeLimitMiddleware:
    """Begrenzt auch Multipart/Chunked-Requests vor dem vollstaendigen Einlesen."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            too_large = int(headers.get(b"content-length", b"0")) > MAX_REQUEST_BYTES
        except ValueError:
            too_large = True
        if too_large:
            return await JSONResponse({"detail": "Upload zu groß (höchstens 100 MB plus Formulardaten)."},
                                      status_code=413)(scope, receive, send)
        size = 0
        exceeded = rejected = False

        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            size += len(message.get("body", b""))
            if size > MAX_REQUEST_BYTES:
                exceeded = True
                raise HTTPException(status_code=413, detail="Upload zu groß.")
            return message

        async def limited_send(message):
            nonlocal rejected
            if exceeded:
                if not rejected:
                    await JSONResponse({"detail": "Upload zu groß."}, status_code=413)(scope, receive, send)
                    rejected = True
                return
            await send(message)

        # Multipart-Parser koennen einen Empfangsfehler als 400 behandeln.
        # Die tatsaechliche Groessenueberschreitung bleibt nach aussen eine 413.
        await self.app(scope, limited_receive, limited_send)


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
        code = secrets.token_hex(16).upper()
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_storage(settings)
        engine = make_engine(settings.db_path)
        init_db(engine, settings.backup_dir)
        app.state.engine = engine
        app.state.SessionLocal = make_sessionmaker(engine)
        with app.state.SessionLocal() as db:
            _remove_password_copies(settings)  # 0.9: Passwort-Anzeige entfernt - Reste loeschen
            shots.backfill(db, settings)
            shots.convert_existing(db, settings)
            accounts.backfill(db)  # 0.6: Aussagen ohne Account (alte Daten) zuordnen
            ocr.reflow_existing(db)  # 0.6.2: zerhackte OCR-Zeilen zu Absaetzen
            dates.backfill_from_ids(db)  # 0.6.3: fehlendes Datum aus der Beitrags-ID
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
    app.state.setup_throttle = LoginThrottle()

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
            response = await call_next(request)

        if fresh:
            response.set_cookie(CSRF_COOKIE, fresh, httponly=True, samesite="strict",
                                secure=settings.cookie_secure, path=cookie_path(request))
        # Sicherheits-Header. Kein X-Frame-Options: DENY, sonst geht das
        # HA-Ingress-Panel (iframe, gleicher Ursprung) nicht.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'")
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
        return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=msg)

    # --- Routen ---------------------------------------------------------------
    @app.get("/health", include_in_schema=False)
    def health() -> Response:
        try:
            with app.state.engine.connect() as conn:
                database = conn.execute(text("SELECT 1")).scalar() == 1
        except Exception:
            database = False
        storage = settings.db_path.is_file() and all(path.is_dir() and os.access(path, os.R_OK | os.W_OK)
                      for path in (settings.db_dir, settings.screenshot_dir, settings.gallery_dir))
        worker = getattr(app.state, "worker", None)
        worker_ok = not settings.worker_enabled or bool(worker and worker._task and not worker._task.done())
        ok = database and storage and worker_ok
        return JSONResponse({"status": "ok" if ok else "error", "version": VERSION,
                             "checks": {"database": database, "storage": storage, "worker": worker_ok}},
                            status_code=200 if ok else 503)

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
            "description": "Quellenarchiv für öffentliche Aussagen von X und Bluesky",
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
                   imports.router, lists.router, gallery.router, generator.router, admin.router):
        app.include_router(router)

    app.add_middleware(RequestSizeLimitMiddleware)
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
