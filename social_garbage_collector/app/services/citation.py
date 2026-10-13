"""Quellenangaben: jede Aussage ist eindeutig und dauerhaft zitierbar.

Archiv-Nummer = ID in der Datenbank, sechsstellig. Sie aendert sich nie,
auch nicht, wenn der Beitrag auf der Plattform geloescht wird.
"""

from __future__ import annotations

from datetime import timezone

from .. import APP_NAME
from ..models import Post
from ..timezone import LOCAL_TZ
from .platforms import LABELS

EXCERPT_CHARS = 160


def archive_no(post: Post) -> str:
    return f"{post.id:06d}"


def _local(dt, fmt: str) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime(fmt) if dt else ""


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:–-") + " …"


def citation(post: Post, full_text: bool = False) -> str:
    """Zitierfertige Quellenangabe, z. B.

    Jack Dorsey (@jack): „just setting up my twttr“. X, 21.03.2006, 22:50.
    https://x.com/jack/status/20 – archiviert am 13.10.2026 in TrashTwitter, Archiv-Nr. 000020.
    """
    who = post.author_display_name or ""
    if post.author_handle:
        who = f"{who} (@{post.author_handle})" if who else f"@{post.author_handle}"
    who = who or "Unbekannt"
    text = (post.text or "").strip()
    quote = (" ".join(text.split()) if full_text else excerpt(text)) if text else ""
    # Endet das Zitat schon mit einem Satzzeichen, kein zweiter Punkt dahinter.
    end = "" if quote and quote[-1] in ".!?…" else "."
    parts = [f"{who}: „{quote}“{end}" if quote else f"{who}."]
    platform = LABELS.get(post.platform, post.platform)
    when = ""
    if post.posted_at:
        when = _local(post.posted_at, "%d.%m.%Y" if post.date_only else "%d.%m.%Y, %H:%M")
    parts.append(f"{platform}, {when}." if when else f"{platform}, Datum unbekannt.")
    source = post.url or "Originallink unbekannt (Beleg: eigener Screenshot)"
    parts.append(f"{source} – archiviert am {_local(post.created_at, '%d.%m.%Y')} in {APP_NAME}, "
                 f"Archiv-Nr. {archive_no(post)}.")
    return " ".join(parts)
