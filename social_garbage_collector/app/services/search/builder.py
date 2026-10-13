"""Erzeugt Suchbefehle fuer X und Bluesky - ohne jede Oberflaeche.

    result = build_query("x", {"from_account": "name", "min_faves": "100"})
    result.query    -> 'from:name min_faves:100'
    result.summary  -> 'Beiträge von @name mit mindestens 100 Likes'
    result.url("latest") -> 'https://x.com/search?q=from%3Aname%20min_faves%3A100&src=typed_query&f=live'

Welche Felder es gibt und welcher Operator dahinter steckt, steht in
operators_x.py bzw. operators_bluesky.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from types import ModuleType
from urllib.parse import quote, urlencode, urlparse

from . import operators_bluesky, operators_x
from .fields import LANGUAGES, Field

PLATFORMS: dict[str, ModuleType] = {"x": operators_x, "bluesky": operators_bluesky}

_TOKEN = re.compile(r'"([^"]*)"|([^\s,;]+)')
# Woerter, die ohne Anfuehrungszeichen sicher sind. Alles andere (Doppelpunkt,
# Klammern, fuehrendes Minus, ...) wird gequotet, damit es nicht ploetzlich
# als Operator wirkt.
_PLAIN_WORD = re.compile(r"^[\w][\w'’.\-]*$", re.UNICODE)
_RESERVED = {"OR", "AND", "NOT"}
_HASHTAG = re.compile(r"^[\w]+$", re.UNICODE)
_DOMAIN = re.compile(r"^(?=.{3,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_MAX_LEN = 200


@dataclass
class BuildResult:
    platform: str
    query: str
    summary: str
    warnings: list[str] = field(default_factory=list)
    used: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.query

    def url(self, sort: str = "") -> str:
        mod = PLATFORMS[self.platform]
        params: dict[str, str] = {"q": self.query}
        params.update(mod.EXTRA_URL_PARAMS)
        if mod.SORT_IN_URL:
            sorts = {key: extra for key, _label, extra in mod.SORTS}
            params.update(sorts.get(sort) or mod.SORTS[0][2])
        # quote statt quote_plus: Leerzeichen als %20, das verstehen beide sicher.
        return f"{mod.SEARCH_URL}?{urlencode(params, quote_via=quote)}"


# --------------------------------------------------------------------------
# Einzelne Bausteine
# --------------------------------------------------------------------------

def split_terms(raw: str) -> list[str]:
    """Zerlegt Eingaben in Begriffe; "zitierte Teile" bleiben zusammen."""
    out = []
    for quoted, plain in _TOKEN.findall((raw or "")[:_MAX_LEN * 3]):
        term = (quoted if quoted else plain).strip()
        term = term.replace('"', "").strip()
        if term:
            out.append(term)
    return out


def format_term(term: str) -> str:
    """Ein Begriff, sicher fuer den Suchbefehl."""
    term = term.replace('"', "").strip()
    if not term:
        return ""
    if " " in term or term in _RESERVED or not _PLAIN_WORD.match(term):
        return f'"{term}"'
    return term


def format_phrase(raw: str) -> str:
    phrase = re.sub(r"\s+", " ", (raw or "").replace('"', " ")).strip()[:_MAX_LEN]
    return f'"{phrase}"' if phrase else ""


def _de_list(items: list[str], conj: str = "und") -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _quoted(items: list[str]) -> list[str]:
    return [f"„{i}“" for i in items]


def _de_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def normalize_account(mod: ModuleType, raw: str, warnings: list[str], label: str) -> str:
    acc = (raw or "").strip()
    # Ganze Profil-Links akzeptieren: x.com/name, bsky.app/profile/name
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})", acc) or re.search(r"bsky\.app/profile/([^/?#\s]+)", acc)
    if m:
        acc = m.group(1)
    acc = acc.lstrip("@").strip().rstrip("/")
    if not acc:
        return ""
    if mod is operators_bluesky:
        acc = acc.lower() if not acc.startswith("did:") else acc
        if "." not in acc and not acc.startswith("did:") and re.match(r"^[a-z0-9-]{1,63}$", acc):
            acc = acc + operators_bluesky.DEFAULT_HANDLE_SUFFIX
            warnings.append(f"{label}: „{raw.strip()}“ als „{acc}“ verstanden.")
    if not mod.ACCOUNT_PATTERN.match(acc):
        warnings.append(f"{label}: „{raw.strip()}“ ist kein gültiger Name. {mod.ACCOUNT_HINT}")
        return ""
    return acc


def parse_date(raw: str, warnings: list[str], label: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        warnings.append(f"{label}: „{raw}“ ist kein gültiges Datum (JJJJ-MM-TT).")
        return None


def parse_min(raw: str, warnings: list[str], label: str) -> int | None:
    raw = (raw or "").strip().replace(".", "")
    if not raw:
        return None
    if not raw.isdigit():
        warnings.append(f"{label}: bitte eine ganze Zahl eingeben.")
        return None
    value = int(raw)
    return value if value > 0 else None


def normalize_domain(raw: str, warnings: list[str], label: str) -> str:
    raw = (raw or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else "https://" + raw).hostname or ""
    host = host.removeprefix("www.")  # domain:spiegel.de findet auch www.spiegel.de
    if not _DOMAIN.match(host):
        warnings.append(f"{label}: „{raw}“ ist keine gültige Domain.")
        return ""
    return host


def normalize_url(raw: str, warnings: list[str], label: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or " " in raw or '"' in raw:
        warnings.append(f"{label}: bitte eine vollständige Adresse mit https:// einfügen.")
        return ""
    return raw[:500]


# --------------------------------------------------------------------------
# Hauptfunktion
# --------------------------------------------------------------------------

def fields_for(platform: str) -> tuple[Field, ...]:
    return PLATFORMS[platform].FIELDS


def build_query(platform: str, values: dict[str, str]) -> BuildResult:
    if platform not in PLATFORMS:
        platform = "x"
    mod = PLATFORMS[platform]
    by_key = {f.key: f for f in mod.FIELDS}
    warnings: list[str] = []
    parts: dict[str, str] = {}
    used: dict[str, str] = {}

    # Klartext-Bausteine
    s_from = s_to = ""
    s_with: list[str] = []
    s_without = ""
    s_lang = ""
    s_since = s_until = ""
    s_tail: list[str] = []

    for key in mod.ORDER:
        fld = by_key[key]
        raw = str(values.get(key, "") or "")
        if not raw.strip():
            continue
        if fld.kind == "words":
            terms = [format_term(t) for t in split_terms(raw)]
            terms = [t for t in terms if t]
            if terms:
                parts[key] = " ".join(terms)
                plain = [t.strip('"') for t in terms]
                s_with.append(("dem Wort " if len(plain) == 1 else "allen Wörtern ") + _de_list(_quoted(plain)))
        elif fld.kind == "phrase":
            phrase = format_phrase(raw)
            if phrase:
                parts[key] = phrase
                s_with.append(f"der Phrase „{phrase.strip(chr(34))}“")
        elif fld.kind == "any_words":
            terms = [t for t in (format_term(x) for x in split_terms(raw)) if t]
            if len(terms) == 1:
                parts[key] = terms[0]
                s_with.append(f"dem Wort „{terms[0].strip(chr(34))}“")
            elif terms:
                parts[key] = "(" + " OR ".join(terms) + ")"
                s_with.append("mindestens einem der Wörter " + _de_list(_quoted([t.strip('"') for t in terms]), "oder"))
        elif fld.kind == "none_words":
            terms = [t for t in (format_term(x) for x in split_terms(raw)) if t]
            if terms:
                parts[key] = " ".join("-" + t for t in terms)
                s_without = "ohne " + _de_list(_quoted([t.strip('"') for t in terms]), "oder")
        elif fld.kind == "hashtags":
            tags = []
            for t in split_terms(raw):
                t = t.lstrip("#")
                if _HASHTAG.match(t):
                    tags.append("#" + t)
                elif t:
                    warnings.append(f"Hashtag „{t}“ enthält ungültige Zeichen und wurde weggelassen.")
            if tags:
                parts[key] = " ".join(tags)
                s_with.append(_de_list(tags))
        elif fld.kind == "account":
            acc = normalize_account(mod, raw, warnings, fld.label)
            if acc:
                parts[key] = f"{fld.operator}{acc}"
                if key == "from_account":
                    s_from = f" von @{acc}"
                elif key == "to_account":
                    s_to = f" als Antwort an @{acc}"
                else:
                    s_with.append(f"Erwähnung von @{acc}")
        elif fld.kind == "lang":
            code = raw.strip().lower()
            lang = next((lang for lang in LANGUAGES if lang[0] == code), None)
            if re.fullmatch(r"[a-z]{2}", code):
                parts[key] = f"{fld.operator}{code}"
                s_lang = " " + (lang[2] if lang else f"in der Sprache „{code}“")
            else:
                warnings.append(f"Sprache „{raw}“ ist kein zweistelliger Sprachcode.")
        elif fld.kind == "date":
            d = parse_date(raw, warnings, fld.label)
            if d:
                parts[key] = f"{fld.operator}{d.isoformat()}"
                if key == "since":
                    s_since = f" seit {_de_date(d)}"
                else:
                    s_until = f" vor dem {_de_date(d)}"
        elif fld.kind == "min":
            n = parse_min(raw, warnings, fld.label)
            if n:
                parts[key] = f"{fld.operator}{n}"
                s_with.append(f"mindestens {n:,} {fld.summary_label}".replace(",", "."))
        elif fld.kind == "select":
            opt = next((o for o in fld.options if o.value == raw.strip()), None)
            if opt and opt.query:
                parts[key] = opt.query
                if opt.summary.startswith("mit "):
                    s_with.append(opt.summary.removeprefix("mit "))
                else:
                    s_tail.append(opt.summary)
        elif fld.kind == "domain":
            host = normalize_domain(raw, warnings, fld.label)
            if host:
                parts[key] = f"{fld.operator}{host}"
                s_with.append(f"Links zu {host}")
        elif fld.kind == "url":
            url = normalize_url(raw, warnings, fld.label)
            if url:
                parts[key] = url
                s_with.append(f"dem Link {url}")
        if key in parts:
            used[key] = raw

    # Plausibilitaet Zeitraum
    since_d = parse_date(values.get("since", ""), [], "") if "since" in parts else None
    until_d = parse_date(values.get("until", ""), [], "") if "until" in parts else None
    if since_d and until_d and since_d >= until_d:
        warnings.append("Der Zeitraum ist leer: „Bis“ muss nach „Von“ liegen.")

    query = " ".join(parts[k] for k in mod.ORDER if k in parts)

    if not query:
        summary = "Noch keine Kriterien – fülle mindestens ein Feld aus."
    else:
        summary = "Beiträge" + s_from + s_to
        if s_with:
            summary += " mit " + _de_list(s_with)
        if s_without:
            summary += " " + s_without
        summary += s_lang + s_since + s_until
        if s_tail:
            summary += ", " + ", ".join(s_tail)

    return BuildResult(platform=platform, query=query, summary=summary, warnings=warnings, used=used)


def shared_keys() -> set[str]:
    """Felder, die es auf beiden Plattformen gibt (bleiben beim Wechsel erhalten)."""
    keys = [{f.key for f in mod.FIELDS} for mod in PLATFORMS.values()]
    return set.intersection(*keys)


def all_field_keys() -> list[str]:
    seen: list[str] = []
    for mod in PLATFORMS.values():
        for f in mod.FIELDS:
            if f.key not in seen:
                seen.append(f.key)
    return seen
