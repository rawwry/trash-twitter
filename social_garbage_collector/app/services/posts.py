"""Postings: hinzufuegen, Duplikate erkennen, Tags, Archivsuche."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import Select, and_, exists, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from ..models import (
    PLATFORM_BLUESKY,
    PLATFORM_X,
    PLATFORMS,
    STATUS_PENDING,
    Account,
    ListPost,
    Post,
    PostList,
    Tag,
    User,
    post_tags,
    utcnow,
)
from . import accounts
from .platforms import detect
from .platforms.base import USER_AGENT

MAX_NOTE = 2000
MAX_TAGS = 20
_TAG_CLEAN = re.compile(r"[^\w\-äöüß+.]", re.UNICODE)


class AddPostError(ValueError):
    def __init__(self, message: str, existing: Post | None = None) -> None:
        super().__init__(message)
        self.existing = existing


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

def normalize_tag(raw: str) -> str:
    """'#Lustig ' -> 'lustig'. Nur Buchstaben, Ziffern, - _ + ."""
    tag = raw.strip().lstrip("#").lower()
    tag = _TAG_CLEAN.sub("", tag.replace(" ", "-"))
    return tag[:64]


def parse_tag_input(raw: str) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[,;\n]", raw or ""):
        tag = normalize_tag(part)
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:MAX_TAGS]


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    if not names:
        return []
    existing = {t.name: t for t in db.scalars(select(Tag).where(Tag.name.in_(names)))}
    out = []
    for name in names:
        tag = existing.get(name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            existing[name] = tag
        out.append(tag)
    return out


def set_post_tags(db: Session, post: Post, raw: str) -> None:
    post.tags = get_or_create_tags(db, parse_tag_input(raw))
    db.flush()
    remove_orphan_tags(db)


def remove_orphan_tags(db: Session) -> None:
    db.execute(text("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM post_tags)"))


def suggest_tags(db: Session, prefix: str, limit: int = 8) -> list[str]:
    prefix = normalize_tag(prefix)
    stmt = (
        select(Tag.name, func.count(post_tags.c.post_id).label("n"))
        .join(post_tags, post_tags.c.tag_id == Tag.id, isouter=True)
        .group_by(Tag.id)
        .order_by(text("n DESC"), Tag.name)
        .limit(limit)
    )
    if prefix:
        stmt = stmt.where(Tag.name.like(prefix.replace("%", "").replace("_", r"\_") + "%", escape="\\"))
    return [row[0] for row in db.execute(stmt)]


def all_tags(db: Session) -> list[str]:
    return list(db.scalars(select(Tag.name).order_by(Tag.name)))


# --------------------------------------------------------------------------
# Hinzufuegen
# --------------------------------------------------------------------------

def find_duplicate(db: Session, platform: str, dedup_key: str, post_id: str,
                   handle: str = "", did: str | None = None) -> Post | None:
    dup = db.scalar(select(Post).where(Post.dedup_key == dedup_key))
    if dup is None:
        dup = find_as_thread_part(db, platform, post_id)
    if dup or platform != PLATFORM_BLUESKY:
        return dup
    # Bluesky: derselbe Beitrag kann mal per Handle, mal per DID verlinkt sein.
    conds = []
    if did:
        conds.append(Post.author_did == did)
    if handle:
        conds.append(func.lower(Post.author_handle) == handle.lower())
    if not conds:
        return None
    return db.scalar(select(Post).where(Post.platform == platform, Post.post_id == post_id, or_(*conds)))


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_as_thread_part(db: Session, platform: str, post_id: str) -> Post | None:
    """Steckt der Beitrag schon als Teil eines Threads in eines anderen Postings?
    (zusammengeklebte Teile in thread_parts, von Hand ergaenzte in thread_extra)"""
    if not post_id:
        return None
    pid = _like_escape(post_id)
    segment = "/status/" if platform == "x" else "/post/"
    return db.scalar(select(Post).where(Post.platform == platform, or_(
        Post.thread_parts.like(f'%"post_id": "{pid}"%', escape="\\"),
        Post.thread_extra.like(f'%{segment}{pid}"%', escape="\\"),
    )).limit(1))


def parse_thread_extra(raw: str, platform: str) -> list[str]:
    """Von Hand ergaenzte Thread-Teile: ein Link pro Zeile, gleiche Plattform."""
    from .platforms.base import MAX_THREAD_PARTS

    urls: list[str] = []
    bad: list[str] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        found = detect(line)
        if not found or found[1].platform != platform:
            bad.append(line[:60])
            continue
        if found[1].canonical_url not in urls:
            urls.append(found[1].canonical_url)
    if bad:
        raise AddPostError("Diese Thread-Links passen nicht (andere Plattform oder kein Beitrags-Link): " + ", ".join(bad))
    if len(urls) >= MAX_THREAD_PARTS:
        raise AddPostError(f"Höchstens {MAX_THREAD_PARTS - 1} weitere Thread-Teile.")
    return urls


async def add_post(db: Session, user: User, url: str, note: str, tags_raw: str,
                   network: bool = True, thread_extra: str = "") -> Post:
    url = (url or "").strip()
    if not url:
        raise AddPostError("Bitte einen Link einfügen.")
    if len(url) > 500:
        raise AddPostError("Der Link ist zu lang.")
    found = detect(url)
    if not found:
        raise AddPostError(
            "Das ist kein unterstützter Beitrags-Link. Erwartet wird z. B. "
            "https://x.com/name/status/123… oder https://bsky.app/profile/name.bsky.social/post/3k…"
        )
    service, parsed = found
    if network:
        # Bluesky: DID sofort nachschlagen, damit Duplikate auch nach einem
        # Handle-Wechsel erkannt werden. Kurzer Timeout - klappt es nicht,
        # holt der Hintergrund-Task die DID spaeter nach.
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            parsed = await service.resolve(parsed, client)
    extras = parse_thread_extra(thread_extra, parsed.platform)
    key = service.dedup_key(parsed)
    dup = find_duplicate(db, parsed.platform, key, parsed.post_id, parsed.author_handle, parsed.author_did)
    if dup:
        raise AddPostError("Dieses Posting ist schon im Archiv.", existing=dup)

    post = Post(
        platform=parsed.platform,
        url=parsed.canonical_url,
        dedup_key=key,
        post_id=parsed.post_id,
        author_handle=parsed.author_handle,
        author_did=parsed.author_did,
        note=(note or "").strip()[:MAX_NOTE],
        status=STATUS_PENDING,
        added_by_id=user.id,
        thread_mode="off",  # automatische Thread-Erkennung seit 0.6.1 aus
        thread_extra=json.dumps(extras) if extras else "",
    )
    db.add(post)
    db.flush()
    set_post_tags(db, post, tags_raw)
    accounts.ensure_for_post(db, post)
    db.commit()
    return post


# --------------------------------------------------------------------------
# Archivsuche
# --------------------------------------------------------------------------

def fts_query(raw: str) -> str | None:
    """Macht aus Nutzereingaben eine sichere FTS5-Abfrage.

    Jedes Wort wird in Anfuehrungszeichen gesetzt (FTS5-Operatoren wie
    AND/NEAR/-/: verlieren so ihre Wirkung) und als Praefix gesucht.
    "In Anfuehrungszeichen" eingegebene Phrasen bleiben Phrasen.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    parts: list[str] = []
    for phrase, word in re.findall(r'"([^"]+)"|(\S+)', raw):
        if phrase:
            cleaned = phrase.replace('"', " ").strip()
            if cleaned:
                parts.append(f'"{cleaned}"')
        else:
            cleaned = word.replace('"', "")
            cleaned = re.sub(r"[^\w@#.\-']", "", cleaned, flags=re.UNICODE).strip(".-'")
            if cleaned:
                parts.append(f'"{cleaned}"*')
    return " ".join(parts) or None


@dataclass
class ArchiveFilter:
    q: str = ""
    platform: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    list_id: int | None = None
    user_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str = ""
    person_id: int | None = None
    account_id: int | None = None
    sort: str = "new"

    @property
    def active(self) -> bool:
        return any([self.q, self.platform, self.tags, self.author, self.list_id, self.user_id,
                    self.date_from, self.date_to, self.status, self.person_id, self.account_id])

    @property
    def advanced_count(self) -> int:
        """Anzahl aktiver Filter im aufklappbaren Filterbereich (fuer das Zaehler-Badge)."""
        return sum(bool(x) for x in (self.platform, self.author, self.list_id, self.user_id,
                                     self.date_from or self.date_to, self.status, self.person_id,
                                     self.account_id))


# posted: nach Datum des Postings (Standard), new/old: nach Archivierung.
SORTS = {"posted", "posted_old", "new", "old"}


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def filter_from_params(params, default_sort: str = "new") -> ArchiveFilter:
    platform = params.get("platform", "")
    sort = params.get("sort") or default_sort
    return ArchiveFilter(
        q=(params.get("q") or "")[:200],
        platform=platform if platform in PLATFORMS else "",
        tags=parse_tag_input(params.get("tags", "")),
        author=(params.get("author") or "").strip().lstrip("@")[:100],
        list_id=_parse_int(params.get("list")),
        user_id=_parse_int(params.get("user")),
        date_from=_parse_date(params.get("from")),
        date_to=_parse_date(params.get("to")),
        status=params.get("status", "") if params.get("status") in {"pending", "running", "done", "error"} else "",
        person_id=_parse_int(params.get("person")),
        account_id=_parse_int(params.get("account")),
        sort=sort if sort in SORTS else "new",
    )


def archive_query(f: ArchiveFilter) -> Select:
    stmt = select(Post).options(selectinload(Post.tags), selectinload(Post.added_by), selectinload(Post.media),
                                selectinload(Post.account).selectinload(Account.person))
    conds = []
    match = fts_query(f.q)
    if match:
        conds.append(Post.id.in_(
            select(text("rowid")).select_from(text("posts_fts"))
            .where(text("posts_fts MATCH :m").bindparams(m=match))
        ))
    if f.platform:
        conds.append(Post.platform == f.platform)
    for tag in f.tags:  # mehrere Tags = UND
        conds.append(exists().where(
            post_tags.c.post_id == Post.id,
            post_tags.c.tag_id == select(Tag.id).where(Tag.name == tag).scalar_subquery(),
        ))
    if f.author:
        like = f"%{f.author.lower()}%"
        conds.append(or_(func.lower(Post.author_handle).like(like),
                         func.lower(Post.author_display_name).like(like),
                         Post.author_did == f.author,
                         Post.account_id.in_(select(Account.id).where(or_(
                             func.lower(Account.handle).like(like), func.lower(Account.display_name).like(like))))))
    if f.person_id:
        conds.append(Post.account_id.in_(select(Account.id).where(Account.person_id == f.person_id)))
    if f.account_id:
        conds.append(Post.account_id == f.account_id)
    if f.list_id:
        conds.append(exists().where(ListPost.post_id == Post.id, ListPost.list_id == f.list_id))
    if f.user_id:
        conds.append(Post.added_by_id == f.user_id)
    # Zeitraum = wann das Posting gemacht wurde (Rueckfall: Archivierung).
    said = func.coalesce(Post.posted_at, Post.created_at)
    if f.date_from:
        conds.append(said >= datetime.combine(f.date_from, time.min))
    if f.date_to:
        conds.append(said < datetime.combine(f.date_to + timedelta(days=1), time.min))
    if f.status:
        conds.append(Post.status == f.status)
    if conds:
        stmt = stmt.where(and_(*conds))

    if f.sort == "new":
        return stmt.order_by(Post.created_at.desc(), Post.id.desc())
    if f.sort == "old":
        return stmt.order_by(Post.created_at.asc(), Post.id.asc())
    if f.sort == "posted_old":
        return stmt.order_by(said.asc(), Post.id.asc())
    return stmt.order_by(said.desc(), Post.id.desc())


def search_archive(db: Session, f: ArchiveFilter, page: int = 1, per_page: int = 30) -> tuple[list[Post], int]:
    stmt = archive_query(f)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    page = max(page, 1)
    posts = list(db.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).unique())
    return posts, total


# --------------------------------------------------------------------------
# Live-Pruefung beim Einfuegen und Nachbarn fuer die Detailseite
# --------------------------------------------------------------------------

@dataclass
class LinkCheck:
    state: str                 # empty | invalid | ok | duplicate
    platform: str = ""
    handle: str = ""
    post_id: str = ""
    existing: Post | None = None
    message: str = ""


def check_url(db: Session, url: str) -> LinkCheck:
    url = (url or "").strip()
    if not url:
        return LinkCheck("empty")
    found = detect(url)
    if not found:
        return LinkCheck("invalid", message="Kein Beitrags-Link von X oder Bluesky erkannt.")
    service, parsed = found
    key = service.dedup_key(parsed)
    dup = find_duplicate(db, parsed.platform, key, parsed.post_id, parsed.author_handle, parsed.author_did)
    state = "duplicate" if dup else "ok"
    return LinkCheck(state, parsed.platform, parsed.author_handle or parsed.author_did or "", parsed.post_id, dup)


def neighbors(db: Session, post: Post) -> tuple[int | None, int | None]:
    """(neuere, aeltere) Posting - nach dem Datum des Postings, wie im Archiv."""
    said = func.coalesce(Post.posted_at, Post.created_at)
    mine = post.said_at
    newer = db.scalar(select(Post.id).where(
        or_(said > mine, and_(said == mine, Post.id > post.id))
    ).order_by(said.asc(), Post.id.asc()).limit(1))
    older = db.scalar(select(Post.id).where(
        or_(said < mine, and_(said == mine, Post.id < post.id))
    ).order_by(said.desc(), Post.id.desc()).limit(1))
    return newer, older


# --------------------------------------------------------------------------
# Tags verwalten
# --------------------------------------------------------------------------

def tag_counts(db: Session) -> list[tuple[Tag, int]]:
    return list(db.execute(
        select(Tag, func.count(post_tags.c.post_id))
        .join(post_tags, post_tags.c.tag_id == Tag.id, isouter=True)
        .group_by(Tag.id).order_by(Tag.name)
    ).tuples())


def rename_tag(db: Session, tag: Tag, new_raw: str) -> str | None:
    """Benennt um; gibt es den Zielnamen schon, werden beide zusammengefuehrt.
    Rueckgabe: Fehlermeldung oder None."""
    new = normalize_tag(new_raw)
    if not new:
        return "Bitte einen gültigen Namen angeben."
    if new == tag.name:
        return None
    target = db.scalar(select(Tag).where(Tag.name == new))
    if target is None:
        tag.name = new
    else:
        for post in list(tag.posts):
            if target not in post.tags:
                post.tags.append(target)
        db.delete(tag)
    db.commit()
    return None


def detect_ok(url: str) -> bool:
    return bool(url) and detect(url) is not None


def add_many_to_list(db: Session, user: User, post_ids: list[int], target: PostList) -> tuple[int, int]:
    """Mehrere Beitraege in eine Liste legen. Rueckgabe: (neu abgelegt, schon drin)."""
    valid = set(db.scalars(select(Post.id).where(Post.id.in_(post_ids))))
    present = set(db.scalars(select(ListPost.post_id).where(ListPost.list_id == target.id,
                                                             ListPost.post_id.in_(valid))))
    added = 0
    for pid in post_ids:
        if pid in valid and pid not in present:
            db.add(ListPost(list_id=target.id, post_id=pid, added_by_id=user.id))
            present.add(pid)
            added += 1
    db.commit()
    return added, len(valid) - added


# --------------------------------------------------------------------------
# Selbst hochgeladene Screenshots
# --------------------------------------------------------------------------

def _posted_at(raw: str) -> datetime | None:
    try:
        return datetime.combine(date.fromisoformat(raw), time(12, 0)) if raw else None
    except ValueError:
        raise AddPostError("Das Datum ist ungültig.") from None


async def add_upload(db: Session, user: User, settings, blobs: list[bytes], link: str = "", platform: str = "",
                     handle: str = "", posted: str = "", text_: str = "", note: str = "", tags_raw: str = "",
                     network: bool = True) -> Post:
    """Beitrag aus eigenem Screenshot. Mit Link: Duplikat-Pruefung und Metadaten
    wie gewohnt, nur das Bild kommt vom Nutzer. Ohne Link: Plattform waehlen."""
    from ..config import safe_path
    from . import shots, uploads
    from .capture import CaptureWorker

    try:
        images = uploads.load_images(blobs)
    except uploads.UploadError as exc:
        raise AddPostError(str(exc)) from exc
    link = (link or "").strip()
    did, auto = None, False
    if link:
        found = detect(link)
        if not found:
            raise AddPostError("Der Link ist kein Beitrags-Link von X oder Bluesky. Lass ihn leer, wenn du keinen hast.")
        service, parsed = found
        if network:
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
                parsed = await service.resolve(parsed, client)
        key = service.dedup_key(parsed)
        dup = find_duplicate(db, parsed.platform, key, parsed.post_id, parsed.author_handle, parsed.author_did)
        if dup:
            raise AddPostError("Dieses Posting ist schon im Archiv – dort kannst du den Beleg-Screenshot ersetzen.",
                               existing=dup)
        platform, post_id, url, did = parsed.platform, parsed.post_id, parsed.canonical_url, parsed.author_did
        handle = parsed.author_handle or handle
    else:
        auto = platform not in PLATFORMS
        if auto:
            # 0.12: Die App erkennt die Plattform selbst (Worker liest den Screenshot).
            # Bis dahin: ein Handle mit Punkt kann nur Bluesky sein.
            platform = PLATFORM_BLUESKY if "." in (handle or "").strip().lstrip("@") else PLATFORM_X
        fp = uploads.fingerprint(blobs)
        key = f"upload:{fp}"
        dup = db.scalar(select(Post).where(Post.dedup_key == key))
        if dup:
            raise AddPostError("Genau dieses Bild wurde schon hochgeladen.", existing=dup)
        post_id, url = "u" + fp[:12], ""

    post = Post(
        platform=platform, url=url, dedup_key=key, post_id=post_id,
        author_handle=(handle or "").strip().lstrip("@")[:255], author_did=did,
        posted_at=_posted_at(posted), date_source="manual" if posted else None, date_has_time=False,
        note=(note or "").strip()[:MAX_NOTE],
        status=STATUS_PENDING, added_by_id=user.id, shot_source="upload", thread_mode="off",
        platform_auto=not link and auto,
    )
    text_ = (text_ or "").strip()[:20000]
    if text_:
        post.text, post.text_source = text_, "manual"
    db.add(post)
    db.flush()
    set_post_tags(db, post, tags_raw)
    accounts.ensure_for_post(db, post)
    rel = CaptureWorker._screenshot_rel(post)
    target = safe_path(settings.base_path, rel)
    uploads.save(images, target)
    post.screenshot_path = rel
    shots.apply(post, target)
    db.commit()
    return post


def replace_screenshot(db: Session, settings, post: Post, blobs: list[bytes]) -> None:
    """Eigenen Screenshot fuer einen vorhandenen Beitrag hochladen (z. B. wenn das
    Original geloescht ist). Die App nimmt danach nie wieder selbst auf."""
    from ..config import safe_path
    from . import shots, uploads
    from .capture import CaptureWorker

    try:
        images = uploads.load_images(blobs)
    except uploads.UploadError as exc:
        raise AddPostError(str(exc)) from exc
    rel = CaptureWorker._screenshot_rel(post)
    target = safe_path(settings.base_path, rel)
    uploads.save(images, target)
    if post.screenshot_path and post.screenshot_path != rel:
        try:
            safe_path(settings.base_path, post.screenshot_path).unlink(missing_ok=True)
        except Exception:
            pass
    post.screenshot_path = rel
    post.shot_source = "upload"
    post.shot_reconstructed = False
    post.thread_count, post.thread_parts = 0, ""
    shots.apply(post, target)
    post.status, post.status_message = STATUS_PENDING, ""  # Worker liest den Text neu
    post.updated_at = utcnow()
    db.commit()


# --------------------------------------------------------------------------
# Loeschen (einzeln und per Mehrfachauswahl)
# --------------------------------------------------------------------------

def delete_posts(db: Session, settings, posts: list[Post]) -> int:
    """Loescht Postings samt Beleg und gesicherten Medien. Danach verschwinden
    leere Tags, Accounts ohne Postings und unbearbeitete Personen ohne Accounts."""
    from ..config import UnsafePathError, safe_path

    for post in posts:
        files = [post.screenshot_path] + [p for m in getattr(post, "media", []) for p in (m.path, m.thumb_path)]
        for rel in filter(None, files):
            try:
                safe_path(settings.base_path, rel).unlink(missing_ok=True)
            except (UnsafePathError, OSError):
                pass
        db.delete(post)
    db.flush()
    remove_orphan_tags(db)
    accounts.prune_empty(db)
    db.commit()
    return len(posts)
