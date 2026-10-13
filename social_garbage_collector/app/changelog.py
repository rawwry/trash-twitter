"""Versionsverlauf - erscheint in Einstellungen → Über."""

CHANGES = [
    {
        "version": "0.9.0",
        "date": "14.10.2026",
        "title": "Galerie",
        "items": [
            "Neue Galerie: Bilder hochladen, eigene Kategorien vergeben, filtern – Raster im Blocksatz, Vollbild mit Blättern",
            "Listen: Auswahlfenster statt Dropdown (antippen, suchen, neue Liste direkt anlegen), Beschreibung, Kacheln mit Gesichtern",
            "Passwörter kann niemand mehr einsehen – die Testfunktion ist samt gespeicherter Kopien entfernt",
            "„Passwort ändern“ direkt im Kontomenü",
        ],
    },
    {
        "version": "0.8.0",
        "date": "13.10.2026",
        "title": "Massenimport",
        "items": [
            "Neuer Reiter „Viele Links“: bis zu 500 Links von X und Bluesky auf einmal einfügen, auch mitten in Text",
            "Keine Duplikate: doppelt eingefügte, schon archivierte und schon als Thread-Teil erfasste Beiträge werden übersprungen",
            "Optional Tags und eine Liste für alle",
            "Fortschrittsseite mit Zusammenfassung; frühere Importe unter /import",
            "Duplikat-Prüfung erkennt jetzt auch Thread-Teile (auch beim einzelnen Hinzufügen)",
        ],
    },
    {
        "version": "0.7.1",
        "date": "13.10.2026",
        "title": "Lange Beiträge im Beleg",
        "items": [
            "Lange X-Beiträge: der vollständige Wortlaut wird vor dem Screenshot in die Ansicht eingesetzt, „Mehr anzeigen“ entfällt",
            "Solche Belege sind auf der Detailseite als „Text ergänzt“ gekennzeichnet",
        ],
    },
    {
        "version": "0.7.0",
        "date": "13.10.2026",
        "title": "Personen gestalten, lange Beiträge",
        "items": [
            "Personen: eigenes Foto, Kurzbeschreibung und Beschreibung – betrifft nur die Darstellung",
            "Personenübersicht als Kacheln (Standard), Liste weiterhin umschaltbar",
            "Lange X-Beiträge („Mehr anzeigen“): der volle Wortlaut wird nachgeladen",
            "Beleg langer Beiträge: Hinweis, dass X nur den Anfang zeigt – Vollbild als eigener Screenshot möglich",
        ],
    },
    {
        "version": "0.6.3",
        "date": "13.10.2026",
        "title": "Datum nachgetragen",
        "items": [
            "Fehlendes Datum wird automatisch bestimmt: aus der Beitrags-ID (X und Bluesky, auf die Sekunde genau)",
            "Wo das nicht geht (Uploads ohne Link, Tweets vor Nov. 2010): per Texterkennung aus dem Screenshot",
            "Auf der Detailseite steht, woher das Datum stammt – und es lässt sich von Hand korrigieren",
        ],
    },
    {
        "version": "0.6.2",
        "date": "13.10.2026",
        "title": "Ganze Sätze",
        "items": [
            "Per Texterkennung gelesene Texte werden zu Absätzen zusammengefügt statt Zeile für Zeile umzubrechen",
            "Gilt auch rückwirkend für alle vorhandenen OCR-Texte (von Hand korrigierte bleiben unberührt)",
        ],
    },
    {
        "version": "0.6.1",
        "date": "13.10.2026",
        "title": "Feinschliff",
        "items": [
            "Neuer Name: TrashTwitter",
            "Zitatkarten: Fußzeile bricht nicht mehr um (Datum und Nummer links, Original rechts, Status darüber)",
            "Automatische Thread-Erkennung abgeschaltet – weitere Teile ergänzt du per Link",
        ],
    },
    {
        "version": "0.6.0",
        "date": "13.10.2026",
        "title": "Quellenarchiv",
        "items": [
            "Neuer Name und neue Ausrichtung: Wortlaut dokumentiert öffentliche Aussagen – sachlich, mit Quelle und Beleg",
            "Personen und Accounts: Accounts werden über ihre feste ID erkannt, Handle-, Namens- und Bildwechsel landen im Verlauf",
            "Mehrere Accounts einer Person lassen sich zusammenführen, Zuordnungen jederzeit ändern",
            "Profilbilder der Verfasser werden lokal gesichert, Stand bei der Archivierung",
            "Einheitliche Zitatkarte für X und Bluesky, Screenshot nur noch als Beleg",
            "Quellenangabe zum Kopieren und feste Archiv-Nummer für jede Aussage",
            "X: Wortlaut jetzt exakt von der Plattform statt per Texterkennung",
            "Archiv sortiert nach dem Datum der Aussage; Ansichten Karten, Liste, Zeitachse (nach Monaten)",
            "Entfernt: Reaktionen, „Neu für dich“, Zufallsfund, „Heute vor …“ und der Discomodus",
        ],
    },
    {
        "version": "0.5.0",
        "date": "12.10.2026",
        "title": "Eigene Screenshots",
        "items": [
            "Eigene Screenshots hochladen – z. B. für gelöschte oder geschützte Tweets",
            "Auswählen, hierher ziehen oder einfach mit ⌘V/Strg+V einfügen (öffnet sich von selbst)",
            "Mehrere Bilder werden untereinander geklebt, Text kommt per Texterkennung",
            "Optional mit Original-Link: dann Duplikatprüfung, Autor und Text wie gewohnt",
            "Beitragsseite: eigenen Screenshot statt der automatischen Aufnahme hochladen",
        ],
    },
    {
        "version": "0.4.0",
        "date": "12.10.2026",
        "title": "Threads und Mehrfachauswahl",
        "items": [
            "Mehrfachauswahl im Archiv: viele Beiträge auf einmal in eine (auch neue) Liste legen",
            "Threads: Bluesky komplett automatisch, X automatisch bis zum Anfang – alle Teile zu einem Bild zusammengeklebt",
            "Thread-Teile von Hand ergänzen, auch nachträglich auf der Beitragsseite",
            "Screenshots als WebP: rund 80 % weniger Speicher, vorhandene werden beim Update umgewandelt",
            "Teilen und Speichern liefern JPG, das versteht jede App",
            "Fix: Bei X-Antworten landete der Vorgänger-Tweet im Screenshot statt des eigentlichen Tweets",
        ],
    },
    {
        "version": "0.3.2",
        "date": "12.10.2026",
        "title": "Keine weißen Ränder mehr",
        "items": [
            "Fix: Unter manchen X-Screenshots war eine dünne weiße Linie",
            "Vorhandene Screenshots werden beim Update automatisch bereinigt",
        ],
    },
    {
        "version": "0.3.1",
        "date": "12.10.2026",
        "title": "Mobile Darstellung",
        "items": [
            "Handy: nichts ragt mehr über den Rand – geprüft von 320 bis 1280 px auf allen Seiten",
            "Benutzer und Protokoll als Karten statt seitlich wischbarer Tabellen",
            "Einstellungen mit vielen Optionen brechen sauber um",
            "Archiv-Kopf am Handy kompakter, der erste Beitrag ist ohne Scrollen sichtbar",
            "Suchgenerator am Handy: der Suchbefehl schwebt beim Tippen unten mit",
            "Beitragsseite: Vor/Zurück als ↑/↓, damit es nicht mit „Zurück zum Archiv“ verwechselt wird",
        ],
    },
    {
        "version": "0.3.0",
        "date": "11.10.2026",
        "title": "Dunkle Screenshots, Darstellungen, Profile",
        "items": [
            "Screenshots im Dark Mode und ohne die eigenen Rahmen/Rundungen von X und Bluesky",
            "Archiv in vier Darstellungen: Raster (alle Kacheln gleich groß), Mosaik, Timeline, Liste",
            "Profil: eigener Anzeigename und Profilbild",
            "Passwörter ab 5 Zeichen",
            "Admins: alle Screenshots auf einen Schlag neu aufnehmen",
        ],
    },
    {
        "version": "0.2.0",
        "date": "11.10.2026",
        "title": "Überarbeitete Oberfläche",
        "items": [
            "Neues Design passend zum Icon: Nachtblau, Hell/Dunkel/System, vier Akzentfarben",
            "Handy: Tab-Leiste unten, Hinzufügen als Sheet, App-Icon für den Homescreen",
            "Einstellungen mit allen persönlichen Optionen, Tag-Verwaltung und (für Admins) System",
            "Neu: Reaktionen, „Neu für dich“, Zufallsfund & „Heute vor X Jahren“",
            "Neu: Live-Prüfung beim Einfügen (Plattform, Duplikat) und Teilen direkt aus anderen Apps",
            "Tastenkürzel, Vor/Zurück auf der Beitragsseite, Screenshot teilen oder speichern",
        ],
    },
    {
        "version": "0.1.0",
        "date": "10.10.2026",
        "title": "Erste Version",
        "items": [
            "Archiv für X und Bluesky mit Screenshot, Texterkennung, Tags, Listen und Volltextsuche",
            "Suchbefehl-Generator, Benutzerverwaltung, Protokoll",
        ],
    },
]
