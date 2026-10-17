"""Automatische Tags (0.20): Regeln "Wortlaut enthaelt … → #tag".

  - Begriffe sind ganze Woerter oder Wortgruppen, Gross-/Kleinschreibung egal.
    Ein "*" steht fuer eine beliebige Fortsetzung: "verstorb*" findet verstorben,
    verstorbene, verstorbener; "*katze" findet hauskatze.
  - "mindestens eines" oder "alle" Begriffe; Ausnahmen schliessen aus.
  - Optional nur fuer die Postings einer Person.
  - Neue Postings bekommen die Tags beim Archivieren (capture) und wenn jemand
    den Wortlaut von Hand korrigiert. Vorhandene nur auf Knopfdruck.
  - Regeln fuegen nur hinzu, sie entfernen nie. Was eine Regel vergeben hat,
    steht in auto_tags und laesst sich rueckgaengig machen.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session, selectinload

from ..models import STATUS_DONE, Account, AutoTag, Post, Tag, TagRule, post_tags

MAX_TERMS = 40
MAX_TERM_LEN = 60
_W = r"[\w]"   # Wortzeichen inkl. Umlaute (str-Muster sind Unicode)


def parse_terms(raw: str) -> list[str]:
    """Ein Begriff pro Zeile oder durch Komma getrennt; klein, ohne Doppelte."""
    out: list[str] = []
    for part in re.split(r"[\n,;]", raw or ""):
        term = " ".join(part.strip().lower().split())[:MAX_TERM_LEN]
        term = re.sub(r"\*{2,}", "*", term)
        if term.strip("*") and term not in out:
            out.append(term)
    return out[:MAX_TERMS]


def _pattern(term: str) -> str:
    start, end = term.startswith("*"), term.endswith("*")
    core = re.escape(term.strip("*")).replace(r"\ ", r"\s+")
    left = rf"{_W}*" if start else rf"(?<!{_W})"
    right = rf"{_W}*" if end else rf"(?!{_W})"
    return left + core + right


@dataclass
class Matcher:
    terms: list[str]
    match: str = "any"
    exclude: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._terms = [re.compile(_pattern(t), re.IGNORECASE) for t in self.terms]
        self._exclude = [re.compile(_pattern(t), re.IGNORECASE) for t in self.exclude]

    def hits(self, text: str) -> list[str]:
        """Gefundene Stellen (fuer die Vorschau); leer = passt nicht."""
        if not text or not self._terms:
            return []
        if any(p.search(text) for p in self._exclude):
            return []
        found = [m.group(0) for p in self._terms if (m := p.search(text))]
        if self.match == "all" and len(found) < len(self._terms):
            return []
        return found

    def __call__(self, text: str) -> bool:
        return bool(self.hits(text))


def matcher_for(rule: TagRule) -> Matcher:
    return Matcher(rule.term_list, rule.match, rule.exclude_list)


def _person_of(post: Post) -> int | None:
    return post.account.person_id if post.account else None


# --- Neue Postings ------------------------------------------------------------------------

def apply_to_post(db: Session, post: Post) -> list[str]:
    """Alle aktiven Regeln auf ein Posting anwenden (nur hinzufuegen). Rueckgabe: neue Tags."""
    rules = list(db.scalars(select(TagRule).where(TagRule.active.is_(True)).options(selectinload(TagRule.tag))))
    if not rules or not post.text:
        return []
    person = _person_of(post)
    have = {t.id for t in post.tags}
    added = []
    for rule in rules:
        if rule.tag_id in have or (rule.person_id and rule.person_id != person):
            continue
        if matcher_for(rule)(post.text):
            post.tags.append(rule.tag)
            db.add(AutoTag(post_id=post.id, tag_id=rule.tag_id, rule_id=rule.id))
            have.add(rule.tag_id)
            added.append(rule.tag.name)
    return added


# --- Vorhandene Postings ---------------------------------------------------------------------

@dataclass
class Preview:
    matching: int = 0           # passt, unabhaengig von vorhandenen Tags
    already: int = 0            # hat das Tag schon
    untagged: int = 0           # passt und hat noch gar kein Tag
    other_tags: int = 0         # passt, hat andere Tags, aber dieses nicht
    examples: list[tuple[Post, list[str]]] = field(default_factory=list)
    missed: int = 0             # hat das Tag, passt aber nicht (Hinweis auf fehlende Begriffe)

    @property
    def new(self) -> int:
        return self.untagged + self.other_tags


def _candidates(db: Session, person_id: int | None):
    stmt = select(Post).where(Post.status == STATUS_DONE, Post.text != "").options(selectinload(Post.tags))
    if person_id:
        stmt = stmt.where(Post.account_id.in_(select(Account.id).where(Account.person_id == person_id)))
    return db.scalars(stmt.order_by(Post.posted_at.desc().nulls_last(), Post.id.desc()))


def preview(db: Session, matcher: Matcher, tag_id: int | None, person_id: int | None, limit: int = 12) -> Preview:
    out = Preview()
    for post in _candidates(db, person_id):
        hits = matcher.hits(post.text)
        has_tag = tag_id is not None and any(t.id == tag_id for t in post.tags)
        if not hits:
            if has_tag:
                out.missed += 1
            continue
        out.matching += 1
        if has_tag:
            out.already += 1
            continue
        if post.tags:
            out.other_tags += 1
        else:
            out.untagged += 1
        if len(out.examples) < limit:
            out.examples.append((post, hits))
    return out


def apply_to_existing(db: Session, rule: TagRule, only_untagged: bool) -> int:
    """Regel auf vorhandene Postings anwenden. only_untagged: nur Postings ganz ohne Tag."""
    match = matcher_for(rule)
    n = 0
    for post in _candidates(db, rule.person_id):
        if any(t.id == rule.tag_id for t in post.tags) or (only_untagged and post.tags):
            continue
        if match(post.text):
            post.tags.append(rule.tag)
            db.add(AutoTag(post_id=post.id, tag_id=rule.tag_id, rule_id=rule.id))
            n += 1
    return n


def untagged_reach(db: Session) -> tuple[int, int]:
    """(Postings ohne Tag, davon von mindestens einer aktiven Regel erreichbar)."""
    rules = [(r, matcher_for(r)) for r in db.scalars(select(TagRule).where(TagRule.active.is_(True)))]
    total = reach = 0
    for post in _candidates(db, None):
        if post.tags:
            continue
        total += 1
        person = _person_of(post) if any(r.person_id for r, _ in rules) else None
        if any((not r.person_id or r.person_id == person) and m(post.text) for r, m in rules):
            reach += 1
    return total, reach


def apply_all_untagged(db: Session) -> tuple[int, int]:
    """Alle aktiven Regeln auf die Postings, die VOR dem Lauf ohne Tag waren -
    so koennen mehrere Regeln dasselbe Posting taggen. Rueckgabe: (Postings, Tags)."""
    rules = list(db.scalars(select(TagRule).where(TagRule.active.is_(True)).options(selectinload(TagRule.tag))))
    if not rules:
        return 0, 0
    posts = [p for p in _candidates(db, None) if not p.tags]
    touched, n_tags = set(), 0
    for rule in rules:
        match = matcher_for(rule)
        for post in posts:
            if rule.person_id and rule.person_id != _person_of(post):
                continue
            if any(t.id == rule.tag_id for t in post.tags) or not match(post.text):
                continue
            post.tags.append(rule.tag)
            db.add(AutoTag(post_id=post.id, tag_id=rule.tag_id, rule_id=rule.id))
            touched.add(post.id)
            n_tags += 1
    return len(touched), n_tags


def assigned_count(db: Session) -> dict[int, int]:
    from sqlalchemy import func

    return dict(db.execute(select(AutoTag.rule_id, func.count()).where(AutoTag.rule_id.is_not(None))
                           .group_by(AutoTag.rule_id)).all())


def undo(db: Session, rule: TagRule) -> int:
    """Alle Tags entfernen, die diese Regel vergeben hat (und die noch dranhaengen)."""
    rows = list(db.scalars(select(AutoTag).where(AutoTag.rule_id == rule.id)))
    n = 0
    for row in rows:
        res = db.execute(delete(post_tags).where(post_tags.c.post_id == row.post_id, post_tags.c.tag_id == row.tag_id))
        n += res.rowcount or 0
        db.delete(row)
    return n


def forget_manual_removal(db: Session, post_id: int, keep_tag_ids: set[int]) -> None:
    """Hat jemand ein Tag von Hand entfernt, vergisst auto_tags es (sonst wuerde
    "Rueckgaengig" spaeter ins Leere greifen - harmlos, aber unordentlich)."""
    db.execute(delete(AutoTag).where(AutoTag.post_id == post_id, AutoTag.tag_id.not_in(keep_tag_ids or {-1})))


# --- Wortvorschlaege -----------------------------------------------------------------------

_STOP = set("""
und oder aber auch noch nur schon jetzt dann mal immer sehr ganz ja nein doch heute hier dort alle alles
der die das den dem des ein eine einen einem einer eines kein keine keinen nicht nichts
ich du er sie es wir ihr mich dich sich uns euch mir dir ihm ihn ihnen mein meine meinen meiner meinem
dein deine sein seine ihre ihren unser unsere euer eure
ist sind war waren bin bist sei wird werden wurde wurden hat habe hatte haben hast kann können konnte muss
mit von zu zur zum auf aus bei nach vor für über unter um an am im in ins durch gegen ohne bis seit wie als
was wer wo wenn weil dass ob so da denn also nun gerade wieder viel viele mehr sehr etwas einfach selbst
diese dieser dieses jede jeder jedes man gibt geht gar evtl
""".split())
_WORD = re.compile(r"[a-zäöüß][a-zäöüß\-]{2,}")


@dataclass
class WordHint:
    word: str
    in_tag: int        # Postings mit dem Tag, die das Wort enthalten
    tagged: int        # alle schon getaggten Postings mit dem Wort (mit irgendeinem Tag)
    untagged: int      # Postings ganz ohne Tag mit dem Wort - die wuerde eine Regel erreichen

    @property
    def precision(self) -> int:
        return round(100 * self.in_tag / self.tagged) if self.tagged else 0


def word_hints(db: Session, tag: Tag, person_id: int | None = None, limit: int = 12) -> list[WordHint]:
    """Woerter, die in Postings mit #tag oft und in anders getaggten selten vorkommen.
    Ungetaggte Postings zaehlen nicht dagegen - sie sind ja gerade das, was eine
    Regel nachtaggen soll."""
    posts = list(_candidates(db, person_id))
    words = {p.id: set(_WORD.findall((p.text or "").lower())) - _STOP for p in posts}
    with_tag = [p for p in posts if any(t.id == tag.id for t in p.tags)]
    if not with_tag:
        return []
    counts = Counter(w for p in with_tag for w in words[p.id])
    tagged = Counter(w for p in posts if p.tags for w in words[p.id])
    untagged = Counter(w for p in posts if not p.tags for w in words[p.id])
    min_n = max(2, round(len(with_tag) * 0.08))   # bei grossen Tags keine Zufallswoerter
    hints = [WordHint(w, n, tagged[w], untagged[w]) for w, n in counts.items() if n >= min_n and n / tagged[w] >= 0.6]
    hints.sort(key=lambda h: (-(h.in_tag * h.in_tag / h.tagged), -h.untagged, h.word))
    return hints[:limit]


def has_rules(db: Session) -> bool:
    return bool(db.scalar(select(exists().where(TagRule.active.is_(True)))))
