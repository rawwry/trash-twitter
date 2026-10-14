"""Personen und Accounts: wer hat eine Aussage gemacht?

Jede Aussage gehoert zu einem Account, jeder Account zu einer Person.

- Accounts werden ueber ihre feste ID erkannt (Bluesky-DID, X-User-ID). Neuer
  Handle, neuer Name oder neues Profilbild -> derselbe Account, plus ein
  Eintrag im Verlauf (account_changes).
- Ist die ID noch unbekannt (Upload ohne Link, Netz aus), wird ueber den
  Handle zugeordnet. Taucht die ID spaeter auf, wird der Account aufgewertet
  bzw. mit dem schon bekannten Account zusammengelegt.
- Personen entstehen automatisch (eine pro neuem Account). Gehoeren mehrere
  Accounts zu einem Menschen, fuehrt man sie von Hand zusammen.
"""

from __future__ import annotations

import hashlib
import io
import logging

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import PLATFORM_BLUESKY, Account, AccountChange, Person, Post, utcnow

log = logging.getLogger("sgc.accounts")

AVATAR_SIZE = 200
AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_HOSTS = ("pbs.twimg.com", "abs.twimg.com", "cdn.bsky.app", "av-cdn.bsky.app")
MAX_PERSON_NAME = 200
MAX_PERSON_NOTE = 5000


def clean_handle(platform: str, handle: str | None) -> str:
    handle = (handle or "").strip().lstrip("@")[:255]
    return handle.lower() if platform == PLATFORM_BLUESKY else handle


# --------------------------------------------------------------------------
# Account finden oder anlegen
# --------------------------------------------------------------------------

def _record(db: Session, acc: Account, field: str, new: str | None) -> None:
    """Setzt ein Feld und merkt sich die Aenderung im Verlauf."""
    new = (new or "").strip()
    old = getattr(acc, field) or ""
    if not new or new == old:
        return
    if old:
        db.add(AccountChange(account_id=acc.id, field=field, old_value=old, new_value=new))
    setattr(acc, field, new)


def _sync_person_name(acc: Account) -> None:
    person = acc.person
    if person is not None and not person.name_locked:
        person.name = (acc.display_name or acc.label)[:MAX_PERSON_NAME]


def _new_account(db: Session, platform: str, stable_id: str | None, handle: str, display_name: str) -> Account:
    person = Person(name=(display_name or (f"@{handle}" if handle else "Unbekannt"))[:MAX_PERSON_NAME])
    db.add(person)
    db.flush()
    acc = Account(platform=platform, stable_id=stable_id, handle=handle, display_name=display_name,
                  person_id=person.id)
    db.add(acc)
    db.flush()
    return acc


def _by_handle(db: Session, platform: str, handle: str, unbound_only: bool) -> Account | None:
    if not handle:
        return None
    stmt = select(Account).where(Account.platform == platform, func.lower(Account.handle) == handle.lower())
    if unbound_only:
        stmt = stmt.where(Account.stable_id.is_(None))
    return db.scalar(stmt.order_by(Account.id.desc()).limit(1))


def resolve(db: Session, platform: str, stable_id: str | None = None, handle: str | None = None,
            display_name: str | None = None, candidate: Account | None = None) -> Account | None:
    """Liefert den passenden Account (legt ihn bei Bedarf an) und haelt Handle
    und Namen aktuell. Ohne ID und ohne Handle: None.

    candidate: der Account, an dem die Aussage bisher haengt. Hat er noch
    keine feste ID, ist er derselbe wie der jetzt gefundene - auch wenn der
    Handle inzwischen anders lautet (Umbenennung)."""
    stable_id = (stable_id or "").strip() or None
    handle = clean_handle(platform, handle)
    display_name = (display_name or "").strip()[:255]
    if not stable_id and not handle:
        return None

    acc = None
    if stable_id:
        acc = db.scalar(select(Account).where(Account.platform == platform, Account.stable_id == stable_id))
        if candidate is not None and candidate.stable_id is None and candidate.platform == platform:
            unbound = candidate
        else:
            unbound = _by_handle(db, platform, handle, unbound_only=True)
        if acc is None and unbound is not None:
            # Bisher nur per Handle bekannt -> jetzt mit fester ID.
            acc, unbound = unbound, None
            acc.stable_id = stable_id
        if acc is not None and unbound is not None and unbound.id != acc.id:
            merge_accounts(db, unbound, acc)
    else:
        acc = _by_handle(db, platform, handle, unbound_only=False)

    if acc is None:
        return _new_account(db, platform, stable_id, handle, display_name)
    _record(db, acc, "handle", handle)
    _record(db, acc, "display_name", display_name)
    _sync_person_name(acc)
    db.flush()
    return acc


def attach(db: Session, post: Post, acc: Account | None) -> None:
    """Haengt eine Aussage an einen Account. Ein dadurch leerer Account ohne
    feste ID (nur per Handle angelegt) wird aufgeraeumt."""
    if acc is None or post.account_id == acc.id:
        return
    old = db.get(Account, post.account_id) if post.account_id else None
    post.account = acc
    if post.author_avatar_path is None and acc.avatar_path:
        post.author_avatar_path = acc.avatar_path
    db.flush()
    if old is not None and old.stable_id is None and not _has_posts(db, old.id):
        _delete_account(db, old)


def ensure_for_post(db: Session, post: Post) -> Account | None:
    """Ohne Netz: Account aus dem, was die Aussage selbst weiss (Handle, DID)."""
    stable = post.author_did if post.platform == PLATFORM_BLUESKY else None
    acc = resolve(db, post.platform, stable, post.author_handle, post.author_display_name)
    attach(db, post, acc)
    return acc


def _has_posts(db: Session, account_id: int) -> bool:
    return db.scalar(select(Post.id).where(Post.account_id == account_id).limit(1)) is not None


def _delete_account(db: Session, acc: Account) -> None:
    person = acc.person
    db.delete(acc)
    db.flush()
    if person is not None:
        _cleanup_person(db, person)


def prune_empty(db: Session) -> int:
    """Nach dem Loeschen von Postings: Accounts ohne Postings entfernen, dann
    Personen ohne Accounts (ausser jemand hat sie bearbeitet - Foto, Name, Text)."""
    empty = list(db.scalars(select(Account).where(~Account.posts.any())))
    for acc in empty:
        _delete_account(db, acc)
    return len(empty)


def _cleanup_person(db: Session, person: Person) -> None:
    """Personen ohne Accounts verschwinden - ausser jemand hat sie bearbeitet."""
    db.refresh(person)
    if (not person.accounts and not person.name_locked and not (person.note or "").strip()
            and not person.subtitle and not person.photo_path):
        db.delete(person)
        db.flush()


# --------------------------------------------------------------------------
# Zusammenfuehren und Trennen
# --------------------------------------------------------------------------

def merge_accounts(db: Session, source: Account, target: Account) -> None:
    """Zwei Datensaetze desselben Kontos (z. B. erst per Handle, dann per ID
    bekannt) werden einer. Aussagen und Verlauf wandern mit."""
    if source.id == target.id:
        return
    # Ueber die Beziehungen umhaengen, nicht ueber die ID-Spalten: sonst
    # loescht die Kaskade beim Entfernen von source den Verlauf mit.
    for post in db.scalars(select(Post).where(Post.account_id == source.id)):
        post.account = target
    for change in list(source.changes):
        change.account = target
    if source.avatar_path and not target.avatar_path:
        target.avatar_path = source.avatar_path
    if source.handle and source.handle != target.handle:
        db.add(AccountChange(account_id=target.id, field="handle", old_value=source.handle,
                             new_value=target.handle or source.handle))
    db.flush()
    _delete_account(db, source)


def move_account(db: Session, acc: Account, person: Person) -> Person | None:
    """Account einer anderen Person zuordnen. Gibt die alte Person zurueck,
    falls es sie danach noch gibt."""
    old = acc.person
    if old is not None and old.id == person.id:
        return old
    acc.person = person
    db.flush()
    if old is None:
        return None
    _cleanup_person(db, old)
    return old if old in db else None


def merge_persons(db: Session, source: Person, target: Person) -> None:
    """Alle Accounts von source gehoeren danach zu target; source verschwindet.
    Notizen werden aneinandergehaengt, nichts geht verloren."""
    if source.id == target.id:
        return
    for acc in list(source.accounts):
        acc.person = target
    if (source.note or "").strip():
        joined = "\n\n".join(x for x in ((target.note or "").strip(), source.note.strip()) if x)
        target.note = joined[:MAX_PERSON_NOTE * 2]
    target.name_locked = target.name_locked or source.name_locked
    target.subtitle = target.subtitle or source.subtitle
    if source.photo_path and not target.photo_path:
        target.photo_path, source.photo_path = source.photo_path, None
    db.flush()
    db.delete(source)
    db.flush()


def split_account(db: Session, acc: Account) -> Person:
    """Account aus einer Person loesen -> eigene, neue Person."""
    person = Person(name=(acc.display_name or acc.label)[:MAX_PERSON_NAME])
    db.add(person)
    db.flush()
    move_account(db, acc, person)
    return person


def rename_person(person: Person, name: str, note: str, subtitle: str | None = None) -> None:
    name = " ".join((name or "").split())[:MAX_PERSON_NAME]
    if name and name != person.name:
        person.name = name
        person.name_locked = True
    person.note = (note or "").strip()[:MAX_PERSON_NOTE]
    if subtitle is not None:
        person.subtitle = " ".join(subtitle.split())[:120]


# --------------------------------------------------------------------------
# Profilbilder der Verfasser
# --------------------------------------------------------------------------

def _allowed_avatar_url(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    return parsed.scheme == "https" and (parsed.hostname or "") in AVATAR_HOSTS


def process_avatar(data: bytes) -> bytes:
    """Prueft das Bild und speichert es klein und quadratisch als WebP neu."""
    with Image.open(io.BytesIO(data)) as img:
        img.seek(0)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, "WEBP", quality=82, method=4)
        return out.getvalue()


async def download_avatar(client: httpx.AsyncClient, settings: Settings, url: str) -> str | None:
    """Laedt ein Profilbild und legt es unter authors/ ab. Gleiche Bilder
    landen in derselben Datei (Name = Pruefsumme). Rueckgabe: relativer Pfad."""
    if not _allowed_avatar_url(url):
        return None
    try:
        resp = await client.get(url, timeout=10)
    except httpx.HTTPError as exc:
        log.info("Profilbild nicht ladbar: %s", exc)
        return None
    if resp.status_code != 200 or not resp.content or len(resp.content) > AVATAR_MAX_BYTES:
        return None
    try:
        webp = process_avatar(resp.content)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None
    name = hashlib.sha256(webp).hexdigest()[:24] + ".webp"
    settings.author_dir.mkdir(parents=True, exist_ok=True)
    target = settings.author_dir / name
    if not target.exists():
        target.write_bytes(webp)
    return f"authors/{name}"


def set_avatar(db: Session, acc: Account, rel: str | None) -> None:
    if rel:
        _record(db, acc, "avatar_path", rel)


async def apply_metadata(db: Session, settings: Settings, client: httpx.AsyncClient | None,
                         post: Post, meta) -> Account | None:
    """Nach dem Abruf der Metadaten: Account bestimmen, Profilbild sichern,
    Aussage anhaengen. Das Profilbild der Aussage bleibt auf dem Stand der
    ersten Archivierung - spaetere Wechsel stehen nur im Account-Verlauf."""
    stable = meta.author_id or (meta.did if post.platform == PLATFORM_BLUESKY else None)
    acc = resolve(db, post.platform, stable, meta.handle or post.author_handle,
                  meta.display_name or post.author_display_name, candidate=post.account)
    if acc is None:
        return None
    if client is not None and meta.avatar_url:
        rel = await download_avatar(client, settings, meta.avatar_url)
        set_avatar(db, acc, rel)
    acc.checked_at = utcnow()
    attach(db, post, acc)
    if post.author_avatar_path is None and acc.avatar_path:
        post.author_avatar_path = acc.avatar_path
    db.flush()
    return acc


# --------------------------------------------------------------------------
# Uebernahme alter Daten (vor 0.6) und Abfragen
# --------------------------------------------------------------------------

def backfill(db: Session) -> int:
    """Aussagen ohne Account bekommen einen (ohne Netz, aus Handle/DID)."""
    count = 0
    for post in db.scalars(select(Post).where(Post.account_id.is_(None)).order_by(Post.id)):
        if ensure_for_post(db, post) is not None:
            count += 1
    if count:
        db.commit()
        log.info("%d Aussagen einem Account zugeordnet.", count)
    return count


def needing_refresh(db: Session, limit: int = 50) -> list[Account]:
    """Accounts ohne Profilbild, die noch nie nachgeschlagen wurden."""
    return list(db.scalars(select(Account).where(Account.avatar_path.is_(None), Account.checked_at.is_(None))
                           .order_by(Account.id).limit(limit)))


def person_stats(db: Session, person_ids: list[int]) -> dict[int, dict]:
    """Anzahl Aussagen und Zeitraum je Person (fuer die Uebersicht)."""
    if not person_ids:
        return {}
    said = func.coalesce(Post.posted_at, Post.created_at)
    rows = db.execute(
        select(Account.person_id, func.count(Post.id), func.min(said), func.max(said))
        .join(Post, Post.account_id == Account.id)
        .where(Account.person_id.in_(person_ids))
        .group_by(Account.person_id)
    )
    return {pid: {"count": n, "first": first, "last": last} for pid, n, first, last in rows}


def list_persons(db: Session, q: str = "") -> list[Person]:
    stmt = select(Person).order_by(func.lower(func.ltrim(Person.name, "@")))
    q = (q or "").strip().lstrip("@").lower()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            func.lower(Person.name).like(like),
            Person.id.in_(select(Account.person_id).where(or_(func.lower(Account.handle).like(like),
                                                              func.lower(Account.display_name).like(like)))),
        ))
    return list(db.scalars(stmt))
