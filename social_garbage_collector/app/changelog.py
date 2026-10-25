"""Versionsverlauf - erscheint in Einstellungen → Über.

Ab 0.14 (Timo): Jede x.x-Version (Feature-Release, nicht x.x.x) bekommt
"highlights" - die zeigt die App jedem Mitglied einmal als Fenster
"Neu in TrashTwitter x.x" (siehe release_notice). Je Punkt: (Symbol, Titel, Satz).
"""

CHANGES = [
    {
        "version": "0.22.0",
        "date": "25.10.2026",
        "title": "Collage & schnelleres Hinzufügen",
        "highlights": [
            ("mosaic", "Collage als JPG", "Suche im Idiotarium nach einem Thema und tippe „Collage“: Alle Treffer werden zu einer großen, sauber angeordneten Grafik. Format, Stil und Inhalt wählen, Unpassendes abhaken, speichern oder teilen."),
            ("tag", "Tags direkt beim Hinzufügen", "Die Tag-Auswahl ist jetzt sofort offen – mit Chips zum Antippen. Nach dem Einfügen des Links zeigt die App den Wortlaut und schlägt passende Tags vor."),
            ("sparkles", "Was automatisch kommt", "Greift eine Tag-Regel, siehst du schon beim Hinzufügen „Kommt automatisch: #…“."),
        ],
        "items": [
            "Collage-Studio (/collage): aus Suche, Auswahl oder Liste; Formate Quadrat, Hochformat, Story, Breit, Endlos; Stile Hell, Dunkel, Papier, Akzent; Karten oder Original-Belege; Wörter markieren; Datum, Archiv-Nummer, Bilder, Fußzeile; Postings abhaken und sortieren",
            "Automatische Anordnung: größtmögliche Schrift bei gut lesbarer Zeilenlänge, gleichmäßig gefüllte Spalten",
            "Export als JPG in voller Auflösung (bis 3840 px), am Handy auch teilen",
            "Hinzufügen: Tag-Auswahl offen mit Schnellauswahl, Wortlaut-Vorschau nach dem Einfügen, Tag-Vorschläge aus Regeln und den häufigsten Tags der Person; Anmerkung als „+ Anmerkung“",
        ],
    },
    {
        "version": "0.21.1",
        "date": "21.10.2026",
        "title": "Läuft auch auf dem eigenen Server",
        "items": [
            "TrashTwitter gibt es jetzt zusätzlich als fertiges Abbild für einen eigenen Server (gebaut von GitHub nach bestandenen Tests); das Home-Assistant-Add-on bleibt",
            "Hinter einem Proxy wie dem Cloudflare-Tunnel zählt die Login-Sperre wieder pro Besucher statt für alle gemeinsam",
        ],
    },
    {
        "version": "0.21.0",
        "date": "19.10.2026",
        "title": "Wiederholungen, Gelöscht-Wächter, Tags für viele",
        "highlights": [
            ("repeat", "Wiederholt erzählt", "Erzählt jemand dieselbe Geschichte mehrmals – auch umformuliert –, erkennt die App das. Auf der Personenseite gesammelt, am Posting unter „Auch so erzählt“."),
            ("close", "Original weg?", "Die App prüft im Hintergrund, ob die Originale noch online sind. Gelöschte tragen „Original weg“, wer archiviert hat, bekommt Bescheid. Im Filter: „Original nicht mehr online“."),
            ("tag", "Tags für viele auf einmal", "Im Idiotarium mehrere Postings auswählen und mit „Tags …“ Tags vergeben oder abnehmen."),
            ("search", "Suche mit Wortformen", "„Pakete“ findet jetzt auch „Paket“, „verstorbene“ auch „verstorben“. Genau so wie getippt: in Anführungszeichen."),
        ],
        "items": [
            "Wiederholt erzählt: ähnliche Postings einer Person über seltene gemeinsame Wörter (TF-IDF), an echten Daten eingestellt; Personenseite, Detailseite, „Festhalten“ als Recherche mit allen Postings",
            "Gelöscht-Wächter: Hintergrundprüfung (gemächlich, je Posting alle paar Tage), „weg“ erst nach zwei Fehlschlägen, Vermerk am Beleg mit „Jetzt prüfen“, Markierung in allen Ansichten, Filter, Benachrichtigung",
            "Mehrfachauswahl: Tags hinzufügen oder entfernen",
            "Suche: Wortstamm als Präfix, Anführungszeichen für exakte Suche",
        ],
    },
    {
        "version": "0.20.1",
        "date": "17.10.2026",
        "title": "Feinschliff",
        "items": [
            "Automatisch taggen: Übersicht oben (aktive Regeln, Postings ohne Tag, wie viele davon die Regeln erreichen) mit „Alle auf ungetaggte anwenden“; ruhigere Karten",
            "Tags organisieren: Tags mit Regel tragen ein „auto“-Abzeichen",
            "Idiotarium-Raster: Tags stehen dezent neben dem Datum",
            "Personen: sortierbar nach meisten Postings (neu Standard), zuletzt aktiv oder Name",
        ],
    },
    {
        "version": "0.20.0",
        "date": "17.10.2026",
        "title": "Automatisch taggen",
        "highlights": [
            ("tag", "Tags vergeben sich selbst", "Unter „Tags organisieren → Automatisch taggen“ legst du Regeln an: enthält der Wortlaut bestimmte Wörter, bekommt das Posting das Tag – bei jedem neu archivierten Posting von selbst."),
            ("sparkles", "Vorschau und Wortvorschläge", "Schon beim Tippen siehst du, welche Postings passen, mit markierten Treffern. Die App schlägt Wörter vor, die bei einem Tag typisch sind."),
            ("refresh", "Nachtaggen und rückgängig", "Bestehende Postings auf Knopfdruck nachtaggen – nur die ohne Tag oder alle. Was eine Regel vergeben hat, lässt sich mit einem Klick wieder abnehmen."),
        ],
        "items": [
            "Regeln: Tag, Begriffe (ganze Wörter, * als Platzhalter), mindestens einer oder alle, Ausnahmen, optional nur für eine Person; pausieren, bearbeiten, löschen",
            "Neue Postings werden beim Archivieren geprüft, auch nach einer Text-Korrektur von Hand; Regeln fügen nur hinzu, nie weg",
            "Live-Vorschau beim Anlegen, Zahlen je Regel (passend, getaggt, offen, automatisch vergeben), Anwenden auf vorhandene mit Auswahl „nur ohne Tag“ oder „alle“",
            "Wortvorschläge je Tag aus den eigenen Postings (Treffsicherheit und wie viele ungetaggte es erreichen würde)",
            "„Automatisch vergebene entfernen“ nimmt genau die Tags zurück, die eine Regel vergeben hat – von Hand vergebene bleiben",
            "Tags mit Regel bleiben auch ohne Postings erhalten; beim Zusammenführen wandern Regeln mit",
        ],
    },
    {
        "version": "0.19.1",
        "date": "17.10.2026",
        "title": "Zurück zu 0.18, schönere Tag-Verwaltung",
        "items": [
            "„Muster“, Figuren und Aufräum-Vorschläge aus 0.19.0 wieder entfernt – das Netzwerk ist zurück",
            "Tags organisieren: übersichtliche Tabelle mit festen Spalten (Tag, Postings mit Balken, Oberbegriff), Suche und Sortierung, neuer Oberbegriff über den Knopf oben",
        ],
    },
    {
        "version": "0.18.0",
        "date": "17.10.2026",
        "title": "Netzwerk",
        "highlights": [
            ("graph", "Das Archiv als Netzwerk", "Neu oben im Menü: Personen, Tags, Listen und Recherche als leuchtende Landkarte. Wer nah beieinander liegt, redet über dieselben Themen."),
            ("search", "Antippen, suchen, eingrenzen", "Ein Tipp zeigt alle Verbindungen und Details, „Nur Umgebung“ blendet den Rest aus. Dazu Suche, Zeitraum und auf Wunsch jedes einzelne Posting."),
            ("people", "Themen-Netz jeder Person", "Auf jeder Personenseite: ihre Themen und wer sonst noch darüber postet – ein Tipp öffnet die Person oder den Tag."),
            ("sparkles", "Entdeckungen", "Unter dem Netz: Brückenthemen, themenbreite Personen, Personen ohne Recherche und Postings, die noch einen Tag brauchen."),
        ],
        "items": [
            "Neue Seite „Netzwerk“: Kraft-Graph mit Personen (Profilbild, Größe nach Postings), Tags und Oberbegriffen, Listen und Recherche (Farbe nach Art)",
            "Person – Tag als Linie, so dick wie die Zahl der Postings; Liste – Person, Recherche – Person, Tag – Oberbegriff; Personen nie direkt verbunden",
            "Hervorheben beim Darüberfahren, Detailfeld mit Nachbarn, „Nur Umgebung“, Suche, Filter nach Art, Zeitraum, Postings einblenden, Vollbild, Zoom-Knöpfe",
            "Scrollen bewegt die Seite; Zoomen mit zwei Fingern oder ⌘/Strg + Scrollen",
            "Themen-Netz auf jeder Personenseite mit Sprung ins große Netz",
            "Entdeckungen unter dem Netz: Brückenthemen, themenbreit, ohne Recherche, noch einzuordnen",
            "Grafik-Bibliothek force-graph 1.51.4 (MIT) liegt lokal in der App – keine externen Server",
        ],
    },
    {
        "version": "0.17.1",
        "date": "17.10.2026",
        "title": "Senden-Knopf",
        "items": ["Der Senden-Pfeil im Kommentarfeld sitzt wieder mittig und ragt nicht mehr über den Rand"],
    },
    {
        "version": "0.17.0",
        "date": "17.10.2026",
        "title": "Kommentare & Benachrichtigungen",
        "highlights": [
            ("comment", "Kommentare unter jedem Posting", "Schreib, was dir dazu einfällt – mit Namen, für alle Mitglieder. Senden mit dem Pfeil oder ⌘/Strg + Enter."),
            ("bell", "Glocke für Neues", "Kommentiert jemand ein Posting, das du archiviert oder selbst kommentiert hast, zeigt die Glocke oben die Zahl der neuen."),
            ("archive", "Markierung im Idiotarium", "Postings mit Kommentaren tragen eine kleine Sprechblase mit der Anzahl – ein Tipp springt direkt zu den Kommentaren."),
        ],
        "items": [
            "Kommentare unter jedem Posting (flach, mit Namen und Zeit, Links klickbar); eigene bearbeiten, eigene oder als Admin löschen",
            "Benachrichtigungen für die Person, die archiviert hat, und alle, die schon mitkommentiert haben; Glocke mit Zähler, Seite „Benachrichtigungen“",
            "Sprechblase mit Anzahl an Kacheln, Zeilen und Zeitachse",
        ],
    },
    {
        "version": "0.16.0",
        "date": "17.10.2026",
        "title": "Herzstücke, aufgeräumte Threads, neue Handy-Leiste",
        "highlights": [
            ("heart", "Herzen & Herzstücke", "Gib richtig guten Postings ein Herz. Sie landen automatisch in der Liste „Herzstücke“ – die mit den meisten Herzen zuerst."),
            ("timeline", "Threads wie aus einem Guss", "Im Beleg stehen Name, Handle und Datum nur noch einmal oben – ohne „Folgen“ und „Antwort an“. Vorhandene Threads werden einmal neu aufgenommen."),
            ("lists", "Listen mit Ansichten", "Übersicht als Kacheln oder Zeilen, jede Liste als Raster, Liste oder Zeitachse."),
            ("image", "Galerie direkt in der Handy-Leiste", "Unten: Archiv, Personen, Recherche, Listen, Galerie. Das Plus schwebt rechts darüber."),
        ],
        "items": [
            "Herzen für Postings (je Mitglied eins), automatische Liste „Herzstücke“, Sortierung „Meiste Herzen“",
            "Thread-Belege: ab dem zweiten Teil nur noch Wortlaut und Medien; „Folgen“ und Bluesky-Zähler fallen immer weg; bestehende Threads werden einmal neu aufgenommen",
            "Idiotarium: Karten-Ansicht entfallen, Raster ist Standard",
            "Listen: Übersicht als Kacheln oder Zeilen, Listen als Raster, Liste oder Zeitachse",
            "Handy: fünf Ziele unten inklusive Galerie, „Hinzufügen“ als schwebender Knopf, „Mehr“ entfällt (Suchgenerator im Profil-Menü)",
        ],
    },
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
