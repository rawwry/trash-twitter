"""Screenshots: Speicherformat, Zusammenkleben (Threads), Randbereinigung, Masse.

Speicherformat WebP (Qualitaet 82): gemessen an echten Screenshots rund 80 %
kleiner als PNG, Schrift ohne sichtbaren Unterschied, schnell genug fuer den
Pi. AVIF waere nochmal ~40 % kleiner, kodiert aber 3x langsamer und weicht
kleine Schrift eher auf - deshalb nicht.

Metadaten: Groesse und Randfarbe.

Damit das Raster im Archiv ruhig wirkt, sind alle Kacheln gleich gross.
Breite Screenshots (X) werden darin eingepasst statt beschnitten; die freie
Flaeche bekommt die Randfarbe des Screenshots, so sieht man keine Kante.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from statistics import median

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..models import Post

log = logging.getLogger("sgc.shots")


def measure(path: Path) -> tuple[int, int, str]:
    """(Breite, Hoehe, Randfarbe als #rrggbb) - Randfarbe = Median der obersten Pixelreihe."""
    with Image.open(path) as img:
        w, h = img.size
        rgb = img.convert("RGB")
        y = min(3, h - 1)
        row = [rgb.getpixel((x, y)) for x in range(0, w, max(1, w // 64))]
    r, g, b = (int(median(c[i] for c in row)) for i in range(3))
    return w, h, f"#{r:02x}{g:02x}{b:02x}"


# --- Randstreifen entfernen ----------------------------------------------------
MAX_TRIM = 4          # hoechstens so viele Pixel pro Seite (bei 2x = 2 CSS-Pixel)
_EDGE_DIFF = 60       # so stark muss sich ein Streifen vom Hintergrund abheben
_UNIFORM = 18         # so wenig darf die Farbe innerhalb des Streifens schwanken


def _dist(a, b) -> int:
    return max(abs(a[i] - b[i]) for i in range(3))


def _line(img, side: str, i: int) -> list[tuple[int, int, int]]:
    w, h = img.size
    if side in ("top", "bottom"):
        y = i if side == "top" else h - 1 - i
        return [img.getpixel((x, y)) for x in range(0, w, max(1, w // 80))]
    x = i if side == "left" else w - 1 - i
    return [img.getpixel((x, y)) for y in range(0, h, max(1, h // 80))]


def _median(px):
    return tuple(int(median(c[k] for c in px)) for k in range(3))


def trim_edges(path: Path) -> bool:
    """Schneidet einfarbige Randstreifen ab, die nicht zum Beitrag gehoeren
    (z. B. die weisse Linie unter X-Embeds). True, wenn etwas geaendert wurde.

    Ein Streifen wird nur entfernt, wenn er (a) einfarbig ist, (b) sich deutlich
    von der Hintergrundfarbe des Beitrags abhebt und (c) weiter innen wieder
    Beitragshintergrund kommt. So bleiben echte Inhalte am Rand unangetastet.
    """
    with Image.open(path) as raw:
        img = raw.convert("RGB")
    w, h = img.size
    if w < 40 or h < 40:
        return False
    cut = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    for side in cut:
        inner = _median(_line(img, side, MAX_TRIM + 2))
        for i in range(MAX_TRIM):
            line = _line(img, side, i)
            color = _median(line)
            uniform = max(_dist(p, color) for p in line) <= _UNIFORM
            if uniform and _dist(color, inner) >= _EDGE_DIFF:
                cut[side] = i + 1
            else:
                break
    if not any(cut.values()):
        return False
    box = (cut["left"], cut["top"], w - cut["right"], h - cut["bottom"])
    if path.suffix.lower() == ".webp":
        img.crop(box).save(path, "WEBP", quality=WEBP_QUALITY, method=4)
    else:
        img.crop(box).save(path, "PNG", optimize=True)
    log.info("Randstreifen entfernt (%s): %s", ", ".join(f"{k} {v}px" for k, v in cut.items() if v), path.name)
    return True


def cleanup_existing(settings: Settings) -> int:
    """Einmalig fuer Screenshots vor 0.3.1 (Marker-Datei verhindert Wiederholung)."""
    marker = settings.screenshot_dir / ".rand-bereinigt-v1"
    if marker.exists():
        return 0
    fixed = 0
    for path in [*settings.screenshot_dir.rglob("*.png"), *settings.screenshot_dir.rglob("*.webp")]:
        try:
            fixed += trim_edges(path)
        except OSError as exc:
            log.warning("Screenshot %s nicht bearbeitbar: %s", path.name, exc)
    marker.write_text("ok", encoding="utf-8")
    if fixed:
        log.info("Randstreifen in %d vorhandenen Screenshots entfernt.", fixed)
    return fixed


# --- Speichern als WebP, Threads zusammenkleben ---------------------------------
WEBP_QUALITY = 82
THREAD_GAP = 20  # Abstand zwischen Thread-Teilen (Pixel, bei 2x = 10 CSS-Pixel)


def edge_color(img: Image.Image) -> tuple[int, int, int]:
    rgb = img.convert("RGB")
    w, h = rgb.size
    y = min(3, h - 1)
    return _median([rgb.getpixel((x, y)) for x in range(0, w, max(1, w // 64))])


def stitch(images: list[Image.Image], gap: int = THREAD_GAP) -> Image.Image:
    """Klebt Thread-Teile untereinander. Die Luecke bekommt die Hintergrundfarbe
    des ersten Teils, schmalere Teile werden mittig gesetzt."""
    if len(images) == 1:
        return images[0].convert("RGB")
    bg = edge_color(images[0])
    width = max(i.width for i in images)
    height = sum(i.height for i in images) + gap * (len(images) - 1)
    canvas = Image.new("RGB", (width, height), bg)
    y = 0
    for img in images:
        canvas.paste(img.convert("RGB"), ((width - img.width) // 2, y))
        y += img.height + gap
    return canvas


def finalize(pngs: list[Path], target: Path) -> None:
    """Rohaufnahmen (PNG von Playwright) -> Raender bereinigen -> ggf. zusammenkleben
    -> als WebP speichern. Schreibt atomar (erst .tmp, dann umbenennen)."""
    images = []
    for path in pngs:
        trim_edges(path)
        with Image.open(path) as img:
            images.append(img.convert("RGB"))
    out = stitch(images)
    tmp = target.with_name(target.name + ".tmp")
    out.save(tmp, "WEBP", quality=WEBP_QUALITY, method=4)
    os.replace(tmp, target)


def as_jpeg(path: Path) -> bytes:
    """Fuer Teilen/Herunterladen: JPEG versteht jede App (WebP nicht jeder Messenger)."""
    with Image.open(path) as img:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=90, optimize=True, progressive=True)
        return buf.getvalue()


def convert_existing(db: Session, settings: Settings) -> int:
    """Einmalig (0.4.0): vorhandene PNG-Screenshots in WebP umwandeln."""
    marker = settings.screenshot_dir / ".webp-v1"
    if marker.exists():
        return 0
    done = 0
    posts = list(db.scalars(select(Post).where(Post.screenshot_path.like("%.png"))))
    for post in posts:
        try:
            src = safe_path(settings.base_path, post.screenshot_path)
        except UnsafePathError:
            continue
        if not src.is_file():
            continue
        dst = src.with_suffix(".webp")
        try:
            with Image.open(src) as img:
                img.convert("RGB").save(dst, "WEBP", quality=WEBP_QUALITY, method=4)
        except OSError as exc:
            log.warning("Umwandlung fehlgeschlagen fuer %s: %s", src.name, exc)
            continue
        post.screenshot_path = post.screenshot_path[:-4] + ".webp"
        src.unlink(missing_ok=True)
        done += 1
    db.commit()
    marker.write_text("ok", encoding="utf-8")
    if done:
        log.info("%d Screenshots von PNG nach WebP umgewandelt.", done)
    return done


def apply(post: Post, path: Path) -> None:
    """Nach jeder Aufnahme: Format und Randfarbe messen."""
    try:
        post.shot_w, post.shot_h, post.shot_bg = measure(path)
    except (OSError, ValueError) as exc:
        log.warning("Screenshot %s nicht lesbar: %s", path, exc)


def backfill(db: Session, settings: Settings, limit: int = 2000) -> int:
    """Einmalig fuer Screenshots aus Versionen vor 0.3.0 nachholen
    (und nach der Randbereinigung von 0.3.1 neu messen)."""
    if cleanup_existing(settings):
        db.execute(Post.__table__.update().values(shot_w=None))
        db.commit()
    posts = list(db.scalars(
        select(Post).where(Post.screenshot_path.is_not(None), Post.shot_w.is_(None)).limit(limit)
    ))
    done = 0
    for post in posts:
        try:
            path = safe_path(settings.base_path, post.screenshot_path)
        except UnsafePathError:
            continue
        if path.is_file():
            apply(post, path)
            done += 1
    if done:
        db.commit()
        log.info("Screenshot-Masse fuer %d Beitraege nachgetragen.", done)
    return done
