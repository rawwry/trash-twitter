"""Einstellungen: alles Persoenliche an einem Ort, dazu Tags und Infos.

Admin-Bereiche (Benutzer, System, Protokoll) haengen weiterhin am
Admin-Router mit require_admin und nutzen nur dasselbe Layout.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Tag, User
from ..prefs import PREFS, get_prefs, section_prefs, update_prefs
from ..security import (
    SESSION_COOKIE,
    destroy_user_sessions,
    get_db,
    get_settings,
    password_problem,
    require_user,
    require_user_allow_pw_change,
    set_password,
    verify_password,
)
from ..services import avatars
from ..services import posts as post_service
from ..templating import redirect, render, root_path, toast_header

router = APIRouter(prefix="/settings")

PREF_SECTIONS = {
    "darstellung": ("Darstellung", "Erscheinungsbild, Farben und Bewegung"),
    "archiv": ("Archiv", "Ansicht, Sortierung und Hinzufügen"),
    "suchgenerator": ("Suchgenerator", "Startplattform und Sortierung"),
    "teilen": ("Teilen & Kürzel", "Aus anderen Apps teilen, Tastenkürzel"),
}


@router.get("")
def overview(request: Request, user: User = Depends(require_user)):
    return render(request, "settings/overview.html", section="")


# --- Konto ----------------------------------------------------------------------

@router.get("/konto")
def konto(request: Request, user: User = Depends(require_user_allow_pw_change)):
    return render(request, "settings/konto.html", section="konto", forced=user.must_change_password)


@router.post("/konto/passwort")
def change_password(request: Request, current: str = Form(""), new: str = Form(""), new2: str = Form(""),
                    user: User = Depends(require_user_allow_pw_change), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)):
    error = None
    if not verify_password(user.password_hash, current):
        error = "Das aktuelle Passwort stimmt nicht."
    elif new != new2:
        error = "Die beiden neuen Passwörter stimmen nicht überein."
    elif new == current:
        error = "Das neue Passwort muss sich vom alten unterscheiden."
    else:
        error = password_problem(new)
    if error:
        return render(request, "settings/konto.html", status_code=400, section="konto", error=error,
                      forced=user.must_change_password)
    was_forced = user.must_change_password
    set_password(settings, user, new, must_change=False)
    destroy_user_sessions(db, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
    db.commit()
    if was_forced:
        return redirect(request, "/", toast="Passwort gespeichert. Willkommen!")
    return render(request, "settings/konto.html", section="konto", forced=False,
                  toast={"message": "Passwort geändert. Andere Geräte wurden abgemeldet.", "kind": "ok"})


@router.post("/konto/profil")
async def save_profile(request: Request, display_name: str = Form(""), avatar: UploadFile | None = File(None),
                       remove_avatar: str = Form(""), user: User = Depends(require_user),
                       db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    name = " ".join(display_name.split())[:40]
    user.display_name = "" if name == user.username else name
    if remove_avatar:
        avatars.remove(settings, user)
    elif avatar is not None and avatar.filename:
        data = await avatar.read(avatars.MAX_BYTES + 1)
        try:
            avatars.save(settings, user, data)
        except avatars.AvatarError as exc:
            db.rollback()
            return render(request, "settings/konto.html", status_code=400, section="konto",
                          profile_error=str(exc), forced=False)
    db.commit()
    return redirect(request, "/settings/konto", toast="Profil gespeichert")


@router.post("/konto/abmelden")
def logout_others(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    destroy_user_sessions(db, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
    db.commit()
    return redirect(request, "/settings/konto", toast="Alle anderen Geräte sind abgemeldet.")


# --- Persoenliche Einstellungen -----------------------------------------------------

def _base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "homeassistant.local:8780"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}{root_path(request)}"


@router.post("/prefs")
async def save_prefs(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    form = await request.form()
    values = {p.key: str(form[p.key]) for p in PREFS if p.key in form}
    changed = update_prefs(user, values)
    db.commit()
    section = str(form.get("section", ""))
    if request.headers.get("hx-request"):
        response = Response(status_code=204)
        return toast_header(response, "Gespeichert" if changed else "Nichts geändert")
    target = f"/settings/{section}" if section in PREF_SECTIONS else "/settings"
    return redirect(request, target, toast="Gespeichert")


# --- Tags (gemeinsam) -------------------------------------------------------------

@router.get("/tags")
def tags(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..services import tags as tag_service

    groups, loose = tag_service.tree(db)
    return render(request, "settings/tags.html", section="tags", groups=groups, loose=loose,
                  cleanup=tag_service.cleanup(db))


def _get_tag(db: Session, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404)
    return tag


@router.post("/tags/{tag_id}/rename")
def rename_tag(request: Request, tag_id: int, name: str = Form(""), user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    tag = _get_tag(db, tag_id)
    old = tag.name
    new = post_service.normalize_tag(name)
    merged = new != old and db.scalar(select(Tag.id).where(Tag.name == new)) is not None
    error = post_service.rename_tag(db, tag, name)
    if error:
        return redirect(request, "/settings/tags", toast=error, kind="error")
    if new == old:
        return redirect(request, "/settings/tags", toast="Nichts geändert")
    return redirect(request, "/settings/tags",
                    toast=f"#{old} mit #{new} zusammengeführt" if merged else f"#{old} heißt jetzt #{new}")


@router.post("/tags/group")
def create_group(request: Request, name: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..services import tags as tag_service

    try:
        tag = tag_service.get_or_create_group(db, name)
    except tag_service.TagError as exc:
        db.rollback()
        return redirect(request, "/settings/tags", toast=str(exc), kind="error")
    db.commit()
    return redirect(request, "/settings/tags", toast=f"Oberbegriff #{tag.name} angelegt")


@router.post("/tags/{tag_id}/move")
def move_tag(request: Request, tag_id: int, parent: str = Form(""), user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    from ..services import tags as tag_service

    tag = _get_tag(db, tag_id)
    target = db.get(Tag, int(parent)) if parent.isdigit() else None
    try:
        tag_service.move(db, tag, target)
    except tag_service.TagError as exc:
        db.rollback()
        return redirect(request, "/settings/tags", toast=str(exc), kind="error")
    db.commit()
    msg = f"#{tag.name} steht jetzt unter #{target.name}" if target else f"#{tag.name} hat keinen Oberbegriff mehr"
    return redirect(request, f"/settings/tags#tag-{tag.id}", toast=msg)


@router.post("/tags/{tag_id}/ungroup")
def ungroup_tag(request: Request, tag_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..services import tags as tag_service

    tag = _get_tag(db, tag_id)
    name = tag.name
    tag_service.ungroup(db, tag)
    db.commit()
    return redirect(request, "/settings/tags", toast=f"Oberbegriff #{name} aufgelöst")


@router.post("/tags/bulk")
def bulk_tags(request: Request, ids: list[int] = Form(default=[]), action: str = Form(""), parent: str = Form(""),
              name: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Mehrere Tags auf einmal: einordnen, zusammenfuehren, loeschen."""
    from ..services import tags as tag_service

    tags = [t for t in (db.get(Tag, i) for i in dict.fromkeys(ids[:500])) if t is not None]
    if not tags:
        return redirect(request, "/settings/tags", toast="Keine Tags ausgewählt.", kind="error")
    try:
        if action == "move":
            target = db.get(Tag, int(parent)) if parent.isdigit() else None
            for tag in tags:
                tag_service.move(db, tag, target)
            msg = f"{len(tags)} Tags unter #{target.name} eingeordnet" if target else f"{len(tags)} Tags ohne Oberbegriff"
        elif action == "merge":
            new = post_service.normalize_tag(name) or tags[0].name
            target = db.scalar(select(Tag).where(Tag.name == new))
            if target is None:
                target = tags[0]
                target.name = new
            for tag in tags:
                if tag.id != target.id:
                    tag_service.merge_into(db, tag, target)
            msg = f"{len(tags)} Tags zu #{new} zusammengeführt"
        elif action in ("figur", "thema"):
            for tag in tags:
                tag.kind = action
            msg = f"{len(tags)} Tags sind jetzt {'Figuren' if action == 'figur' else 'Themen'}"
        elif action == "delete":
            for tag in tags:
                for child in list(tag.children):
                    child.parent_id = None
                db.delete(tag)
            msg = f"{len(tags)} Tags gelöscht"
        else:
            return redirect(request, "/settings/tags", toast="Unbekannte Aktion.", kind="error")
    except tag_service.TagError as exc:
        db.rollback()
        return redirect(request, "/settings/tags", toast=str(exc), kind="error")
    db.commit()
    return redirect(request, "/settings/tags", toast=msg)


@router.post("/tags/{tag_id}/delete")
def delete_tag(request: Request, tag_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tag = _get_tag(db, tag_id)
    name = tag.name
    for child in list(tag.children):  # Unter-Tags bleiben, nur ohne Oberbegriff
        child.parent_id = None
    db.delete(tag)
    db.commit()
    return redirect(request, "/settings/tags", toast=f"#{name} gelöscht")


# --- Info ---------------------------------------------------------------------------

@router.get("/info")
def info(request: Request, user: User = Depends(require_user)):
    return render(request, "settings/info.html", section="info", prefs=get_prefs(user))


# Muss als LETZTE GET-Route stehen, sonst schluckt sie /tags und /info.
# --- Persoenlicher Schluessel fuer Kurzbefehle (0.11.0) ---------------------------

@router.post("/schluessel")
def create_api_token(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..security import new_api_token

    token = new_api_token(user)
    db.commit()
    return render(request, "partials/api_token.html", new_token=token)


@router.post("/schluessel/loeschen")
def delete_api_token(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..security import revoke_api_token

    revoke_api_token(user)
    db.commit()
    return toast_header(render(request, "partials/api_token.html"), "Schlüssel gelöscht – Kurzbefehle damit funktionieren nicht mehr")


@router.get("/{section}")
def pref_section(request: Request, section: str, user: User = Depends(require_user)):
    if section not in PREF_SECTIONS:
        raise HTTPException(status_code=404)
    title, _sub = PREF_SECTIONS[section]
    return render(request, "settings/prefs.html", section=section, title=title,
                  items=section_prefs(section), base_url=_base_url(request))
