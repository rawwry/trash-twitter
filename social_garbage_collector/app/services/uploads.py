"""Selbst hochgeladene Screenshots: pruefen, aufbereiten, als WebP ablegen.

Wie bei Profilbildern wird nie die Originaldatei gespeichert: Pillow oeffnet
jedes Bild (das ist die eigentliche Pruefung), dreht es nach EXIF, entfernt
Metadaten (z. B. GPS aus Handyfotos), verkleinert sehr grosse Bilder und
speichert neu. Mehrere Bilder werden wie ein Thread untereinander geklebt.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from . import shots
from .image_limits import MAX_CANVAS_PIXELS, validate_size, run_image_job

MAX_FILES = 10
MAX_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_WIDTH = 1400          # breiter bringt fuer Screenshots nichts, kostet nur Platz
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class UploadError(ValueError):
    pass


@dataclass
class PreparedUpload:
    images: list[Image.Image]
    digest: str

    def close(self) -> None:
        for image in self.images:
            image.close()


def _check_canvas(images: list[Image.Image]) -> None:
    if images:
        validate_size(max(i.width for i in images),
                      sum(i.height for i in images) + shots.THREAD_GAP * (len(images) - 1),
                      pixels=MAX_CANVAS_PIXELS)


async def prepare_files(files) -> PreparedUpload:
    files = [f for f in files if f and f.filename]
    if not files:
        raise UploadError("Bitte mindestens ein Bild auswählen.")
    if len(files) > MAX_FILES:
        raise UploadError(f"Höchstens {MAX_FILES} Bilder auf einmal.")
    images, total, digest = [], 0, hashlib.sha256()
    try:
        for file in files:
            data = await file.read(min(MAX_BYTES, MAX_TOTAL_BYTES - total) + 1)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise UploadError("Zusammen höchstens 50 MB pro Upload.")
            digest.update(hashlib.sha256(data).digest())
            images.extend(await run_image_job(load_images, [data]))
            _check_canvas(images)
        return PreparedUpload(images, digest.hexdigest())
    except BaseException as exc:
        for image in images:
            image.close()
        if isinstance(exc, ValueError):
            raise UploadError(str(exc)) from exc
        raise


def load_images(blobs: list[bytes]) -> list[Image.Image]:
    if not blobs:
        raise UploadError("Bitte mindestens ein Bild auswählen.")
    if len(blobs) > MAX_FILES:
        raise UploadError(f"Höchstens {MAX_FILES} Bilder auf einmal.")
    images = []
    for n, data in enumerate(blobs, start=1):
        if len(data) > MAX_BYTES:
            raise UploadError(f"Bild {n} ist zu groß (höchstens 15 MB).")
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.format not in ALLOWED_FORMATS:
                    raise UploadError(f"Bild {n}: bitte JPG, PNG, WebP oder GIF (iPhone: „Kompatibelste“ Fotoformat).")
                validate_size(img.width, img.height)
                img.seek(0)
                img = ImageOps.exif_transpose(img).convert("RGB")
        except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise UploadError(f"Bild {n} ist kein lesbares Bild.") from exc
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.Resampling.LANCZOS)
        images.append(img)
        try:
            _check_canvas(images)
        except ValueError as exc:
            for image in images:
                image.close()
            raise UploadError(str(exc)) from exc
    return images


def fingerprint(blobs: list[bytes]) -> str:
    """Kennung fuer die Duplikaterkennung: dieselben Dateien -> derselbe Wert."""
    h = hashlib.sha256()
    for data in blobs:
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def save(images: list[Image.Image], target: Path) -> None:
    _check_canvas(images)
    target.parent.mkdir(parents=True, exist_ok=True)
    out = shots.stitch(images)
    tmp = target.with_name(target.name + ".tmp")
    try:
        out.save(tmp, "WEBP", quality=shots.WEBP_QUALITY, method=4)
        os.replace(tmp, target)
    finally:
        out.close()
        tmp.unlink(missing_ok=True)
