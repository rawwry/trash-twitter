"""Zentrale Einstellungen und Pfade.

Alles kommt aus Umgebungsvariablen (run.sh uebersetzt die HA-Optionen),
jeweils mit einem sinnvollen Standardwert. Die Tests bauen sich ihre eigenen
Settings-Objekte und reichen sie an create_app() weiter.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("sgc")

DEFAULT_BASE_PATH = "/share/SocialGarbageCollector"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    base_path: Path = field(default_factory=lambda: Path(DEFAULT_BASE_PATH))
    admin_username: str = "admin"
    admin_password: str = ""
    # Notfall (0.10.1): beim Start admin_username auf admin_password zuruecksetzen
    reset_password: bool = False
    session_hours: int = 168
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    backup_keep: int = 7
    # "dark" oder "light": in welchem Look X und Bluesky fotografiert werden.
    screenshot_theme: str = "dark"
    # Bilder, GIFs und Videos aus Postings mitsichern (0.10.0); Grenze je Datei.
    save_media: bool = True
    media_max_mb: int = 150
    # Im Test aus: kein Playwright, kein Netz, keine Hintergrund-Tasks.
    worker_enabled: bool = True
    # Im Test aus: kein DID-Lookup beim Hinzufuegen.
    network_enabled: bool = True

    # --- abgeleitete Pfade -------------------------------------------------
    @property
    def db_dir(self) -> Path:
        return self.base_path / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "archiv.sqlite"

    @property
    def screenshot_dir(self) -> Path:
        return self.base_path / "screenshots"

    @property
    def backup_dir(self) -> Path:
        return self.base_path / "backups"

    @property
    def avatar_dir(self) -> Path:
        return self.base_path / "avatars"

    @property
    def media_dir(self) -> Path:
        # Bilder, GIFs und Videos aus den Postings (nicht die Beleg-Screenshots)
        return self.base_path / "media"

    @property
    def gallery_dir(self) -> Path:
        return self.base_path / "gallery"

    @property
    def author_dir(self) -> Path:
        # Profilbilder der zitierten Accounts (nicht der Mitglieder).
        return self.base_path / "authors"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_path=Path(os.environ.get("SGC_BASE_PATH") or DEFAULT_BASE_PATH),
            admin_username=os.environ.get("SGC_ADMIN_USERNAME") or "admin",
            admin_password=os.environ.get("SGC_ADMIN_PASSWORD") or "",
            reset_password=_env_bool("SGC_RESET_PASSWORD", False),
            session_hours=_env_int("SGC_SESSION_HOURS", 168),
            cookie_secure=_env_bool("SGC_COOKIE_SECURE", False),
            login_max_attempts=_env_int("SGC_LOGIN_MAX_ATTEMPTS", 5),
            login_lock_minutes=_env_int("SGC_LOGIN_LOCK_MINUTES", 15),
            backup_keep=_env_int("SGC_BACKUP_KEEP", 7),
            screenshot_theme="light" if os.environ.get("SGC_SCREENSHOT_THEME") == "light" else "dark",
            save_media=_env_bool("SGC_SAVE_MEDIA", True),
            media_max_mb=_env_int("SGC_MEDIA_MAX_MB", 150),
            worker_enabled=_env_bool("SGC_WORKER_ENABLED", True),
            network_enabled=_env_bool("SGC_NETWORK_ENABLED", True),
        )


class StorageError(RuntimeError):
    """Datenordner fehlt oder ist nicht beschreibbar."""


def prepare_storage(settings: Settings) -> None:
    """Legt fehlende Unterordner an und prueft, ob alles beschreibbar ist.

    Schlaegt das fehl, gibt es eine klare Meldung im Log und die App startet
    nicht - lieber ein rotes Add-on als stillschweigend verlorene Daten.
    """
    base = settings.base_path
    if not base.is_relative_to("/share"):
        # Nur ein Hinweis: ausserhalb von /share ueberlebt nichts ein Rebuild.
        log.warning("Datenordner %s liegt nicht unter /share - im Add-on gehen Daten bei einem Neubau verloren.", base)
    try:
        for d in (base, settings.db_dir, settings.screenshot_dir, settings.backup_dir, settings.avatar_dir,
                  settings.author_dir, settings.gallery_dir, settings.media_dir):
            d.mkdir(parents=True, exist_ok=True)
        probe = base / ".schreibtest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        msg = (
            f"FEHLER: Datenordner {base} ist nicht beschreibbar ({exc}). "
            "Ist in config.yaml 'map: share:rw' gesetzt und existiert /share?"
        )
        log.error(msg)
        raise StorageError(msg) from exc


class UnsafePathError(ValueError):
    """Pfad zeigt aus dem erlaubten Ordner heraus."""


def safe_path(root: Path, relative: str | os.PathLike[str]) -> Path:
    """Loest einen relativen Pfad sicher unterhalb von root auf.

    Schutz vor Pfad-Manipulation: absolute Pfade, Null-Bytes und alles, was
    nach dem Aufloesen (inkl. Symlinks und '..') ausserhalb von root landet,
    wird abgelehnt.
    """
    rel = str(relative)
    if not rel or "\x00" in rel or os.path.isabs(rel) or rel.startswith(("\\", "~")):
        raise UnsafePathError(rel)
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise UnsafePathError(rel)
    return candidate
