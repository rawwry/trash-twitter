"""Geloescht-Waechter (0.21): sind die Originale noch online?

Der Worker prueft im Hintergrund nach und nach alle Postings mit Link, ganz
gemaechlich (ein Posting alle paar Sekunden, jedes hoechstens alle paar Tage).
  - Antwortet die Plattform "gibt es nicht" (geloescht, geschuetzt, Konto
    gesperrt), zaehlt das als Fehlschlag. Erst beim zweiten Fehlschlag in Folge
    gilt das Original als weg - ein Ausrutscher der Plattform macht so keinen
    falschen Vermerk. Nach dem ersten wird bald noch einmal geprueft.
  - Netzfehler und Bot-Schutz sagen nichts aus: dann bleibt alles, wie es ist.
  - Taucht ein Original wieder auf (z. B. Konto entsperrt), wird der Vermerk
    zurueckgenommen.
Wird ein Original als weg erkannt, bekommt die Person, die es archiviert hat,
eine Benachrichtigung.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import STATUS_DONE, Notification, Post, utcnow
from .platforms import get_service
from .platforms.base import ParsedPost, PlatformError, PostNotFound

log = logging.getLogger("sgc")

ONLINE, GONE = "online", "gone"
RECHECK_AFTER = timedelta(days=3)       # online: so selten erneut pruefen
RECHECK_SUSPECT = timedelta(hours=1)    # nach dem ersten Fehlschlag: bald nochmal
RECHECK_GONE = timedelta(days=7)        # weg: ab und zu schauen, ob es zurueck ist
MISSES_FOR_GONE = 2


async def probe(post: Post, client: httpx.AsyncClient) -> str | None:
    """ONLINE, GONE oder None (keine Aussage moeglich)."""
    if not post.url or not post.post_id:
        return None
    service = get_service(post.platform)
    parsed = ParsedPost(platform=post.platform, post_id=post.post_id, author_handle=post.author_handle,
                        canonical_url=post.url, author_did=post.author_did)
    try:
        meta = await service.fetch_metadata(parsed, client)
    except PostNotFound:
        return GONE
    except (PlatformError, httpx.HTTPError, ValueError) as exc:
        log.info("Original %s nicht pruefbar: %s", post.id, exc)
        return None
    return ONLINE if meta is not None else None


def record(db: Session, post: Post, result: str | None) -> bool:
    """Ergebnis eintragen. Rueckgabe: True, wenn das Original gerade als weg erkannt wurde."""
    now = utcnow()
    post.origin_checked_at = now   # auch ohne Aussage: nicht sofort wieder dieselbe Anfrage
    if result is None:
        return False
    if result == ONLINE:
        post.origin_misses = 0
        post.origin_state = ONLINE
        post.origin_gone_at = None
        return False
    post.origin_misses = (post.origin_misses or 0) + 1
    if post.origin_misses >= MISSES_FOR_GONE and post.origin_state != GONE:
        post.origin_state = GONE
        post.origin_gone_at = now
        if post.added_by_id:
            db.add(Notification(user_id=post.added_by_id, kind="gone", post_id=post.id))
        return True
    return False


def due(db: Session, limit: int = 20) -> list[Post]:
    """Die naechsten zu pruefenden Postings: nie geprueft zuerst, dann die aeltesten."""
    now = utcnow()
    stmt = (select(Post).where(Post.status == STATUS_DONE, Post.url != "", Post.post_id != "")
            .where(or_(Post.origin_checked_at.is_(None),
                       (Post.origin_misses > 0) & (Post.origin_state != GONE) & (Post.origin_checked_at < now - RECHECK_SUSPECT),
                       (Post.origin_state == GONE) & (Post.origin_checked_at < now - RECHECK_GONE),
                       (Post.origin_state != GONE) & (Post.origin_checked_at < now - RECHECK_AFTER)))
            .order_by(Post.origin_checked_at.is_not(None), Post.origin_checked_at, Post.id)
            .limit(limit))
    return list(db.scalars(stmt))
