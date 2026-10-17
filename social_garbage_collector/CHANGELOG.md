# Changelog

## 0.18.0 – Netzwerk (17.10.2026)

- **Netzwerk** (`/netzwerk`, `routers/graph.py`, `static/graph.js`): Kraft-Graph auf Canvas mit force-graph 1.51.4 (MIT, lokal unter `static/vendor/`). Der Server liefert Knoten und Kanten auf Posting-Ebene (`/netzwerk/daten`: Posting–Person, Posting–Tag, Posting–Liste, Recherche–Person/Posting, Tag–Oberbegriff); der Browser fasst zusammen zu Person – Tag (Gewicht = Postings) und Liste – Person. Personen sind nie direkt verbunden.
- Darstellung: dunkle Bühne, Personen als Profilbild (Größe nach Postings), Tags türkis, Oberbegriffe als Ring, Listen als Quadrat, Recherche als Raute nach Art, Postings als Punkte (rosa mit Herz). Hover hebt Nachbarn hervor (Partikel auf den Linien), Klick öffnet ein Detailfeld mit Nachbarn; „Nur Umgebung“ (2 Schritte), Suche, Filter je Art mit Zählern, Zeitraum, Postings einblenden, Vollbild, Zoom-Knöpfe, `?fokus=p1` als Direktlink.
- Layout: Schwerkraft nach Seitenverhältnis der Bühne, Abstandskraft gegen Überlappen, vorberechnet. Scrollen bewegt die Seite, Zoomen nur mit Pinch, ⌘/Strg + Rad oder im Vollbild. Am Handy liegen die Leisten neben statt über dem Netz.
- **Themen-Netz** auf jeder Personenseite (`?person=`): eigene Postings, deren Tags, Listen und Recherche plus die 12 Personen mit den meisten gemeinsamen Tags – nur über gemeinsame Themen.
- **Entdeckungen** unter dem Netz: Brückenthemen, themenbreit, ohne Recherche, noch einzuordnen.

## 0.17.1 – Senden-Knopf (17.10.2026)

- Kommentarfeld: Die Textarea war inline gesetzt, ihre Unterlänge machte die Box ein paar Pixel höher – der absolut positionierte Senden-Pfeil rutschte dadurch über den unteren Rand. Jetzt `display: block`, Pfeil 6 px vom Rand, ohne Browser-Innenabstand.

## 0.17.0 – Kommentare & Benachrichtigungen (17.10.2026)

- **Kommentare** (`routers/comments.py`, Tabelle `comments`, Zähler `posts.comment_count`): flach unter jedem Posting, mit Namen und relativer Zeit, Links klickbar (`richtext`). Schreiben/Bearbeiten/Löschen per htmx ohne Seitenwechsel; Bearbeiten nur eigene, Löschen eigene oder als Admin. Feld wächst mit, ⌘/Strg+Enter sendet. Am Handy direkt unter dem Posting.
- **Benachrichtigungen** (Tabelle `notifications`): Empfänger sind, wer das Posting archiviert hat, und alle, die dort schon kommentiert haben (nie man selbst). Glocke in der Kopfzeile mit Zähler, Seite `/benachrichtigungen`, Antippen springt zum Kommentar; Öffnen des Postings markiert dessen Benachrichtigungen als gelesen, „Alle als gelesen markieren“.
- **Markierung** in Raster, Liste und Zeitachse: Sprechblase mit Anzahl, Link direkt zu `#kommentare`.

## 0.16.0 – Herzstücke, aufgeräumte Threads, neue Handy-Leiste (17.10.2026)

- **Herzen:** Tabelle `post_hearts` (ein Herz je Mitglied und Posting), Zähler `posts.hearts` (beim Start mit der Tabelle abgeglichen). Herz-Knopf in Raster (unten rechts, bei Herzen immer sichtbar), Liste, Zeitachse und Detailseite (`POST /posts/{id}/herz`, htmx). Automatische Liste **Herzstücke** (`/lists/herzstuecke`, meiste Herzen zuerst) als erste Kachel unter Listen; Sortierung „Meiste Herzen“ im Idiotarium.
- **Thread-Belege:** `ParsedPost.thread_index`; ab Teil 2 entfernt `CLEAN_JS` alles vor dem Wortlaut (Profilbild, Name, Handle, Plattform-Logo, „Antwort an …“) und die Zeitzeile. „Folgen“/„Follow“ fällt in allen Teilen weg, bei Bluesky zusätzlich die Zähler (Likes, Reposts, Antworten). Bestehende Thread-Postings werden beim ersten Start einmal neu aufgenommen (`PRAGMA user_version` 8).
- **Ansichten:** Karten-Ansicht im Idiotarium entfernt, Raster ist Standard (gespeicherte „Karten“ fallen auf Raster zurück). Listen: Übersicht Kacheln/Zeilen (`lists_overview`), jede Liste Raster/Liste/Zeitachse (`list_view`), jeweils gemerkt.
- **Handy-Leiste:** Archiv · Personen · Recherche · Listen · Galerie, „Hinzufügen“ als schwebender Knopf (FAB) rechts unten; „Mehr“-Sheet entfernt, Suchgenerator im Profil-Menü. Detail-Aktionen am Handy in zwei Reihen.

## 0.15.1 – Keine Fehler 500 mehr, Feinschliff (17.10.2026)

- **Verbindungs-Leck behoben (Hauptursache der 500er):** `get_db()` schließt die Sitzung bei einer Exception *vor* dem Fehler-Handler. Der rendert die Fehlerseite und fragt dabei erneut die DB → neue Verbindung, die nie zurückkam. Nach 15 Fehlerseiten (404/403) war der Pool (5 + 10) leer, jede weitere Anfrage wartete 30 s und endete in `QueuePool limit … reached` → 500. Jetzt schließt die Middleware die Sitzung am Ende jeder Anfrage, die Fehler-Handler ebenfalls (`_close_request_db`). Test: 80 Fehlerseiten, danach 0 ausgeliehene Verbindungen.
- **Keine Schreibsperre während langer Schritte:** Der Worker hielt eine SQLite-Schreib-Transaktion offen, während er Profilbilder/Medien lud und Screenshots machte (oft > 30 s) – Speichern im Web lief dann in `database is locked`. Jetzt `commit()` vor Medien, Screenshots und Bluesky-Suche; Profilbild wird vor dem Account-Abgleich geladen; `refresh_accounts` schreibt erst nach dem Netzabruf. Massenimport: Bluesky-Handles werden vorab (parallel, 6 gleichzeitig) aufgelöst, gespeichert wird danach in einem Rutsch.
- **Fehlerseite** für unerwartete Fehler (500) bzw. belegte Datenbank (503) mit „Noch einmal versuchen“; bei htmx-Anfragen ein Toast. Der volle Fehler steht im Protokoll.
- Geprüft: ~10.000 GET-Aufrufe (alle Seiten, echte/unsinnige IDs und Parameter) und alle Formulare mit kaputten Eingaben – kein 5xx.
- **Design:** Platzhalter (Skeleton) und „wird archiviert“ für Postings in Arbeit; Medienraster der Detailseite nach Anzahl (2/3/4+); Personenkacheln mit Zahlen und Handles untereinander, doppelter Handle ausgeblendet; Einstellungen-Navigation kompakter, doppelter Suchgenerator entfernt; Galerie-Sortierfeld am Handy ohne gekachelten Pfeil; „Idiotarium“ auch in Zurück-Links, Personenseite, Import und Tastenkürzeln.

## 0.15.0 – Recherche-Arbeitsplatz, Tags im Griff, neues Design (16.10.2026)

- **Recherche-Arbeitsplatz** (`/recherche`): links alle Einträge (neueste zuerst oder „Nach Person“ gruppiert, Filter Art/Person, Suche auch in Personennamen), rechts der gewählte Eintrag. Lesen, Bearbeiten und Neu-Anlegen laufen rechts per htmx (`HX-Target: rs-pane`), danach lädt die Liste neu (`HX-Trigger: research-changed`), die Adresse merkt sich den Eintrag (`?id=`). Am Handy (< 1000 px) bleiben es eigene Seiten.
- **Recherche-Formular vereinfacht:** Text zuerst; Titel optional (sonst erster Satz, `auto_title`). Personen und Postings per Suchfeld mit Treffern (`/recherche/suche/personen`, `/recherche/suche/postings` – Wortlaut, Verfasser oder Archiv-Nr.), Quellen einklappbar. Archiv-Nummern als Text gehen weiterhin (`posts`), neu `post_ids`.
- **Tags im Idiotarium:** Die Tag-Zeile ist weg. Knopf „Tags“ in der Suchleiste öffnet ein Fenster mit Suche, „Häufig“ und allen Tags nach Oberbegriffen; Tags und Filter öffnen sich abwechselnd. `#tag` im Suchfeld schlägt vorhandene Tags vor (Enter/Leertaste übernimmt), `#wort` in der Adresse wirkt als Tag-Filter (`split_hashtags`). Aktive Tags stehen als Chips mit × über den Ergebnissen; × entfernt den Tag auch aus der Suche.
- **Redesign:** neues Token-System (Farben, Abstände, Radien, Schatten), einheitlicher Seitenkopf (`.page-header`) auf allen Hauptseiten, Navigation als Pillen mit dunklem Aktiv-Zustand, Kopfzeile mit Kante beim Scrollen, ruhigere Karten (Schatten statt Rand, Status als Punkt-Pillen), einheitliche Knöpfe/Eingabefelder (42 px), Sheets mit 24 px Radius, Anmelden als Karte, Listen-Kopf mit Umbenennen/Beschreibung inline, Hinzufügen-Reiter am Handy (Symbol über Text), Seitenhintergrund mit zwei leichten Farbverläufen. Personen-Suche im selben Stil wie das Idiotarium.

## 0.14.0 – Recherche, Tags mit Oberbegriffen, Threads (16.10.2026)

- **Recherche** (`/recherche`, `routers/research.py`, Tabellen `research_notes`, `research_persons`, `research_posts`): eigene Fakten und Hintergründe des Teams. Art (Widerspruch, Fakt, Hintergrund), Titel, Text (Links klickbar), Quellen (eine pro Zeile), Personen (mind. eine) und Postings per Archiv-Nummer – deren Personen werden automatisch zugeordnet. Alle lesen und bearbeiten, löschen nur Anlegende oder Admins. Erscheint auf der Personenseite und am Posting („Recherche dazu“), Aktion „Recherche“ in der Aktionsleiste. Beim Zusammenführen von Personen wandern die Einträge mit; Personen mit Recherche werden nicht automatisch aufgeräumt.
- **Tags mit zwei Ebenen** (`tags.parent_id`, `tags.is_group`, `services/tags.py`): Oberbegriffe fassen Tags zusammen, Filtern nach dem Oberbegriff findet alle Unter-Tags mit. Oberbegriffe bleiben auch ohne eigene Postings bestehen.
  - **Tag-Auswahl** statt Freitext: Chips + Suche; Vorschläge in der Reihenfolge Anfang → enthalten → ähnlich geschrieben („Meintest du …?“, difflib ≥ 0,72). Enter übernimmt nur einen passenden vorhandenen Tag, ein neuer Tag braucht den Klick auf „+ Neuen Tag anlegen“.
  - **Idiotarium:** Tag-Leiste mit den 12 häufigsten (Oberbegriffe hervorgehoben) und „Alle Tags“ als durchsuchbare Übersicht nach Oberbegriffen.
  - **Tags organisieren** (vorher „Tags verwalten“): Oberbegriff anlegen, je Tag einordnen/umbenennen/löschen, Mehrfachauswahl zum Einordnen, Zusammenführen, Löschen; Oberbegriff auflösen.
- **Threads:** eigener Reiter „Thread“ beim Hinzufügen – Links der Reihe nach, Felder wachsen mit, mehrere eingefügte Links werden verteilt (`POST /posts/thread`). Im Link-Reiter: „Als Thread hinzufügen →“ (nimmt den Link mit). Detailseite: „Thread ergänzen“ und „Wortlaut korrigieren“ direkt unter dem Text.
- **Hilfe & Anleitung:** neuer Abschnitt „Grundlagen“ zu allen Funktionen, Hilfe-Knopf (?) immer oben rechts, am Handy zusätzlich unter „Mehr“.
- **Neu-Fenster:** Bei jeder x.x-Version sieht jedes Mitglied einmal die wichtigsten Neuerungen (`highlights` in `changelog.py`, `users.release_seen`, `POST /neuigkeiten/gesehen`). x.x.x-Versionen zeigen nichts.
- **Benennung:** Das Archiv heißt „Das Idiotarium“; X heißt überall „X (Twitter)“ (auch in der Quellenangabe).
- **Navigation:** „Recherche“ in der Kopfzeile; am Handy Tab-Leiste Archiv · Personen · + · Recherche · Mehr (Listen, Galerie, Suchgenerator, Tags, Hilfe, Ideen).
- **Design:** zweiter, warmer Akzent (Widerspruch, Neu-Badge, Anführungszeichen am Idiotarium), runderere Karten (18 px), Primärknöpfe mit leichtem Verlauf, sichtbare Fokusringe, Wortmarke mit Farbverlauf.

## 0.13.1 – Belege ohne Bedienleiste (16.10.2026)

- X-Screenshots (Embed und x.com direkt): Vor der Aufnahme entfernt `TRIM_JS` alles, was im Beitrag nach der `<time>` kommt – Aktionsleiste (Herz, Antworten, Link kopieren), „n Antworten lesen“, „Auf X weiterlesen“, Info-Symbol. Gearbeitet wird von der Zeit aus nach oben bis zum `<article>`, nicht über X’ Klassennamen. Unter der Zeitzeile bleiben 10 px Luft. Gilt für jeden Thread-Teil, der Sammel-Beleg wirkt dadurch ruhiger.
- Alte Belege ändern sich erst bei „Neu erfassen“ bzw. Einstellungen → System → „Alle Screenshots neu aufnehmen“.

## 0.13.0 – Videos in der Galerie (15.10.2026)

- **Videos hochladen:** MP4/M4V, MOV und WebM, erkannt am Dateikopf (nicht an der Endung). Gespeichert wird das Original, gestreamt ohne die Datei im Speicher zu halten; Grenze je Video = Add-on-Option `media_max_mb` (Standard 150 MB). Doppelte erkennt die App über SHA-256.
- **Vorschaubild:** Der Browser zeichnet beim Hochladen ein Standbild (bei ca. 1 s) und misst die Länge (app.js, `posters` + `video_info`). Kann er das Format nicht abspielen, versucht es der Server mit ffmpeg (falls vorhanden – im Add-on-Abbild nicht enthalten), sonst neutrale 16:9-Fläche.
- **Anzeige:** Play-Symbol mit Länge im Raster, Player in der Vollansicht (Range-Anfragen → spulen), Herunterladen liefert das Original. Blättern und Schließen halten das Video an.
- Upload mit Fortschrittsbalken; danach Sortierung „Zuletzt hinzugefügt“. Knopf heißt „Bilder & Videos hinzufügen“.
- Datenbank: `gallery_images.kind`, `poster_path`, `mime`, `bytes`, `duration`.

## 0.12.0 – Screenshots verstehen, aufgeräumte Oberfläche (15.10.2026)

- **Screenshots ohne Link** (`services/screenshot.py`, `ocr.ocr_layout`): Tesseract liefert Zeilen mit Positionen. Daraus liest die App
  - den Kopf: erstes `@handle` oben, Anzeigename in derselben Spalte darüber (Profilbild-Müll links davon fällt weg),
  - die Fußzeile: letzte Zeile mit Datum (auch „22 Jan. 25“ mit zweistelligem Jahr), Aufrufe/Reposts/Knöpfe werden abgeschnitten, ebenso „Mehr anzeigen“ und als ®/© gelesene Emojis,
  - die Plattform: Handle mit Punkt = Bluesky, sonst Hinweise wie „Mal angezeigt“, „Uhrzeit · Datum“ (X) oder „Datum um Uhrzeit“ (Bluesky),
  - das Profilbild: Ausschnitt links neben Name/Handle (nur wenn dort ein kompakter Bildbereich ist).
  - Hochladen ohne Plattform ist jetzt möglich („Automatisch“, Spalte `posts.platform_auto`). Von Hand Eingetragenes (Handle, Text, Datum, gewählte Plattform) gewinnt immer.
  - **Bluesky:** Profil per `app.bsky.actor.getProfile` (DID, Name, Profilbild), dann bis zu 500 Beiträge per `getAuthorFeed` durchsuchen und den Text ähnlich vergleichen (≥ 80 %, kurze Texte ≥ 93 %). Gefunden → Posting bekommt Link, ID, Duplikat-Schlüssel und danach die API-Daten (exakter Text, Datum, Medien).
  - Alte Uploads ohne Link werden einmal im Hintergrund neu ausgewertet (`posts.shot_parsed`).
  - Ist das Original eines Upload-Postings mit Link gelöscht, liest die App jetzt ebenfalls Kopf/Text/Datum aus dem Bild.
- **Archiv-Leiste:** Suche, Sortierung (mit Symbol, am Handy nur Symbol) und Filter in einer Fläche. Plattform, Verfasser, Zeitraum (eine Zeile von–bis), Liste, Archiviert von, Status im Filter – Standard zu. Aktive Filter als Chips mit × (entfernt genau diesen Filter). Auswahl- und Ansichts-Umschalter als Symbole. Standard-Sortierung jetzt „Zuletzt archiviert“ (Einstellung `sort`). Stift am Ende der Tag-Leiste → Tags verwalten.
- **Raster:** volle Texthöhe statt Ausblenden (Grenze 40 Zeilen), Mauerwerk per CSS-Grid mit 2-px-Zeilen und `grid-row-end: span n` (app.js, ResizeObserver), Reihenfolge bleibt zeilenweise. Ohne JS: Zeilen so hoch wie die längste Kachel.
- **Detailseite:** eine Karte mit Wortlaut, Medien (Download-Knopf auf dem Bild), Datum/Nr., Anmerkung, Tags, Listen und einer Aktionsleiste (Original, Text, Zitieren, Listen, Tags, Wortlaut). Beleg rechts, „Angaben & Quellenangabe“ und „Beleg ersetzen & Thread“ eingeklappt. Sprungmarken (z. B. `#datum`) klappen den Bereich auf.
- **Tags umbenennen:** „Tags verwalten“ im Menü und über den Stift in der Tag-Leiste. Umbenennen inline (Name ist gleich markiert), Suche ab 9 Tags, Rückmeldung „heißt jetzt“ bzw. „zusammengeführt“.
- **Galerie:** Sortierung Zufällig (Standard, „Neu mischen“), Zuletzt hinzugefügt, Neueste Aufnahmen (EXIF-Aufnahmedatum, vor dem Entfernen der Metadaten gelesen – Spalte `gallery_images.taken_at`; ältere Bilder ohne Datum zählen mit dem Hinzufüge-Datum), Zuerst hinzugefügt. Darstellung Mosaik/Quadrate und Größe (5 Stufen) per Regler, im Browser gemerkt.
- **Listen:** „Liste hinzufügen“ öffnet ein Sheet statt eines Felds im Seitenkopf.
- **Handy:** Die Tab-Leiste verschwindet, solange ein Textfeld aktiv ist (Android schob sie über die Tastatur, iOS ließ sie danach manchmal mitten im Bild stehen); Eingabefelder mit 16 px, damit iOS nicht hineinzoomt. Tablet (761–1020 px): „hinzufügen“ nur als Plus, damit die Kopfzeile passt.

## 0.11.0 – Facelift, Teilen vom Handy, Ideen (14.10.2026)

- **Facelift:** wärmerer Hintergrund mit leichtem Verlauf, Karten mit 16 px Rundung, leisen Schatten und Anheben beim Drüberfahren, Plattform als kleines Logo, Navigation als Pillen in einer Spur, Suche/Plattform/Sortierung/Filter als eine gemeinsame Leiste, Überschriften mit Eyebrow-Zeile, runderere Knöpfe und Sheets.
- **Medien in der Übersicht:** Karten und Zeitachse zeigen bis zu 4 Bilder/Videos/GIFs als Raster (Video mit Play-Symbol, „+n“ bei mehr), das Raster das erste Bild. Dafür gibt es Vorschaubilder (`<datei>.thumb.webp`, max. 720 px): für Bilder selbst erzeugt, für Videos aus dem Vorschaubild der Plattform. Vorhandene Bilder bekommen sie beim Start (`media.backfill_thumbs`), Spalte `post_media.thumb_path`.
- **Teilen vom Handy:** persönlicher Schlüssel (Einstellungen → Teilen & Kürzel oder Hilfe; nur der SHA-256-Hash wird gespeichert, Klartext einmalig angezeigt) und `POST /api/teilen` mit `Authorization: Bearer …` – nimmt `url`/`text` als Formular oder JSON, sucht den ersten X-/Bluesky-Link und antwortet mit einer Zeile Text („Archiviert: @… (Nr. …)“ / „Schon im Archiv“). Kein CSRF nötig, weil Browser den Header nie selbst senden.
- **Hilfe & FAQ** (`/hilfe`): Kurzbefehl für iPhone/iPad, Android über installierte Web-App (HTTPS) oder „HTTP Shortcuts“, Lesezeichen für den Computer, Hinweis zur direkten Adresse (Port 8780 statt HA-Seitenleiste), häufige Fragen.
- **Ideen** (`/ideen`): Wünsche für neue Funktionen aufschreiben, „Will ich auch“-Stimmen, Filter Offen/Umgesetzt/Alle. Admins setzen den Stand (Neu, Geplant, Umgesetzt, Nicht geplant) und können antworten. Tabellen `feature_ideas`, `idea_votes`.
- **Eindeutige Knöpfe:** „Posting hinzufügen“, „Bilder hinzufügen“, „Screenshot hinzufügen“, „Alle Postings hinzufügen“.

## 0.10.1 – Notfall-Zugang (14.10.2026)

- **Kein Admin kommt mehr rein?** Add-on-Optionen: `reset_password: true`, `admin_username` = Konto, `admin_password` = neues Passwort (mind. 5 Zeichen), Add-on neu starten. Das Konto bekommt das Passwort, wird entsperrt, aktiviert und Admin (gibt es den Namen nicht, wird er angelegt). Beim ersten Login muss ein eigenes Passwort vergeben werden. Danach `reset_password` ausschalten und `admin_password` leeren.
- Beim Start steht im Protokoll, welche Admin-Konten es gibt.

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
