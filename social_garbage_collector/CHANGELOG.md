# Changelog

## 0.10.0 – Medien, Raster, schnell aufräumen (14.10.2026)

- **Medien sichern** (`services/media.py`, Tabelle `post_media`, Ordner `media/`): Bilder (Originalgröße), GIFs und Videos aus Postings.
  - X: Bilder `pbs.twimg.com …?name=orig`, Videos/GIFs als MP4 der höchsten Bitrate von `video.twimg.com` (GIFs sind bei X stumme MP4-Schleifen).
  - Bluesky: Bilder vom CDN, Videos als **Originaldatei vom PDS** des Accounts (`com.atproto.sync.getBlob`, PDS über das DID-Dokument) – kein ffmpeg nötig. GIFs (Tenor/Giphy-Links) von dort.
  - Sicherheit: nur https, nur bekannte Medien-Server; PDS und Weiterleitungen nur mit öffentlicher IP. Grenze je Datei: neue Option `media_max_mb` (Standard 150), abschaltbar mit `save_media: false`.
  - Ältere Postings werden einmal im Hintergrund nachgesehen (`posts.media_checked`). Detailseite: Abschnitt „Medien“ mit Player (spulen per HTTP-Range), Karten zeigen „▶ Video“, „GIF“, „n Bilder“.
- **Raster** (`?view=raster`): ultraclean, festes Raster gleich großer Kacheln – nur Verfasser, Wortlaut, Datum.
- **Tags antippen:** Tag-Leiste über dem Archiv (häufigste zuerst, mehrere = alle müssen passen), Schnellauswahl unter jedem Tag-Feld.
- **Schnell löschen:** Mülleimer beim Drüberfahren (Touch: dezent sichtbar), „Löschen“ in der Mehrfachauswahl; eigenes Rückfrage-Fenster statt Browser-Dialog (gilt jetzt auch für andere Rückfragen). Löschen entfernt Beleg und Medien-Dateien, leere Accounts und unbearbeitete Personen.
- **Personen:** Kacheln 4:5, Foto füllt die Kachel, Name/Kurzbeschreibung/Zahlen auf Verlauf; ohne Foto Monogramm auf Farbe. Eigene Fotos werden jetzt hochkant bis 720 × 900 gespeichert. Personen ohne Postings erscheinen nicht mehr.
- **Benennung:** „Aussage“ → „Posting“ in der ganzen Oberfläche. **Ein** Hinzufügen-Knopf oben rechts (und das Plus unten), der sich nach dem Bereich richtet: „Posting“, in der Galerie „Bilder“. Taste `n` ebenso.

## 0.9.0 – Galerie (14.10.2026)

- **Galerie** (`/galerie`, Tab-Leiste): Bilder hochladen (auswählen, ziehen, ⌘V; bis 40 auf einmal, je 25 MB), frei anlegbare Kategorien. Raster im Blocksatz (alle Bilder einer Zeile gleich hoch, ohne Beschnitt-Lücken), Platzhalter in der Durchschnittsfarbe. Filter-Chips mit Anzahl, mehrere kombinierbar (= eine davon), „Ohne Kategorie“. Vollbild mit Blättern (← →, Wischen), Schließen per Esc oder Wischen nach unten, Infoleiste auf Knopf/Taste i. Bearbeiten (Titel, Notiz, Kategorien) für alle, Löschen nur für wer hochgeladen hat oder Admins. Kategorien umbenennen (gleicher Name = zusammenführen) und löschen (Bilder bleiben).
  - Speicherung: WebP, Ansicht ≤ 2400 px, Vorschau 720 px hoch, EXIF-Drehung angewendet, Metadaten (GPS) entfernt, Duplikate per SHA-256. Ordner `gallery/`, Tabellen `gallery_images`, `gallery_categories`.
- **Listen:** Auswahlfenster statt Dropdown – auf der Detailseite („Listen wählen“: antippen = rein/raus, sofort gespeichert), in der Mehrfachauswahl und als Chips im Massenimport. Suchen filtert, unbekannter Name → „als neue Liste anlegen“ (Enter). Listen haben eine Beschreibung; Übersicht als Kacheln mit den Personen darin.
- **Passwort-Anzeige entfernt:** Route, Oberfläche, Optionen `admin_password_view`/`fernet_key` und `cryptography` sind raus. Beim Start werden die gespeicherten Kopien gelöscht (Spalte `users.password_enc` entfernt) und `secrets/fernet.key` gelöscht.
- **Passwort ändern** für alle: Eintrag im Kontomenü und in der Einstellungsübersicht.
- Am Handy: Tab-Leiste Archiv · Personen · + · Listen · Galerie; Einstellungen über das Profilbild oben rechts.

## 0.8.0 – Massenimport (13.10.2026)

- **Viele Links auf einmal:** dritter Reiter „Viele Links“ im Hinzufügen-Sheet (`/add?mode=bulk`). Bis zu 500 Links von X und Bluesky, einer pro Zeile oder mitten in beliebigem Text (`services/bulk.py`). Der Worker erfasst sie nacheinander, mit 1,5 s Pause zwischen zwei Beiträgen (Rate-Limits).
- **Keine Duplikate**, dreifach geprüft: doppelt im eingefügten Text (auch x.com/twitter.com/`?s=`-Varianten, Bluesky per Handle oder DID), schon im Archiv, schon als Thread-Teil einer anderen Aussage. Letzteres gilt jetzt auch beim einzelnen Hinzufügen (`find_as_thread_part`).
- Optional Tags und eine (neue oder vorhandene) Liste für alle Links.
- **Fortschritt:** `/import/<id>` zeigt neu / schon im Archiv / doppelt / nicht erkannt, darunter den Stand jeder Aussage (aktualisiert alle 4 s). Frühere Importe unter `/import`.
- Neue Tabelle `import_batches`, neue Spalte `posts.import_batch`.

## 0.7.1 – Lange Beiträge im Beleg (13.10.2026)

- **Volltext im Beleg:** Ist der vollständige Wortlaut eines langen X-Beitrags bekannt, setzt die Aufnahme ihn in das Textfeld des Embeds ein und entfernt „Mehr anzeigen“ (`EXPAND_JS` in `platforms/x.py`). Aussehen, Verfasser, Datum und Zahlen stammen von X.
- **Kennzeichnung:** Solche Belege bekommen `shot_reconstructed`; die Detailseite zeigt „Text ergänzt“. Ein eigener hochgeladener Screenshot hebt die Kennzeichnung auf.
- Ist der Volltext nicht verfügbar, bleibt der Beleg die gekürzte Originalansicht (kein Einsetzen von Teiltexten).
- Vorhandene lange Beiträge: auf der Detailseite „Neu erfassen“.

## 0.7.0 – Personen gestalten, lange Beiträge (13.10.2026)

- **Personen bearbeiten (nur Darstellung):** eigenes Foto (256-px-WebP, ohne Metadaten), Kurzbeschreibung unter dem Namen, Beschreibung. Die archivierten Aussagen behalten Wortlaut, Namen und Original-Profilbild. Beim Zusammenführen wandern Foto und Kurzbeschreibung mit, bearbeitete Personen werden nie automatisch aufgeräumt.
- **Personenübersicht:** Kacheln als Standard, Liste per Umschalter (wird gemerkt, Einstellung „Personen“ im Bereich Archiv).
- **Lange X-Beiträge:** Embed-Backend und oEmbed liefern nur die ersten ~280 Zeichen. Bei Anzeichen dafür (`note_tweet`, Auslassungszeichen, Länge ≥ 270) holt die App den vollen Text über die öffentliche fxtwitter-API und übernimmt ihn nur, wenn er länger ist und genauso anfängt. Klappt das nicht, steht ein Hinweis im Status. Neue Spalte `posts.long_post`.
- **Beleg langer Beiträge:** Das X-Embed kann sie nicht ausklappen („Mehr anzeigen“ ist dort nur ein Link zu x.com, und x.com zeigt ohne Login eine Login-Wand). Der Beleg bleibt deshalb die echte, gekürzte Ansicht; die Detailseite sagt das und bietet den eigenen Screenshot an.

## 0.6.3 – Datum nachgetragen (13.10.2026)

- **Fehlende Daten werden automatisch bestimmt** (`services/dates.py`), in dieser Reihenfolge:
  1. Plattform-API beim Erfassen (wie bisher),
  2. **Beitrags-ID:** X-Snowflake-IDs (ab Nov. 2010) und Bluesky-TIDs enthalten den Zeitpunkt auf die Millisekunde. Läuft beim Start für alle Aussagen ohne Datum, ohne Netz.
  3. **Screenshot:** Texterkennung sucht den Zeitstempel („10:12 vorm. · 4. März 2019“, „Mar 4, 2019“, „09.01.24“ …). Ein im Text erwähntes Datum verliert gegen den Zeitstempel mit Uhrzeit. Läuft einmal im Hintergrund, Fundlose werden nicht bei jedem Start erneut gelesen.
- **Herkunft sichtbar:** In den Angaben steht „aus der Beitrags-ID“, „aus dem Screenshot gelesen“, „von der Plattform“ oder „von Hand eingetragen“.
- **Von Hand korrigieren:** Datum (und optional Uhrzeit, Ortszeit) auf der Detailseite; leeres Feld entfernt das Datum.
- Neue Spalten `posts.date_source`, `posts.date_has_time`; vorhandene Daten werden beim Start als „Plattform“ bzw. bei Uploads als „von Hand, ohne Uhrzeit“ eingetragen.

## 0.6.2 – Ganze Sätze (13.10.2026)

- **Zerhackte Texte:** Die Texterkennung übernahm jeden Zeilenumbruch aus dem Screenshot, im Archiv standen Sätze dann in Bruchstücken untereinander. Jetzt werden die Zeilen eines Absatzes zusammengefügt (`ocr.reflow`): Leerzeilen trennen Absätze, Aufzählungen bleiben, Silbentrennung am Zeilenende wird aufgelöst.
- Beim Start werden alle vorhandenen OCR-Texte einmal so umgebrochen. Von der Plattform geholte und von Hand korrigierte Texte bleiben unberührt.

## 0.6.1 – Feinschliff (13.10.2026)

- **Neuer Name: TrashTwitter** (Slug und Datenordner bleiben).
- **Zitatkarten:** Die Fußzeile brach bei schmalen Karten auf bis zu vier Zeilen um. Jetzt ist sie immer einzeilig: links Datum (in Karten ohne Uhrzeit) und Archiv-Nummer, rechts „Original ↗“. Status und Thread-Hinweis stehen in einer eigenen Zeile darüber, nur wenn es sie gibt. Geprüft in 13 Breiten von 320 bis 1920 px.
- **Threads:** Die automatische Erkennung ist abgeschaltet, sie lag zu oft daneben. Weitere Teile ergänzt du wie bisher per Link (beim Hinzufügen oder auf der Detailseite). Alte Beiträge mit „automatisch“ werden beim Neu-Erfassen nur noch mit ihren manuellen Teilen erfasst. Der Erkennungscode in `platforms/` bleibt für später erhalten.

## 0.6.0 – Quellenarchiv (13.10.2026)

Neue Ausrichtung: aus dem Spaß-Archiv wird ein sachliches Quellenarchiv für öffentliche Aussagen. Neuer Name **Wortlaut** (Slug und Datenordner bleiben).

- **Personen und Accounts:** Jede Aussage hängt an einem Account (feste ID: Bluesky-DID, X-User-ID), jeder Account an einer Person. Handle-, Namens- und Bildwechsel landen im Verlauf statt einen neuen Account zu erzeugen. Accounts, die zuerst nur per Handle bekannt waren, werden aufgewertet, sobald die ID auftaucht.
  - Personenseiten mit allen Accounts, Verlauf und Aussagen. Personen zusammenführen, Accounts umhängen oder abtrennen (steht im Protokoll).
  - Alte Daten werden beim Start automatisch zugeordnet. Profilbilder alter Accounts schlägt der Worker einmalig nach.
- **Profilbilder der Verfasser** werden lokal gesichert (`authors/`, 200-px-WebP, nur von den Bild-Servern der Plattformen). Jede Aussage behält das Bild vom Zeitpunkt der Archivierung.
- **Zitatkarte:** einheitliche Darstellung für X und Bluesky, Wortlaut in Buchschrift. Der Screenshot ist nur noch Beleg auf der Detailseite.
- **Quellenangabe** zum Kopieren und feste **Archiv-Nummer** je Aussage.
- **X-Wortlaut** jetzt exakt aus dem Embed-Backend (`cdn.syndication.twimg.com`): t.co-Links ausgeschrieben, Medien-Links und @Antwort-Präfixe entfernt, lange Tweets vollständig. Texterkennung nur noch Rückfall.
- **Archiv:** sortiert nach dem Datum der Aussage, Zeitraum-Filter ebenso. Ansichten Karten, Liste, Zeitachse (nach Monaten). Filter nach Person.
- **Design:** Papier und Tinte, Buchschrift für Zitate, keine Verläufe/Glow, neues Icon (Anführungszeichen). Neutrale Texte überall.
- **Entfernt:** Reaktionen (Tabelle wird beim Start gelöscht), Favoriten, „Neu für dich“, Zufallsfund, „Heute vor …“, Discomodus.
- 176 Tests (neu: `tests/test_v06.py`).

## 0.5.0 – „Gerettet aus dem Papierkorb“ (12.10.2026)

- **Eigene Screenshots hochladen:** Im Hinzufügen-Sheet gibt es den Reiter „Screenshot“. Bilder auswählen (am iPhone aus den Fotos), hierher ziehen oder mit ⌘V/Strg+V einfügen. Ein eingefügtes Bild öffnet das Sheet von selbst.
  - Mehrere Bilder werden wie ein Thread untereinander geklebt. Gespeichert wird als WebP, ohne Standort- und Kameradaten, und breiter als 1400 px wird verkleinert.
  - Mit Original-Link: Duplikatprüfung über den Link, Autor und Text über die Plattform. Ohne Link: Plattform wählen, Autor und Datum optional, Duplikatprüfung über das Bild selbst.
  - Text: eigener Text oder Texterkennung aus dem Bild.
  - Der Worker nimmt hochgeladene Beiträge nie selbst auf (`shot_source = "upload"`).
- **Beitragsseite:** „Eigenen Screenshot hochladen“ ist bei fehlgeschlagener Aufnahme schon aufgeklappt. „Doch wieder automatisch aufnehmen“ macht das rückgängig.
- Karten zeigen 🖼️ für eigene Screenshots.

## 0.4.0 – „Am laufenden Faden“ (12.10.2026)

- **Mehrfachauswahl:** Im Archiv „Auswählen“ antippen, Karten markieren (alle vier Ansichten), unten Liste wählen oder neu anlegen, „Ablegen“. Die Auswahl übersteht Filterwechsel und „Mehr laden“.
- **Threads:** Selbst-Antworten desselben Kontos werden erkannt und zu einem Bild zusammengeklebt.
  - Bluesky: komplett automatisch, in beide Richtungen (`getPostThread`).
  - X: automatisch rückwärts bis zum Thread-Anfang (Embed-Backend `cdn.syndication.twimg.com`, ohne Login). Spätere Teile kennt X ohne Login nicht – im Dialog von Hand ergänzbar.
  - Der Thread-Anfang wird zum Hauptbeitrag. Text = alle Teile, Badge 🧵 mit Anzahl, Links zu allen Originalen.
  - Schalter im Hinzufügen-Dialog („Threads erkennen“), nachträglich auf der Beitragsseite änderbar.
- **WebP statt PNG** (Qualität 82): gemessen ~80 % kleiner, Schrift unverändert scharf. AVIF wäre ~40 % kleiner, kodiert aber 3× langsamer – auf dem Pi zu teuer. Vorhandene PNGs werden beim ersten Start umgewandelt.
- Teilen/Herunterladen liefert JPG (`?as=jpg`), weil nicht jeder Messenger WebP mag.
- Fix: Das X-Embed zeigte bei Antworten den Vorgänger mit an, und fotografiert wurde der erste (= falsche) Tweet. Jetzt immer `hideThread=true`.

## 0.3.2 – „Keine weißen Ränder mehr“ (12.10.2026)

- Fix: dünne weiße Linie unter manchen X-Screenshots. Ursache: Das Embed ist nicht ganzzahlig hoch, Playwright rundet den Ausschnitt auf und erwischte eine Zeile des (transparenten → weißen) Seitenhintergrunds. Jetzt wird der Seitenhintergrund vor der Aufnahme in der Beitragsfarbe eingefärbt (X und Bluesky).
- Sicherheitsnetz: Nach jeder Aufnahme werden bis zu 4 px einfarbige, kontrastierende Randstreifen abgeschnitten (`services/shots.trim_edges`). Breitere Streifen gelten als Inhalt und bleiben.
- Beim ersten Start nach dem Update werden alle vorhandenen Screenshots einmalig bereinigt und neu vermessen.

## 0.3.1 – „Passt in jede Hosentasche“ (12.10.2026)

- Mobile Darstellung komplett geprüft: alle 35 Seiten/Zustände bei 320, 375, 390, 430, 768, 1024 und 1280 px ohne seitliches Scrollen.
- Fix: Grid-Spalten mit `1fr` wuchsen auf die Breite langer Inhalte (Listenansicht, Einstellungen → Archiv, Benutzer, Protokoll) → überall `minmax(0, 1fr)`.
- Benutzer- und Protokoll-Tabelle werden bis 1100 px zu Karten.
- Auswahlfelder mit mehr als drei Optionen stehen unter dem Text und brechen am Handy in ein Raster um.
- Reaktions-Auswahl hängt an der Karte und ragt nicht mehr über den Rand.
- Archiv-Kopf am Handy kompakter (Zufallsfund und Filter als Symbol).
- Suchgenerator: schwebende Leiste mit dem aktuellen Befehl am Handy, X/Bluesky-Schalter füllt die Breite.
- Beitragsseite: Werkzeugleiste passt in eine Zeile, Vor/Zurück als ↑/↓.

## 0.3.0 – „Licht aus, Tonne an“ (11.10.2026)

- Screenshots werden dunkel aufgenommen (Option `screenshot_theme`, Standard `dark`). Die eigenen Rahmen und Rundungen der Plattformen werden entfernt, die Ecken rundet die App einheitlich.
- Archiv in vier Darstellungen, umschaltbar und pro Person gemerkt: Raster (gleich große Kacheln), Mosaik, Timeline (nach Tagen, „Anna hat archiviert“), Liste
- Breite Screenshots stehen im Raster eingepasst auf ihrer eigenen Hintergrundfarbe (Format und Farbe werden beim Aufnehmen gemessen)
- Profil: Anzeigename und Profilbild (zugeschnitten, 256 px WebP, ohne Metadaten)
- Passwörter ab 5 Zeichen, gewürfelte Passwörter haben 10 Zeichen
- System-Seite: „Alle Screenshots neu aufnehmen“
- Fix: Nach dem Neuaufnehmen zeigte der Browser einen Tag lang das alte Bild (Cache) – Bild-URLs tragen jetzt eine Version

## 0.2.0 – „Frisch aus der Tonne“ (11.10.2026)

- Neues Design passend zum App-Icon: Nachtblau, Hell/Dunkel/System, vier Akzentfarben, kompakte Ansicht
- Handy: Tab-Leiste unten, Hinzufügen als Sheet, Homescreen-Icon für iPhone und Android (PWA)
- Einstellungen: Konto, Darstellung, Archiv, Suchgenerator, Teilen & Kürzel, Tags verwalten. Für Admins: Benutzer, System & Sicherung, Protokoll
- Neu: Reaktionen, „Neu für dich“, Zufallsfund, „Heute vor X Jahren“
- Neu: Live-Prüfung beim Einfügen, Teilen-Ziel (/teilen), Screenshot teilen und speichern, Tastenkürzel
- Discomodus nur noch als Easter Egg (5× auf die Versionsnummer)
- Fix: „Heute vor X Jahren“ rechnet in Ortszeit statt UTC

## 0.1.0 – „Die Tonne ist aufgestellt“ (10.10.2026)

- Erste Version.
- Archiv für X und Bluesky mit Screenshot im Hintergrund, OCR bzw. API-Text, Tags, Listen und Volltextsuche.
- Suchbefehl-Generator für X und Bluesky mit Vorlagen und gespeicherten Suchen.
- Benutzerverwaltung mit Rollen, Login-Sperre und Protokoll, dazu die Testfunktion Passwort-Anzeige.
- Discomodus.
