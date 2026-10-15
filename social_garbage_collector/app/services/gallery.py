"""Galerie: Bilder und Videos hochladen, Kategorien verwalten.

Jedes Bild wird neu kodiert (EXIF-Drehung angewendet, Metadaten wie GPS weg):
  - Ansicht:   lange Seite hoechstens 2400 px, WebP q86
  - Vorschau:  hoechstens 720 px hoch, WebP q78 (fuer das Raster)
Gleiche Bilder (SHA-256 der Originaldatei) werden nicht doppelt gespeichert.

Videos (0.13) bleiben im Original (MP4, MOV, WebM) - umrechnen waere auf dem
Pi zu langsam. Das Standbild fuer Raster und Player schickt der Browser beim
Hochladen mit (app.js zeichnet ein Bild aus dem Video). Fehlt es, versucht es
der Server mit ffmpeg (falls installiert), sonst gibt es eine neutrale Flaeche.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..models import GalleryCategory, GalleryImage, User, gallery_image_categories

log = logging.getLogger("sgc.gallery")

MAX_FILES = 40
MAX_BYTES = 25 * 1024 * 1024
FULL_EDGE = 2400
THUMB_HEIGHT = 720
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF", "HEIF", "MPO", "BMP", "TIFF"}
Image.MAX_IMAGE_PIXELS = 80_000_000
MAX_CATEGORY = 60


# Videos: Endung nach Dateikopf (nicht nach dem, was der Browser behauptet)
VIDEO_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
VIDEO_HINTS = (".mp4", ".m4v", ".mov", ".webm", ".qt")
CHUNK = 1024 * 1024


def is_video_upload(filename: str, content_type: str) -> bool:
    return (content_type or "").startswith("video/") or (filename or "").lower().endswith(VIDEO_HINTS)


def sniff_video(head: bytes) -> str | None:
    """Endung aus den ersten Bytes: ISO-Container (MP4/MOV) oder Matroska (WebM)."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ".mov" if head[8:12] == b"qt  " else ".mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    return None


class GalleryError(ValueError):
    pass


@dataclass
class UploadResult:
    added: list[GalleryImage] = field(default_factory=list)
    duplicates: int = 0
    failed: list[str] = field(default_factory=list)


def _encode(img: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    img.save(out, "WEBP", quality=quality, method=4)
    return out.getvalue()


def _taken_at(img: Image.Image) -> datetime | None:
    """Aufnahmezeitpunkt aus EXIF (DateTimeOriginal, sonst DateTime). Die
    Kameradaten selbst werden danach nicht mitgespeichert."""
    try:
        exif = img.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        when = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S") if raw else None
    except Exception:
        return None
    return when if when and datetime(1990, 1, 1) < when < datetime.now().replace(year=datetime.now().year + 1) else None


def _process(data: bytes) -> tuple[bytes, bytes, int, int, str, datetime | None]:
    with Image.open(io.BytesIO(data)) as src:
        if src.format not in ALLOWED:
            raise GalleryError("Format nicht unterstützt")
        taken = _taken_at(src)
        src.seek(0)
        img = ImageOps.exif_transpose(src)
        img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
        if img.mode == "RGBA":  # Transparenz auf Weiss, WebP-Vorschau sonst dunkel
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        img.thumbnail((FULL_EDGE, FULL_EDGE), Image.Resampling.LANCZOS)
        full = _encode(img, 86)
        thumb_img = img.copy()
        if thumb_img.height > THUMB_HEIGHT:
            thumb_img.thumbnail((10_000, THUMB_HEIGHT), Image.Resampling.LANCZOS)
        thumb = _encode(thumb_img, 78)
        r, g, b = (int(v) for v in ImageStat.Stat(img.resize((16, 16))).mean[:3])
        return full, thumb, img.width, img.height, f"#{r:02x}{g:02x}{b:02x}", taken


def normalize_category(raw: str) -> str:
    return " ".join((raw or "").split())[:MAX_CATEGORY]


def get_or_create_categories(db: Session, user: User, ids: list[int], new_raw: str) -> list[GalleryCategory]:
    cats = list(db.scalars(select(GalleryCategory).where(GalleryCategory.id.in_(ids)))) if ids else []
    for name in re.split(r"[,;\n]", new_raw or ""):
        name = normalize_category(name)
        if not name:
            continue
        cat = db.scalar(select(GalleryCategory).where(func.lower(GalleryCategory.name) == name.lower()))
        if cat is None:
            cat = GalleryCategory(name=name, created_by_id=user.id)
            db.add(cat)
            db.flush()
        if cat not in cats:
            cats.append(cat)
    return cats


def add_images(db: Session, settings: Settings, user: User, files: list[tuple[str, bytes]],
               categories: list[GalleryCategory]) -> UploadResult:
    if not files:
        raise GalleryError("Bitte mindestens ein Bild auswählen.")
    if len(files) > MAX_FILES:
        raise GalleryError(f"Höchstens {MAX_FILES} Bilder auf einmal.")
    result = UploadResult()
    year = datetime.now().year
    folder = settings.gallery_dir / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        label = (name or "Bild")[:80]
        if len(data) > MAX_BYTES:
            result.failed.append(f"{label} (größer als 25 MB)")
            continue
        digest = hashlib.sha256(data).hexdigest()
        if db.scalar(select(GalleryImage.id).where(GalleryImage.sha256 == digest)):
            result.duplicates += 1
            continue
        try:
            full, thumb, w, h, color, taken = _process(data)
        except (GalleryError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            result.failed.append(label)
            continue
        stem = secrets.token_hex(8)
        (folder / f"{stem}.webp").write_bytes(full)
        (folder / f"{stem}.thumb.webp").write_bytes(thumb)
        image = GalleryImage(
            path=f"gallery/{year}/{stem}.webp", thumb_path=f"gallery/{year}/{stem}.thumb.webp",
            width=w, height=h, color=color, sha256=digest, original_name=label, taken_at=taken,
            uploaded_by_id=user.id, categories=list(categories),
        )
        db.add(image)
        db.flush()
        result.added.append(image)
    db.commit()
    return result


def _placeholder_poster() -> bytes:
    """Neutrale 16:9-Flaeche, wenn es kein Standbild gibt (Abspielen geht trotzdem)."""
    img = Image.new("RGB", (1280, 720), (31, 34, 41))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _ffmpeg_poster(video: "os.PathLike[str]", duration: float | None) -> bytes | None:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    at = f"{min(1.0, (duration or 2) / 3):.2f}"
    try:
        run = subprocess.run([exe, "-v", "error", "-ss", at, "-i", os.fspath(video), "-frames:v", "1",
                              "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout if run.returncode == 0 and run.stdout else None


async def add_video(db: Session, settings: Settings, user: User, upload, poster: bytes | None,
                    duration: float | None, categories: list[GalleryCategory], result: UploadResult) -> None:
    """Speichert ein Video im Original (gestreamt, ohne alles in den Speicher zu laden)."""
    label = (upload.filename or "Video")[:80]
    limit = max(1, settings.media_max_mb) * 1024 * 1024
    year = datetime.now().year
    folder = settings.gallery_dir / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    stem = secrets.token_hex(8)
    tmp = folder / f"{stem}.part"
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with open(tmp, "wb") as out:
            while chunk := await upload.read(CHUNK):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > limit:
                    result.failed.append(f"{label} (größer als {settings.media_max_mb} MB)")
                    return
                digest.update(chunk)
                out.write(chunk)
        suffix = sniff_video(head)
        if suffix is None:
            result.failed.append(label)
            return
        sha = digest.hexdigest()
        if db.scalar(select(GalleryImage.id).where(GalleryImage.sha256 == sha)):
            result.duplicates += 1
            return
        target = folder / f"{stem}{suffix}"
        os.replace(tmp, target)
        if duration is not None and not (0 < duration < 86_400):
            duration = None
        frame = None
        for candidate in (poster, None):
            data = candidate if candidate is not None else await _to_thread(_ffmpeg_poster, target, duration)
            if not data:
                continue
            try:
                frame = _process(data)
                break
            except (GalleryError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
                continue
        full, thumb, w, h, color, _ = frame or _process(_placeholder_poster())
        (folder / f"{stem}.webp").write_bytes(full)
        (folder / f"{stem}.thumb.webp").write_bytes(thumb)
        image = GalleryImage(
            kind="video", path=f"gallery/{year}/{stem}{suffix}", poster_path=f"gallery/{year}/{stem}.webp",
            thumb_path=f"gallery/{year}/{stem}.thumb.webp", width=w, height=h, color=color, sha256=sha,
            original_name=label, mime=VIDEO_MIME[suffix], bytes=size, duration=duration,
            uploaded_by_id=user.id, categories=list(categories),
        )
        db.add(image)
        db.flush()
        result.added.append(image)
    finally:
        tmp.unlink(missing_ok=True)


async def _to_thread(fn, *args):
    import asyncio

    return await asyncio.to_thread(fn, *args)


def delete_image(db: Session, settings: Settings, image: GalleryImage) -> None:
    for rel in (image.path, image.thumb_path, image.poster_path):
        if not rel:
            continue
        try:
            safe_path(settings.base_path, rel).unlink(missing_ok=True)
        except (UnsafePathError, OSError):
            pass
    db.delete(image)
    db.commit()


def category_counts(db: Session) -> list[tuple[GalleryCategory, int]]:
    return [tuple(r) for r in db.execute(
        select(GalleryCategory, func.count(gallery_image_categories.c.image_id))
        .join(gallery_image_categories, gallery_image_categories.c.category_id == GalleryCategory.id, isouter=True)
        .group_by(GalleryCategory.id).order_by(func.lower(GalleryCategory.name))
    ).all()]


# Sortierungen der Galerie (0.12). Standard: zufaellig - jeder Besuch zeigt andere Bilder zuerst.
SORTS = {
    "zufall": "Zufällig",
    "neu": "Zuletzt hinzugefügt",
    "aufnahme": "Neueste Aufnahmen",
    "alt": "Zuerst hinzugefügt",
}


def query_images(db: Session, category_ids: list[int], uncategorized: bool, sort: str = "zufall") -> list[GalleryImage]:
    if sort == "neu":
        order = (GalleryImage.created_at.desc(), GalleryImage.id.desc())
    elif sort == "alt":
        order = (GalleryImage.created_at.asc(), GalleryImage.id.asc())
    elif sort == "aufnahme":
        order = (func.coalesce(GalleryImage.taken_at, GalleryImage.created_at).desc(), GalleryImage.id.desc())
    else:
        order = (func.random(),)
    stmt = select(GalleryImage).order_by(*order)
    if uncategorized:
        stmt = stmt.where(~GalleryImage.categories.any())
    elif category_ids:  # mehrere Kategorien = "eine davon"
        stmt = stmt.where(GalleryImage.categories.any(GalleryCategory.id.in_(category_ids)))
    return list(db.scalars(stmt))
