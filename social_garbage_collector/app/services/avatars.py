"""Profilbilder: pruefen, quadratisch zuschneiden, klein speichern.

Hochgeladene Dateien werden nie unveraendert abgelegt: Pillow oeffnet sie
(das ist die eigentliche Pruefung), dreht sie nach EXIF, schneidet die Mitte
quadratisch aus und speichert 256x256 als WebP neu. Damit sind auch
Metadaten wie GPS-Daten aus Handyfotos weg.
"""

from __future__ import annotations

import io
import logging
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import Settings, UnsafePathError, safe_path
from ..models import User
from .image_limits import validate_size

log = logging.getLogger("sgc.avatars")

MAX_BYTES = 8 * 1024 * 1024
SIZE = 256
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
# Schutz vor "Dekompressionsbomben" (winzige Datei, riesiges Bild).


class AvatarError(ValueError):
    pass


def process(data: bytes) -> bytes:
    if not data:
        raise AvatarError("Keine Datei ausgewählt.")
    if len(data) > MAX_BYTES:
        raise AvatarError("Das Bild ist zu groß (höchstens 8 MB).")
    try:
        with Image.open(io.BytesIO(data)) as img:
            validate_size(img.width, img.height)
            if img.format not in ALLOWED_FORMATS:
                raise AvatarError("Bitte ein JPG-, PNG-, WebP- oder GIF-Bild hochladen.")
            img.seek(0)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img = ImageOps.fit(img, (SIZE, SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=85, method=4)
            return out.getvalue()
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AvatarError("Das ist kein lesbares Bild.") from exc


def _remove_file(settings: Settings, rel: str | None) -> None:
    if not rel:
        return
    try:
        safe_path(settings.base_path, rel).unlink(missing_ok=True)
    except (UnsafePathError, OSError):
        pass


def save(settings: Settings, user: User, data: bytes) -> None:
    webp = process(data)
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    # Zufallsteil im Namen = neue URL bei jedem Wechsel -> Browser-Cache passt immer.
    name = f"{user.id}-{secrets.token_hex(4)}.webp"
    (settings.avatar_dir / name).write_bytes(webp)
    user.avatar_path = f"avatars/{name}"


def remove(settings: Settings, user: User) -> None:
    user.avatar_path = None


# --- Eigenes Foto fuer eine Person (nur Darstellung, 0.7.0) -----------------------

def save_person_photo(settings: Settings, person, data: bytes) -> None:
    webp = process(data)
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    name = f"p{person.id}-{secrets.token_hex(4)}.webp"
    (settings.avatar_dir / name).write_bytes(webp)
    person.photo_path = f"avatars/{name}"


def remove_person_photo(settings: Settings, person) -> None:
    person.photo_path = None


def commit_change(db, settings: Settings, old: str | None, new: str | None) -> None:
    try:
        db.commit()
    except BaseException:
        db.rollback()
        if new != old:
            _remove_file(settings, new)
        raise
    if old != new:
        _remove_file(settings, old)
