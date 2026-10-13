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

from PIL import Image, ImageOps, UnidentifiedImageError

from . import shots

MAX_FILES = 10
MAX_BYTES = 15 * 1024 * 1024
MAX_WIDTH = 1400          # breiter bringt fuer Screenshots nichts, kostet nur Platz
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 60_000_000  # Schutz vor Dekompressionsbomben


class UploadError(ValueError):
    pass


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
                img.seek(0)
                img = ImageOps.exif_transpose(img).convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise UploadError(f"Bild {n} ist kein lesbares Bild.") from exc
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.Resampling.LANCZOS)
        images.append(img)
    return images


def fingerprint(blobs: list[bytes]) -> str:
    """Kennung fuer die Duplikaterkennung: dieselben Dateien -> derselbe Wert."""
    h = hashlib.sha256()
    for data in blobs:
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def save(images: list[Image.Image], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    out = shots.stitch(images)
    tmp = target.with_name(target.name + ".tmp")
    out.save(tmp, "WEBP", quality=shots.WEBP_QUALITY, method=4)
    os.replace(tmp, target)
