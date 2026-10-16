"""Schnittstelle fuer Kurzbefehle: Teilen auf iPhone/Android -> direkt ins Archiv.

    POST /api/teilen
    Authorization: Bearer <persoenlicher Schluessel>
    Formular (url=... oder text=...) oder JSON {"url": "..."}

Antwort: eine kurze Zeile Text (fuer "Mitteilung anzeigen" im Kurzbefehl),
mit ?format=json als JSON. Kein Login-Cookie noetig, kein CSRF (siehe security.py).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ..config import Settings
from ..security import get_db, get_settings, user_from_api_token
from ..services import posts as post_service
from ..services.citation import archive_no

router = APIRouter(prefix="/api")

_URL = re.compile(r"https?://\S+")


def _reply(request: Request, ok: bool, message: str, status: int = 200, post_id: int | None = None):
    if request.query_params.get("format") == "json":
        return JSONResponse({"ok": ok, "message": message, "id": post_id}, status_code=status)
    return PlainTextResponse(message, status_code=status)


@router.post("/teilen")
async def share(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = user_from_api_token(db, request.headers.get("authorization"))
    if user is None:
        return _reply(request, False, "TrashTwitter: Schlüssel fehlt oder ist ungültig.", 401)
    raw = ""
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = await request.json()
            raw = " ".join(str(data.get(k) or "") for k in ("url", "text"))
        except ValueError:
            raw = ""
    else:
        form = await request.form()
        raw = " ".join(str(form.get(k) or "") for k in ("url", "text", "title"))
    # Apps teilen mal den nackten Link, mal "Schau mal https://..." - ersten passenden Link nehmen.
    candidates = _URL.findall(raw) or [raw.strip()]
    url = next((c for c in candidates if post_service.detect_ok(c)), "")
    if not url:
        return _reply(request, False, "Kein Link zu einem Posting auf X (Twitter) oder Bluesky gefunden.", 400)
    try:
        post = await post_service.add_post(db, user, url, "", "", network=settings.network_enabled)
    except post_service.AddPostError as exc:
        db.rollback()
        if exc.existing is not None:
            return _reply(request, False, f"Schon im Archiv (Nr. {archive_no(exc.existing)}).", 200, exc.existing.id)
        return _reply(request, False, str(exc), 400)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.enqueue(post.id)
    who = f"@{post.author_handle}" if post.author_handle else "Posting"
    return _reply(request, True, f"Archiviert: {who} (Nr. {archive_no(post)}). Wortlaut und Beleg folgen.", 201, post.id)
