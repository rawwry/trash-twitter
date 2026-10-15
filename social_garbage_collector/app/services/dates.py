"""Datum einer Aussage nachtraeglich bestimmen.

Reihenfolge (das Genaueste zuerst):
  1. Plattform-API (macht der Worker beim Erfassen)        date_source "api"
  2. Beitrags-ID: X-Snowflake und Bluesky-TID enthalten
     den Zeitpunkt auf die Millisekunde - ohne Netz          date_source "id"
  3. Screenshot per Texterkennung ("10:12 · 4. März 2019")  date_source "ocr"
  4. Von Hand                                               date_source "manual"

Gespeichert wird immer naive UTC (wie ueberall in der DB).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PLATFORM_BLUESKY, PLATFORM_X, Post, utcnow
from ..timezone import LOCAL_TZ

log = logging.getLogger("sgc.dates")

DATE_API, DATE_ID, DATE_OCR, DATE_MANUAL = "api", "id", "ocr", "manual"
EARLIEST = datetime(2006, 3, 21)  # erster Tweet

# --- 2. aus der ID ------------------------------------------------------------

X_EPOCH_MS = 1288834974657
# Snowflake-IDs gibt es seit 4.11.2010; aeltere Tweet-IDs sind fortlaufend.
X_FIRST_SNOWFLAKE = 29_700_859_247
TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def _plausible(dt: datetime | None) -> datetime | None:
    if dt is None or dt < EARLIEST or dt > utcnow() + timedelta(days=1):
        return None
    return dt


def from_x_id(post_id: str) -> datetime | None:
    if not (post_id or "").isdigit() or int(post_id) < X_FIRST_SNOWFLAKE:
        return None
    ms = (int(post_id) >> 22) + X_EPOCH_MS
    return _plausible(datetime.fromtimestamp(ms / 1000, timezone.utc).replace(tzinfo=None))


def from_bluesky_tid(rkey: str) -> datetime | None:
    """TID: 13 Zeichen base32-sortierbar, die oberen 53 Bit = Mikrosekunden seit 1970."""
    rkey = rkey or ""
    if len(rkey) != 13 or any(c not in TID_ALPHABET for c in rkey) or rkey[0] not in TID_ALPHABET[:16]:
        return None
    n = 0
    for c in rkey:
        n = n * 32 + TID_ALPHABET.index(c)
    micros = n >> 10
    try:
        dt = datetime(1970, 1, 1) + timedelta(microseconds=micros)
    except OverflowError:
        return None
    return _plausible(dt)


def from_id(platform: str, post_id: str) -> datetime | None:
    if platform == PLATFORM_X:
        return from_x_id(post_id)
    if platform == PLATFORM_BLUESKY:
        return from_bluesky_tid(post_id)
    return None


# --- 3. aus dem Screenshot-Text ------------------------------------------------

_MONTHS = {
    # deutsch (auch ohne Umlaut, wie OCR es oft liefert)
    "januar": 1, "jan": 1, "jänner": 1, "februar": 2, "feb": 2, "märz": 3, "marz": 3, "maerz": 3, "mär": 3, "mrz": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
    # englisch
    "january": 1, "february": 2, "march": 3, "mar": 3, "may": 5, "june": 6, "july": 7,
    "october": 10, "oct": 10, "december": 12, "dec": 12,
}
_MONTH_WORD = r"([A-Za-zÄÖÜäöü]{3,9})\.?"
_PATTERNS = [
    # 4. März 2019
    ("dmy_word", re.compile(rf"\b(\d{{1,2}})\.?\s*{_MONTH_WORD}\s+(\d{{4}})\b")),
    # 22 Jan. 25 (X auf Deutsch kuerzt das Jahr)
    ("dmy_word2", re.compile(rf"\b(\d{{1,2}})\.?\s*{_MONTH_WORD}\s+(\d{{2}})(?!\d|[:.]\d)")),
    # Mar 4, 2019 / March 4 2019
    ("mdy_word", re.compile(rf"\b{_MONTH_WORD}\s+(\d{{1,2}}),?\s+(\d{{4}})\b")),
    # 04.03.19 / 4.3.2019 (X-App auf Deutsch)
    ("dmy_num", re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b")),
    # 2019-03-04
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
]
_TIME = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(AM|PM|am|pm|vorm\.?|nachm\.?)?")
_TIME_WINDOW = 28  # so weit darf die Uhrzeit vom Datum entfernt stehen (gleiche Zeile)


def _build(kind: str, g: tuple[str, ...]) -> tuple[int, int, int] | None:
    try:
        if kind in ("dmy_word", "dmy_word2"):
            day, month, year = int(g[0]), _MONTHS.get(g[1].lower().rstrip(".")), int(g[2])
            year += 2000 if year < 100 else 0
        elif kind == "mdy_word":
            month, day, year = _MONTHS.get(g[0].lower().rstrip(".")), int(g[1]), int(g[2])
        elif kind == "dmy_num":
            day, month, year = int(g[0]), int(g[1]), int(g[2])
            year += 2000 if year < 100 else 0
        else:
            year, month, day = int(g[0]), int(g[1]), int(g[2])
    except (TypeError, ValueError):
        return None
    if not month or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    return year, month, day


def _time_near(text: str, start: int, end: int) -> tuple[int, int] | None:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    lo, hi = max(line_start, start - _TIME_WINDOW), min(line_end, end + _TIME_WINDOW)
    for m in _TIME.finditer(text, lo, hi):
        if m.start() >= start and m.end() <= end:
            continue  # Teil des Datums selbst (z. B. "04.03")
        h, mi, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
        if ampm in ("pm", "nachm", "nachm.") and h < 12:
            h += 12
        if ampm in ("am", "vorm", "vorm.") and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= mi < 60:
            return h, mi
    return None


def from_text(text: str) -> tuple[datetime, bool] | None:
    """Sucht das Veroeffentlichungsdatum in OCR-Text. Rueckgabe: (UTC, mit Uhrzeit?).

    Ein Beitrag kann selbst Daten erwaehnen ("am 4. März …"). Der Zeitstempel
    des Beitrags steht aber fast immer zusammen mit einer Uhrzeit und ganz
    unten - deshalb gewinnt das letzte Datum mit Uhrzeit, sonst das letzte."""
    best: tuple[int, datetime, bool] | None = None
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text or ""):
            ymd = _build(kind, m.groups())
            if not ymd:
                continue
            hm = _time_near(text, m.start(), m.end())
            try:
                local = datetime(*ymd, *(hm or (12, 0)))
            except ValueError:
                continue
            utc = local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
            if not _plausible(utc):
                continue
            score = (1 if hm else 0, m.start())
            if best is None or score > best[0]:
                best = (score, utc, bool(hm))
    return (best[1], best[2]) if best else None


# --- Anwenden --------------------------------------------------------------------

def set_date(post: Post, when: datetime | None, source: str | None, has_time: bool = True) -> None:
    post.posted_at = when
    post.date_source = source if when else None
    post.date_has_time = bool(has_time) if when else True


def fill_from_id(post: Post) -> bool:
    if post.posted_at is not None:
        return False
    when = from_id(post.platform, post.post_id)
    if when:
        set_date(post, when, DATE_ID)
        return True
    return False


def backfill_from_ids(db: Session) -> int:
    """Beim Start: Aussagen ohne Datum, deren ID den Zeitpunkt verraet."""
    count = sum(fill_from_id(p) for p in db.scalars(select(Post).where(Post.posted_at.is_(None))))
    if count:
        db.commit()
        log.info("Datum fuer %d Aussagen aus der Beitrags-ID bestimmt.", count)
    return count


def fill_from_ocr_text(post: Post, text: str) -> bool:
    if post.posted_at is not None:
        return False
    found = from_text(text)
    if found:
        set_date(post, found[0], DATE_OCR, has_time=found[1])
        return True
    return False


def parse_manual(day: str, clock: str) -> tuple[datetime | None, bool]:
    """Formular: Datum (YYYY-MM-DD) und optional Uhrzeit (HH:MM), Ortszeit."""
    day, clock = (day or "").strip(), (clock or "").strip()
    if not day:
        return None, True
    d = datetime.strptime(day, "%Y-%m-%d").date()
    t = datetime.strptime(clock, "%H:%M").time() if clock else time(12, 0)
    utc = datetime.combine(d, t).replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    return utc, bool(clock)
