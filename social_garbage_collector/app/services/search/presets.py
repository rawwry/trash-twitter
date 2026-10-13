"""Beispiel-Vorlagen fuer den Suchbefehl-Generator.

Leere Felder in einer Vorlage sind Absicht: dort traegt man selbst etwas ein
(z. B. den Account). "focus" sagt der Oberflaeche, welches Feld das ist.
"""

from __future__ import annotations

from datetime import date, timedelta


def presets(platform: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    if platform == "bluesky":
        return [
            {"key": "account_topic", "name": "Beiträge eines Accounts zu einem Thema",
             "focus": "from_account", "values": {"from_account": "", "all_words": ""}},
            {"key": "links_domain", "name": "Beiträge mit Links zu einer Website",
             "focus": "domain", "values": {"domain": "tagesschau.de"}},
            {"key": "german_week", "name": "Deutsche Beiträge der letzten 7 Tage",
             "focus": "all_words", "values": {"lang": "de", "since": week_ago}},
            {"key": "hashtag_de", "name": "Hashtag auf Deutsch",
             "focus": "hashtags", "values": {"hashtags": "", "lang": "de"}},
        ]
    return [
        {"key": "popular_account", "name": "Beliebte Beiträge eines Accounts",
         "focus": "from_account", "values": {"from_account": "", "min_faves": "100", "replies": "exclude"}},
        {"key": "images_topic", "name": "Beiträge mit Bildern zu einem Thema",
         "focus": "all_words", "values": {"all_words": "", "media": "images", "replies": "exclude"}},
        {"key": "viral_week", "name": "Virale Beiträge der letzten 7 Tage",
         "focus": "all_words", "values": {"min_retweets": "500", "since": week_ago, "replies": "exclude"}},
        {"key": "german_no_replies", "name": "Deutsche Beiträge ohne Antworten",
         "focus": "all_words", "values": {"lang": "de", "replies": "exclude"}},
    ]
