"""Bilder, GIFs und Videos aus Postings sichern (0.10.0).

- X:       Bilder in Originalgroesse von pbs.twimg.com, Videos und GIFs als MP4
           von video.twimg.com (bestes Format).
- Bluesky: Bilder von cdn.bsky.app, Videos als ORIGINALDATEI direkt vom Server
           des Accounts (PDS, com.atproto.sync.getBlob) - so braucht es kein
           ffmpeg zum Zusammensetzen der Streaming-Haeppchen. GIFs sind bei
           Bluesky Tenor-/Giphy-Links und werden von dort geladen.

Sicherheit: nur https, nur bekannte Bild-/Video-Server - einzige Ausnahme ist
der PDS eines Accounts, der muss eine oeffentliche IP-Adresse haben (kein
Zugriff ins Heimnetz). Groessenbremse je Datei (Option media_max_mb).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import mimetypes
import secrets
import socket
from datetime import datetime
from urllib.parse import quote, urlparse

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..models import Post, PostMedia

log = logging.getLogger("sgc.media")

MEDIA_HOSTS = {
    "pbs.twimg.com", "video.twimg.com", "cdn.bsky.app", "video.bsky.app",
    "media.tenor.com", "c.tenor.com", "media.giphy.com", "i.giphy.com",
}
MAX_PER_POST = 10
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}


class MediaError(Exception):
    pass


def _host_ok(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host in MEDIA_HOSTS or host.endswith(".giphy.com"))


async def _public_host(host: str) -> bool:
    """Nur Server mit oeffentlicher Adresse - kein Weg ins Heimnetz (SSRF)."""
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, 443)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def pds_blob_url(client: httpx.AsyncClient, did: str, cid: str) -> str | None:
    """Wo liegt die Originaldatei? DID-Dokument -> PDS -> getBlob."""
    if did.startswith("did:plc:"):
        doc_url = f"https://plc.directory/{did}"
    elif did.startswith("did:web:"):
        doc_url = f"https://{did.removeprefix('did:web:')}/.well-known/did.json"
    else:
        return None
    try:
        resp = await client.get(doc_url, timeout=10)
        services = resp.json().get("service") or [] if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None
    endpoint = next((s.get("serviceEndpoint") for s in services if str(s.get("id", "")).endswith("#atproto_pds")), None)
    parsed = urlparse(endpoint or "")
    if parsed.scheme != "https" or not parsed.hostname or not await _public_host(parsed.hostname):
        return None
    return f"{endpoint.rstrip('/')}/xrpc/com.atproto.sync.getBlob?did={quote(did)}&cid={quote(cid)}"


async def _download(client: httpx.AsyncClient, url: str, max_bytes: int, hops: int = 3) -> tuple[bytes, str]:
    # Weiterleitungen nur zu erlaubten bzw. oeffentlichen Servern folgen.
    async with client.stream("GET", url, timeout=60, follow_redirects=False) as resp:
        if resp.status_code in (301, 302, 303, 307, 308) and hops > 0:
            nxt = str(resp.url.join(resp.headers.get("location", "")))
            host = urlparse(nxt).hostname or ""
            if urlparse(nxt).scheme == "https" and (_host_ok(nxt) or await _public_host(host)):
                return await _download(client, nxt, max_bytes, hops - 1)
            raise MediaError("Weiterleitung zu unbekanntem Server")
        if resp.status_code != 200:
            raise MediaError(f"HTTP {resp.status_code}")
        mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        length = int(resp.headers.get("content-length") or 0)
        if length and length > max_bytes:
            raise MediaError("zu groß")
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise MediaError("zu groß")
            chunks.append(chunk)
    return b"".join(chunks), mime


def _sniff(data: bytes, mime: str) -> str:
    """Dateityp aus dem Inhalt (Server liefern oft application/octet-stream)."""
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "video/quicktime" if data[8:10] == b"qt" else "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    return mime


async def save_media(db: Session, settings: Settings, client: httpx.AsyncClient, post: Post, refs: list) -> list[str]:
    """Laedt die Medien eines Postings und legt sie ab. Rueckgabe: Probleme (fuer den Status)."""
    problems: list[str] = []
    if not settings.save_media or post.media:
        post.media_checked = True
        return problems
    max_bytes = settings.media_max_mb * 1024 * 1024
    year = (post.created_at or datetime.now()).year
    folder = settings.media_dir / post.platform / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    for pos, ref in enumerate(refs[:MAX_PER_POST]):
        url = ref.url
        if not url and ref.did and ref.cid:
            url = await pds_blob_url(client, ref.did, ref.cid)
            if not url:
                problems.append("Video: Server des Accounts nicht erreichbar.")
                continue
        elif not _host_ok(url):
            continue
        try:
            data, mime = await _download(client, url, max_bytes)
        except (MediaError, httpx.HTTPError) as exc:
            problems.append(f"{'Video' if ref.kind == 'video' else 'GIF' if ref.kind == 'gif' else 'Bild'} nicht gesichert ({exc}).")
            continue
        mime = _sniff(data, mime)
        if mime not in _EXT:
            problems.append(f"Medium mit unbekanntem Format übersprungen ({mime or '?'}).")
            continue
        name = f"{post.post_id[:40]}-{pos}-{secrets.token_hex(3)}{_EXT[mime]}"
        target = folder / name
        target.write_bytes(data)
        width, height = ref.width, ref.height
        if mime.startswith("image/") and not (width and height):
            try:
                with Image.open(target) as im:
                    width, height = im.size
            except OSError:
                pass
        thumb = None
        if mime.startswith("image/"):
            thumb = make_thumb(target)
        elif ref.poster and _host_ok(ref.poster):
            try:
                poster, _ = await _download(client, ref.poster, 10 * 1024 * 1024)
                thumb = make_thumb(target, poster)
            except (MediaError, httpx.HTTPError):
                pass
        post.media.append(PostMedia(position=pos, kind=ref.kind, path=f"media/{post.platform}/{year}/{name}",
                         thumb_path=_rel(settings, thumb) if thumb else None,
                         mime=mime, width=width, height=height, bytes=len(data), alt=ref.alt or "",
                         source_url=(ref.url or url)[:2000]))
    post.media_checked = True
    db.flush()
    return problems


THUMB_EDGE = 720


def make_thumb(target, data: bytes | None = None):
    """Vorschaubild <name>.thumb.webp neben der Datei - aus dem Bild selbst
    (oder bei Videos aus dem Vorschaubild der Plattform). None bei Fehlern."""
    import io

    from PIL import ImageOps

    out = target.with_name(target.stem + ".thumb.webp")
    try:
        with Image.open(io.BytesIO(data) if data else target) as im:
            im.seek(0)
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
            im.save(out, "WEBP", quality=78, method=4)
        return out
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _rel(settings: Settings, path) -> str:
    return str(path.resolve().relative_to(settings.base_path.resolve()))


def backfill_thumbs(db: Session, settings: Settings) -> int:
    """Beim Start: Vorschaubilder fuer Bilder, die vor 0.11 gesichert wurden."""
    from sqlalchemy import select

    done = 0
    for m in db.scalars(select(PostMedia).where(PostMedia.thumb_path.is_(None), PostMedia.mime.like("image/%"))):
        try:
            target = safe_path(settings.base_path, m.path)
        except UnsafePathError:
            continue
        if target.is_file() and (thumb := make_thumb(target)):
            m.thumb_path = _rel(settings, thumb)
            done += 1
    if done:
        db.commit()
        log.info("%d Vorschaubilder fuer gesicherte Medien erzeugt.", done)
    return done


def remove_files(settings: Settings, post: Post) -> None:
    for m in post.media:
        try:
            safe_path(settings.base_path, m.path).unlink(missing_ok=True)
        except (UnsafePathError, OSError):
            pass


def guess_mime(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"
