"""Tags mit zwei Ebenen (0.14): Oberbegriffe und Unter-Tags.

Viele aehnliche Tags ("klima", "klimawandel", "klimakrise") machen die Suche
unbrauchbar. Deshalb:
  - Oberbegriffe (is_group) fassen Tags zusammen; Filtern nach dem Oberbegriff
    findet alle Postings seiner Unter-Tags mit.
  - Genau zwei Ebenen: ein Oberbegriff hat keinen Oberbegriff, ein Unter-Tag
    keine eigenen Unter-Tags.
  - Die Tag-Eingabe schlaegt vorhandene Tags (auch aehnlich geschriebene) vor;
    neue anzulegen ist ein bewusster Extra-Klick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Tag, post_tags
from .posts import normalize_tag, remove_orphan_tags


class TagError(ValueError):
    pass


@dataclass
class TagNode:
    tag: Tag
    count: int = 0            # Postings direkt mit diesem Tag
    total: int = 0            # inkl. Unter-Tags (ohne doppelte)
    children: list["TagNode"] = field(default_factory=list)


def _direct_counts(db: Session) -> dict[int, int]:
    return dict(db.execute(select(post_tags.c.tag_id, func.count()).group_by(post_tags.c.tag_id)).all())


def tree(db: Session) -> tuple[list[TagNode], list[TagNode]]:
    """(Oberbegriffe mit Unter-Tags, Tags ohne Oberbegriff) - jeweils alphabetisch."""
    counts = _direct_counts(db)
    tags = list(db.scalars(select(Tag).order_by(Tag.name)))
    nodes = {t.id: TagNode(t, counts.get(t.id, 0)) for t in tags}
    groups, loose = [], []
    for t in tags:
        node = nodes[t.id]
        if t.parent_id and t.parent_id in nodes:
            nodes[t.parent_id].children.append(node)
    for t in tags:
        node = nodes[t.id]
        if t.parent_id and t.parent_id in nodes:
            continue
        (groups if (t.is_group or node.children) else loose).append(node)
    totals = _group_totals(db, [g.tag.id for g in groups])
    for g in groups:
        g.total = totals.get(g.tag.id, g.count)
    for n in loose:
        n.total = n.count
    return groups, loose


def _group_totals(db: Session, group_ids: list[int]) -> dict[int, int]:
    if not group_ids:
        return {}
    member = select(Tag.id.label("tid"), func.coalesce(Tag.parent_id, Tag.id).label("gid")) \
        .where((Tag.id.in_(group_ids)) | (Tag.parent_id.in_(group_ids))).subquery()
    rows = db.execute(
        select(member.c.gid, func.count(func.distinct(post_tags.c.post_id)))
        .join(post_tags, post_tags.c.tag_id == member.c.tid).group_by(member.c.gid)
    ).all()
    return dict(rows)


def bar_items(db: Session, limit: int = 14) -> tuple[list[tuple[str, int, bool]], int]:
    """Fuer die Tag-Leiste im Archiv: Oberbegriffe und lose Tags nach Haeufigkeit.
    Rueckgabe: ([(name, anzahl, ist_oberbegriff)], Gesamtzahl aller Tags)."""
    groups, loose = tree(db)
    items = [(g.tag.name, g.total, True) for g in groups if g.total] + [(n.tag.name, n.count, False) for n in loose if n.count]
    items.sort(key=lambda r: (-r[1], r[0]))
    total = sum(1 + len(g.children) for g in groups) + len(loose)
    return items[:limit], total


# --- Aendern ------------------------------------------------------------------------

def get_or_create_group(db: Session, raw: str) -> Tag:
    name = normalize_tag(raw)
    if not name:
        raise TagError("Bitte einen gültigen Namen angeben.")
    tag = db.scalar(select(Tag).where(Tag.name == name))
    if tag is None:
        tag = Tag(name=name, is_group=True)
        db.add(tag)
        db.flush()
    elif tag.parent_id:
        raise TagError(f"#{name} steht selbst unter einem Oberbegriff und kann keiner sein.")
    tag.is_group = True
    return tag


def move(db: Session, tag: Tag, parent: Tag | None) -> None:
    """Tag unter einen Oberbegriff stellen (parent=None: heraus nehmen)."""
    if parent is None:
        tag.parent_id = None
        return
    if parent.id == tag.id:
        raise TagError("Ein Tag kann nicht unter sich selbst stehen.")
    if parent.parent_id:
        raise TagError(f"#{parent.name} ist selbst ein Unter-Tag – bitte einen Oberbegriff wählen.")
    if tag.children or tag.is_group:
        raise TagError(f"#{tag.name} ist ein Oberbegriff und kann nicht eingeordnet werden.")
    parent.is_group = True
    tag.parent_id = parent.id


def merge_into(db: Session, source: Tag, target: Tag) -> None:
    """source verschwindet; Postings und Unter-Tags wandern zu target."""
    if source.id == target.id:
        return
    for post in list(source.posts):
        if target not in post.tags:
            post.tags.append(target)
    for child in list(source.children):
        child.parent_id = None if child.id == target.id else (target.parent_id or target.id)
    if source.is_group:
        target.is_group = target.parent_id is None
    db.flush()
    db.delete(source)
    db.flush()


def ungroup(db: Session, tag: Tag) -> None:
    """Oberbegriff aufloesen: Unter-Tags werden wieder lose, der Begriff selbst
    verschwindet, wenn er keine eigenen Postings hat."""
    for child in list(tag.children):
        child.parent_id = None
    tag.is_group = False
    db.flush()
    remove_orphan_tags(db)


# --- Vorschlaege beim Eintippen --------------------------------------------------------

@dataclass
class Suggestion:
    name: str
    count: int
    parent: str = ""
    similar: bool = False   # nur aehnlich geschrieben ("Meintest du …?")


def suggest(db: Session, raw: str, taken: set[str], limit: int = 8) -> tuple[list[Suggestion], str]:
    """Vorhandene Tags zum Eingetippten: erst Anfang, dann enthalten, dann aehnlich
    geschrieben (Tippfehler). Rueckgabe: (Vorschlaege, normalisierter neuer Name -
    leer, wenn es den Tag schon gibt)."""
    q = normalize_tag(raw)
    counts = _direct_counts(db)
    tags = [t for t in db.scalars(select(Tag)) if t.name not in taken]
    parents = {t.id: t.name for t in tags}
    parents.update({t.id: t.name for t in db.scalars(select(Tag).where(Tag.is_group.is_(True)))})

    def sug(t: Tag, similar=False) -> Suggestion:
        return Suggestion(t.name, counts.get(t.id, 0), parents.get(t.parent_id, "") if t.parent_id else "", similar)

    if not q:
        top = sorted(tags, key=lambda t: (-counts.get(t.id, 0), t.name))
        return [sug(t) for t in top[:limit]], ""
    starts = [t for t in tags if t.name.startswith(q)]
    contains = [t for t in tags if q in t.name and t not in starts]
    pool = sorted(starts, key=lambda t: (-counts.get(t.id, 0), t.name)) + \
        sorted(contains, key=lambda t: (-counts.get(t.id, 0), t.name))
    out = [sug(t) for t in pool[:limit]]
    if len(out) < limit and len(q) >= 3:
        seen = {s.name for s in out}
        close = sorted(((SequenceMatcher(None, q, t.name).ratio(), t) for t in tags if t.name not in seen),
                       key=lambda r: (-r[0], -counts.get(r[1].id, 0)))
        out += [sug(t, similar=True) for score, t in close if score >= 0.72][: limit - len(out)]
    exists = q in taken or any(t.name == q for t in tags)
    return out, ("" if exists else q)


# --- Aufraeumen (0.19) --------------------------------------------------------------------

@dataclass
class Cleanup:
    unused: list[Tag] = field(default_factory=list)                    # 0 Postings, kein Oberbegriff
    similar: list[tuple[Tag, Tag, int, int]] = field(default_factory=list)  # (behalten, zusammenlegen, n_a, n_b)
    shadows: list[tuple[Tag, Tag, int, int]] = field(default_factory=list)  # (tag, fast immer mit, gemeinsam, gesamt)

    @property
    def any(self) -> bool:
        return bool(self.unused or self.similar or self.shadows)


_SUFFIXES = ("ungen", "ung", "innen", "in", "en", "er", "es", "e", "n", "s")


def _stem(name: str) -> str:
    """Grober deutscher Wortstamm, nur fuer Aufraeum-Vorschlaege."""
    for suf in _SUFFIXES:
        if name.endswith(suf) and len(name) - len(suf) >= 4:
            return name[: -len(suf)]
    return name


def cleanup(db: Session, limit: int = 8) -> Cleanup:
    """Vorschlaege fuer "Tags organisieren":
      - ungenutzt: haengt an keinem Posting mehr,
      - aehnlich geschrieben: vermutlich derselbe Tag (wohnen/wohnung, Tippfehler),
      - Schatten: ein Tag kommt (fast) nur zusammen mit einem anderen vor - meist
        ein Unterfall davon (#spender-verstorben unter #todesfall)."""
    counts = _direct_counts(db)
    tags = list(db.scalars(select(Tag).order_by(Tag.name)))
    out = Cleanup()
    out.unused = [t for t in tags if not counts.get(t.id) and not t.is_group and not t.children]

    used = [t for t in tags if counts.get(t.id) and not t.is_group]
    pairs = []
    for i, a in enumerate(used):
        for b in used[i + 1:]:
            if a.parent_id and a.parent_id == b.id or b.parent_id and b.parent_id == a.id:
                continue
            if min(len(a.name), len(b.name)) < 4:
                continue
            ratio = SequenceMatcher(None, a.name, b.name).ratio()
            sa, sb = _stem(a.name), _stem(b.name)
            # Gleicher Wortstamm (wohnen/wohnung, hund/hunde) oder sehr aehnlich (Tippfehler).
            # Nur "aehnlich" reicht nicht: betreuung/betrug oder leben/liebe sind verschieden.
            if (sa == sb and len(sa) >= 4) or ratio >= 0.9:
                keep, drop = (a, b) if counts[a.id] >= counts[b.id] else (b, a)
                pairs.append((ratio, keep, drop))
    pairs.sort(key=lambda r: -r[0])
    out.similar = [(k, d, counts[k.id], counts[d.id]) for _, k, d in pairs[:limit]]

    links = db.execute(select(post_tags.c.post_id, post_tags.c.tag_id)).all()
    by_post: dict[int, set[int]] = {}
    for pid, tid in links:
        by_post.setdefault(pid, set()).add(tid)
    together: dict[tuple[int, int], int] = {}
    for tids in by_post.values():
        for a in tids:
            for b in tids:
                if a != b:
                    together[(a, b)] = together.get((a, b), 0) + 1
    by_id = {t.id: t for t in tags}
    shadows = []
    for (a, b), n in together.items():
        ta, tb = by_id.get(a), by_id.get(b)
        if not ta or not tb or ta.is_group or tb.is_group or ta.parent_id or ta.is_figure:
            continue
        total = counts.get(a, 0)
        if total >= 3 and n / total >= 0.85 and counts.get(b, 0) > total:
            shadows.append((ta, tb, n, total))
    shadows.sort(key=lambda r: (-r[2], r[0].name))
    out.shadows = shadows[:limit]
    return out
