"""Personen und ihre Accounts: Uebersicht, Detail, Zusammenfuehren, Trennen.

Alle Mitglieder duerfen zusammenfuehren und trennen (das Archiv wird
gemeinsam gepflegt). Jede Aenderung landet im Protokoll.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Person, Post, User
from ..config import Settings
from ..prefs import get_prefs, update_prefs
from ..security import get_db, get_settings, require_user
from ..services import accounts as account_service
from ..services import admin_log
from ..services import posts as post_service
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

PERSON_PAGE_POSTS = 30


def _get_person(db: Session, person_id: int) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404)
    return person


def _get_account(db: Session, account_id: int) -> Account:
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404)
    return acc


@router.get("/personen")
def overview(request: Request, q: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    # Kacheln oder Liste - umschalten direkt hier, wird pro Person gemerkt.
    view = request.query_params.get("view")
    if view and update_prefs(user, {"persons_view": view}):
        db.commit()
    sort = request.query_params.get("sort")
    if sort and update_prefs(user, {"persons_sort": sort}):
        db.commit()
    prefs = get_prefs(user)
    persons = account_service.list_persons(db, q[:100])
    stats = account_service.person_stats(db, [p.id for p in persons])
    # Personen ohne archiviertes Posting erscheinen nicht (z. B. nach dem Loeschen).
    persons = [p for p in persons if stats.get(p.id, {}).get("count", 0)]
    persons.sort(key=lambda p: p.name.lstrip("@").lower())
    if prefs["persons_sort"] == "posts":
        persons.sort(key=lambda p: -stats[p.id]["count"])
    elif prefs["persons_sort"] == "recent":
        persons.sort(key=lambda p: stats[p.id]["last"] or datetime.min, reverse=True)
    tpl = "partials/person_rows.html" if request.headers.get("hx-request") else "persons.html"
    return render(request, tpl, persons=persons, stats=stats, q=q, pview=prefs["persons_view"], psort=prefs["persons_sort"])


@router.get("/personen/{person_id}")
def detail(request: Request, person_id: int, db: Session = Depends(get_db)):
    person = _get_person(db, person_id)
    flt = post_service.ArchiveFilter(person_id=person.id, sort="posted")
    posts, total = post_service.search_archive(db, flt, per_page=PERSON_PAGE_POSTS)
    stats = account_service.person_stats(db, [person.id]).get(person.id, {})
    counts = dict(db.execute(
        select(Post.account_id, func.count()).where(Post.account_id.in_([a.id for a in person.accounts]))
        .group_by(Post.account_id)).all()) if person.accounts else {}
    others = list(db.scalars(select(Person).where(Person.id != person.id).order_by(func.lower(Person.name))))
    from .research import notes_for_person

    return render(request, "person.html", person=person, posts=posts, total=total, stats=stats,
                  account_counts=counts, others=others, view="cards", notes=notes_for_person(db, person.id))


@router.post("/personen/{person_id}/bearbeiten")
async def edit(request: Request, person_id: int, name: str = Form(""), note: str = Form(""),
               subtitle: str = Form(""), photo: UploadFile | None = File(None), remove_photo: str = Form(""),
               user: User = Depends(require_user), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    """Nur Darstellung: Name, Kurzbeschreibung, Beschreibung, eigenes Foto.
    Die archivierten Postings (Wortlaut, Original-Profilbild) bleiben unveraendert."""
    from ..services import avatars

    person = _get_person(db, person_id)
    account_service.rename_person(person, name, note, subtitle)
    if remove_photo:
        avatars.remove_person_photo(settings, person)
    elif photo is not None and photo.filename:
        try:
            avatars.save_person_photo(settings, person, await photo.read(avatars.MAX_BYTES + 1))
        except avatars.AvatarError as exc:
            db.rollback()
            return redirect(request, f"/personen/{person.id}", toast=str(exc), kind="error")
    db.commit()
    return redirect(request, f"/personen/{person.id}", toast="Gespeichert")


@router.post("/personen/{person_id}/zusammenfuehren")
def merge(request: Request, person_id: int, target_id: int = Form(0), user: User = Depends(require_user),
          db: Session = Depends(get_db)):
    """Diese Person in eine andere aufgehen lassen (alle Accounts wandern mit)."""
    source = _get_person(db, person_id)
    target = db.get(Person, target_id) if target_id else None
    if target is None or target.id == source.id:
        return redirect(request, f"/personen/{source.id}#zusammenfuehren",
                        toast="Bitte eine andere Person auswählen.", kind="error")
    label = source.name
    account_service.merge_persons(db, source, target)
    admin_log.record(db, user, "merge_persons", target.name, f"„{label}“ → „{target.name}“")
    db.commit()
    return redirect(request, f"/personen/{target.id}", toast=f"„{label}“ mit „{target.name}“ zusammengeführt")


@router.post("/accounts/{account_id}/person")
def move(request: Request, account_id: int, person_id: str = Form(""), user: User = Depends(require_user),
         db: Session = Depends(get_db)):
    """Account einer anderen Person zuordnen ("neu" = eigene Person)."""
    acc = _get_account(db, account_id)
    old_id = acc.person_id
    if person_id == "neu":
        target = account_service.split_account(db, acc)
    else:
        try:
            target = db.get(Person, int(person_id))
        except ValueError:
            target = None
        if target is None:
            return redirect(request, f"/personen/{old_id}", toast="Bitte eine Person auswählen.", kind="error")
        account_service.move_account(db, acc, target)
    admin_log.record(db, user, "move_account", acc.label, f"Person {old_id} → {target.id}")
    db.commit()
    return redirect(request, f"/personen/{target.id}", toast=f"{acc.label} gehört jetzt zu „{target.name}“")


@router.get("/accounts/{account_id}")
def account_page(request: Request, account_id: int, db: Session = Depends(get_db)):
    acc = _get_account(db, account_id)
    return redirect(request, f"/personen/{acc.person_id}#account-{acc.id}")
