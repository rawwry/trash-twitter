"""Massenimport: viele Links auf einmal, der Worker arbeitet sie nacheinander ab.

Duplikate werden dreifach abgefangen - nichts wird doppelt archiviert:
  1. doppelt im eingefuegten Text (auch als x.com/twitter.com/?s=…-Varianten)
  2. schon im Archiv (gleicher Duplikat-Schluessel, bei Bluesky auch Handle/DID)
  3. schon als Teil eines Threads eines anderen Postings
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from ..models import STATUS_PENDING, ImportBatch, ListPost, Post, PostList, User
from . import accounts
from .platforms import detect
from .platforms.base import USER_AGENT

MAX_LINKS = 500
MAX_INPUT = 200_000
# Links im Freitext: mit oder ohne https://, auch mitten in Saetzen.
_URL = re.compile(r"(?:https?://)?(?:www\.|mobile\.)?(?:x\.com|twitter\.com|fxtwitter\.com|vxtwitter\.com|bsky\.app)/[^\s<>\"'()\[\]]+",
                  re.IGNORECASE)
_ANY_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_TRAILING = ".,;:!?…»«“”‘’"


class BulkError(ValueError):
    pass


@dataclass
class Candidate:
    url: str
    line: str


@dataclass
class BulkResult:
    batch: ImportBatch
    created: list[Post] = field(default_factory=list)


def extract(raw: str) -> tuple[list[Candidate], list[str]]:
    """Alle Beitrags-Links aus dem Text, in Reihenfolge. Zeilen ohne erkennbaren
    X-/Bluesky-Link (aber mit Inhalt) kommen als "nicht erkannt" zurueck."""
    found: list[Candidate] = []
    invalid: list[str] = []
    for line in (raw or "")[:MAX_INPUT].splitlines():
        line = line.strip()
        if not line:
            continue
        hits = [m.group(0).rstrip(_TRAILING) for m in _URL.finditer(line)]
        if hits:
            found.extend(Candidate(h, line) for h in hits)
        else:
            # andere Links (z. B. Zeitungsartikel) oder Text ohne Link
            others = [m.group(0) for m in _ANY_URL.finditer(line)]
            invalid.extend(others or [line])
    return found, [i[:200] for i in invalid]


async def import_links(db: Session, user: User, raw: str, tags_raw: str = "", target_list: PostList | None = None,
                       network: bool = True) -> BulkResult:
    from .posts import find_duplicate, set_post_tags

    candidates, invalid = extract(raw)
    if not candidates and not invalid:
        raise BulkError("Bitte Links einfügen – einen pro Zeile oder einfach hintereinander.")
    if len(candidates) > MAX_LINKS:
        raise BulkError(f"Höchstens {MAX_LINKS} Links auf einmal ({len(candidates)} gefunden). Bitte aufteilen.")

    # 1) Erst alle Links erkennen und (Bluesky) Handles nachschlagen - OHNE offene
    #    Schreib-Transaktion. Sonst haelt der Import bei vielen Bluesky-Links die
    #    Datenbank minutenlang gesperrt und andere Anfragen laufen in Fehler 500.
    detected = []
    for cand in candidates:
        found = detect(cand.url)
        if not found:
            invalid.append(cand.url[:200])
            continue
        detected.append((cand, *found))
    if network and any(svc.name == "bluesky" and not parsed.author_did for _, svc, parsed in detected):
        sem = asyncio.Semaphore(6)
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            async def _resolve(svc, parsed):
                async with sem:
                    return await svc.resolve(parsed, client)  # Bluesky: Handle -> DID
            resolved = await asyncio.gather(*(_resolve(svc, parsed) for _, svc, parsed in detected))
        detected = [(cand, svc, parsed) for (cand, svc, _), parsed in zip(detected, resolved)]

    # 2) Dann in einem kurzen Rutsch speichern
    batch = ImportBatch(id=secrets.token_hex(6), created_by_id=user.id, total_links=len(candidates))
    db.add(batch)
    result = BulkResult(batch=batch)
    seen: set[str] = set()
    existing: list[dict] = []
    repeated: list[str] = []
    for cand, service, parsed in detected:
        key = service.dedup_key(parsed)
        # Bluesky: gleicher Beitrag per Handle und per DID -> auch ueber post_id abgleichen
        short = f"{parsed.platform}:{parsed.post_id}"
        if key in seen or short in seen:
            repeated.append(cand.url)
            continue
        seen.update({key, short})
        dup = find_duplicate(db, parsed.platform, key, parsed.post_id, parsed.author_handle, parsed.author_did)
        if dup:
            existing.append({"url": cand.url, "post_id": dup.id})
            continue
        post = Post(
            platform=parsed.platform, url=parsed.canonical_url, dedup_key=key, post_id=parsed.post_id,
            author_handle=parsed.author_handle, author_did=parsed.author_did, status=STATUS_PENDING,
            added_by_id=user.id, thread_mode="off", import_batch=batch.id,
        )
        db.add(post)
        db.flush()
        set_post_tags(db, post, tags_raw)
        accounts.ensure_for_post(db, post)
        if target_list is not None:
            db.add(ListPost(list_id=target_list.id, post_id=post.id, added_by_id=user.id))
        result.created.append(post)

    batch.created_count = len(result.created)
    batch.existing = json.dumps(existing)
    batch.repeated = json.dumps(repeated)
    batch.invalid = json.dumps(invalid[:200])
    db.commit()
    return result
