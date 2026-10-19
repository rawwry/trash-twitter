"""Wiederholt erzaehlt (0.21): fast gleiche Geschichten einer Person finden.

Wer dieselbe Geschichte mehrmals erzaehlt, formuliert sie meist um. Reiner
Textvergleich findet das nicht, Themen-Gleichheit ("verstorben") ist zu grob.
Deshalb:
  - Woerter klein, ohne Fuellwoerter, grob auf den Wortstamm gekuerzt.
  - Gewichtet nach Seltenheit innerhalb der Postings dieser Person (TF-IDF):
    Allerweltswoerter der Person ("verstorben") zaehlen kaum, seltene
    ("nackt", "Sommernachtstraum") viel. Aehnlichkeit = Kosinus.
  - Zwei Postings gehoeren zusammen, wenn sie aehnlich genug sind UND sich
    mindestens zwei fuer diese Person seltene Woerter teilen - sonst entstehen
    Ketten aus Postings, die nur dasselbe Thema haben.
Eingestellt an echten Daten (17.10.2026): findet z. B. 6x "Frau nackt im Bett -
NEIN", 4x die DVD-Bitte, 3x dieselbe Rettungsgeschichte.

Berechnet bei Bedarf, im Speicher zwischengespeichert, bis sich die Postings
der Person aendern. Gespeichert wird nichts.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import STATUS_DONE, Account, Post

MIN_SIMILARITY = 0.20
MIN_RARE_SHARED = 2
RARE_SHARE = 0.12          # "selten": in hoechstens 12 % der Postings der Person
MIN_WORDS = 5              # kuerzere Postings sagen zu wenig

_STOP = set("""
und oder aber auch noch nur schon jetzt dann mal immer sehr ganz ja nein doch heute hier dort alle alles
der die das den dem des ein eine einen einem einer eines kein keine keinen nicht nichts
ich du er sie es wir ihr mich dich sich uns euch mir dir ihm ihn ihnen mein meine meinen meiner meinem
dein deine sein seine ihre ihren unser unsere euer eure
ist sind war waren bin bist sei wird werden wurde wurden hat habe hatte haben hast kann können konnte muss
mit von zu zur zum auf aus bei nach vor für über unter um an am im in ins durch gegen ohne bis seit wie als
was wer wo wenn weil dass ob so da denn also nun gerade wieder viel viele mehr etwas einfach selbst
diese dieser dieses jede jeder jedes man gibt geht gar
""".split())
_SUFFIXES = ("ungen", "heiten", "keiten", "ung", "heit", "keit", "ern", "em", "en", "er", "es", "e", "n", "s")
_WORD = re.compile(r"[a-zäöüß]{3,}")


def _stem(w: str) -> str:
    if len(w) < 5:
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _surface(stem: str, text: str) -> str:
    """Fuer die Anzeige: das haeufigste echte Wort zum Stamm ("sage" -> "sagen")."""
    found = Counter(w for w in _WORD.findall(text.lower()) if _stem(w) == stem)
    return found.most_common(1)[0][0] if found else stem


def words(text: str) -> set[str]:
    text = re.sub(r"https?://\S+|@\S+", " ", (text or "").lower())
    return {_stem(w) for w in _WORD.findall(text) if w not in _STOP}


@dataclass
class Item:
    id: int
    when: datetime | None
    text: str


@dataclass
class Cluster:
    items: list[Item]                       # chronologisch
    words: list[str] = field(default_factory=list)   # gemeinsame, seltene Woerter
    score: float = 0.0

    @property
    def ids(self) -> set[int]:
        return {i.id for i in self.items}

    @property
    def span(self) -> str:
        years = sorted({i.when.year for i in self.items if i.when})
        if not years:
            return ""
        return str(years[0]) if years[0] == years[-1] else f"{years[0]}–{years[-1]}"


def find(items: list[Item]) -> list[Cluster]:
    """Gruppen fast gleicher Geschichten (mind. 2 Postings), groesste zuerst."""
    docs = [(it, words(it.text)) for it in items]
    docs = [(it, w) for it, w in docs if len(w) >= MIN_WORDS]
    n = len(docs)
    if n < 2:
        return []
    df = Counter(w for _, ws in docs for w in ws)
    idf = {w: math.log(n / c) for w, c in df.items()}
    norm = [math.sqrt(sum(idf[w] ** 2 for w in ws)) or 1.0 for _, ws in docs]
    rare_limit = max(RARE_SHARE * n, 5)     # bei wenigen Postings: in hoechstens 5 Postings
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Kandidaten nur ueber seltene Woerter: Paare, die sich mindestens zwei davon teilen
    postings: dict[str, list[int]] = {}
    for i, (_, ws) in enumerate(docs):
        for w in ws:
            if df[w] <= rare_limit and df[w] >= 2:
                postings.setdefault(w, []).append(i)
    rare_pairs: Counter = Counter()
    for ids in postings.values():
        rare_pairs.update(combinations(ids, 2))

    edge_score: dict[tuple[int, int], float] = {}
    for (i, j), k in rare_pairs.items():
        if k < MIN_RARE_SHARED:
            continue
        shared = docs[i][1] & docs[j][1]
        sim = sum(idf[w] ** 2 for w in shared) / (norm[i] * norm[j])
        if sim >= MIN_SIMILARITY:
            parent[root(i)] = root(j)
            edge_score[(i, j)] = sim

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        common = Counter(w for m in members for w in docs[m][1] if df[w] <= rare_limit)
        ranked = sorted((w for w, c in common.items() if c >= 2), key=lambda w: (-common[w], -idf[w], w))
        texts = " ".join(docs[m][0].text for m in members)
        top = [_surface(w, texts) for w in ranked[:4]]
        scores = [s for (a, b), s in edge_score.items() if a in members and b in members]
        its = sorted((docs[m][0] for m in members), key=lambda it: (it.when or datetime.min, it.id))
        out.append(Cluster(its, top, max(scores) if scores else 0.0))
    out.sort(key=lambda c: (-len(c.items), -c.score))
    return out


# --- Je Person, mit Zwischenspeicher ---------------------------------------------------------

_cache: dict[int, tuple[tuple, list[Cluster]]] = {}


def _signature(db: Session, person_id: int) -> tuple:
    row = db.execute(
        select(func.count(Post.id), func.max(Post.id), func.sum(func.length(Post.text)))
        .join(Account, Account.id == Post.account_id)
        .where(Account.person_id == person_id, Post.status == STATUS_DONE)
    ).one()
    return tuple(row)


def for_person(db: Session, person_id: int) -> list[Cluster]:
    sig = _signature(db, person_id)
    hit = _cache.get(person_id)
    if hit and hit[0] == sig:
        return hit[1]
    rows = db.execute(
        select(Post.id, Post.posted_at, Post.created_at, Post.text)
        .join(Account, Account.id == Post.account_id)
        .where(Account.person_id == person_id, Post.status == STATUS_DONE, Post.text != "")
    ).all()
    clusters = find([Item(r.id, r.posted_at or r.created_at, r.text) for r in rows])
    _cache[person_id] = (sig, clusters)
    return clusters


def for_post(db: Session, post: Post) -> Cluster | None:
    person_id = post.account.person_id if post.account else None
    if not person_id:
        return None
    return next((c for c in for_person(db, person_id) if post.id in c.ids), None)
