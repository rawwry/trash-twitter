"""Recherche: Fakten und Hintergruende, die das Team selbst zusammentraegt.

0.14: Eintraege mit Personen, Postings und Quellen.
0.15: zentraler Arbeitsplatz /recherche - links alle Eintraege (auch nach
Person gruppiert), rechts Lesen, Bearbeiten und Neu-Anlegen ohne Seitenwechsel.
Einfacheres Formular: erst der Text, Titel optional (sonst erste Zeile),
Personen und Postings per Suche statt Archiv-Nummern.

Alle Mitglieder lesen und bearbeiten; loeschen darf, wer den Eintrag angelegt
hat, oder ein Admin.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import RESEARCH_KINDS, Person, Post, ResearchNote, User, research_persons
from ..security import get_db, require_user
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

MAX_BODY = 20_000
PANE = "rs-pane"
_POST_REF = re.compile(r"(?:/posts/|nr\.?\s*|#)?0*(\d{1,9})", re.I)


def _note(db: Session, note_id: int) -> ResearchNote:
    note = db.get(ResearchNote, note_id)
    if note is None:
        raise HTTPException(status_code=404)
    return note


def _in_pane(request: Request) -> bool:
    return request.headers.get("hx-target") == PANE


def _changed(response: HTMLResponse, toast: str) -> HTMLResponse:
    """Liste links neu laden und Toast zeigen (htmx-Ereignisse)."""
    response.headers["HX-Trigger"] = json.dumps({"research-changed": True, "toast": {"message": toast, "kind": "ok"}})
    return response


def parse_post_refs(raw: str) -> list[int]:
    """"Nr. 000219, 12, https://…/posts/7" -> [219, 12, 7]"""
    out: list[int] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        m = _POST_REF.search(part)
        if m and int(m.group(1)) not in out:
            out.append(int(m.group(1)))
    return out[:100]


def auto_title(body: str) -> str:
    """Erste Zeile/erster Satz als Titel, hoechstens ~110 Zeichen an Wortgrenze."""
    first = next((line.strip() for line in (body or "").splitlines() if line.strip()), "")
    first = re.split(r"(?<=[.!?])\s", first)[0]
    if len(first) > 110:
        first = first[:110].rsplit(" ", 1)[0] + " …"
    return first


# --- Lesen ----------------------------------------------------------------------------------

def _query(q: str, person: int, art: str):
    stmt = (select(ResearchNote).options(selectinload(ResearchNote.persons), selectinload(ResearchNote.posts),
                                         selectinload(ResearchNote.updated_by))
            .order_by(ResearchNote.updated_at.desc(), ResearchNote.id.desc()))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(ResearchNote.title).like(like), func.lower(ResearchNote.body).like(like),
                              func.lower(ResearchNote.sources).like(like),
                              ResearchNote.persons.any(func.lower(Person.name).like(like))))
    if person:
        stmt = stmt.where(ResearchNote.persons.any(Person.id == person))
    if art in RESEARCH_KINDS:
        stmt = stmt.where(ResearchNote.kind == art)
    return stmt


def _grouped(notes: list[ResearchNote]) -> list[tuple[Person, list[ResearchNote]]]:
    """Nach Person: jede Person mit ihren Eintraegen (ein Eintrag kann bei mehreren stehen)."""
    by: dict[int, tuple[Person, list[ResearchNote]]] = {}
    for n in notes:
        for p in n.persons:
            by.setdefault(p.id, (p, []))[1].append(n)
    return sorted(by.values(), key=lambda r: (-len(r[1]), r[0].name.lower()))


@router.get("/recherche")
def hub(request: Request, q: str = "", person: int = 0, art: str = "", ansicht: str = "", id: int = 0,
        user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = q.strip()[:200]
    ansicht = "personen" if ansicht == "personen" else "eintraege"
    notes = list(db.scalars(_query(q, person, art)))
    ctx = dict(notes=notes, groups=_grouped(notes) if ansicht == "personen" else [], q=q, person_id=person, art=art,
               ansicht=ansicht, kinds=RESEARCH_KINDS, selected_id=id)
    if request.headers.get("hx-target") == "rs-index":
        return render(request, "partials/research_index.html", **ctx)
    selected = db.get(ResearchNote, id) if id else (notes[0] if notes else None)
    persons_with = db.execute(select(Person, func.count(research_persons.c.research_id))
                              .join(research_persons, research_persons.c.person_id == Person.id)
                              .group_by(Person.id).order_by(func.lower(Person.name))).all()
    total = db.scalar(select(func.count()).select_from(ResearchNote)) or 0
    ctx.update(selected=selected, selected_id=selected.id if selected else 0, persons_with=persons_with, total=total,
               may_delete=bool(selected and (user.is_admin or selected.created_by_id == user.id)),
               filter_person=db.get(Person, person) if person else None)
    return render(request, "research.html", nav="research", **ctx)


@router.get("/recherche/{note_id:int}")
def detail(request: Request, note_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    ctx = dict(note=note, may_delete=user.is_admin or note.created_by_id == user.id)
    if _in_pane(request):
        return render(request, "partials/research_pane.html", **ctx)
    return render(request, "research_detail.html", nav="research", **ctx)


# --- Schreiben ------------------------------------------------------------------------------

def _editor(request: Request, db: Session, note: ResearchNote | None, error: str = "", **values):
    ctx = dict(note=note, kinds=RESEARCH_KINDS, error=error, **values)
    ids = values.get("form_person_ids") or []
    ctx["chosen_persons"] = list(db.scalars(select(Person).where(Person.id.in_(ids)))) if ids else []
    post_ids = values.get("form_post_ids") or []
    ctx["chosen_posts"] = list(db.scalars(select(Post).where(Post.id.in_(post_ids)))) if post_ids else []
    if _in_pane(request):
        return render(request, "partials/research_editor.html", **ctx)  # 200, sonst tauscht htmx nicht
    return render(request, "research_form.html", nav="research", status_code=400 if error else 200, **ctx)


@router.get("/recherche/neu")
def new_form(request: Request, person: int = 0, post: int = 0, posts: str = "", titel: str = "",
             db: Session = Depends(get_db)):
    """Vorbelegt aus Posting (?post=), mehreren Postings (?posts=1,2,3 - z. B. aus
    "Muster") und Titel (?titel=)."""
    person_ids = [person] if person else []
    wanted = [post] if post else []
    wanted += [int(x) for x in posts.split(",")[:100] if x.strip().isdigit()]
    post_ids = []
    for p in (db.get(Post, i) for i in dict.fromkeys(wanted)):
        if p is None:
            continue
        post_ids.append(p.id)
        if p.account and p.account.person_id and p.account.person_id not in person_ids:
            person_ids.append(p.account.person_id)
    return _editor(request, db, None, form_person_ids=person_ids, form_post_ids=post_ids,
                   form_kind="widerspruch" if post_ids else "hintergrund", form_title=" ".join(titel.split())[:200])


def _apply(db: Session, note: ResearchNote, user: User, title: str, kind: str, body: str, sources: str,
           person_ids: list[int], post_ids: list[int], posts: str) -> str:
    body = body.strip()[:MAX_BODY]
    title = " ".join(title.split())[:200] or auto_title(body)
    if len(title) < 3:
        return "Bitte etwas schreiben – mindestens einen Satz oder einen Titel."
    note.title = title
    note.kind = kind if kind in RESEARCH_KINDS else "hintergrund"
    note.body = body
    note.sources = "\n".join(line.strip() for line in sources.splitlines() if line.strip())[:5000]
    note.persons = list(db.scalars(select(Person).where(Person.id.in_(person_ids[:200])))) if person_ids else []
    refs = list(dict.fromkeys(list(post_ids) + parse_post_refs(posts)))[:100]
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
        return "Bitte mindestens eine Person zuordnen (oder ein Posting verknüpfen)."
    note.updated_by_id = user.id
    return ""


def _saved(request: Request, note: ResearchNote, user: User, toast: str):
    if _in_pane(request):
        response = render(request, "partials/research_pane.html", note=note,
                          may_delete=user.is_admin or note.created_by_id == user.id)
        response.headers["HX-Push-Url"] = f"{request.scope.get('root_path', '')}/recherche?id={note.id}"
        return _changed(response, toast)
    return redirect(request, f"/recherche/{note.id}", toast=toast)


@router.post("/recherche")
def create(request: Request, title: str = Form(""), kind: str = Form("hintergrund"), body: str = Form(""),
           sources: str = Form(""), person_ids: list[int] = Form(default=[]), post_ids: list[int] = Form(default=[]),
           posts: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = ResearchNote(created_by_id=user.id)
    db.add(note)
    error = _apply(db, note, user, title, kind, body, sources, person_ids, post_ids, posts)
    if error:
        db.rollback()
        return _editor(request, db, None, error=error, form_title=title, form_kind=kind, form_body=body,
                       form_sources=sources, form_person_ids=person_ids,
                       form_post_ids=list(post_ids) + parse_post_refs(posts))
    db.commit()
    return _saved(request, note, user, "Recherche gespeichert")


@router.get("/recherche/{note_id:int}/bearbeiten")
def edit_form(request: Request, note_id: int, db: Session = Depends(get_db)):
    note = _note(db, note_id)
    return _editor(request, db, note, form_title=note.title, form_kind=note.kind, form_body=note.body,
                   form_sources=note.sources, form_person_ids=[p.id for p in note.persons],
                   form_post_ids=[p.id for p in note.posts])


@router.post("/recherche/{note_id:int}")
def update(request: Request, note_id: int, title: str = Form(""), kind: str = Form("hintergrund"), body: str = Form(""),
           sources: str = Form(""), person_ids: list[int] = Form(default=[]), post_ids: list[int] = Form(default=[]),
           posts: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    error = _apply(db, note, user, title, kind, body, sources, person_ids, post_ids, posts)
    if error:
        db.rollback()
        return _editor(request, db, _note(db, note_id), error=error, form_title=title, form_kind=kind, form_body=body,
                       form_sources=sources, form_person_ids=person_ids,
                       form_post_ids=list(post_ids) + parse_post_refs(posts))
    db.commit()
    return _saved(request, note, user, "Gespeichert")


@router.post("/recherche/{note_id:int}/loeschen")
def delete(request: Request, note_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    note = _note(db, note_id)
    if not (user.is_admin or note.created_by_id == user.id):
        raise HTTPException(status_code=403, detail="Nur wer den Eintrag angelegt hat (oder ein Admin) kann ihn löschen.")
    db.delete(note)
    db.commit()
    if _in_pane(request):
        response = render(request, "partials/research_pane.html", note=None, may_delete=False)
        response.headers["HX-Push-Url"] = f"{request.scope.get('root_path', '')}/recherche"
        return _changed(response, "Recherche gelöscht")
    return redirect(request, "/recherche", toast="Recherche gelöscht")


# --- Suche fuer die Auswahlfelder ------------------------------------------------------------

@router.get("/recherche/suche/personen")
def pick_persons(request: Request, q: str = "", db: Session = Depends(get_db)):
    from ..services.accounts import list_persons

    q = q.strip()[:100]
    persons = list_persons(db, q)[:12] if q else []
    return render(request, "partials/research_pick.html", kind="person", persons=persons, q=q)


@router.get("/recherche/suche/postings")
def pick_posts(request: Request, q: str = "", db: Session = Depends(get_db)):
    from ..services import posts as post_service

    q = q.strip()[:200]
    posts: list[Post] = []
    if q:
        refs = parse_post_refs(q) if re.fullmatch(r"[\d\s,;#.nrNR/]+", q) else []
        if refs:
            posts = list(db.scalars(select(Post).where(Post.id.in_(refs))))
        else:
            posts, _ = post_service.search_archive(db, post_service.ArchiveFilter(q=q, sort="posted"), per_page=8)
    return render(request, "partials/research_pick.html", kind="post", posts=posts, q=q)


# --- Fuer Personen- und Posting-Seiten -------------------------------------------------------

def notes_for_person(db: Session, person_id: int) -> list[ResearchNote]:
    return list(db.scalars(select(ResearchNote).where(ResearchNote.persons.any(Person.id == person_id))
                           .order_by(ResearchNote.updated_at.desc())))


def notes_for_post(db: Session, post_id: int) -> list[ResearchNote]:
    return list(db.scalars(select(ResearchNote).where(ResearchNote.posts.any(Post.id == post_id))
                           .order_by(ResearchNote.updated_at.desc())))
