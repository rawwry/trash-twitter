"""Suchoperatoren fuer X - zentral an EINER Stelle.

Aendert X einen Operator oder streicht ihn, wird nur diese Datei angepasst.

⚠️ Hinweis: X dokumentiert seine Operatoren nur lueckenhaft und aendert sie
ohne Ankuendigung. Nicht jeder Operator funktioniert dauerhaft oder fuer
alle Konten (z. B. liefern min_*-Filter ohne Login oft nichts, und die
Suche selbst verlangt inzwischen meist einen Login).
"""

from __future__ import annotations

import re

from .fields import Field, Option

PLATFORM = "x"
LABEL = "X"
SEARCH_URL = "https://x.com/search"
OPEN_LABEL = "Auf X öffnen"

# Sortierung ueber den URL-Parameter f: "top" bzw. "live" (= Neueste).
SORT_IN_URL = True
SORTS = (
    ("latest", "Neueste", {"f": "live"}),
    ("top", "Top", {"f": "top"}),
)
EXTRA_URL_PARAMS = {"src": "typed_query"}

# Handles: 1-15 Zeichen, Buchstaben, Ziffern, Unterstrich.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")
ACCOUNT_HINT = "X-Namen bestehen aus 1–15 Buchstaben, Ziffern oder _."

FIELDS: tuple[Field, ...] = (
    Field("all_words", "Alle diese Wörter", "Jedes Wort muss vorkommen, egal wo. Mehrere Wörter mit Leerzeichen trennen.",
          "words", placeholder="katze kaffee"),
    Field("phrase", "Exakte Phrase", "Genau diese Wortfolge, wird in Anführungszeichen gesetzt.",
          "phrase", placeholder="guten morgen"),
    Field("any_words", "Mindestens eines dieser Wörter", "Eines der Wörter reicht (ODER-Verknüpfung).",
          "any_words", placeholder="hund katze maus"),
    Field("none_words", "Keines dieser Wörter", "Beiträge mit diesen Wörtern werden ausgeschlossen (Minus-Operator).",
          "none_words", placeholder="werbung gewinnspiel"),
    Field("hashtags", "Hashtags", "Alle genannten Hashtags müssen vorkommen. Mit oder ohne # eingeben.",
          "hashtags", placeholder="#montag"),
    Field("from_account", "Von Account", "Nur Beiträge, die dieser Account geschrieben hat (from:).",
          "account", operator="from:", placeholder="@name", group="Accounts"),
    Field("to_account", "An Account", "Nur Antworten an diesen Account (to:).",
          "account", operator="to:", placeholder="@name", group="Accounts"),
    Field("mention", "Erwähnt Account", "Beiträge, die diesen Account erwähnen (@name).",
          "account", operator="@", placeholder="@name", group="Accounts"),
    Field("lang", "Sprache", "Nur Beiträge in dieser Sprache (lang:). Die Erkennung macht X automatisch.",
          "lang", operator="lang:", group="Filter"),
    Field("since", "Von (Datum)", "Beiträge ab diesem Tag (since:, einschließlich).",
          "date", operator="since:", group="Zeitraum"),
    Field("until", "Bis (Datum)", "Beiträge VOR diesem Tag (until:, der Tag selbst zählt nicht mehr).",
          "date", operator="until:", group="Zeitraum"),
    Field("min_faves", "Mindestens Likes", "Nur Beiträge mit mindestens so vielen Likes (min_faves:).",
          "min", operator="min_faves:", summary_label="Likes", group="Reichweite"),
    Field("min_retweets", "Mindestens Reposts", "Nur Beiträge mit mindestens so vielen Reposts (min_retweets:).",
          "min", operator="min_retweets:", summary_label="Reposts", group="Reichweite"),
    Field("min_replies", "Mindestens Antworten", "Nur Beiträge mit mindestens so vielen Antworten (min_replies:).",
          "min", operator="min_replies:", summary_label="Antworten", group="Reichweite"),
    Field("replies", "Antworten", "Antworten einschließen, ausschließen oder nur Antworten zeigen.",
          "select", group="Filter", options=(
              Option("", "egal"),
              Option("only", "nur Antworten", "filter:replies", "nur Antworten"),
              Option("exclude", "keine Antworten", "-filter:replies", "ohne Antworten"),
          )),
    Field("media", "Medien", "Nur Beiträge mit Medien, Bildern, Videos oder Links.",
          "select", group="Filter", options=(
              Option("", "egal"),
              Option("media", "mit Medien (Bild oder Video)", "filter:media", "mit Medien"),
              Option("images", "mit Bildern", "filter:images", "mit Bildern"),
              Option("videos", "mit Videos", "filter:videos", "mit Videos"),
              Option("links", "mit Links", "filter:links", "mit Links"),
          )),
)

# Reihenfolge im Suchbefehl (angelehnt an die erweiterte Suche von X).
ORDER = ("all_words", "phrase", "any_words", "none_words", "hashtags", "from_account", "to_account",
         "mention", "min_replies", "min_faves", "min_retweets", "lang", "until", "since", "replies", "media")

# Bewusst NICHT umgesetzt / unsicher:
TODO = (
    "filter:verified / filter:blue_verified - Verhalten seit 2023 unklar, daher weggelassen.",
    "near:/within: (Ort) - von X nicht mehr verlässlich unterstützt, daher weggelassen.",
)
