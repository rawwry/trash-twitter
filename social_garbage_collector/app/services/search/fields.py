"""Bausteine fuer die Operator-Konfiguration (geteilt von X und Bluesky).

Ein Feld beschreibt, WAS der Nutzer eingibt (Formular) und WIE daraus ein
Stueck Suchbefehl wird (kind + operator). Die eigentliche Logik steckt in
builder.py, die Operator-Listen pro Plattform in operators_x.py und
operators_bluesky.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    query: str = ""      # Stueck Suchbefehl, z. B. "-filter:replies"
    summary: str = ""    # Klartext, z. B. "ohne Antworten"


@dataclass(frozen=True)
class Field:
    key: str            # Formularname; gleiche Keys = Eingabe bleibt beim Plattformwechsel erhalten
    label: str
    help: str           # Tooltip-Text
    kind: str           # words | phrase | any_words | none_words | hashtags | account | lang | date | min | select | domain | url
    operator: str = ""  # z. B. "from:", "since:", "min_faves:"
    summary_label: str = ""  # z. B. "Likes" fuer "mindestens 100 Likes"
    placeholder: str = ""
    options: tuple[Option, ...] = field(default_factory=tuple)
    group: str = "Inhalt"


# Sprachen fuer das Auswahlfeld (ISO 639-1). Die Liste ist bewusst kurz.
LANGUAGES: tuple[tuple[str, str, str], ...] = (
    # code, Anzeige, Klartext fuer die Zusammenfassung
    ("de", "Deutsch", "auf Deutsch"),
    ("en", "Englisch", "auf Englisch"),
    ("fr", "Französisch", "auf Französisch"),
    ("es", "Spanisch", "auf Spanisch"),
    ("it", "Italienisch", "auf Italienisch"),
    ("nl", "Niederländisch", "auf Niederländisch"),
    ("pt", "Portugiesisch", "auf Portugiesisch"),
    ("pl", "Polnisch", "auf Polnisch"),
    ("tr", "Türkisch", "auf Türkisch"),
    ("ja", "Japanisch", "auf Japanisch"),
)
