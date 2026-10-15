"""Screenshot verstehen: aus einem hochgeladenen Bild eines Postings die
Angaben lesen, die ein Link automatisch liefern wuerde.

Ein Screenshot von X oder Bluesky ist immer gleich aufgebaut:

    [App-Leiste, Uhrzeit, "Post"]           -> weg
    (Profilbild) Anzeigename                 -> Verfasser
                 @handle                     -> Account, Plattform
    Wortlaut ...                             -> Text
    22:10 · 22 Jan. 25 · 78 Mal angezeigt    -> Datum, Plattform
    Reposts, Gefaellt mir, Antworten ...     -> weg

parse() arbeitet nur auf den erkannten Zeilen (ohne Tesseract testbar),
crop_avatar() schneidet das runde Profilbild links neben dem Namen aus.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageChops, ImageStat

from ..models import PLATFORM_BLUESKY, PLATFORM_X
from . import dates
from .ocr import Layout, Line, reflow

# @handle: X erlaubt Buchstaben, Ziffern, _ (max. 15); Bluesky-Handles sind Domains.
_BSKY_HANDLE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)+)")
_X_HANDLE = re.compile(r"@([A-Za-z0-9_]{2,15})(?![A-Za-z0-9_.])")

# Fusszeilen und Bedienelemente, die nicht zum Wortlaut gehoeren
_CHROME = re.compile(
    r"(mal angezeigt|aufrufe|ansichten|\bviews?\b|\breposts?\b|\bzitate?\b|\bquotes?\b|\blikes?\b|gef[aä]llt mir|"
    r"lesezeichen|bookmarks?|(beitrag|post|tweet) [uü]bersetzen|translate (post|tweet)|show translation|"
    r"[uü]bersetzung anzeigen|everybody can reply|jede[rs]? kann antworten|antwort posten|post your reply|"
    r"relevanteste|most relevant|neueste antworten|twitter for|twitter web app|via bluesky|"
    r"auf ?x ?ansehen|view on x|link zum post kopieren|copy link|antworten lesen|read \d+ repl|"
    r"reply|antworten|weitere antworten|show replies)", re.I)
_MORE = re.compile(r"\s*(…|\.\.\.)?\s*(mehr anzeigen|show more|weiterlesen|read more)\s*$", re.I)
_REPLY_TO = re.compile(r"^(antwort an|replying to|als antwort auf|in reply to)\b", re.I)
_RELATIVE = re.compile(r"[·•]\s*\d{1,2}\s*(s|sek|min|m|h|std\.?|stunden?|t|d|tg\.?)\b.*$", re.I)
_BUTTONS = re.compile(r"\s+(folgen|follow|following|gefolgt|abonnieren|abonniert|subscribe)\s*$", re.I)
# Tesseract liest Emojis als einzelne Zeichen wie ® © ™ - die gibt es in Postings praktisch nie.
_EMOJI_NOISE = re.compile(r"\s?[®©™¥§¤]+(?=\s|$)")


@dataclass
class ShotInfo:
    platform: str | None = None       # x | bluesky | None (unklar)
    handle: str = ""
    display_name: str = ""
    text: str = ""
    posted_at: datetime | None = None  # UTC
    has_time: bool = False
    # Kopfzeilen (Name + Handle) im Originalbild - fuer das Profilbild
    header: list[Line] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)


def _find_handle(text: str) -> tuple[str, str, re.Match] | None:
    """(handle, plattform-hinweis, treffer). Bluesky-Handles enthalten immer einen Punkt."""
    m = _BSKY_HANDLE.search(text)
    if m and not m.group(1).lower().endswith((".", "-")):
        return m.group(1).lower(), PLATFORM_BLUESKY, m
    m = _X_HANDLE.search(text)
    if m:
        return m.group(1), PLATFORM_X, m
    return None


def _wordlike(token: str) -> bool:
    return sum(c.isalpha() for c in token) >= 2 or token[:1].isupper()


def _clean_name(raw: str) -> str:
    name = _RELATIVE.sub("", raw)
    name = _BUTTONS.sub("", name).strip(" ·•|:-")
    # Haken/Abzeichen und Menue-Punkte hinter dem Namen liest Tesseract als
    # Kleinkram ("©", "@", "#", "xX", "|x") - kurze Reste am Ende fallen weg.
    tokens = name.split()
    while tokens and (len(tokens[-1]) <= 2 or not any(c.isalnum() for c in tokens[-1])):
        tokens.pop()
    while tokens and not any(c.isalnum() for c in tokens[0]):
        tokens.pop(0)
    if tokens:
        tokens[-1] = tokens[-1].rstrip("®©@#&*|%»«“”\"'")
    return " ".join(tokens)[:255]


def _handle_left(ln: Line, handle: str) -> int:
    for word, left, _right, _conf in ln.words:
        if handle.lower() in word.lower():
            return left
    return ln.left


def _from(ln: Line, left: int) -> Line:
    """Zeile ab einer x-Position (fuer den Profilbild-Ausschnitt)."""
    return Line(ln.text, max(ln.left, left), ln.top, ln.right, ln.bottom, ln.para, ln.words)


def _is_chrome(text: str) -> bool:
    """Zeile ohne Inhalt: Aufrufe, Knoepfe, nur Zahlen/Symbole."""
    t = text.strip()
    if not t:
        return True
    letters = sum(c.isalpha() for c in t)
    if letters <= 1:
        return True
    # Zahlenreihen der Aktionsleiste ("O24k (64 D 408"): kein einziges richtiges Wort
    if not any(sum(c.isalpha() for c in tok) >= 3 for tok in t.split()):
        return True
    return bool(_CHROME.search(t)) and len(t) < 90


def _score(info: ShotInfo, all_text: str, footer: str, handle_hint: str | None) -> None:
    s = {PLATFORM_X: 0, PLATFORM_BLUESKY: 0}
    if handle_hint == PLATFORM_BLUESKY:
        s[PLATFORM_BLUESKY] += 6
    elif handle_hint == PLATFORM_X:
        s[PLATFORM_X] += 3
    low = all_text.lower()
    if re.search(r"mal angezeigt|\bviews\b|aufrufe|ansichten", low):
        s[PLATFORM_X] += 3
    if re.search(r"(beitrag|post|tweet) [uü]bersetzen|translate (post|tweet)|x\.com|twitter", low):
        s[PLATFORM_X] += 2
    if re.search(r"bsky|bluesky|everybody can reply|jede[rs]? kann antworten", low):
        s[PLATFORM_BLUESKY] += 3
    # X: "22:10 · 22 Jan. 25" (Uhrzeit zuerst). Bluesky: "22. Jan. 2025 um 22:10" / "at 10:10 PM".
    if re.match(r"\s*\d{1,2}[:.]\d{2}\s*(am|pm)?\s*[·•:.\-]", footer, re.I):
        s[PLATFORM_X] += 2
    if re.search(r"\d{4}\s+(um|at)\s+\d{1,2}[:.]\d{2}", footer, re.I):
        s[PLATFORM_BLUESKY] += 2
    info.scores = s
    if s[PLATFORM_X] != s[PLATFORM_BLUESKY] and max(s.values()) >= 2:
        info.platform = max(s, key=s.get)


def _join(lines: list[Line]) -> str:
    """Zeilen zu Text: grosse Abstaende oder Tesseract-Absatzwechsel = Absatz."""
    if not lines:
        return ""
    heights = sorted(ln.height for ln in lines)
    typical = heights[len(heights) // 2]
    out = [lines[0].text]
    for prev, ln in zip(lines, lines[1:]):
        gap = ln.top - prev.bottom
        new_para = ln.para != prev.para or gap > typical * 0.9
        out.append(("\n\n" if new_para else "\n") + ln.text)
    return "".join(out)


def clean_body(text: str) -> str:
    text = _EMOJI_NOISE.sub("", text)
    return _MORE.sub("", reflow(text))


def parse(layout: Layout) -> ShotInfo:
    info = ShotInfo()
    lines = [ln for ln in layout.lines if ln.text.strip()]
    if not lines:
        return info
    height = layout.height or max(ln.bottom for ln in lines)

    # 1) Kopf: erstes @handle im oberen Teil des Bildes
    start, handle_hint = 0, None
    for i, ln in enumerate(lines[:8]):
        if ln.top > height * 0.55 and i > 0:
            break
        found = _find_handle(ln.text)
        if not found:
            continue
        info.handle, handle_hint, m = found
        start = i + 1
        hx = _handle_left(ln, info.handle)
        tol = ln.height * 0.8
        prev = lines[i - 1] if i > 0 else None
        # Zwei Zeilen (Name ueber @handle, buendig): Name = Woerter der Zeile davor,
        # die in derselben Spalte stehen. Was links davon steht, ist das Profilbild.
        prev_words = [w for w in (prev.words if prev else []) if w[1] >= hx - tol]
        if prev is not None and prev_words and ln.top - prev.bottom < ln.height * 1.5:
            name = _clean_name(" ".join(w[0] for w in prev_words))
            if name and not _is_chrome(name):
                info.display_name = name
                info.header = [_from(prev, hx), _from(ln, hx)]
        if not info.display_name:
            # Eine Zeile: "Name @handle · 3h" - unsichere Woerter vorn sind das Profilbild
            before = [w for w in ln.words if w[2] <= hx]
            while before and (before[0][3] < 60 or not _wordlike(before[0][0])):
                before = before[1:]
            info.display_name = _clean_name(" ".join(w[0] for w in before))
            left = before[0][1] if before else hx
            info.header = [_from(ln, left)]
        # "Name @handle · 22. Jan." (Timeline-Ansicht): Rest der Zeile ist Datum
        rest = ln.text[m.end():]
        if rest.strip(" ·•"):
            found_date = dates.from_text(rest)
            if found_date:
                info.posted_at, info.has_time = found_date
        break

    body = lines[start:]
    while body and _REPLY_TO.match(body[0].text):
        body = body[1:]

    # 2) Fuss: die letzte Zeile mit Datum; alles ab dort ist Fusszeile
    footer = ""
    for j in range(len(body) - 1, -1, -1):
        found_date = dates.from_text(body[j].text)
        if found_date and (j > 0 or len(body) == 1):
            if not info.posted_at or found_date[1]:
                info.posted_at, info.has_time = found_date
            footer = " ".join(ln.text for ln in body[j:])
            body = body[:j]
            break
    # Fusszeilen ohne Datum (Reposts, Likes, Knoepfe) von unten abschneiden
    while body and _is_chrome(body[-1].text):
        footer = body[-1].text + " " + footer
        body = body[:-1]

    info.text = clean_body(_join(body))
    _score(info, " ".join(ln.text for ln in lines), footer, handle_hint)
    if info.platform == PLATFORM_X and handle_hint == PLATFORM_BLUESKY:
        info.handle = ""  # Domain-Handle passt nicht zu X - lieber keins als ein falsches
    return info


# --------------------------------------------------------------------------
# Profilbild
# --------------------------------------------------------------------------

def crop_avatar(img: Image.Image, header: list[Line]) -> bytes | None:
    """Schneidet das Profilbild links neben Name/Handle aus. None, wenn dort
    nichts Rundes/Quadratisches zu finden ist (z. B. abgeschnittener Screenshot)."""
    if not header:
        return None
    left = min(ln.left for ln in header)
    top = min(ln.top for ln in header)
    bottom = max(ln.bottom for ln in header)
    span = max(bottom - top, 20)
    x1 = left - max(4, span // 8)
    y0, y1 = max(0, top - span), min(img.height, bottom + span)
    if x1 < 24 or y1 - y0 < 24:
        return None
    region = img.crop((0, y0, x1, y1)).convert("RGB")
    # Hintergrund = Farbe am Bildrand neben dem Kopf
    bg = Image.new("RGB", region.size, img.getpixel((min(6, img.width - 1), min(top, img.height - 1))))
    diff = ImageChops.difference(region, bg).convert("L").point(lambda v: 255 if v > 38 else 0)
    rw, rh = diff.size
    px = diff.load()
    # Spalten mit viel Inhalt -> zusammenhaengende Bereiche; Rahmenlinien sind zu schmal
    cols = [sum(1 for y in range(rh) if px[x, y]) for x in range(rw)]
    run = _widest_run([c >= rh * 0.15 for c in cols])
    if run is None:
        return None
    xa, xb = run
    rows = [sum(1 for x in range(xa, xb) if px[x, y]) for y in range(rh)]
    run = _widest_run([r >= (xb - xa) * 0.15 for r in rows])
    if run is None:
        return None
    ya, yb = run
    box = (xa, ya, xb, yb)
    w, h = xb - xa, yb - ya
    if w < 24 or h < 24 or not (0.75 <= w / h <= 1.33):
        return None
    if ImageStat.Stat(diff.crop(box)).mean[0] < 255 * 0.45:  # zu duenn besetzt: Icon/Text, kein Bild
        return None
    side = max(w, h)
    cx, cy = box[0] + w // 2, y0 + box[1] + h // 2
    crop = img.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side))
    out = io.BytesIO()
    crop.convert("RGB").save(out, "PNG")
    return out.getvalue()


def _widest_run(flags: list[bool]) -> tuple[int, int] | None:
    best, start = None, None
    for i, on in enumerate(flags + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best if best and best[1] - best[0] >= 24 else None
