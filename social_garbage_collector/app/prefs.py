"""Persoenliche Einstellungen pro Benutzer.

Alle Einstellungen stehen HIER mit Standardwert und erlaubten Werten. Die
Einstellungsseiten bauen sich daraus, und update_prefs() laesst nur Werte
aus dieser Liste durch - so landet nie Unsinn in users.prefs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .models import User


@dataclass(frozen=True)
class Pref:
    key: str
    label: str
    help: str
    default: str
    choices: tuple[tuple[str, str], ...]  # (Wert, Anzeige)
    section: str
    live: bool = False  # sofort im Browser anwenden (Design-Attribute an <html>)


PREFS: tuple[Pref, ...] = (
    # --- Darstellung --------------------------------------------------------
    Pref("theme", "Erscheinungsbild", "„System“ folgt der Einstellung deines Geräts.", "system",
         (("system", "System"), ("light", "Hell"), ("dark", "Dunkel")), "darstellung", live=True),
    Pref("accent", "Akzentfarbe", "Farbe für Links, Knöpfe und Markierungen.", "ink",
         (("ink", "Tinte"), ("blue", "Blau"), ("green", "Grün"), ("red", "Bordeaux")), "darstellung", live=True),
    Pref("density", "Dichte", "Kompakt zeigt mehr Aussagen auf einmal.", "comfortable",
         (("comfortable", "Luftig"), ("compact", "Kompakt")), "darstellung", live=True),
    Pref("motion", "Animationen", "„Reduziert“ schaltet Übergänge ab.", "system",
         (("system", "System"), ("full", "An"), ("reduced", "Reduziert")), "darstellung", live=True),
    # --- Archiv -------------------------------------------------------------
    Pref("archive_view", "Ansicht", "Karten: Zitate nebeneinander. Liste: eine Zeile pro Aussage. "
         "Zeitachse: nach Monaten, in voller Länge.", "cards",
         (("cards", "Karten"), ("list", "Liste"), ("timeline", "Zeitachse")), "archiv"),
    Pref("sort", "Sortierung", "Standard: nach dem Datum der Aussage.", "posted",
         (("posted", "Aussage: neueste"), ("posted_old", "Aussage: älteste"),
          ("new", "Archiviert: neueste"), ("old", "Archiviert: älteste")), "archiv"),
    Pref("persons_view", "Personen", "Wie die Personenübersicht aussieht.", "tiles",
         (("tiles", "Kacheln"), ("list", "Liste")), "archiv"),
    Pref("per_page", "Aussagen pro Seite", "Weitere lädt der Knopf „Mehr laden“.", "24",
         (("24", "24"), ("48", "48"), ("96", "96")), "archiv"),
    Pref("after_add", "Nach dem Hinzufügen", "Wohin es nach dem Archivieren geht.", "detail",
         (("detail", "Aussage öffnen"), ("archive", "Im Archiv bleiben")), "archiv"),
    Pref("add_expanded", "Anmerkung & Tags beim Hinzufügen", "Felder gleich aufgeklappt zeigen.", "off",
         (("off", "Eingeklappt"), ("on", "Aufgeklappt")), "archiv"),
    # --- Suchgenerator ------------------------------------------------------
    Pref("gen_platform", "Standard-Plattform", "Mit welcher Plattform der Generator startet.", "x",
         (("x", "X"), ("bluesky", "Bluesky")), "suchgenerator"),
    Pref("gen_sort", "Sortierung bei X", "Ob „Auf X öffnen“ die neuesten oder die Top-Beiträge zeigt.", "latest",
         (("latest", "Neueste"), ("top", "Top")), "suchgenerator"),
    # --- Bedienung ----------------------------------------------------------
    Pref("shortcuts", "Tastenkürzel", "„/“ sucht, „n“ fügt hinzu, „?“ zeigt alle.", "on",
         (("on", "An"), ("off", "Aus")), "teilen"),
)

BY_KEY = {p.key: p for p in PREFS}
DEFAULTS = {p.key: p.default for p in PREFS}


def get_prefs(user: User | None) -> dict[str, str]:
    prefs = dict(DEFAULTS)
    if user is None:
        return prefs
    try:
        stored = json.loads(user.prefs or "{}")
    except (TypeError, ValueError):
        stored = {}
    for key, value in stored.items():
        pref = BY_KEY.get(key)
        if pref and value in {c[0] for c in pref.choices}:
            prefs[key] = value
    return prefs


def update_prefs(user: User, values: dict[str, str]) -> list[str]:
    """Uebernimmt nur bekannte Schluessel mit erlaubten Werten. Gibt die geaenderten Schluessel zurueck."""
    current = get_prefs(user)
    changed = []
    for key, value in values.items():
        pref = BY_KEY.get(key)
        if pref and value in {c[0] for c in pref.choices} and current.get(key) != value:
            current[key] = value
            changed.append(key)
    # Nur Abweichungen vom Standard speichern - so greifen neue Standardwerte.
    user.prefs = json.dumps({k: v for k, v in current.items() if v != DEFAULTS[k]})
    return changed


def section_prefs(section: str) -> list[Pref]:
    return [p for p in PREFS if p.section == section]
