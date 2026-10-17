"""Jinja2-Templates mit den Helfern, die jede Seite braucht.

url('/pfad') beruecksichtigt den Ingress-Praefix von Home Assistant
(X-Ingress-Path), sonst laufen Links im HA-Panel ins Leere.

Rueckmeldungen ("Gespeichert", "Liste geloescht") laufen als Toast:
  - nach einer Weiterleitung ueber das Cookie sgc_toast (flash())
  - bei htmx-Antworten ueber den Header HX-Trigger (toast_header())
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from . import APP_NAME, VERSION
from .changelog import CHANGES
from .models import TEXT_API, TEXT_MANUAL, TEXT_OCR, utcnow
from .prefs import get_prefs
from .timezone import LOCAL_TZ
from .services.citation import archive_no, citation
from .services.platforms import LABELS

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
env = templates.env


TOAST_COOKIE = "sgc_toast"


def root_path(request: Request) -> str:
    return request.scope.get("root_path") or ""


@pass_context
def _url(ctx, path: str) -> str:
    return root_path(ctx["request"]) + path


@pass_context
def _shot(ctx, post) -> str:
    """Screenshot-URL mit Version: nach "Neu aufnehmen" bleibt der Dateiname
    gleich - ohne ?v= zeigte der Browser einen Tag lang das alte Bild."""
    stamp = int(post.updated_at.timestamp()) if post.updated_at else 0
    return f"{root_path(ctx['request'])}/media/{post.screenshot_path}?v={stamp}"


@pass_context
def _file_url(ctx, rel: str | None) -> str:
    """Profilbilder (Mitglieder: avatars/..., Verfasser: authors/...)."""
    return f"{root_path(ctx['request'])}/{rel}" if rel else ""


def _post_avatar(post) -> str | None:
    """Profilbild zur Aussage: Stand der Archivierung, sonst das aktuelle."""
    if post.author_avatar_path:
        return post.author_avatar_path
    return post.account.avatar_path if post.account else None


@pass_context
def _tag_choices(ctx, limit: int = 200) -> list[tuple[str, int]]:
    """Alle Tags mit Anzahl, die meistgenutzten zuerst (fuer die Schnellauswahl)."""
    db = getattr(ctx["request"].state, "db", None)
    if db is None:
        return []
    from .services.posts import tag_counts

    rows = sorted(((t.name, n) for t, n in tag_counts(db) if n), key=lambda r: (-r[1], r[0]))
    return rows[:limit]


@pass_context
def _unread_count(ctx) -> int:
    """Ungelesene Benachrichtigungen (Glocke oben)."""
    request = ctx["request"]
    db, user = getattr(request.state, "db", None), getattr(request.state, "user", None)
    if db is None or user is None:
        return 0
    from sqlalchemy import func, select

    from .models import Notification

    return db.scalar(select(func.count()).select_from(Notification)
                     .where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0


@pass_context
def _my_hearts(ctx) -> set[int]:
    """IDs der Postings, die das angemeldete Mitglied mit Herz markiert hat (einmal je Anfrage)."""
    request = ctx["request"]
    cached = getattr(request.state, "my_hearts", None)
    if cached is not None:
        return cached
    db, user = getattr(request.state, "db", None), getattr(request.state, "user", None)
    if db is None or user is None:
        return set()
    from sqlalchemy import select

    from .models import PostHeart

    request.state.my_hearts = set(db.scalars(select(PostHeart.post_id).where(PostHeart.user_id == user.id)))
    return request.state.my_hearts


@pass_context
def _tag_tree(ctx):
    """Oberbegriffe mit Unter-Tags und lose Tags (Archiv-Tagleiste, Tags verwalten)."""
    db = getattr(ctx["request"].state, "db", None)
    if db is None:
        return [], []
    from .services.tags import tree

    return tree(db)


@pass_context
def _all_lists(ctx) -> list:
    """Alle Listen (fuer Auswahlfelder, die auf jeder Seite stehen, z. B. im Massenimport)."""
    db = getattr(ctx["request"].state, "db", None)
    if db is None:
        return []
    from sqlalchemy import select

    from .models import PostList

    return list(db.scalars(select(PostList).order_by(PostList.title)))


@pass_context
def _static(ctx, path: str) -> str:
    return f"{root_path(ctx['request'])}/static/{path}?v={VERSION}"


def _localtime(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return "–"
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime(fmt)


def _ago(value: datetime | None) -> str:
    """Relative Zeit auf Deutsch: 'vor 5 Min.', 'gestern', '12.03.2025'."""
    if not value:
        return ""
    secs = (utcnow() - value).total_seconds()
    if secs < 60:
        return "gerade eben"
    if secs < 3600:
        return f"vor {int(secs // 60)} Min."
    local = value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    today = datetime.now(LOCAL_TZ).date()
    days = (today - local.date()).days
    if days == 0:
        return f"vor {int(secs // 3600)} Std."
    if days == 1:
        return "gestern"
    if days < 7:
        return f"vor {days} Tagen"
    return local.strftime("%d.%m.%Y")


_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
           "September", "Oktober", "November", "Dezember")
_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def _localday(value: datetime | None) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m-%d") if value else ""


def _monthkey(value: datetime | None) -> str:
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).strftime("%Y-%m") if value else ""


def _monthname(value: datetime | None) -> str:
    """Ueberschrift der Zeitachse: 'März 2021'."""
    if not value:
        return ""
    d = value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _said(post) -> str:
    """Datum der Aussage, bei selbst eingetragenem Datum ohne Uhrzeit."""
    if not post.posted_at:
        return "Datum unbekannt"
    return _localtime(post.posted_at, "%d.%m.%Y" if post.date_only else "%d.%m.%Y, %H:%M")


def _dayname(value: datetime | None) -> str:
    """Tagestrenner der Timeline: 'Heute', 'Gestern', 'Montag, 6. Oktober', '6. Oktober 2025'."""
    if not value:
        return ""
    d = value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).date()
    today = datetime.now(LOCAL_TZ).date()
    diff = (today - d).days
    if diff == 0:
        return "Heute"
    if diff == 1:
        return "Gestern"
    if 1 < diff < 7:
        return f"{_WEEKDAYS[d.weekday()]}, {d.day}. {_MONTHS[d.month - 1]}"
    if d.year == today.year:
        return f"{d.day}. {_MONTHS[d.month - 1]}"
    return f"{d.day}. {_MONTHS[d.month - 1]} {d.year}"


TEXT_SOURCE_LABELS = {TEXT_OCR: "Texterkennung", TEXT_API: "Plattform", TEXT_MANUAL: "manuell"}
TEXT_SOURCE_HELP = {
    TEXT_OCR: "Per Texterkennung aus dem Screenshot gelesen – kann Fehler enthalten.",
    TEXT_API: "Wörtlich von der Plattform abgerufen.",
    TEXT_MANUAL: "Von Hand eingegeben oder korrigiert.",
}
STATUS_LABELS = {"pending": "wartend", "running": "läuft", "done": "fertig", "error": "Fehler"}

env.globals.update(
    APP_NAME=APP_NAME,
    VERSION=VERSION,
    CHANGES=CHANGES,
    url=_url,
    static=_static,
    shot=_shot,
    PLATFORM_LABELS=LABELS,
    TEXT_SOURCE_LABELS=TEXT_SOURCE_LABELS,
    TEXT_SOURCE_HELP=TEXT_SOURCE_HELP,
    STATUS_LABELS=STATUS_LABELS,
    DATE_SOURCE_LABELS={"api": "von der Plattform", "id": "aus der Beitrags-ID", "ocr": "aus dem Screenshot gelesen",
                        "manual": "von Hand eingetragen"},
    CHANGE_LABELS={"handle": "Handle", "display_name": "Anzeigename", "avatar_path": "Profilbild"},
    file_url=_file_url,
    list_choices=_all_lists,
    tag_choices=_tag_choices,
    tag_tree=_tag_tree,
    my_hearts=_my_hearts,
    unread_count=_unread_count,
    post_avatar=_post_avatar,
    citation=citation,
    archive_no=archive_no,
    said=_said,
)
env.filters["localtime"] = _localtime
env.filters["ago"] = _ago
env.filters["localday"] = _localday
env.filters["fromjson"] = lambda v: (json.loads(v) if v else [])
env.filters["dayname"] = _dayname
env.filters["monthkey"] = _monthkey
env.filters["monthname"] = _monthname


def _qs_without(query_string: str, key: str, value: str | None = None) -> str:
    """Query-String ohne einen Parameter (bzw. ohne einen Tag aus "tags") -
    fuer die x-Knoepfe an aktiven Filtern."""
    from urllib.parse import parse_qsl, urlencode

    pairs = []
    for k, v in parse_qsl(query_string or ""):
        if k == key and key == "tags" and value is not None:
            rest = [t for t in v.split(",") if t.strip() and t.strip() != value]
            if rest:
                pairs.append((k, ",".join(rest)))
        elif k == "q" and key == "tags" and value is not None:
            # Tag kam als "#tag" aus der Suche -> dort mit entfernen
            rest_q = " ".join(w for w in v.split() if w.lower().lstrip("#") != value or not w.startswith("#"))
            if rest_q:
                pairs.append((k, rest_q))
        elif k == key or (key == "from" and k == "to"):
            continue
        else:
            pairs.append((k, v))
    return urlencode(pairs)


env.filters["qs_without"] = _qs_without

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _richtext(text: str):
    """Freitext sicher anzeigen: maskieren, Links klickbar, Absaetze und Zeilenumbrueche."""
    from markupsafe import Markup, escape

    def link(m):
        url = m.group(0).rstrip(".,;:!?)")
        rest = m.group(0)[len(url):]
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>{rest}'

    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    html = "".join(f"<p>{_URL_RE.sub(link, str(escape(p))).replace(chr(10), '<br>')}</p>" for p in paras)
    return Markup(html)


env.filters["richtext"] = _richtext


# --- Toasts ------------------------------------------------------------------

def _encode_toast(message: str, kind: str) -> str:
    raw = json.dumps({"m": message, "k": kind}, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_toast(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
        return {"message": str(data.get("m", ""))[:200], "kind": data.get("k", "ok")}
    except (ValueError, TypeError):
        return None


def flash(response: Response, request: Request, message: str, kind: str = "ok") -> Response:
    """Toast fuer die naechste Seite (nach einer Weiterleitung)."""
    response.set_cookie(TOAST_COOKIE, _encode_toast(message, kind), max_age=60, httponly=True,
                        samesite="lax", path=(root_path(request) or "") + "/")
    return response


def toast_header(response: Response, message: str, kind: str = "ok") -> Response:
    """Toast fuer htmx-Antworten (ohne Seitenwechsel)."""
    response.headers["HX-Trigger"] = json.dumps({"toast": {"message": message, "kind": kind}})
    return response


# --- Rendern -----------------------------------------------------------------

def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    user = context.setdefault("user", getattr(request.state, "user", None))
    context.setdefault("csrf_token", getattr(request.state, "csrf_token", "") or getattr(request.state, "anon_csrf", ""))
    prefs = context.setdefault("prefs", get_prefs(user))
    toast = _decode_toast(request.cookies.get(TOAST_COOKIE))
    context.setdefault("toast", toast)
    if user is not None and not getattr(user, "must_change_password", False):
        from .changelog import release_notice

        context.setdefault("release", release_notice(VERSION, user.release_seen or ""))
    response = templates.TemplateResponse(request, name, context, status_code=status_code)
    if toast:
        response.delete_cookie(TOAST_COOKIE, path=(root_path(request) or "") + "/")
    return response


def redirect(request: Request, path: str, toast: str | None = None, kind: str = "ok") -> Response:
    """Weiterleitung, die auch bei htmx-Anfragen und unter Ingress klappt."""
    target = root_path(request) + path
    if request.headers.get("hx-request"):
        response: Response = Response(status_code=204, headers={"HX-Redirect": target})
    else:
        response = RedirectResponse(target, status_code=303)
    if toast:
        flash(response, request, toast, kind)
    return response
