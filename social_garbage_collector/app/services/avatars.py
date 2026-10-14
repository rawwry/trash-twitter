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

log = logging.getLogger("sgc.avatars")

MAX_BYTES = 8 * 1024 * 1024
SIZE = 256
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
# Schutz vor "Dekompressionsbomben" (winzige Datei, riesiges Bild).
Image.MAX_IMAGE_PIXELS = 40_000_000


class AvatarError(ValueError):
    pass


def process(data: bytes) -> bytes:
    if not data:
        raise AvatarError("Keine Datei ausgewählt.")
    if len(data) > MAX_BYTES:
        raise AvatarError("Das Bild ist zu groß (höchstens 8 MB).")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise AvatarError("Bitte ein JPG-, PNG-, WebP- oder GIF-Bild hochladen.")
            img.seek(0)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img = ImageOps.fit(img, (SIZE, SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=85, method=4)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
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
    _remove_file(settings, user.avatar_path)
    user.avatar_path = f"avatars/{name}"


def remove(settings: Settings, user: User) -> None:
    _remove_file(settings, user.avatar_path)
    user.avatar_path = None


# --- Eigenes Foto fuer eine Person (nur Darstellung, 0.7.0) -----------------------

PORTRAIT = (720, 900)  # 4:5 - fuellt die Personen-Kachel komplett


def process_portrait(data: bytes) -> bytes:
    """Wie process(), aber hochkant 4:5 und groesser - fuer Personenfotos."""
    if not data:
        raise AvatarError("Keine Datei ausgewählt.")
    if len(data) > MAX_BYTES:
        raise AvatarError("Das Bild ist zu groß (höchstens 8 MB).")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise AvatarError("Bitte ein JPG-, PNG-, WebP- oder GIF-Bild hochladen.")
            img.seek(0)
            img = ImageOps.exif_transpose(img).convert("RGB")
            # Kleine Bilder nicht kuenstlich aufblasen
            w = min(PORTRAIT[0], img.width, int(img.height * 0.8))
            size = (max(w, 64), max(int(w * 1.25), 80))
            img = ImageOps.fit(img, size, Image.Resampling.LANCZOS, centering=(0.5, 0.35))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=84, method=4)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AvatarError("Das ist kein lesbares Bild.") from exc


def save_person_photo(settings: Settings, person, data: bytes) -> None:
    webp = process_portrait(data)
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    name = f"p{person.id}-{secrets.token_hex(4)}.webp"
    (settings.avatar_dir / name).write_bytes(webp)
    _remove_file(settings, person.photo_path)
    person.photo_path = f"avatars/{name}"


def remove_person_photo(settings: Settings, person) -> None:
    _remove_file(settings, person.photo_path)
    person.photo_path = None
