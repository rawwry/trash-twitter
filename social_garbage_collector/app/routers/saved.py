"""Gemerkte Suchen (0.23): Stern an der Suche, Leiste oben im Idiotarium."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import QueryParams

from ..models import Person, PinnedSearch, Post, PostList, User, utcnow
from ..security import get_db, require_user
from ..services import posts as post_service
from ..templating import redirect

router = APIRouter(dependencies=[Depends(require_user)])

MAX_SAVED = 12
_IGNORE = {"page", "more", "after_group", "view"}   # aendern nur die Darstellung


def clean_query(raw: str) -> str:
    pairs = [(k, v) for k, v in parse_qsl(raw or "", keep_blank_values=False) if k not in _IGNORE and v]
    return urlencode(pairs)


def default_name(db: Session, query: str) -> str:
    f = post_service.filter_from_params(QueryParams(query))
    parts = []
    if f.person_id and (p := db.get(Person, f.person_id)):
        parts.append(p.name)
    parts += ["#" + t for t in f.tags]
    if f.q:
        parts.append(f"„{f.q}“")
    if f.list_id and (pl := db.get(PostList, f.list_id)):
        parts.append(pl.title)
    if f.author:
        parts.append("@" + f.author)
    if f.origin == "weg":
        parts.append("Original weg")
    if f.date_from or f.date_to:
        parts.append(f"{f.date_from.year if f.date_from else '…'}–{f.date_to.year if f.date_to else '…'}")
    return " · ".join(parts)[:80] or "Meine Suche"


@dataclass
class Entry:
    search: PinnedSearch
    new: int


def for_user(db: Session, user: User) -> list[Entry]:
    out = []
    for s in db.scalars(select(PinnedSearch).where(PinnedSearch.user_id == user.id).order_by(PinnedSearch.created_at)):
        f = post_service.filter_from_params(QueryParams(s.query))
        stmt = post_service.archive_query(f).where(Post.created_at > s.seen_at).order_by(None)
        new = db.scalar(select(func.count()).select_from(stmt.with_only_columns(Post.id).subquery())) or 0
        out.append(Entry(s, new))
    return out


@router.post("/suchen/merken")
def save(request: Request, query: str = Form(""), name: str = Form(""), user: User = Depends(require_user),
         db: Session = Depends(get_db)):
    query = clean_query(query)
    if not query:
        return redirect(request, "/", toast="Erst suchen oder filtern, dann merken.", kind="error")
    existing = db.scalar(select(PinnedSearch).where(PinnedSearch.user_id == user.id, PinnedSearch.query == query))
    if existing:
        return redirect(request, f"/?{query}", toast=f"„{existing.name}“ ist schon gemerkt")
    if db.scalar(select(func.count()).select_from(PinnedSearch).where(PinnedSearch.user_id == user.id)) >= MAX_SAVED:
        return redirect(request, f"/?{query}", toast=f"Höchstens {MAX_SAVED} gemerkte Suchen – entferne erst eine.", kind="error")
    s = PinnedSearch(user_id=user.id, query=query, name=" ".join(name.split())[:80] or default_name(db, query))
    db.add(s)
    db.commit()
    return redirect(request, f"/?{query}", toast=f"„{s.name}“ gemerkt – steht jetzt oben im Idiotarium")


def _own(db: Session, user: User, search_id: int) -> PinnedSearch:
    s = db.get(PinnedSearch, search_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404)
    return s


@router.get("/suchen/{search_id}")
def open_search(request: Request, search_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = _own(db, user, search_id)
    s.seen_at = utcnow()
    db.commit()
    return redirect(request, f"/?{s.query}")


@router.post("/suchen/{search_id}/loeschen")
def remove(request: Request, search_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = _own(db, user, search_id)
    name, query = s.name, s.query
    db.delete(s)
    db.commit()
    return redirect(request, "/", toast=f"„{name}“ entfernt",
                    undo={"url": "/suchen/merken", "fields": {"query": query, "name": name}})
