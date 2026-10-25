"""Collage-Studio (0.22): Postings auswaehlen, gestalten, als JPG speichern.

  /collage               Studio. Quelle: ?ids=1,2,3 (Auswahl) oder die Filter
                         des Idiotariums (?q=…&tags=…&person=…&list=…).
  /collage/vorschau      Die Collage-Seite selbst (fuer das iframe im Studio).
  /collage/bild.jpg      Export: dieselbe Seite, per Playwright als JPG.
Logik und Optionen in services/collage.py, Anordnung in static/collage.js.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from markupsafe import Markup, escape
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Person, PostList
from ..security import get_db, get_settings, require_user
from ..services import collage as svc
from ..services import posts as post_service
from ..services.citation import archive_no
from ..templating import _localtime, render, root_path, templates

router = APIRouter(dependencies=[Depends(require_user)])
log = logging.getLogger("sgc")
_export_lock = asyncio.Lock()   # ein Export nach dem anderen - Chromium braucht Speicher


def _marked(text: str, words: str) -> Markup:
    """Suchwoerter (als Wortanfang/Stamm) im Text markieren."""
    stems = [post_service.search_stem(w) for w in re.findall(r"[\wäöüß]{3,}", (words or "").lower())]
    stems = [s.lower() for s in stems if len(s) >= 3]
    if not stems:
        return escape(text)
    rx = re.compile(r"(?<!\w)(" + "|".join(re.escape(s) for s in sorted(set(stems), key=len, reverse=True)) + r")\w*", re.IGNORECASE)
    out, pos = [], 0
    for m in rx.finditer(text):
        out.append(escape(text[pos:m.start()]))
        out.append(Markup("<mark>") + escape(m.group(0)) + Markup("</mark>"))
        pos = m.end()
    out.append(escape(text[pos:]))
    return Markup("".join(str(x) for x in out))


def _cards(request: Request, settings: Settings, posts, opts: svc.Options, inline: bool) -> list[dict]:
    from ..templating import _post_avatar

    root = root_path(request)
    cards = []
    for p in posts:
        handle = (p.account.handle if p.account and p.account.handle else p.author_handle) or ""
        thumb = next((m.thumb_path for m in p.media if m.thumb_path), None) if opts.media else None
        shot = None
        if p.screenshot_path:
            shot = svc.file_source(settings, p.screenshot_path, inline, f"{root}/media") if inline else f"{root}/media/{p.screenshot_path}"
        if not inline and thumb:
            thumb_src = f"{root}/medien/{thumb}"
        else:
            thumb_src = svc.file_source(settings, thumb, True, "") if thumb else ""
        cards.append(dict(
            name=p.author_name, handle=handle.lstrip("@"), platform=p.platform,
            avatar=svc.file_source(settings, _post_avatar(p), inline, root),
            initial=(p.author_name or "?").lstrip("@")[:1].upper(),
            text=_marked(p.text or "", opts.highlight), media=thumb_src,
            date=_localtime(p.posted_at, "%d.%m.%Y") if p.posted_at else "", no=archive_no(p),
            gone=p.origin_state == "gone", shot=shot,
            ratio=round((p.shot_h or 1) / (p.shot_w or 1), 4) if p.shot_w and p.shot_h else 1.0,
        ))
    return cards


def _html(request: Request, settings: Settings, posts, opts: svc.Options, inline: bool) -> str:
    width, height = opts.size
    static_url = f"{root_path(request)}/static"
    return templates.get_template("collage_render.html").render(
        request=request, opts=opts, width=width, height=height, cards=_cards(request, settings, posts, opts, inline),
        fonts=svc.font_faces(inline, static_url), script=svc.collage_script(),
        today=datetime.now().strftime("%d.%m.%Y"))


def _source(request: Request, db: Session):
    """Postings und Vorbelegung aus ?ids= oder aus den Filtern des Idiotariums."""
    params = request.query_params
    ids = svc.parse_ids(params.get("ids", ""))
    flt = post_service.filter_from_params(params, default_sort="posted")
    if not ids:
        found, _ = post_service.search_archive(db, flt, per_page=svc.MAX_POSTS)
        ids = [p.id for p in found]
    posts = [p for p in svc.load_posts(db, ids) if p.status == "done"]
    if flt.tags:
        title = " ".join("#" + t for t in flt.tags)
    elif flt.q:
        title = f"„{flt.q}“"
    elif flt.person_id and (person := db.get(Person, flt.person_id)):
        title = person.name
    elif flt.list_id and (pl := db.get(PostList, flt.list_id)):
        title = pl.title
    else:
        title = "Sammlung"
    return posts, title, flt.q


@router.get("/collage")
def studio(request: Request, db: Session = Depends(get_db)):
    posts, title, q = _source(request, db)
    return render(request, "collage.html", nav="archive", posts=posts, title=title, subtitle=svc.default_subtitle(posts),
                  highlight=q, formats=svc.FORMATS, styles=svc.STYLES, modes=svc.MODES, max_posts=svc.MAX_POSTS,
                  has_shots=any(p.screenshot_path for p in posts))


@router.get("/collage/vorschau", response_class=HTMLResponse)
def preview(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    opts = svc.Options.from_params(request.query_params)
    posts = svc.load_posts(db, svc.parse_ids(request.query_params.get("ids", "")))
    return HTMLResponse(_html(request, settings, posts, opts, inline=False),
                        headers={"Cache-Control": "private, no-store"})


@router.get("/collage/bild.jpg")
async def export(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    opts = svc.Options.from_params(request.query_params)
    posts = svc.load_posts(db, svc.parse_ids(request.query_params.get("ids", "")))
    if not posts:
        raise HTTPException(status_code=400, detail="Keine Postings ausgewählt.")
    html = _html(request, settings, posts, opts, inline=True)
    width, height = opts.size
    db.close()  # waehrend Chromium rendert, keine Datenbank-Verbindung festhalten
    async with _export_lock:
        try:
            data = await svc.render_with_browser(request.app, html, width, height)
        except Exception as exc:  # Chromium fehlt oder bricht ab
            log.exception("Collage-Export fehlgeschlagen")
            raise HTTPException(status_code=503, detail="Das Bild ließ sich gerade nicht erzeugen. Bitte gleich noch einmal versuchen.") from exc
    name = svc.export_name(opts, datetime.now())
    disp = "inline" if request.query_params.get("anzeigen") else "attachment"
    return Response(data, media_type="image/jpeg",
                    headers={"Content-Disposition": f'{disp}; filename="{name}"', "Cache-Control": "private, no-store"})
