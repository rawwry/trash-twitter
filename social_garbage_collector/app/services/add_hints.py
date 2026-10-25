"""Hinzufuegen leichter machen (0.22): Vorschau und Tag-Vorschlaege zum eingefuegten Link.

Sobald ein Link erkannt ist, holt die App den Wortlaut kurz bei der Plattform
(ohne zu archivieren) und schlaegt Tags vor:
  - "automatisch": was die Tag-Regeln ohnehin vergeben werden,
  - "passend": die Tags, die Postings dieser Person bisher am haeufigsten haben.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Account, Person, Post, Tag, TagRule, post_tags
from .platforms.base import USER_AGENT, ParsedPost, PlatformError, PostMetadata, PostNotFound

log = logging.getLogger("sgc")

PREVIEW_TIMEOUT_S = 6.0


@dataclass
class Hints:
    text: str = ""
    author: str = ""
    gone: bool = False                       # Plattform sagt: gibt es nicht (mehr)
    person: Person | None = None
    auto: list[str] = field(default_factory=list)       # vergibt eine Regel ohnehin
    suggested: list[str] = field(default_factory=list)  # haeufig bei dieser Person


async def fetch_preview(service, parsed: ParsedPost) -> tuple[PostMetadata | None, bool]:
    """(Metadaten, gone). Netzprobleme -> (None, False)."""
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            meta = await asyncio.wait_for(service.fetch_metadata(parsed, client), PREVIEW_TIMEOUT_S)
        return meta, False
    except PostNotFound:
        return None, True
    except (PlatformError, httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
        log.info("Vorschau nicht moeglich: %s", exc)
        return None, False


def person_for(db: Session, parsed: ParsedPost) -> Person | None:
    conds = []
    if parsed.author_handle:
        conds.append(func.lower(Account.handle) == parsed.author_handle.lower())
    if parsed.author_did:
        conds.append(Account.stable_id == parsed.author_did)
    if not conds:
        return None
    acc = db.scalar(select(Account).where(Account.platform == parsed.platform, or_(*conds), Account.person_id.is_not(None))
                    .limit(1))
    return acc.person if acc else None


def person_tags(db: Session, person_id: int, limit: int = 6) -> list[str]:
    rows = db.execute(
        select(Tag.name, func.count()).join(post_tags, post_tags.c.tag_id == Tag.id)
        .join(Post, Post.id == post_tags.c.post_id).join(Account, Account.id == Post.account_id)
        .where(Account.person_id == person_id).group_by(Tag.id).order_by(func.count().desc(), Tag.name).limit(limit)
    ).all()
    return [name for name, _ in rows]


def rule_tags(db: Session, text: str, person_id: int | None) -> list[str]:
    from .autotag import matcher_for

    out = []
    for rule in db.scalars(select(TagRule).where(TagRule.active.is_(True))):
        if rule.person_id and rule.person_id != person_id:
            continue
        if rule.tag.name not in out and matcher_for(rule)(text):
            out.append(rule.tag.name)
    return out


def build(db: Session, parsed: ParsedPost, meta: PostMetadata | None, gone: bool) -> Hints:
    hints = Hints(gone=gone)
    if meta:
        hints.text = (meta.text or "").strip()
        hints.author = meta.display_name or ""
    hints.person = person_for(db, parsed)
    pid = hints.person.id if hints.person else None
    if hints.text:
        hints.auto = rule_tags(db, hints.text, pid)
    if pid:
        hints.suggested = [t for t in person_tags(db, pid) if t not in hints.auto]
    return hints
