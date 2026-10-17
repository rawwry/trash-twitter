"""Netzwerk (0.18): das Archiv als Graph - wie die Graph-Ansicht von Obsidian.

Knoten: Personen, Tags (mit Oberbegriffen), Listen, Recherche und - auf
Wunsch - die einzelnen Postings. Kanten laufen immer ueber das, was wirklich
im Archiv steht:

    Posting -> Person        (wer hat es gesagt)
    Posting -> Tag / Liste   (wie ihr es eingeordnet habt)
    Recherche -> Person / Posting
    Tag -> Oberbegriff

Ohne Postings fasst der Browser diese Wege zusammen: Person - Tag (Linie so
dick wie die Zahl der Postings) und Liste - Person. Personen sind bewusst nie
direkt miteinander verbunden - sie begegnen sich ueber Themen und Listen.

Der Server liefert nur die Daten (JSON); gezeichnet wird im Browser.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Account,
    ListPost,
    Person,
    Post,
    PostList,
    ResearchNote,
    Tag,
    post_tags,
    research_persons,
    research_posts,
)
from ..security import get_db, require_user
from ..templating import render, root_path

router = APIRouter(dependencies=[Depends(require_user)])

LOCAL_OTHER_PERSONS = 12   # lokaler Graph: so viele weitere Personen mit gemeinsamen Themen
SNIPPET = 140


def _snippet(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET else text[:SNIPPET].rsplit(" ", 1)[0] + " …"


def build_graph(db: Session, base: str, person_id: int | None = None) -> dict:
    """Ganzes Netz, oder (person_id) die Umgebung einer Person: ihre Postings,
    deren Tags und Listen, ihre Recherche - und die Personen, die am meisten
    dieselben Themen haben (ueber die Tags, nicht direkt verbunden)."""
    # --- Postings mit Person ------------------------------------------------------------------
    rows = db.execute(
        select(Post.id, Post.text, Post.platform, Post.posted_at, Post.created_at, Post.hearts, Post.comment_count,
               Account.person_id)
        .join(Account, Account.id == Post.account_id).where(Account.person_id.is_not(None))
    ).all()
    post_person = {r.id: r.person_id for r in rows}
    tag_links = db.execute(select(post_tags.c.post_id, post_tags.c.tag_id)).all()
    list_links = db.execute(select(ListPost.post_id, ListPost.list_id)).all()
    rp_links = db.execute(select(research_persons.c.research_id, research_persons.c.person_id)).all()
    rpost_links = db.execute(select(research_posts.c.research_id, research_posts.c.post_id)).all()

    keep_posts: set[int] | None = None
    keep_persons: set[int] | None = None
    if person_id:
        own = {pid for pid, per in post_person.items() if per == person_id}
        own_tags = {t for p, t in tag_links if p in own}
        # Andere Personen nach gemeinsamen Tags gewichten
        shared: dict[int, int] = {}
        for p, t in tag_links:
            per = post_person.get(p)
            if t in own_tags and per and per != person_id:
                shared[per] = shared.get(per, 0) + 1
        others = sorted(shared, key=lambda k: -shared[k])[:LOCAL_OTHER_PERSONS]
        keep_persons = {person_id, *others}
        other_posts = {p for p, t in tag_links if t in own_tags and post_person.get(p) in others}
        keep_posts = own | other_posts
        # Bei den anderen nur die gemeinsamen Themen zeigen, sonst franst das Netz aus
        tag_links = [(p, t) for p, t in tag_links if p in own or t in own_tags]

    def post_ok(pid: int) -> bool:
        return pid in post_person and (keep_posts is None or pid in keep_posts)

    posts = [r for r in rows if post_ok(r.id)]
    used_persons = {r.person_id for r in posts}
    research_rows = list(db.scalars(select(ResearchNote)))
    if person_id:
        research_rows = [n for n in research_rows if any(r == n.id and p == person_id for r, p in rp_links)]
    research_ids = {n.id for n in research_rows}
    used_persons |= {p for r, p in rp_links if r in research_ids and (keep_persons is None or p in keep_persons)}

    persons = list(db.scalars(select(Person).where(Person.id.in_(used_persons))
                              .options(selectinload(Person.accounts))))
    post_ids = {r.id for r in posts}
    tag_ids = {t for p, t in tag_links if p in post_ids}
    tags = {t.id: t for t in db.scalars(select(Tag))}
    tag_ids |= {tags[t].parent_id for t in tag_ids if t in tags and tags[t].parent_id}
    list_ids = {lid for p, lid in list_links if p in post_ids}
    lists = list(db.scalars(select(PostList).where(PostList.id.in_(list_ids)))) if list_ids else []
    counts = dict(db.execute(select(Account.person_id, func.count(Post.id)).join(Post, Post.account_id == Account.id)
                             .group_by(Account.person_id)).all())

    nodes, links = [], []
    for p in persons:
        nodes.append({"id": f"p{p.id}", "type": "person", "label": p.name, "sub": p.subtitle or "",
                      "img": f"{base}/{p.avatar_path}" if p.avatar_path else "", "n": counts.get(p.id, 0),
                      "url": f"{base}/personen/{p.id}"})
    for t in (tags[i] for i in tag_ids if i in tags):
        nodes.append({"id": f"g{t.id}", "type": "group" if (t.is_group or any(x.parent_id == t.id for x in tags.values())) else "tag",
                      "label": f"#{t.name}", "url": f"{base}/?tags={t.name}"})
        if t.parent_id and t.parent_id in tag_ids:
            links.append({"source": f"g{t.id}", "target": f"g{t.parent_id}", "kind": "tag-group"})
    for pl in lists:
        nodes.append({"id": f"l{pl.id}", "type": "list", "label": pl.title, "url": f"{base}/lists/{pl.id}"})
    for n in research_rows:
        nodes.append({"id": f"r{n.id}", "type": "research", "label": n.title, "kind": n.kind,
                      "kindLabel": n.kind_label, "url": f"{base}/recherche/{n.id}"})
    for r in posts:
        when = r.posted_at or r.created_at
        nodes.append({"id": f"t{r.id}", "type": "post", "label": _snippet(r.text) or "Kein Wortlaut",
                      "platform": r.platform, "year": when.year if when else None,
                      "date": when.strftime("%d.%m.%Y") if when else "", "hearts": r.hearts or 0,
                      "comments": r.comment_count or 0, "person": f"p{r.person_id}", "url": f"{base}/posts/{r.id}"})
        links.append({"source": f"t{r.id}", "target": f"p{r.person_id}", "kind": "post-person"})
    for p, t in tag_links:
        if p in post_ids and t in tag_ids:
            links.append({"source": f"t{p}", "target": f"g{t}", "kind": "post-tag"})
    for p, lid in list_links:
        if p in post_ids and lid in list_ids:
            links.append({"source": f"t{p}", "target": f"l{lid}", "kind": "post-list"})
    person_ids = {p.id for p in persons}
    for r, p in rp_links:
        if r in research_ids and p in person_ids:
            links.append({"source": f"r{r}", "target": f"p{p}", "kind": "research-person"})
    for r, p in rpost_links:
        if r in research_ids and p in post_ids:
            links.append({"source": f"r{r}", "target": f"t{p}", "kind": "research-post"})
    years = sorted(n["year"] for n in nodes if n.get("year"))
    return {"nodes": nodes, "links": links, "years": [years[0], years[-1]] if years else [],
            "focus": f"p{person_id}" if person_id else None}


@router.get("/netzwerk")
def page(request: Request, fokus: str = ""):
    return render(request, "graph.html", nav="graph", fokus=fokus[:20])


@router.get("/netzwerk/daten")
def data(request: Request, person: int = 0, db: Session = Depends(get_db)):
    graph = build_graph(db, root_path(request), person or None)
    return JSONResponse(graph, headers={"Cache-Control": "private, no-store"})
