"""Gemeinsame Schnittstelle fuer alle Plattformen.

Eine neue Plattform (z. B. Mastodon) braucht nur ein Modul mit einer Klasse,
die PlatformService erfuellt, und einen Eintrag in platforms/__init__.py.
Der Rest der App (Hinzufuegen, Worker, Suche, Oberflaeche) bleibt gleich.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:  # Playwright nur zur Typpruefung, die Tests brauchen es nicht.
    from playwright.async_api import Browser


@dataclass
class ParsedPost:
    """Was sich allein aus der URL ablesen laesst."""

    platform: str
    post_id: str
    author_handle: str
    canonical_url: str
    author_did: str | None = None
    # Voller Wortlaut eines langen Beitrags (falls bekannt). Die Aufnahme setzt ihn
    # dann anstelle der gekuerzten Fassung ("Mehr anzeigen") ins Bild.
    full_text: str | None = None


@dataclass
class PostMetadata:
    """Was eine Plattform-API (ohne Login) ueber den Beitrag verraet."""

    text: str = ""
    display_name: str = ""
    handle: str = ""
    did: str | None = None
    posted_at: datetime | None = None
    alt_texts: list[str] = field(default_factory=list)
    # Bleibt bei Umbenennungen gleich: Bluesky-DID bzw. X-User-ID.
    author_id: str | None = None
    avatar_url: str = ""
    # Langer X-Beitrag (> 280 Zeichen). text_complete False = nur der gekuerzte Anfang.
    long_post: bool = False
    text_complete: bool = True


@dataclass
class CaptureResult:
    screenshot: Path
    # Optional ein engerer Ausschnitt nur mit dem Beitragstext - liefert
    # deutlich sauberere OCR-Ergebnisse als der ganze Beitrag.
    text_image: bytes | None = None
    method: str = ""
    # True: Text im Bild von der App ergaenzt (langer Beitrag), kein reines Abbild.
    reconstructed: bool = False


# Hoechstens so viele Teile werden zu einem Thread zusammengeklebt.
MAX_THREAD_PARTS = 20


class PlatformError(Exception):
    """Fehler mit einer Meldung, die so in der Oberflaeche stehen darf."""


class PostNotFound(PlatformError):
    """Beitrag geloescht, privat oder Profil nicht erreichbar."""


class PlatformService(Protocol):
    name: str          # interner Schluessel, z. B. "x"
    label: str         # Anzeigename, z. B. "X"
    # True: Text bevorzugt per API, OCR nur als Rueckfall (Bluesky).
    # False: Text per OCR aus dem Screenshot, API-Text nur als Rueckfall (X).
    prefers_api_text: bool

    def parse_url(self, url: str) -> ParsedPost | None:
        """Erkennt und zerlegt einen Link. None, wenn nicht zustaendig."""

    def dedup_key(self, parsed: ParsedPost) -> str:
        """Schluessel zur Duplikaterkennung."""

    async def resolve(self, parsed: ParsedPost, client: httpx.AsyncClient) -> ParsedPost:
        """Optional: fehlende IDs nachschlagen (z. B. Bluesky-DID)."""

    async def fetch_metadata(self, parsed: ParsedPost, client: httpx.AsyncClient) -> PostMetadata | None:
        """Text und Metadaten ohne Login holen. Darf PlatformError werfen."""

    async def thread_chain(self, parsed: ParsedPost, client: httpx.AsyncClient) -> list[ParsedPost]:
        """Alle Teile des Threads (nur Selbst-Antworten desselben Kontos), in
        Reihenfolge. Einzelbeitrag -> [parsed]. Wirft nie: im Zweifel [parsed]."""

    async def capture(self, parsed: ParsedPost, browser: "Browser", target: Path, dark: bool = True) -> CaptureResult:
        """Screenshot nur des Beitrag-Elements nach target schreiben.

        Ohne eigene Rahmen und Rundungen der Plattform: die Ecken rundet die
        App selbst, sonst passen sie nie zur Karte drumherum."""


# Hilfen ---------------------------------------------------------------------

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_filename(*parts: str) -> str:
    """Dateiname nur aus harmlosen Zeichen - kein '/', kein '..'."""
    name = "_".join(_SAFE_ID.sub("-", p).strip(".-") for p in parts if p)
    return (name or "beitrag")[:150]


def normalize_url_input(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


# ⚠️ 0.3.1: Embeds sind oft nicht ganzzahlig hoch (z. B. 527.4px). Playwright
# rundet den Ausschnitt auf und erwischt eine Zeile Seitenhintergrund - der ist
# bei den Embed-Seiten transparent und wurde als weisse Linie gerendert.
# Darum vor jedem Screenshot den Seitenhintergrund in der Farbe des Beitrags
# einfaerben. (Zusaetzlich schneidet services/shots.trim_edges Reste ab.)
_FILL_BG_JS = """el => {
  let n = el, bg = '';
  while (n && n !== document.documentElement) {
    const c = getComputedStyle(n).backgroundColor;
    if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') { bg = c; break; }
    n = n.parentElement;
  }
  if (!bg) bg = getComputedStyle(document.body).backgroundColor;
  if (bg && bg !== 'rgba(0, 0, 0, 0)') {
    document.documentElement.style.setProperty('background', bg, 'important');
    document.body.style.setProperty('background', bg, 'important');
  }
  return bg;
}"""


async def fill_page_background(locator) -> None:
    try:
        await locator.evaluate(_FILL_BG_JS)
    except Exception:  # nur Kosmetik - der Screenshot darf daran nie scheitern
        pass


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
