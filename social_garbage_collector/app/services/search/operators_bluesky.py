"""Suchoperatoren fuer Bluesky - zentral an EINER Stelle.

Nur Operatoren, die in der offiziellen Doku belegt sind (Stand Oktober 2026):

  * Bluesky-Blog "Tips and Tricks for Bluesky Search" (bsky.social/about/blog/05-31-2024-search):
    "exakte Phrase", #hashtag, from:, mentions: (bzw. to:/@), domain:, lang:,
    since:/until: (YYYY-MM-DD, UTC), komplette URL einfuegen.
  * Lexicon app.bsky.feed.searchPosts: Parameter q, sort (top|latest), since,
    until, mentions, author, lang, domain, url, tag - die Query-Operatoren
    oben entsprechen diesen Parametern.

⚠️ Nicht jeder Operator funktioniert dauerhaft oder in jeder App-Version.
Die Bluesky-Suche ist inzwischen nur noch eingeloggt nutzbar.
"""

from __future__ import annotations

import re

from .fields import Field

PLATFORM = "bluesky"
LABEL = "Bluesky"
SEARCH_URL = "https://bsky.app/search"
OPEN_LABEL = "Auf Bluesky öffnen"

# Die Web-Such-URL kennt (Stand Okt. 2026) KEINEN Sortier-Parameter: der
# Wechsel zwischen "Top" und "Neueste" auf bsky.app aendert die URL nicht.
# Die API kann sortieren (sort=top|latest), der Link aber nicht.
SORT_IN_URL = False
SORTS: tuple = ()
SORT_HINT = "Bluesky-Links kennen keine Sortierung. Auf bsky.app oben zwischen „Top“ und „Neueste“ wechseln."
EXTRA_URL_PARAMS: dict = {}

# Handle mit Punkt (name.bsky.social, eigene Domain) oder DID.
ACCOUNT_PATTERN = re.compile(
    r"^(did:plc:[a-z2-7]{24}|did:web:[A-Za-z0-9.:%-]+|([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]*)$"
)
ACCOUNT_HINT = "Bluesky-Handles enthalten einen Punkt, z. B. name.bsky.social."
DEFAULT_HANDLE_SUFFIX = ".bsky.social"

FIELDS: tuple[Field, ...] = (
    Field("all_words", "Alle diese Wörter", "Jedes Wort muss vorkommen. Mehrere Wörter mit Leerzeichen trennen.",
          "words", placeholder="katze kaffee"),
    Field("phrase", "Exakte Phrase", "Genau diese Wortfolge in Anführungszeichen. Findet auch Alt-Texte von Bildern.",
          "phrase", placeholder="guten morgen"),
    Field("hashtags", "Hashtags", "Alle genannten Hashtags müssen vorkommen. Mit oder ohne # eingeben.",
          "hashtags", placeholder="#montag"),
    Field("from_account", "Von Account", "Nur Beiträge dieses Accounts (from:).",
          "account", operator="from:", placeholder="name.bsky.social", group="Accounts"),
    Field("mention", "Erwähnt Account", "Beiträge, die diesen Account erwähnen (mentions:).",
          "account", operator="mentions:", placeholder="name.bsky.social", group="Accounts"),
    Field("lang", "Sprache", "Nur Beiträge in dieser Sprache (lang:, zweistelliger Code).",
          "lang", operator="lang:", group="Filter"),
    Field("since", "Von (Datum)", "Beiträge ab diesem Tag (since:, UTC, einschließlich).",
          "date", operator="since:", group="Zeitraum"),
    Field("until", "Bis (Datum)", "Beiträge VOR diesem Tag (until:, UTC, der Tag selbst zählt nicht mehr).",
          "date", operator="until:", group="Zeitraum"),
    Field("domain", "Links zu Domain", "Beiträge, die auf diese Website verlinken (domain:), z. B. tagesschau.de.",
          "domain", operator="domain:", placeholder="tagesschau.de", group="Links"),
    Field("link_url", "Link (genaue URL)", "Beiträge, die genau diese Adresse verlinken. Komplette URL einfügen.",
          "url", placeholder="https://…", group="Links"),
)

ORDER = ("all_words", "phrase", "hashtags", "from_account", "mention", "domain", "link_url", "lang", "since", "until")

# TODO: In der offiziellen Doku NICHT belegt - deshalb bewusst weggelassen,
# statt sie zu erfinden. Wieder pruefen, wenn Bluesky die Hilfe aktualisiert:
TODO = (
    "Ausschluss mit -wort: in der offiziellen Doku nicht belegt (die App hat seit 2026 ein Filterfeld "
    "„Wörter ausschließen“, die erzeugte Syntax ist aber nicht dokumentiert).",
    "ODER-Verknüpfung (OR): nicht belegt.",
    "Medientyp-Filter (nur Bilder/Videos): nur als App-Filter bekannt, Syntax nicht dokumentiert.",
    "Antworten ein-/ausschließen: nur als App-Filter bekannt, Syntax nicht dokumentiert.",
    "Mindestanzahl Likes/Reposts: gibt es bei Bluesky nicht.",
    "Sortierung im Such-Link: die Web-URL hat dafür keinen Parameter (nur die API: sort=top|latest).",
)
