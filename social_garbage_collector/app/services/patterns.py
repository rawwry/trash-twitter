"""Muster (0.19): wiederkehrende Geschichten einer Person sichtbar machen.

Ein Archiv wie TrashTwitter ist meist ein Dossier: viele Postings weniger
Personen, mit Tags fuer das, was erzaehlt wird. Spannend ist nicht, wer mit
wem verbunden ist, sondern
  - wie oft eine Geschichte vorkommt (Bilanz),
  - wann (Chronik),
  - womit zusammen (Tag-Kombinationen, Themen-Netz),
  - und was mit den Figuren der Geschichten passiert (Lebenslauf je Figur -
    Tags der Art "figur", z. B. ein Haustier oder eine Bekannte).
Alles wird aus Postings und Tags berechnet; gespeichert wird nichts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Person, Post, Tag, post_tags

BILANZ_TAGS = 6        # so viele Tags oben als grosse Zahl
PARTNERS = 3           # "davon … mit #x" je Bilanz-Tag
SNIPPET = 160


def _snippet(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= SNIPPET else text[:SNIPPET].rsplit(" ", 1)[0] + " …"


@dataclass
class PostInfo:
    id: int
    when: datetime | None
    text: str
    tag_ids: list[int]


@dataclass
class TagStat:
    tag: Tag
    count: int
    first: datetime | None = None
    last: datetime | None = None
    years: dict[int, int] = field(default_factory=dict)
    partners: list[tuple[Tag, int]] = field(default_factory=list)

    @property
    def span(self) -> str:
        if not self.first:
            return ""
        a, b = self.first.year, self.last.year
        return str(a) if a == b else f"{a}–{b}"


@dataclass
class Figure:
    stat: TagStat
    posts: list[PostInfo]          # chronologisch
    events: list[tuple[Tag, int]]  # haeufigste Begleit-Tags


@dataclass
class Patterns:
    person: Person
    total: int
    tagged: int
    posts: list[PostInfo]
    tags: dict[int, Tag]
    stats: list[TagStat]           # alle Tags der Person, haeufigste zuerst
    pairs: list[tuple[Tag, Tag, int]]
    figures: list[Figure]
    years: list[int]

    @property
    def untagged(self) -> int:
        return self.total - self.tagged

    @property
    def bilanz(self) -> list[TagStat]:
        return [s for s in self.stats if s.count > 1][:BILANZ_TAGS]

    @property
    def figure_candidates(self) -> list[TagStat]:
        """Fuer den Hinweis "Welche Tags sind Figuren?" - haeufige Themen-Tags."""
        return [s for s in self.stats if not s.tag.is_figure and not s.tag.is_group][:12]

    def chart_data(self, base: str) -> dict:
        """Fuer Chronik und Themen-Netz im Browser (static/muster.js)."""
        return {
            "posts": [{"id": p.id, "t": p.when.strftime("%Y-%m-%d") if p.when else None, "s": p.text, "g": p.tag_ids}
                      for p in self.posts],
            "tags": [{"id": s.tag.id, "name": s.tag.name, "kind": s.tag.kind, "n": s.count} for s in self.stats],
            "pairs": [[a.id, b.id, n] for a, b, n in self.pairs],
            "years": self.years,
            "person": self.person.id,
            "base": base,
        }


def for_person(db: Session, person: Person) -> Patterns:
    rows = db.execute(
        select(Post.id, Post.posted_at, Post.created_at, Post.text)
        .join(Account, Account.id == Post.account_id)
        .where(Account.person_id == person.id, Post.status == "done")
    ).all()
    ids = [r.id for r in rows]
    links = db.execute(select(post_tags.c.post_id, post_tags.c.tag_id).where(post_tags.c.post_id.in_(ids))).all() if ids else []
    by_post: dict[int, list[int]] = defaultdict(list)
    for pid, tid in links:
        by_post[pid].append(tid)
    tag_ids = {tid for _, tid in links}
    tags = {t.id: t for t in db.scalars(select(Tag).where(Tag.id.in_(tag_ids)))} if tag_ids else {}

    posts = sorted((PostInfo(r.id, r.posted_at or r.created_at, _snippet(r.text), sorted(by_post.get(r.id, []),
                                                                                           key=lambda t: tags[t].name))
                    for r in rows), key=lambda p: (p.when or datetime.min, p.id))
    counts = Counter(tid for _, tid in links)
    pair_counts: Counter = Counter()
    for p in posts:
        for a, b in combinations(sorted(set(p.tag_ids)), 2):
            pair_counts[(a, b)] += 1
    partners: dict[int, Counter] = defaultdict(Counter)
    for (a, b), n in pair_counts.items():
        partners[a][b] += n
        partners[b][a] += n

    stats: dict[int, TagStat] = {}
    for p in posts:
        for tid in p.tag_ids:
            st = stats.get(tid) or stats.setdefault(tid, TagStat(tags[tid], counts[tid]))
            if p.when:
                st.first = st.first or p.when
                st.last = p.when
                st.years[p.when.year] = st.years.get(p.when.year, 0) + 1
    for tid, st in stats.items():
        st.partners = [(tags[o], n) for o, n in partners[tid].most_common(PARTNERS)]
    ordered = sorted(stats.values(), key=lambda s: (-s.count, s.tag.name))

    figures = []
    for st in ordered:
        if st.tag.is_figure:
            fposts = [p for p in posts if st.tag.id in p.tag_ids]
            events = [(tags[o], n) for o, n in partners[st.tag.id].most_common(8)]
            figures.append(Figure(st, fposts, events))

    years = sorted({p.when.year for p in posts if p.when})
    pairs = sorted(((tags[a], tags[b], n) for (a, b), n in pair_counts.items()), key=lambda r: (-r[2], r[0].name))
    return Patterns(person=person, total=len(posts), tagged=sum(1 for p in posts if p.tag_ids), posts=posts,
                    tags=tags, stats=ordered, pairs=pairs, figures=figures,
                    years=[years[0], years[-1]] if years else [])


@dataclass
class PersonSummary:
    person: Person
    total: int
    tagged: int
    top: list[tuple[str, int]]


def overview(db: Session, limit_tags: int = 4) -> list[PersonSummary]:
    """Alle Personen mit Postings, die meisten zuerst - fuer /muster."""
    rows = db.execute(
        select(Account.person_id, Post.id).join(Post, Post.account_id == Account.id)
        .where(Account.person_id.is_not(None), Post.status == "done")
    ).all()
    per_person: dict[int, list[int]] = defaultdict(list)
    for pid, post_id in rows:
        per_person[pid].append(post_id)
    if not per_person:
        return []
    post_person = {post_id: pid for pid, post_id in rows}
    links = db.execute(select(post_tags.c.post_id, Tag.name).join(Tag, Tag.id == post_tags.c.tag_id)).all()
    tag_counts: dict[int, Counter] = defaultdict(Counter)
    tagged: dict[int, set[int]] = defaultdict(set)
    for post_id, name in links:
        pid = post_person.get(post_id)
        if pid:
            tag_counts[pid][name] += 1
            tagged[pid].add(post_id)
    persons = {p.id: p for p in db.scalars(select(Person).where(Person.id.in_(per_person)))}
    out = [PersonSummary(persons[pid], len(posts), len(tagged[pid]), tag_counts[pid].most_common(limit_tags))
           for pid, posts in per_person.items() if pid in persons]
    out.sort(key=lambda s: (-s.total, s.person.name.lower()))
    return out


