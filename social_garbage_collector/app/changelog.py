"""Versionsverlauf - erscheint in Einstellungen → Über.

Ab 0.14 (Timo): Jede x.x-Version (Feature-Release, nicht x.x.x) bekommt
"highlights" - die zeigt die App jedem Mitglied einmal als Fenster
"Neu in TrashTwitter x.x" (siehe release_notice). Je Punkt: (Symbol, Titel, Satz).
"""

CHANGES = [
    {
        "version": "0.15.1",
        "date": "17.10.2026",
        "title": "Keine Fehler 500 mehr, Feinschliff",
        "items": [
            "Behoben: Nach mehreren Fehlerseiten (z. B. gelöschtes Posting) gingen der App die Datenbank-Verbindungen aus – danach endete jede Seite in Fehler 500",
            "Behoben: Während des Archivierens (Videos, Screenshots) und beim Massenimport war die Datenbank gesperrt – Speichern konnte in Fehler 500 laufen",
            "Verständliche Fehlerseite mit „Noch einmal versuchen“ statt „Internal Server Error“",
            "Postings in Arbeit zeigen einen Platzhalter und „wird archiviert“",
            "Medien auf der Detailseite als Raster (2, 3 oder 4 Bilder)",
            "Personenkacheln, Einstellungen und Galerie am Handy aufgeräumt; „Idiotarium“ auch in Links und Zurück-Knöpfen",
        ],
    },
    {
        "version": "0.15.0",
        "date": "16.10.2026",
        "title": "Recherche-Arbeitsplatz, Tags im Griff, neues Design",
        "highlights": [
            ("research", "Recherche an einem Ort", "Links alle Einträge – auch nach Person sortiert –, rechts lesen, bearbeiten und neu schreiben, ohne die Seite zu wechseln."),
            ("edit", "Einfacher schreiben", "Erst der Text, der Titel ergibt sich von selbst. Personen und Postings sucht ihr einfach per Name oder Wortlaut."),
            ("tag", "Tags per Knopf – oder #tag", "Die Tag-Zeile ist weg: „Tags“ in der Suchleiste öffnet alle Tags. Oder tippt „#klima“ direkt ins Suchfeld."),
            ("sparkles", "Neues Design", "Ruhigere Seitenköpfe, klarere Karten und Knöpfe, bessere Handy-Ansicht."),
        ],
        "items": [
            "Recherche-Arbeitsplatz: Liste und Eintrag nebeneinander, Ansicht „Nach Person“, Filter nach Art und Person, Bearbeiten und Neu-Anlegen direkt rechts",
            "Recherche-Formular vereinfacht: Text zuerst, Titel optional (sonst erste Zeile), Personen und Postings per Suche, Quellen einklappbar",
            "Idiotarium: Tags als Knopf in der Suchleiste mit allen Tags nach Oberbegriffen; „#tag“ im Suchfeld schlägt Tags vor; aktive Tags als Chips mit ×",
            "Redesign: einheitliche Seitenköpfe, neue Farben und Abstände, Karten, Knöpfe, Eingabefelder, Anmelden-Seite, Listen-Kopf, Handy-Reiter",
        ],
    },
    {
        "version": "0.14.0",
        "date": "16.10.2026",
        "title": "Recherche, Tags mit Oberbegriffen, Threads",
        "highlights": [
            ("research", "Recherche", "Ein gemeinsamer Ort für eure eigenen Fakten und Hintergründe – zugeordnet zu Personen und den Postings, um die es geht."),
            ("tag", "Tags mit Oberbegriffen", "Beim Vergeben schlägt die App vorhandene Tags vor. Unter „Tags organisieren“ fasst ihr ähnliche Tags unter Oberbegriffen zusammen."),
            ("timeline", "Threads hinzufügen", "Eigener Reiter „Thread“: Links aller Teile der Reihe nach eintragen – fertig."),
            ("help", "Hilfe & Anleitung", "Alle Funktionen kurz erklärt – jederzeit über das Fragezeichen oben rechts."),
        ],
        "items": [
            "Neuer Bereich „Recherche“: Widersprüche, Fakten und Hintergründe mit Quellen, zugeordnet zu Personen und Postings",
            "Tags: Auswahl aus vorhandenen Tags (auch ähnlich geschriebene), neue nur per Extra-Klick; Oberbegriffe mit Unter-Tags; „Alle Tags“ im Idiotarium",
            "„Tags organisieren“: einordnen, zusammenführen, löschen – auch mehrere auf einmal",
            "Threads: eigener Reiter beim Hinzufügen, „Thread ergänzen“ direkt unter dem Wortlaut",
            "Hilfe mit Grundlagen zu allen Funktionen, erreichbar über das Fragezeichen oben",
            "Das Archiv heißt jetzt „Das Idiotarium“; X heißt überall „X (Twitter)“",
            "Neu-Fenster bei jeder größeren Version; frischeres Design",
        ],
    },
    {
        "version": "0.13.1",
        "date": "16.10.2026",
        "title": "Belege ohne Bedienleiste",
        "items": [
            "X-Belege enden jetzt mit der Zeitzeile: Herz, „Antworten“, „Link zum Post kopieren“ und „Antworten lesen“ fallen weg – auch in zusammengesetzten Threads",
            "Vorhandene Belege: „Neu erfassen“ am Posting oder Einstellungen → System → alle neu aufnehmen",
        ],
    },
    {
        "version": "0.13.0",
        "date": "15.10.2026",
        "title": "Videos in der Galerie",
        "items": [
            "Die Galerie nimmt jetzt auch Videos (MP4, MOV, WebM) – im Original, mit Vorschaubild und Länge im Raster",
            "Abspielen in der Vollansicht mit Spulen; Blättern und Schließen halten das Video an",
            "Fortschrittsbalken beim Hochladen; danach stehen die neuen Dateien vorn",
        ],
    },
    {
        "version": "0.12.0",
        "date": "15.10.2026",
        "title": "Screenshots verstehen, aufgeräumte Oberfläche",
        "items": [
            "Screenshots ohne Link: Die App liest Verfasser, @Handle, Plattform, Datum und Uhrzeit selbst aus dem Bild, schneidet Kopf- und Fußzeile vom Wortlaut ab und übernimmt das Profilbild",
            "Bei Bluesky sucht sie zum Screenshot das Original – gefunden, wird daraus ein normales Posting mit Link, exaktem Text und Medien",
            "Ältere hochgeladene Screenshots werden einmal neu ausgewertet (von Hand Eingetragenes bleibt)",
            "Archiv: eine ruhige Leiste mit Suche, Sortierung und Filter; die Plattform steckt jetzt im Filter. Standard: zuletzt archiviert zuerst",
            "Aktive Filter als Chips mit ×, Ansicht und Auswahl als Symbole",
            "Raster zeigt die ganze Aussage – kein Ausblenden mehr, Kacheln packen sich dicht wie ein Mauerwerk",
            "Detailseite: Posting mit Medien, Tags und Aktionen in einer Karte; Angaben und Quellenangabe eingeklappt",
            "Tags umbenennen für alle: Stift in der Tag-Leiste und „Tags verwalten“ im Menü",
            "Galerie: zufällige Reihenfolge als Standard, Sortieren nach neu hinzugefügt oder Aufnahmedatum, Mosaik oder Quadrate, Größe per Regler",
            "Listen: „Liste hinzufügen“ als Knopf; am Handy bleibt die Leiste unten kleben, auch beim Tippen",
        ],
    },
    {
        "version": "0.11.0",
        "date": "14.10.2026",
        "title": "Facelift, Teilen vom Handy, Ideen",
        "items": [
            "Neues Erscheinungsbild: weichere Karten mit Tiefe, Navigation als Pillen, ruhigere Werkzeugleiste",
            "Bilder, GIFs und Videos erscheinen jetzt auch in der Archivübersicht (als schnelle Vorschaubilder)",
            "Teilen vom iPhone und Android: persönlicher Schlüssel + Kurzbefehl – ein Tipp, Posting ist im Archiv",
            "Neue Seite „Hilfe & FAQ“ mit Schritt-für-Schritt-Anleitungen",
            "Neue Seite „Ideen“: Wünsche für neue Funktionen sammeln und mitstimmen",
            "Knöpfe heißen jetzt eindeutig „Posting hinzufügen“ und „Bilder hinzufügen“",
        ],
    },
    {
        "version": "0.10.1",
        "date": "14.10.2026",
        "title": "Notfall-Zugang",
        "items": [
            "Neue Add-on-Option reset_password: setzt beim Start das Passwort eines Kontos zurück, entsperrt und macht es zum Admin",
            "Das Protokoll nennt beim Start die Admin-Konten",
        ],
    },
    {
        "version": "0.10.0",
        "date": "14.10.2026",
        "title": "Medien, Raster, schnell aufräumen",
        "items": [
            "Bilder, GIFs und Videos aus Postings werden mitgesichert (X und Bluesky) – auch nachträglich für ältere",
            "Neue Ansicht „Raster“: gleich große Kacheln, nur Name, Text und Datum",
            "Tags im Archiv antippen statt eintippen; Schnellauswahl beim Vergeben",
            "Löschen direkt im Archiv: Mülleimer beim Drüberfahren, auch per Mehrfachauswahl – immer mit Rückfrage",
            "Personen: Foto füllt die ganze Kachel; Personen ohne Postings verschwinden",
            "„Aussage“ heißt jetzt „Posting“; ein Hinzufügen-Knopf oben rechts (in der Galerie: Bilder)",
        ],
    },
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


def release_notice(version: str, seen: str):
    """Eintrag fuer das "Neu in …"-Fenster: nur bei x.x-Versionen mit highlights,
    die das Mitglied noch nicht gesehen hat. Rueckgabe: (x.x, Eintrag) oder None."""
    parts = version.split(".")
    minor = ".".join(parts[:2])
    if seen == minor:
        return None
    for entry in CHANGES:
        if ".".join(entry["version"].split(".")[:2]) == minor and entry.get("highlights"):
            return minor, entry
    return None
