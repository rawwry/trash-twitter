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
    # 0.23: nicht auf den Einstellungsseiten - wird beim Umschalten in der App gemerkt
    # oder folgt dem Geraet. Der Wert bleibt gueltig und gespeichert.
    shown: bool = True


PREFS: tuple[Pref, ...] = (
    # --- Darstellung --------------------------------------------------------
    Pref("theme", "Erscheinungsbild", "„System“ folgt der Einstellung deines Geräts.", "system",
         (("system", "System"), ("light", "Hell"), ("dark", "Dunkel")), "darstellung", live=True),
    Pref("accent", "Akzentfarbe", "Farbe für Links, Knöpfe und Markierungen.", "ink",
         (("ink", "Tinte"), ("blue", "Blau"), ("green", "Grün"), ("red", "Bordeaux")), "darstellung", live=True),
    Pref("density", "Dichte", "Kompakt zeigt mehr Postings auf einmal.", "comfortable",
         (("comfortable", "Luftig"), ("compact", "Kompakt")), "darstellung", live=True),
    Pref("motion", "Animationen", "„Reduziert“ schaltet Übergänge ab.", "system",
         (("system", "System"), ("full", "An"), ("reduced", "Reduziert")), "darstellung", live=True, shown=False),
    # --- Archiv -------------------------------------------------------------
    Pref("archive_view", "Ansicht", "Raster: Kacheln mit dem ganzen Wortlaut. Liste: eine Zeile pro Posting. "
         "Zeitachse: nach Monaten, mit allen Angaben.", "raster",
         (("raster", "Raster"), ("list", "Liste"), ("timeline", "Zeitachse")), "archiv", shown=False),
    Pref("list_view", "Ansicht in Listen", "Wie die Postings einer Liste erscheinen.", "raster",
         (("raster", "Raster"), ("list", "Liste"), ("timeline", "Zeitachse")), "archiv", shown=False),
    Pref("lists_overview", "Listen-Übersicht", "Kacheln mit Gesichtern oder kompakte Zeilen.", "tiles",
         (("tiles", "Kacheln"), ("rows", "Zeilen")), "archiv", shown=False),
    Pref("sort", "Sortierung", "Standard: zuletzt archivierte Postings zuerst.", "new",
         (("new", "Zuletzt archiviert"), ("old", "Zuerst archiviert"),
          ("posted", "Neueste Postings"), ("posted_old", "Älteste Postings")), "archiv"),
    Pref("persons_view", "Personen", "Wie die Personenübersicht aussieht.", "tiles",
         (("tiles", "Kacheln"), ("list", "Liste")), "archiv", shown=False),
    Pref("persons_sort", "Personen sortieren", "Reihenfolge in der Personenübersicht.", "posts",
         (("posts", "Meiste Postings"), ("recent", "Zuletzt aktiv"), ("name", "Name")), "archiv", shown=False),
    Pref("per_page", "Postings pro Seite", "Weitere lädt der Knopf „Mehr laden“.", "24",
         (("24", "24"), ("48", "48"), ("96", "96")), "archiv", shown=False),
    Pref("after_add", "Nach dem Hinzufügen", "Wohin es nach dem Archivieren geht.", "detail",
         (("detail", "Posting öffnen"), ("archive", "Im Archiv bleiben")), "archiv"),
    Pref("add_expanded", "Anmerkung & Tags beim Hinzufügen", "Felder gleich aufgeklappt zeigen.", "off",
         (("off", "Eingeklappt"), ("on", "Aufgeklappt")), "archiv", shown=False),
    # --- Suchgenerator ------------------------------------------------------
    Pref("gen_platform", "Standard-Plattform", "Mit welcher Plattform der Generator startet.", "x",
         (("x", "X (Twitter)"), ("bluesky", "Bluesky")), "suchgenerator"),
    Pref("gen_sort", "Sortierung bei X (Twitter)", "Ob „Auf X (Twitter) öffnen“ die neuesten oder die Top-Beiträge zeigt.", "latest",
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
    return [p for p in PREFS if p.section == section and p.shown]
