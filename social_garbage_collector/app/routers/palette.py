"""Suche ueberall (0.23): ⌘K / Strg+K oder die Lupe oben.

Ein Eingabefeld fuer alles: Aktionen ("Posting hinzufuegen", "Collage"),
Personen, Tags, Listen, Recherche und Postings (Volltext).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Account, Person, PostList, ResearchNote, Tag, post_tags
from ..security import get_db, require_user
from ..services import posts as post_service
from ..templating import render

router = APIRouter(dependencies=[Depends(require_user)])

PER_GROUP = 5


@dataclass
class Item:
    label: str
    href: str = ""
    sub: str = ""
    icon: str = "search"
    open: str = ""          # statt Link: Dialog oeffnen (data-open)


ACTIONS = [
    Item("Posting hinzufügen", open="add-dialog", icon="plus", sub="n"),
    Item("Idiotarium", "/", icon="archive", sub="alle Postings"),
    Item("Personen", "/personen", icon="people"),
    Item("Recherche", "/recherche", icon="research"),
    Item("Neue Recherche", "/recherche/neu", icon="plus"),
    Item("Listen", "/lists", icon="lists"),
    Item("Galerie", "/galerie", icon="image"),
    Item("Collage", "/collage", icon="mosaic", sub="Postings als große Grafik"),
    Item("Tags organisieren", "/settings/tags", icon="tag"),
    Item("Automatisch taggen", "/settings/tags/regeln", icon="sparkles"),
    Item("Suchgenerator", "/generator", icon="search"),
    Item("Benachrichtigungen", "/benachrichtigungen", icon="bell"),
    Item("Einstellungen", "/settings", icon="settings"),
    Item("Hilfe & Anleitung", "/hilfe", icon="help"),
]


def _like(q: str) -> str:
    return f"%{q.lower()}%"


@router.get("/suche/schnell")
def quick(request: Request, q: str = "", db: Session = Depends(get_db)):
    q = " ".join(q.split())[:80]
    low = q.lower().lstrip("#@")
    groups: list[tuple[str, list[Item]]] = []
    actions = [a for a in ACTIONS if not low or low in a.label.lower() or low in a.sub.lower()]
    if q:
        qq = quote(q)
        actions = [Item(f"Im Idiotarium nach „{q}“ suchen", f"/?q={qq}", icon="search"),
                   Item(f"Collage aus „{q}“", f"/collage?q={qq}", icon="mosaic")] + actions[:3]
    groups.append(("Aktionen", actions[: 8 if not q else 5]))
    if low:
        persons = list(db.scalars(
            select(Person).where(or_(func.lower(Person.name).like(_like(low)), Person.id.in_(
                select(Account.person_id).where(func.lower(Account.handle).like(_like(low))))))
            .order_by(func.lower(Person.name)).limit(PER_GROUP)))
        groups.append(("Personen", [Item(p.name, f"/personen/{p.id}", p.subtitle or "", "user") for p in persons]))
        tags = db.execute(
            select(Tag.name, func.count(post_tags.c.post_id)).join(post_tags, post_tags.c.tag_id == Tag.id, isouter=True)
            .where(func.lower(Tag.name).like(_like(low))).group_by(Tag.id)
            .order_by(func.count(post_tags.c.post_id).desc()).limit(PER_GROUP)).all()
        groups.append(("Tags", [Item(f"#{n}", f"/?tags={quote(n)}", f"{c} Postings", "tag") for n, c in tags]))
        lists = list(db.scalars(select(PostList).where(func.lower(PostList.title).like(_like(low))).limit(PER_GROUP)))
        groups.append(("Listen", [Item(pl.title, f"/lists/{pl.id}", icon="lists") for pl in lists]))
        notes = list(db.scalars(select(ResearchNote).where(func.lower(ResearchNote.title).like(_like(low)))
                                .order_by(ResearchNote.updated_at.desc()).limit(PER_GROUP)))
        groups.append(("Recherche", [Item(n.title, f"/recherche/{n.id}", n.kind_label, "research") for n in notes]))
        found, total = post_service.search_archive(db, post_service.ArchiveFilter(q=q, sort="posted"), per_page=PER_GROUP)
        items = [Item(" ".join((p.text or "Kein Wortlaut").split())[:110], f"/posts/{p.id}", p.author_name, "quote") for p in found]
        if total > PER_GROUP:
            items.append(Item(f"Alle {total} Postings anzeigen", f"/?q={quote(q)}", icon="search"))
        groups.append(("Postings", items))
    groups = [(name, items) for name, items in groups if items]
    return render(request, "partials/palette_results.html", groups=groups, q=q)
