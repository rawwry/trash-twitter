"""Recherche (0.14): Fakten und Hintergruende, die das Team selbst zusammentraegt.

Jeder Eintrag gehoert zu einer oder mehreren Personen und kann auf Postings
verweisen ("hier hat sie es selbst relativiert"). Alle Mitglieder lesen und
bearbeiten; loeschen darf, wer den Eintrag angelegt hat, oder ein Admin.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import RESEARCH_KINDS, Account, Person, Post, ResearchNote, User, research_persons
from ..security import get_db, require_user
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

MAX_BODY = 20_000
_POST_REF = re.compile(r"(?:/posts/|nr\.?\s*|#)?0*(\d{1,9})", re.I)


def _note(db: Session, note_id: int) -> ResearchNote:
    note = db.get(ResearchNote, note_id)
    if note is None:
        raise HTTPException(status_code=404)
    return note


def parse_post_refs(raw: str) -> list[int]:
    """"Nr. 000219, 12, https://…/posts/7" -> [219, 12, 7]"""
    out: list[int] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        m = _POST_REF.search(part)
        if m and int(m.group(1)) not in out:
            out.append(int(m.group(1)))
    return out[:100]


def _persons(db: Session) -> list[Person]:
    return list(db.scalars(select(Person).order_by(func.lower(func.ltrim(Person.name, "@")))))


def _form(request: Request, db: Session, note: ResearchNote | None, error: str = "", **values):
    return render(request, "research_form.html", note=note, persons=_persons(db), kinds=RESEARCH_KINDS,
                  error=error, status_code=400 if error else 200, nav="research", **values)


@router.get("/recherche")
def overview(request: Request, q: str = "", person: int = 0, art: str = "", db: Session = Depends(get_db)):
    stmt = (select(ResearchNote).options(selectinload(ResearchNote.persons), selectinload(ResearchNote.posts),
                                         selectinload(ResearchNote.updated_by))
            .order_by(ResearchNote.updated_at.desc()))
    q = q.strip()[:200]
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ResearchNote.title).like(like), func.lower(ResearchNote.body).like(like),
                              func.lower(ResearchNote.sources).like(like)))
    if person:
        stmt = stmt.where(ResearchNote.persons.any(Person.id == person))
    if art in RESEARCH_KINDS:
        stmt = stmt.where(ResearchNote.kind == art)
    notes = list(db.scalars(stmt))
    # Personen mit Eintraegen (fuer den Filter), meiste zuerst
    counts = db.execute(select(Person, func.count(research_persons.c.research_id))
                        .join(research_persons, research_persons.c.person_id == Person.id)
                        .group_by(Person.id).order_by(func.count(research_persons.c.research_id).desc())).all()
    total = db.scalar(select(func.count()).select_from(ResearchNote)) or 0
    return render(request, "research.html", nav="research", notes=notes, q=q, person_id=person, art=art,
                  kinds=RESEARCH_KINDS, person_counts=counts, total=total,
                  filter_person=db.get(Person, person) if person else None)


@router.get("/recherche/neu")
def new_form(request: Request, person: int = 0, post: int = 0, db: Session = Depends(get_db)):
    person_ids = [person] if person else []
    post_refs = ""
    if post:
        p = db.get(Post, post)
        if p is not None:
            post_refs = str(p.id)
            if p.account and p.account.person_id and p.account.person_id not in person_ids:
                person_ids.append(p.account.person_id)
    return _form(request, db, None, form_person_ids=person_ids, form_posts=post_refs, form_kind="widerspruch" if post else "hintergrund")


def _apply(db: Session, note: ResearchNote, user: User, title: str, kind: str, body: str, sources: str,
           person_ids: list[int], posts: str) -> str:
    title = " ".join(title.split())[:200]
    if len(title) < 3:
        return "Bitte einen Titel angeben (mindestens 3 Zeichen)."
    note.title = title
    note.kind = kind if kind in RESEARCH_KINDS else "hintergrund"
    note.body = body.strip()[:MAX_BODY]
    note.sources = "\n".join(line.strip() for line in sources.splitlines() if line.strip())[:5000]
    note.persons = list(db.scalars(select(Person).where(Person.id.in_(person_ids[:200])))) if person_ids else []
    refs = parse_post_refs(posts)
    found = list(db.scalars(select(Post).where(Post.id.in_(refs)))) if refs else []
    missing = sorted(set(refs) - {p.id for p in found})
    if missing:
        return "Diese Archiv-Nummern gibt es nicht: " + ", ".join(f"{n:06d}" for n in missing)
    note.posts = found
    # Postings verraten ihre Person: automatisch mit zuordnen
    for p in found:
        acc = p.account
        if acc is not None and acc.person is not None and acc.person not in note.persons:
            note.persons.append(acc.person)
    if not note.persons:
        return "Bitte mindestens eine Person zuordnen (oder ein Posting angeben)."
    note.updated_by_id = user.id
    return ""


@router.post("/recherche")
def create(request: Request, title: str = Form(""), kind: str = Form("hintergrund"), body: str = Form(""),
           sources: str = Form(""), person_ids: list[int] = Form(default=[]), posts: str = Form(""),
           user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = ResearchNote(created_by_id=user.id)
    db.add(note)
    error = _apply(db, note, user, title, kind, body, sources, person_ids, posts)
    if error:
        db.rollback()
        return _form(request, db, None, error=error, form_title=title, form_kind=kind, form_body=body,
                     form_sources=sources, form_person_ids=person_ids, form_posts=posts)
    db.commit()
    return redirect(request, f"/recherche/{note.id}", toast="Recherche gespeichert")


@router.get("/recherche/{note_id}")
def detail(request: Request, note_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    posts = list(db.scalars(select(Post).where(Post.id.in_([p.id for p in note.posts]))
                            .options(selectinload(Post.tags), selectinload(Post.media),
                                     selectinload(Post.account).selectinload(Account.person))
                            .order_by(Post.posted_at)))
    return render(request, "research_detail.html", nav="research", note=note, posts=posts,
                  may_delete=user.is_admin or note.created_by_id == user.id)


@router.get("/recherche/{note_id}/bearbeiten")
def edit_form(request: Request, note_id: int, db: Session = Depends(get_db)):
    note = _note(db, note_id)
    return _form(request, db, note, form_title=note.title, form_kind=note.kind, form_body=note.body,
                 form_sources=note.sources, form_person_ids=[p.id for p in note.persons],
                 form_posts=", ".join(f"{p.id:06d}" for p in note.posts))


@router.post("/recherche/{note_id}")
def update(request: Request, note_id: int, title: str = Form(""), kind: str = Form("hintergrund"), body: str = Form(""),
           sources: str = Form(""), person_ids: list[int] = Form(default=[]), posts: str = Form(""),
           user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    error = _apply(db, note, user, title, kind, body, sources, person_ids, posts)
    if error:
        db.rollback()
        return _form(request, db, _note(db, note_id), error=error, form_title=title, form_kind=kind, form_body=body,
                     form_sources=sources, form_person_ids=person_ids, form_posts=posts)
    db.commit()
    return redirect(request, f"/recherche/{note.id}", toast="Gespeichert")


@router.post("/recherche/{note_id}/loeschen")
def delete(request: Request, note_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    if not (user.is_admin or note.created_by_id == user.id):
        raise HTTPException(status_code=403, detail="Nur wer den Eintrag angelegt hat (oder ein Admin) kann ihn löschen.")
    db.delete(note)
    db.commit()
    return redirect(request, "/recherche", toast="Recherche gelöscht")


def notes_for_person(db: Session, person_id: int) -> list[ResearchNote]:
    return list(db.scalars(select(ResearchNote).where(ResearchNote.persons.any(Person.id == person_id))
                           .order_by(ResearchNote.updated_at.desc())))


def notes_for_post(db: Session, post_id: int) -> list[ResearchNote]:
    return list(db.scalars(select(ResearchNote).where(ResearchNote.posts.any(Post.id == post_id))
                           .order_by(ResearchNote.updated_at.desc())))
