"""Galerie: Bilder hochladen, verkleinern, Kategorien verwalten.

Jedes Bild wird neu kodiert (EXIF-Drehung angewendet, Metadaten wie GPS weg):
  - Ansicht:   lange Seite hoechstens 2400 px, WebP q86
  - Vorschau:  hoechstens 720 px hoch, WebP q78 (fuer das Raster)
Gleiche Bilder (SHA-256 der Originaldatei) werden nicht doppelt gespeichert.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import secrets
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


def _process(data: bytes) -> tuple[bytes, bytes, int, int, str]:
    with Image.open(io.BytesIO(data)) as src:
        if src.format not in ALLOWED:
            raise GalleryError("Format nicht unterstützt")
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
        return full, thumb, img.width, img.height, f"#{r:02x}{g:02x}{b:02x}"


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
            full, thumb, w, h, color = _process(data)
        except (GalleryError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            result.failed.append(label)
            continue
        stem = secrets.token_hex(8)
        (folder / f"{stem}.webp").write_bytes(full)
        (folder / f"{stem}.thumb.webp").write_bytes(thumb)
        image = GalleryImage(
            path=f"gallery/{year}/{stem}.webp", thumb_path=f"gallery/{year}/{stem}.thumb.webp",
            width=w, height=h, color=color, sha256=digest, original_name=label,
            uploaded_by_id=user.id, categories=list(categories),
        )
        db.add(image)
        db.flush()
        result.added.append(image)
    db.commit()
    return result


def delete_image(db: Session, settings: Settings, image: GalleryImage) -> None:
    for rel in (image.path, image.thumb_path):
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


def query_images(db: Session, category_ids: list[int], uncategorized: bool) -> list[GalleryImage]:
    stmt = select(GalleryImage).order_by(GalleryImage.created_at.desc(), GalleryImage.id.desc())
    if uncategorized:
        stmt = stmt.where(~GalleryImage.categories.any())
    elif category_ids:  # mehrere Kategorien = "eine davon"
        stmt = stmt.where(GalleryImage.categories.any(GalleryCategory.id.in_(category_ids)))
    return list(db.scalars(stmt))
