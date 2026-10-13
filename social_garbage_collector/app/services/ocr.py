"""Texterkennung mit Tesseract (Deutsch + Englisch).

Vorverarbeitung, weil Tesseract auf Screenshots sonst schwaechelt:
  - Graustufen
  - dunkle Bilder (Dark Mode) invertieren: Tesseract mag dunkle Schrift
  - hochskalieren: Tesseract arbeitet am besten bei ~30 px Zeichenhoehe
  - Autokontrast
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

log = logging.getLogger("sgc.ocr")

LANGS = "deu+eng"
# psm 4: eine Spalte Text mit unterschiedlichen Groessen - passt zu Beitraegen.
TESS_CONFIG = "--oem 1 --psm 4"


class OcrUnavailable(RuntimeError):
    pass


def preprocess(img: Image.Image, target_width: int = 1800) -> Image.Image:
    gray = ImageOps.grayscale(img)
    if ImageStat.Stat(gray).mean[0] < 110:
        gray = ImageOps.invert(gray)
    if gray.width < target_width:
        factor = target_width / gray.width
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(gray, cutoff=1)


# Zeilen, die fuer sich stehen sollen: Aufzaehlungen ("- ", "• ", "1. ", "2) ").
_LIST_ITEM = re.compile(r"^\s*(?:[-–•·*]\s|\d{1,3}[.)]\s)")


def reflow(text: str) -> str:
    """Fuegt die Zeilen eines Absatzes wieder zusammen.

    ⚠️ 0.6.2: Tesseract liefert jeden optischen Zeilenumbruch des Screenshots
    mit - im Archiv standen Saetze dann zerhackt untereinander. Absaetze
    (Leerzeile) und Aufzaehlungen bleiben, getrennte Woerter ("Begrün-\ndung")
    werden wieder eins. Mehrfach anwenden aendert nichts mehr.
    """
    paragraphs = re.split(r"\n\s*\n", (text or "").strip())
    out = []
    for para in paragraphs:
        merged = ""
        for line in (ln.strip() for ln in para.splitlines()):
            if not line:
                continue
            if not merged:
                merged = line
            elif _LIST_ITEM.match(line):
                merged += "\n" + line
            elif re.search(r"\w-$", merged) and line[:1].islower():
                merged = merged[:-1] + line  # Silbentrennung am Zeilenende
            else:
                merged += " " + line
        if merged:
            out.append(re.sub(r"[ \t]{2,}", " ", merged))
    return "\n\n".join(out)


def clean_text(text: str) -> str:
    return reflow(text.replace("\x0c", ""))


def reflow_existing(db) -> int:
    """Einmalig fuer Texte aus der Zeit vor 0.6.2: OCR-Texte neu umbrechen.
    Von Hand korrigierte und von der Plattform geholte Texte bleiben unberuehrt."""
    from sqlalchemy import select

    from ..models import TEXT_OCR, Post

    changed = 0
    for post in db.scalars(select(Post).where(Post.text_source == TEXT_OCR, Post.text.like("%\n%"))):
        new = reflow(post.text)
        if new != post.text:
            post.text = new
            changed += 1
    if changed:
        db.commit()
        log.info("%d OCR-Texte neu umgebrochen.", changed)
    return changed


def ocr_image(source: Path | bytes, raw: bool = False) -> str:
    """raw=True: Zeilen nicht zusammenfuegen (fuer die Datumssuche - der
    Zeitstempel steht in einer eigenen Zeile)."""
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - im Image vorhanden
        raise OcrUnavailable("pytesseract fehlt") from exc
    img = Image.open(io.BytesIO(source)) if isinstance(source, bytes) else Image.open(source)
    try:
        text = pytesseract.image_to_string(preprocess(img), lang=LANGS, config=TESS_CONFIG)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable("Tesseract ist nicht installiert") from exc
    return text.replace("\x0c", "").strip() if raw else clean_text(text)
