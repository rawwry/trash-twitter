"""Collage (0.22): viele Postings als eine grosse, gut gestaltete Grafik (JPG).

Die Collage ist eine eigenstaendige HTML-Seite in fester Groesse
(templates/collage_render.html). static/collage.js ordnet die Karten an: es
probiert Spaltenzahlen und Schriftgroessen durch und nimmt die Anordnung, bei
der alles auf die Flaeche passt und die Schrift am groessten bleibt.
  - Vorschau im Studio: dieselbe Seite im iframe (Bilder per URL).
  - Export: Playwright rendert die Seite mit eingebetteten Bildern und
    Schriften (data:-URIs, kein Login noetig) und macht ein JPG daraus.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, UnsafePathError, safe_path
from ..models import Account, Post

MAX_POSTS = 80
STATIC = Path(__file__).resolve().parent.parent / "static"

# Formate: (Schluessel, Name, Breite, Hoehe) - Hoehe 0 = so lang wie noetig
FORMATS = {
    "square": ("Quadrat", 2160, 2160),
    "portrait": ("Hochformat", 2160, 2700),
    "story": ("Story", 2160, 3840),
    "wide": ("Breit", 3840, 2160),
    "long": ("Endlos", 2160, 0),
}
STYLES = {"light": "Hell", "dark": "Dunkel", "paper": "Papier", "accent": "Akzent"}
MODES = {"cards": "Karten", "shots": "Belege"}


@dataclass
class Options:
    fmt: str = "portrait"
    style: str = "light"
    mode: str = "cards"
    title: str = ""
    subtitle: str = ""
    dates: bool = True
    numbers: bool = False
    media: bool = True
    footer: bool = True
    highlight: str = ""      # Suchwoerter, die in den Karten markiert werden

    @property
    def size(self) -> tuple[int, int]:
        _, w, h = FORMATS[self.fmt]
        return w, h

    @classmethod
    def from_params(cls, p) -> "Options":
        def flag(name: str, default: bool) -> bool:
            v = p.get(name)
            return default if v is None else v in ("1", "on", "true")
        return cls(
            fmt=p.get("format") if p.get("format") in FORMATS else "portrait",
            style=p.get("stil") if p.get("stil") in STYLES else "light",
            mode=p.get("inhalt") if p.get("inhalt") in MODES else "cards",
            title=" ".join((p.get("titel") or "").split())[:120],
            subtitle=" ".join((p.get("untertitel") or "").split())[:200],
            dates=flag("datum", True), numbers=flag("nummern", False),
            media=flag("bilder", True), footer=flag("fusszeile", True),
            highlight=" ".join((p.get("markieren") or "").split())[:100],
        )


def parse_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit() and int(part) not in out:
            out.append(int(part))
    return out[:MAX_POSTS]


def load_posts(db: Session, ids: list[int]) -> list[Post]:
    """Postings in der angegebenen Reihenfolge (nur fertige, mit Text oder Beleg)."""
    if not ids:
        return []
    rows = db.scalars(select(Post).where(Post.id.in_(ids)).options(
        selectinload(Post.media), selectinload(Post.tags), selectinload(Post.account).selectinload(Account.person)))
    by_id = {p.id: p for p in rows}
    return [by_id[i] for i in ids if i in by_id]


def date_span(posts: list[Post]) -> str:
    years = sorted({(p.posted_at or p.created_at).year for p in posts if (p.posted_at or p.created_at)})
    if not years:
        return ""
    return str(years[0]) if years[0] == years[-1] else f"{years[0]}–{years[-1]}"


def default_subtitle(posts: list[Post]) -> str:
    n = len(posts)
    people = {p.account.person.name for p in posts if p.account and p.account.person}
    parts = [f"{n} {'Posting' if n == 1 else 'Postings'}"]
    if len(people) == 1:
        parts.append(f"von {next(iter(people))}")
    elif people:
        parts.append(f"von {len(people)} Personen")
    span = date_span(posts)
    if span:
        parts.append(span)
    return " · ".join(parts)


# --- Bilder und Schriften einbetten (Export) ------------------------------------------------

def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or ("image/webp" if path.suffix == ".webp" else "application/octet-stream")
    if path.suffix == ".woff2":
        mime = "font/woff2"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def file_source(settings: Settings, rel: str | None, inline: bool, url_prefix: str) -> str:
    """Bildquelle: im Export als data:-URI, in der Vorschau als URL."""
    if not rel:
        return ""
    if not inline:
        return f"{url_prefix}/{rel}"
    try:
        path = safe_path(settings.base_path, rel)
    except UnsafePathError:
        return ""
    return data_uri(path) if path.is_file() else ""


def font_faces(inline: bool, static_url: str) -> str:
    faces = []
    for family, stem in (("Inter", "inter"), ("Source Serif 4", "source-serif-4")):
        for subset, rng in (("latin", "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD"),
                            ("latin-ext", "U+0100-02AF, U+0304, U+0308, U+0329, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")):
            name = f"{stem}-{subset}-wght-normal.woff2"
            src = data_uri(STATIC / "vendor" / "fonts" / name) if inline else f"{static_url}/vendor/fonts/{name}"
            faces.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:100 900;font-display:block;"
                         f"src:url({src}) format('woff2');unicode-range:{rng};}}")
    return "\n".join(faces)


def collage_script() -> str:
    return (STATIC / "collage.js").read_text(encoding="utf-8")


# --- Export per Playwright -------------------------------------------------------------------

async def render_with_browser(app, html: str, width: int, height: int) -> bytes:
    """Den Chromium des Screenshot-Workers mitbenutzen; ohne Worker einen eigenen starten."""
    worker = getattr(app.state, "worker", None)
    if worker is not None:
        return await render_jpg(await worker._get_browser(), html, width, height)
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        try:
            return await render_jpg(browser, html, width, height)
        finally:
            await browser.close()


async def render_jpg(browser, html: str, width: int, height: int) -> bytes:
    """Seite in fester Breite rendern; Hoehe 0 = so lang wie der Inhalt."""
    context = await browser.new_context(viewport={"width": width, "height": height or 1600}, device_scale_factor=1)
    try:
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.wait_for_function("window.__collageReady === true", timeout=30000)
        return await page.screenshot(type="jpeg", quality=92, full_page=not height)
    finally:
        await context.close()


def export_name(opts: Options, when: datetime) -> str:
    base = "".join(c if c.isalnum() else "-" for c in (opts.title or "collage").lower()).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    return f"{base[:40] or 'collage'}-{when:%Y-%m-%d}.jpg"
