"""Archiv: Postings hinzufuegen, ansehen, korrigieren, suchen; Screenshots und Profilbilder ausliefern."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..models import STATUS_DONE, STATUS_ERROR, TEXT_MANUAL, ListPost, Person, Post, PostList, User
from ..prefs import get_prefs, update_prefs
from ..security import get_db, get_settings, require_user
from ..services import posts as post_service
from ..services import shots
from ..services.capture import reset_for_retry
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])


def _get_post(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    return post


def _enqueue(request: Request, post: Post) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.enqueue(post.id)


def _query_without(request: Request, *keys: str) -> str:
    return urlencode([(k, v) for k, v in request.query_params.multi_items() if k not in keys and v])


# --------------------------------------------------------------------------
# Archiv
# --------------------------------------------------------------------------

@router.get("/")
def archive(request: Request, page: int = 1, user: User = Depends(require_user), db: Session = Depends(get_db)):
    prefs = get_prefs(user)
    # Darstellung direkt im Archiv umschalten - und fuer das naechste Mal merken.
    view = request.query_params.get("view")
    if view and view != prefs["archive_view"] and update_prefs(user, {"archive_view": view}):
        db.commit()
        prefs = get_prefs(user)
    flt = post_service.filter_from_params(request.query_params, default_sort=prefs["sort"])
    per_page = int(prefs["per_page"])
    items, total = post_service.search_archive(db, flt, page=page, per_page=per_page)
    ctx = dict(
        posts=items, total=total, page=page, has_more=page * per_page < total, f=flt,
        view=prefs["archive_view"],
        query_string=_query_without(request, "page", "more", "after_group", "view"),
        # Zeitachse: Monats-Ueberschriften ueber "Mehr laden" hinweg nicht doppeln.
        after_group=request.query_params.get("after_group", ""),
        filter_person=db.get(Person, flt.person_id) if flt.person_id else None,
    )
    hx_target = request.headers.get("hx-target") if request.headers.get("hx-request") else None
    if hx_target == "results":
        return render(request, "partials/results.html", **ctx)
    if request.query_params.get("more"):
        return render(request, "partials/more.html", **ctx)
    ctx.update(
        all_lists=list(db.scalars(select(PostList).order_by(PostList.title))),
        all_users=list(db.scalars(select(User).order_by(User.username))),
    )
    return render(request, "archive.html", **ctx)


# --------------------------------------------------------------------------
# Hinzufuegen (Sheet, eigene Seite, Teilen-Ziel)
# --------------------------------------------------------------------------

_URL_IN_TEXT = re.compile(r"https?://\S+")


@router.get("/add")
def add_page(request: Request, url: str = "", mode: str = "link", user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    check = post_service.check_url(db, url) if url else None
    return render(request, "add.html", form_url=url, check=check,
                  mode=mode if mode in ("upload", "bulk", "thread") else "link")


@router.get("/teilen")
def share_target(request: Request, url: str = "", text: str = "", title: str = "",
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Ziel fuer "Teilen" aus anderen Apps (Android-PWA, iOS-Kurzbefehl, Lesezeichen).

    Apps packen den Link mal in url, mal in text ("Schau mal https://..."),
    deshalb suchen wir in allen Feldern nach dem ersten Link.
    """
    found = url.strip()
    if not post_service.detect_ok(found):
        for candidate in _URL_IN_TEXT.findall(f"{text} {title} {url}"):
            if post_service.detect_ok(candidate):
                found = candidate
                break
    check = post_service.check_url(db, found) if found else None
    return render(request, "add.html", form_url=found, check=check, shared=True)


@router.get("/posts/check")
def check_link(request: Request, url: str = "", db: Session = Depends(get_db)):
    """Live-Pruefung waehrend des Einfuegens: Plattform, Verfasser, schon vorhanden?"""
    check = post_service.check_url(db, url[:500])
    return render(request, "partials/link_check.html", check=check)


@router.post("/posts/bulk/list")
def bulk_to_list(request: Request, ids: list[int] = Form(default=[]), list_id: int = Form(0),
                 new_list: str = Form(""), back: str = Form("/"), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    """Mehrfachauswahl im Archiv: alle markierten Beitraege in eine Liste legen."""
    from .auth import safe_next

    back = safe_next(back)
    ids = list(dict.fromkeys(ids))[:500]
    if not ids:
        return redirect(request, back, toast="Keine Postings ausgewählt.", kind="error")
    title = " ".join(new_list.split())[:120]
    if title:
        target = PostList(title=title, created_by_id=user.id)
        db.add(target)
        db.flush()
    else:
        target = db.get(PostList, list_id) if list_id else None
        if target is None:
            return redirect(request, back, toast="Bitte eine Liste auswählen.", kind="error")
    added, already = post_service.add_many_to_list(db, user, ids, target)
    message = f"{added} {'Posting' if added == 1 else 'Postings'} in „{target.title}“ abgelegt"
    if already:
        message += f" ({already} waren schon drin)"
    return redirect(request, back, toast=message)


@router.post("/posts")
async def add_post(request: Request, url: str = Form(""), note: str = Form(""), tags: str = Form(""),
                   thread_extra: str = Form(""),
                   user: User = Depends(require_user), db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)):
    # Checkbox "Threads erkennen": angehakt -> "auto", sonst fehlt das Feld -> "off"
    try:
        post = await post_service.add_post(db, user, url, note, tags, network=settings.network_enabled,
                                           thread_extra=thread_extra[:5000])
    except post_service.AddPostError as exc:
        db.rollback()
        return render(request, "add.html", status_code=400, add_error=str(exc), existing=exc.existing,
                      form_url=url, form_note=note, form_tags=tags,
                      form_thread_extra=thread_extra, check=None)
    _enqueue(request, post)
    target = "/" if get_prefs(user)["after_add"] == "archive" else f"/posts/{post.id}"
    return redirect(request, target, toast="Archiviert. Text, Verfasser und Beleg werden geholt …")


@router.post("/posts/thread")
async def add_thread(request: Request, thread_url: list[str] = Form(default=[]), note: str = Form(""),
                     tags: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings)):
    """Thread (0.14): alle Teile als Liste. Der erste ist das Posting, die weiteren
    werden wie "von Hand ergaenzte Teile" zu Wortlaut und Beleg zusammengesetzt."""
    urls = []
    for raw in thread_url[:40]:
        for part in (_URL_IN_TEXT.findall(raw) or [raw.strip()]):
            if part and part not in urls:
                urls.append(part[:500])
    if len(urls) < 2:
        error = "Bitte mindestens zwei Links eintragen – für ein einzelnes Posting reicht der Reiter „Link“."
        return render(request, "add.html", status_code=400, add_error=error, mode="thread",
                      form_thread_urls=urls + [""] * (2 - len(urls)), form_note=note, form_tags=tags)
    try:
        post = await post_service.add_post(db, user, urls[0], note, tags, network=settings.network_enabled,
                                           thread_extra="\n".join(urls[1:]))
    except post_service.AddPostError as exc:
        db.rollback()
        return render(request, "add.html", status_code=400, add_error=str(exc), existing=exc.existing, mode="thread",
                      form_thread_urls=urls, form_note=note, form_tags=tags)
    _enqueue(request, post)
    target = "/" if get_prefs(user)["after_add"] == "archive" else f"/posts/{post.id}"
    return redirect(request, target, toast=f"Thread mit {len(urls)} Teilen archiviert. Wortlaut und Beleg werden geholt …")


async def _read_files(files: list[UploadFile]) -> list[bytes]:
    from ..services.uploads import MAX_BYTES, MAX_FILES

    blobs = []
    for f in files[: MAX_FILES + 1]:
        if f and f.filename:
            blobs.append(await f.read(MAX_BYTES + 1))
    return blobs


@router.post("/posts/upload")
async def add_upload(request: Request, files: list[UploadFile] = File(default=[]), link: str = Form(""),
                     platform: str = Form(""), handle: str = Form(""), posted: str = Form(""),
                     text: str = Form(""), note: str = Form(""), tags: str = Form(""),
                     user: User = Depends(require_user), db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings)):
    """Beitrag aus eigenem Screenshot (z. B. geloeschte oder geschuetzte Tweets)."""
    blobs = await _read_files(files)
    try:
        post = await post_service.add_upload(db, user, settings, blobs, link=link[:500], platform=platform,
                                             handle=handle[:100], posted=posted, text_=text, note=note,
                                             tags_raw=tags, network=settings.network_enabled)
    except post_service.AddPostError as exc:
        db.rollback()
        return render(request, "add.html", status_code=400, add_error=str(exc), existing=exc.existing,
                      mode="upload", form_link=link, form_platform=platform, form_handle=handle,
                      form_posted=posted, form_text=text, form_note=note, form_tags=tags, check=None)
    _enqueue(request, post)
    target = "/" if get_prefs(user)["after_add"] == "archive" else f"/posts/{post.id}"
    return redirect(request, target, toast="Archiviert. Text wird aus dem Bild gelesen …")


@router.post("/posts/{post_id}/screenshot")
async def replace_shot(request: Request, post_id: int, files: list[UploadFile] = File(default=[]),
                       db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    post = _get_post(db, post_id)
    blobs = await _read_files(files)
    try:
        post_service.replace_screenshot(db, settings, post, blobs)
    except post_service.AddPostError as exc:
        return redirect(request, f"/posts/{post.id}#eigener-screenshot", toast=str(exc), kind="error")
    _enqueue(request, post)
    return redirect(request, f"/posts/{post.id}", toast="Eigener Screenshot gespeichert")


# --------------------------------------------------------------------------
# Detailseite
# --------------------------------------------------------------------------

@router.get("/posts/{post_id}")
def post_detail(request: Request, post_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    in_lists = {link.list_id for link in post.list_links}
    other_lists = [pl for pl in db.scalars(select(PostList).order_by(PostList.title)) if pl.id not in in_lists]
    newer, older = post_service.neighbors(db, post)
    from .research import notes_for_post

    return render(request, "post.html", post=post, other_lists=other_lists, newer=newer, older=older,
                  notes=notes_for_post(db, post.id))


@router.get("/posts/{post_id}/status")
def post_status(request: Request, post_id: int, db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    response = render(request, "partials/status.html", post=post)
    # Sobald fertig: Detailseite einmal neu laden, damit Screenshot und Text erscheinen.
    if post.status in (STATUS_DONE, STATUS_ERROR) and request.query_params.get("poll"):
        response.headers["HX-Refresh"] = "true"
    return response


@router.post("/posts/{post_id}/retry")
def retry(request: Request, post_id: int, db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    reset_for_retry(db, post)
    _enqueue(request, post)
    return redirect(request, f"/posts/{post.id}", toast="Neuer Versuch läuft …", kind="info")


@router.post("/posts/{post_id}/auto")
def back_to_auto(request: Request, post_id: int, db: Session = Depends(get_db)):
    """Hochgeladenen Screenshot wieder durch eine automatische Aufnahme ersetzen lassen."""
    post = _get_post(db, post_id)
    if not post.url:
        raise HTTPException(status_code=404)
    post.shot_source = "auto"
    reset_for_retry(db, post)
    _enqueue(request, post)
    return redirect(request, f"/posts/{post.id}", toast="Wird automatisch aufgenommen …", kind="info")


@router.post("/posts/{post_id}/thread")
def update_thread(request: Request, post_id: int, thread_extra: str = Form(""),
                  db: Session = Depends(get_db)):
    """Thread-Einstellungen aendern und den Beitrag neu erfassen."""
    import json

    post = _get_post(db, post_id)
    try:
        extras = post_service.parse_thread_extra(thread_extra[:5000], post.platform)
    except post_service.AddPostError as exc:
        return redirect(request, f"/posts/{post.id}#thread", toast=str(exc), kind="error")
    post.thread_mode = "off"  # automatische Erkennung seit 0.6.1 aus
    post.thread_extra = json.dumps(extras) if extras else ""
    reset_for_retry(db, post)
    _enqueue(request, post)
    return redirect(request, f"/posts/{post.id}", toast="Wird neu erfasst …", kind="info")


@router.post("/posts/{post_id}/text")
def update_text(request: Request, post_id: int, text: str = Form(""), db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    post.text = text.strip()[:20000]
    post.text_source = TEXT_MANUAL
    db.commit()
    return redirect(request, f"/posts/{post.id}", toast="Text gespeichert")


@router.post("/posts/{post_id}/date")
def update_date(request: Request, post_id: int, day: str = Form(""), clock: str = Form(""),
                db: Session = Depends(get_db)):
    """Datum des Postings von Hand setzen oder entfernen (leeres Feld)."""
    from ..services import dates

    post = _get_post(db, post_id)
    try:
        when, has_time = dates.parse_manual(day[:10], clock[:5])
    except ValueError:
        return redirect(request, f"/posts/{post.id}#datum", toast="Das Datum ist ungültig.", kind="error")
    if when is not None and dates._plausible(when) is None:
        return redirect(request, f"/posts/{post.id}#datum", toast="Das Datum liegt außerhalb des Möglichen.", kind="error")
    dates.set_date(post, when, dates.DATE_MANUAL, has_time)
    db.commit()
    return redirect(request, f"/posts/{post.id}", toast="Datum gespeichert" if when else "Datum entfernt")


@router.post("/posts/{post_id}/note")
def update_note(request: Request, post_id: int, note: str = Form(""), tags: str = Form(""),
                db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    post.note = note.strip()[: post_service.MAX_NOTE]
    post_service.set_post_tags(db, post, tags)
    db.commit()
    return redirect(request, f"/posts/{post.id}", toast="Notiz & Tags gespeichert")


@router.post("/posts/{post_id}/lists")
def add_to_list(request: Request, post_id: int, list_id: int = Form(0), new_list: str = Form(""),
                user: User = Depends(require_user), db: Session = Depends(get_db)):
    post = _get_post(db, post_id)
    target = None
    if new_list.strip():
        target = PostList(title=" ".join(new_list.split())[:120], created_by_id=user.id)
        db.add(target)
        db.flush()
    elif list_id:
        target = db.get(PostList, list_id)
    if target is None:
        raise HTTPException(status_code=404)
    if not db.get(ListPost, (target.id, post.id)):
        db.add(ListPost(list_id=target.id, post_id=post.id, added_by_id=user.id))
    db.commit()
    return redirect(request, f"/posts/{post.id}", toast=f"In „{target.title}“ abgelegt")


@router.post("/posts/{post_id}/lists/{list_id}/remove")
def remove_from_list(request: Request, post_id: int, list_id: int, back: str = Form(""),
                     db: Session = Depends(get_db)):
    link = db.get(ListPost, (list_id, post_id))
    if link:
        db.delete(link)
        db.commit()
    # Nur interne Ruecksprungziele, keine offene Weiterleitung.
    return redirect(request, f"/lists/{list_id}" if back == "list" else f"/posts/{post_id}",
                    toast="Aus der Liste entfernt")


@router.post("/posts/bulk/delete")
def bulk_delete(request: Request, ids: list[int] = Form(default=[]), back: str = Form("/"),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Mehrfachauswahl: alle markierten Postings loeschen (nach Rueckfrage im Browser)."""
    from .auth import safe_next

    ids = list(dict.fromkeys(ids))[:500]
    posts = list(db.scalars(select(Post).where(Post.id.in_(ids)))) if ids else []
    if not posts:
        return redirect(request, safe_next(back), toast="Keine Postings ausgewählt.", kind="error")
    n = post_service.delete_posts(db, settings, posts)
    return redirect(request, safe_next(back), toast=f"{n} {'Posting' if n == 1 else 'Postings'} gelöscht")


@router.get("/posts/{post_id}/delete")
def delete_confirm(request: Request, post_id: int, db: Session = Depends(get_db)):
    return render(request, "confirm_delete.html", post=_get_post(db, post_id))


@router.post("/posts/{post_id}/delete")
def delete_post(request: Request, post_id: int, db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings)):
    post = _get_post(db, post_id)
    post_service.delete_posts(db, settings, [post])
    if request.headers.get("hx-request") and request.headers.get("hx-target", "").startswith("post-"):
        # Schnell-Loeschen im Archiv: Karte verschwindet, Seite bleibt.
        from ..templating import toast_header

        return toast_header(Response(status_code=200), "Posting gelöscht")
    return redirect(request, "/", toast="Posting aus dem Archiv gelöscht")


@router.get("/tags/suggest")
def tag_suggest(request: Request, tq: str = "", tags: str = "", db: Session = Depends(get_db)):
    """Tag-Auswahl: vorhandene Tags zum Eingetippten (auch aehnlich geschriebene)."""
    from ..services import tags as tag_service

    taken = set(post_service.parse_tag_input(tags))
    suggestions, new = tag_service.suggest(db, tq[:64], taken)
    return render(request, "partials/tag_suggestions.html", suggestions=suggestions, new=new,
                  query=post_service.normalize_tag(tq))


@router.get("/avatars/{name}")
def avatar_file(name: str, settings: Settings = Depends(get_settings)):
    """Profilbilder - nur eingeloggt, nur aus dem Avatar-Ordner."""
    try:
        file = safe_path(settings.avatar_dir, name)
    except UnsafePathError:
        raise HTTPException(status_code=404)
    if not file.is_file() or file.suffix != ".webp":
        raise HTTPException(status_code=404)
    # Dateiname aendert sich bei jedem neuen Bild -> darf lange gecacht werden.
    return FileResponse(file, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/authors/{name}")
def author_avatar(name: str, settings: Settings = Depends(get_settings)):
    """Profilbilder der zitierten Accounts - nur eingeloggt, nur aus authors/."""
    try:
        file = safe_path(settings.author_dir, name)
    except UnsafePathError:
        raise HTTPException(status_code=404)
    if not file.is_file() or file.suffix != ".webp":
        raise HTTPException(status_code=404)
    # Name = Pruefsumme des Inhalts -> aendert sich nie.
    return FileResponse(file, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/medien/{path:path}")
def post_media_file(path: str, download: int = 0, settings: Settings = Depends(get_settings)):
    """Gesicherte Bilder/GIFs/Videos aus Postings - nur eingeloggt, nur aus media/.
    FileResponse beantwortet Range-Anfragen, damit Videos (auch in Safari) spulen."""
    from ..services.media import guess_mime

    try:
        file = safe_path(settings.base_path, path)
        file.relative_to(settings.media_dir.resolve())
    except (UnsafePathError, ValueError):
        raise HTTPException(status_code=404)
    if not file.is_file():
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    if download:
        return FileResponse(file, media_type=guess_mime(file.name), filename=file.name, headers=headers)
    return FileResponse(file, media_type=guess_mime(file.name), headers=headers)


@router.get("/media/{path:path}")
def media(path: str, download: int = 0, as_: str = Query("", alias="as"), settings: Settings = Depends(get_settings)):
    """Liefert Screenshots aus - nur aus dem Screenshot-Ordner, nur eingeloggt."""
    try:
        file = safe_path(settings.base_path, path)
        file.relative_to(settings.screenshot_dir.resolve())
    except (UnsafePathError, ValueError):
        raise HTTPException(status_code=404)
    if not file.is_file() or file.suffix.lower() not in (".webp", ".png"):
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": "private, max-age=86400"}
    if as_ == "jpg":
        # Teilen/Herunterladen: JPEG versteht jede App, WebP nicht jeder Messenger.
        name = file.with_suffix(".jpg").name
        disp = "attachment" if download else "inline"
        headers["Content-Disposition"] = f'{disp}; filename="{name}"'
        return Response(shots.as_jpeg(file), media_type="image/jpeg", headers=headers)
    media_type = "image/webp" if file.suffix == ".webp" else "image/png"
    if download:
        return FileResponse(file, media_type=media_type, filename=file.name, headers=headers)
    return FileResponse(file, media_type=media_type, headers=headers)
