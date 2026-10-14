# TrashTwitter

Quellenarchiv für öffentliche Postingn von **X** und **Bluesky**, als Home-Assistant-Add-on für den Raspberry Pi 5.
Wortlaut, Verfasser, Datum und ein Beleg-Screenshot werden dauerhaft gesichert, nach Personen geordnet und durchsuchbar gemacht. TrashTwitter ist kein soziales Netzwerk: keine Likes, kein Feed, keine Reichweite. Es geht um Nachvollziehbarkeit, Quellenbezug und Einordnung.

> Bis Version 0.5 hieß die App **SocialGarbageCollector** und war ein Spaß-Archiv, in 0.6.0 kurz „Wortlaut“. Der Add-on-Slug (`social_garbage_collector`) und der Datenordner (`/share/SocialGarbageCollector`) behalten den alten Namen, damit bestehende Installationen ihre Daten und Einstellungen behalten.

---

## Inhalt

1. [Funktionen](#funktionen)
2. [Installation auf dem Raspberry Pi 5](#installation-auf-dem-raspberry-pi-5)
3. [Erster Start und Admin-Konto](#erster-start-und-admin-konto)
4. [Optionen](#optionen)
5. [Backup](#backup)
6. [Suchbefehl-Generator: Hinweise zu den Operatoren](#suchbefehl-generator-hinweise-zu-den-operatoren)
7. [Architektur und Dateistruktur](#architektur-und-dateistruktur)
8. [Entwicklung und Tests](#entwicklung-und-tests)
9. [Bekannte Grenzen](#bekannte-grenzen)

---

## Funktionen

| Bereich | Was es macht |
|---|---|
| Posting archivieren | Plus-Knopf, Taste `n` oder Teilen aus anderen Apps öffnet ein Sheet. Beim Einfügen prüft die App live Plattform, Verfasser und Duplikate. Unterstützt: X (x.com, twitter.com) und Bluesky (bsky.app, auch `at://`). |
| Wortlaut | Wörtlich von der Plattform: Bluesky über die öffentliche API, X über das Embed-Backend (`cdn.syndication.twimg.com`), mit ausgeschriebenen Links und ohne vorangestellte @Antwort-Namen. Texterkennung (Tesseract) nur als Rückfall. Korrekturen sind möglich und werden als „manuell“ markiert. |
| Personen gestalten | Eigenes Foto, Kurzbeschreibung und Beschreibung je Person – nur Darstellung, die Postingn bleiben original. Übersicht als Kacheln oder Liste. |
| Personen & Accounts | Jedes Posting hängt an einem Account, jeder Account an einer Person. Accounts werden über ihre **feste ID** erkannt (Bluesky-DID, X-User-ID). Ändert jemand Handle, Anzeigename oder Profilbild, bleibt es derselbe Account; die Änderung steht im Verlauf. Mehrere Accounts eines Menschen führst du auf der Personenseite zusammen, Zuordnungen lassen sich jederzeit ändern oder trennen. |
| Profilbilder | Die Profilbilder der Verfasser werden lokal gesichert (200-px-WebP, gleiche Bilder nur einmal). Jedes Posting zeigt das Bild vom Zeitpunkt der Archivierung. |
| Zitatkarte | Jedes Posting sieht gleich aus, egal ob X oder Bluesky: Verfasser, Wortlaut in einer Buchschrift, Datum, Archiv-Nummer, Link zum Original. Der Plattform-Screenshot ist nur noch **Beleg** auf der Detailseite. |
| Lange X-Beiträge | Über 280 Zeichen liefert X nur den Anfang. Die App lädt den vollen Wortlaut über die öffentliche fxtwitter-API nach (nur in diesem Fall). Der Beleg-Screenshot bekommt den vollen Text eingesetzt und ist dann als „Text ergänzt“ gekennzeichnet. |
| Datum | Kommt von der Plattform. Fehlt es, liest die App es aus der Beitrags-ID (X und Bluesky haben den Zeitpunkt darin, sekundengenau) oder per Texterkennung aus dem Screenshot. Die Herkunft steht in den Angaben, korrigieren geht von Hand. |
| Quellenangabe | Zitierfertig zum Kopieren, z. B. *Maria Müller (@mmueller): „…“ X, 04.03.2019, 10:12. https://x.com/… – archiviert am 13.10.2026 in TrashTwitter, Archiv-Nr. 000001.* Die Archiv-Nummer ändert sich nie. |
| Beleg-Screenshot | Läuft im Hintergrund mit Playwright/Chromium und erfasst nur den Beitrag. Threads: weitere Teile per Link ergänzen (beim Hinzufügen oder später), sie werden zu einem Beleg zusammengesetzt. Die automatische Thread-Erkennung ist seit 0.6.1 abgeschaltet. Eigene Screenshots (z. B. von gelöschten Beiträgen) lassen sich hochladen, ziehen oder mit ⌘V einfügen. |
| Archiv | Volltextsuche (FTS5), Plattform, Verfasser, Person, Tags, Liste, Zeitraum des Postings, archiviert von, Status. Sortiert standardmäßig nach dem **Datum des Postings**. |
| Darstellungen | **Karten** (Zitate mit allen Angaben), **Raster** (gleich große Kacheln, nur Name, Text, Datum), **Liste** (eine Zeile pro Posting), **Zeitachse** (nach Monaten, in voller Länge). Wird pro Person gemerkt. Tags oben antippen zum Filtern. |
| Medien | Bilder, GIFs und Videos aus Postings werden mitgesichert (X: MP4/Originalbild, Bluesky: Originaldatei vom Server des Accounts). Grenze je Datei über `media_max_mb`, abschaltbar mit `save_media`. |
| Schnell löschen | Mülleimer beim Drüberfahren und „Löschen“ in der Mehrfachauswahl, immer mit Rückfrage. |
| Massenimport | Reiter „Viele Links“: bis zu 500 Links von X und Bluesky auf einmal, auch mitten in Text. Doppelte, schon archivierte und schon als Thread-Teil erfasste Beiträge werden übersprungen. Fortschrittsseite mit Zusammenfassung, frühere Importe unter `/import`. |
| Galerie | Eigene Bilder hochladen (auch ⌘V, bis 40 auf einmal) und selbst angelegten Kategorien zuordnen. Raster im Blocksatz ohne weitere Infos, Filter nach Kategorien (mehrere kombinierbar), Vollbild mit Blättern, Wischen und Infoleiste auf Wunsch. Bilder werden verkleinert, ohne Standortdaten gespeichert, Duplikate erkannt. |
| Mehrfachauswahl | Postingn markieren und gesammelt in eine Liste legen. |
| Listen | Gemeinsame Sammlungen zu einem Thema, mit Beschreibung, für alle bearbeitbar. Ablegen über ein Auswahlfenster: antippen, suchen, neue Liste direkt anlegen – einzeln oder per Mehrfachauswahl. |
| Suchgenerator | Baut Suchbefehle für X und Bluesky, um Postingn auf den Plattformen selbst zu finden. |
| Teilen | Android: als App installieren, dann im Teilen-Menü. iPhone: Kurzbefehl „Archivieren“. Computer: Lesezeichen. |
| Benutzer | Rollen Admin und Mitglied. Jede:r ändert das eigene Passwort selbst (Einstellungen → Konto), niemand kann Passwörter einsehen. Konten legt nur der Admin an. Admin-Funktionen sind für Mitglieder unsichtbar und antworten mit 404. Zusammenführungen von Personen stehen im Protokoll. |

Bewusst **nicht** (mehr) enthalten: Reaktionen, Favoriten, „Neu für dich“, Zufallsfunde, Easter Eggs. Die Mitglieder interagieren nicht miteinander, sie dokumentieren gemeinsam.

### Design

Sachlich: Papier und Tinte, eine Akzentfarbe (Tinte, Blau, Grün, Bordeaux), keine Verläufe und kein Glow. Zitate stehen in einer Buchschrift (Iowan Old Style auf Apple-Geräten, sonst Georgia), die Bedienung in der Systemschrift. Hell, Dunkel und System, zwei Dichten, reduzierte Bewegung, alles pro Person.

Am Handy gibt es eine Tab-Leiste (Archiv, Personen, +, Listen, Mehr) und Sheets von unten. Auf der Detailseite stehen dort Posting, Quellenangabe und Beleg ganz oben.

Das Icon (typografisches Anführungszeichen auf Tinte) erzeugt `branding/icons_erzeugen.py` in allen Größen.

### Aufs iPhone holen

In Safari öffnen, dann **Teilen → „Zum Home-Bildschirm“**. TrashTwitter startet danach im Vollbild wie eine App.

**Tastenkürzel:** `n` archivieren · `/` suchen · `←`/`→` blättern · `g a` zum Archiv · `?` Übersicht

> **Hinweis HTTPS:** „Als App installieren“ samt Teilen-Ziel (Android), „Screenshot teilen“ und „Aus Zwischenablage einfügen“ verlangen eine sichere Verbindung. Über `http://homeassistant.local:8780` fallen sie auf Kopieren bzw. Herunterladen zurück. Mit einem HTTPS-Reverse-Proxy (oder über HA-Ingress mit HTTPS) gehen sie vollständig.

---

## Installation auf dem Raspberry Pi 5

Voraussetzung: Home Assistant OS auf dem Pi 5 (aarch64).

### Variante A: lokales Add-on (empfohlen zum Start)

1. **Zugang zum Ordner `/addons` verschaffen**, z. B. über das Add-on **Samba share** (Freigabe `addons`) oder **Advanced SSH & Web Terminal**.
2. Den Ordner **`social_garbage_collector/`** aus diesem Projekt komplett nach `/addons/` kopieren:
   ```
   /addons/social_garbage_collector/
   ├── config.yaml
   ├── Dockerfile
   ├── run.sh
   ├── requirements.txt
   ├── icon.png, logo.png, DOCS.md, CHANGELOG.md
   ├── app/
   └── tests/
   ```
3. In Home Assistant: **Einstellungen → Add-ons → Add-on-Store**, oben rechts **⋮ → Nach Updates suchen**.
4. Unter **Lokale Add-ons** erscheint **TrashTwitter**. Öffnen und **Installieren** klicken.
   Der Pi baut das Image selbst. Das dauert beim ersten Mal **10–20 Minuten**, weil Chromium und Tesseract dazukommen.
5. Im Reiter **Konfiguration** die Optionen prüfen (siehe unten) und **Starten** klicken.
6. **In der Seitenleiste anzeigen** einschalten. Du erreichst die App dann über Ingress im HA-Menü.

**Updates:** neuen Code nach `/addons/social_garbage_collector/` kopieren, `version` in `config.yaml` (und `VERSION` in `app/__init__.py`) erhöhen, dann im Add-on-Store **⋮ → Nach Updates suchen → Aktualisieren** klicken. Die Daten unter `/share` fasst ein Update nicht an.

### Variante B: als GitHub-Repository

Das Repository liegt öffentlich unter **https://github.com/rawwry/trashtwitter-homeassistant**. In HA: **Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories** → diese URL eintragen → **TrashTwitter** installieren. Neue Versionen erscheinen danach per Klick auf „Aktualisieren“ (HA baut das Image auf dem Pi selbst).

> **Umstieg von Variante A:** Für Home Assistant ist das ein *anderes* Add-on als das lokale. Die Add-on-Einstellungen (Optionen, „In der Seitenleiste anzeigen“) musst du neu setzen. Deine Daten bleiben erhalten, weil beide denselben Ordner `/share/SocialGarbageCollector` nutzen. Das lokale Add-on vorher stoppen und danach deinstallieren – nicht beide gleichzeitig laufen lassen (gleicher Port 8780, gleiche Datenbank).

### Zugriff für die Freunde

Deine Freunde haben keinen HA-Zugang. Deshalb öffnet das Add-on zusätzlich den **Port 8780**:

```
http://homeassistant.local:8780
```

Für Zugriff von unterwegs nimm einen Reverse-Proxy mit HTTPS (z. B. Nginx Proxy Manager oder Cloudflare Tunnel) und setz dann `cookie_secure: true`. Ohne HTTPS gehen Passwörter im Klartext übers Netz, also den Port **nicht** direkt ins Internet freigeben.

---

## Erster Start und Admin-Konto

Es gibt **kein eingebautes Standardpasswort**. Zwei Wege:

- **Über die Option:** `admin_username` und `admin_password` setzen und starten. Der Admin wird angelegt und muss das Passwort beim ersten Login ändern, weil es sonst im Klartext in den Add-on-Optionen stehen bleibt. Lösch die Option danach wieder. Sie wird nur beim allerersten Start gelesen.
- **Geführte Ersteinrichtung:** Option leer lassen und starten. Im **Protokoll** des Add-ons steht dann ein **Einrichtungscode**. Die Oberfläche öffnen, Code eingeben, Admin anlegen. Ohne den Code kann sich niemand aus dem Netz zuerst zum Admin machen.

Danach legst du unter **Benutzer** die Konten deiner Freunde an. Das Anfangspasswort kannst du würfeln lassen 🎲. Beim ersten Login müssen sie es ändern.

---

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `base_path` | `/share/SocialGarbageCollector` | Datenordner. Muss unter `/share` liegen, sonst geht er bei einem Neubau verloren. |
| `admin_username` / `admin_password` | `admin` / leer | Erster Admin (nur beim allerersten Start) |
| `reset_password` | `false` | **Notfall:** beim Start bekommt `admin_username` das Passwort `admin_password` – entsperrt, aktiviert, Admin (wird angelegt, falls es den Namen nicht gibt). Danach wieder ausschalten und `admin_password` leeren! |
| `session_hours` | `168` | Wie lange ein Login gültig bleibt (Stunden) |
| `cookie_secure` | `false` | `true`, sobald die App nur noch über HTTPS erreichbar ist |
| `login_max_attempts` | `5` | Fehlversuche bis zur Sperre eines Kontos |
| `login_lock_minutes` | `15` | Dauer der Sperre |
| `backup_keep` | `7` | Anzahl täglicher DB-Sicherungen in `backups/` (0 = aus) |
| `save_media` | `true` | Bilder, GIFs und Videos aus Postings mitsichern |
| `media_max_mb` | `150` | Höchstgröße je Medien-Datei in MB |
| `screenshot_theme` | `dark` | Screenshots von X und Bluesky dunkel oder hell aufnehmen. Vorhandene Beiträge holst du unter Einstellungen → System → „Alle Screenshots neu aufnehmen“ nach. |
| `timezone` | `Europe/Berlin` | Zeitzone für die Anzeige |
| `log_level` | `info` | Ausführlichkeit des Protokolls |

Beim Start legt die App fehlende Unterordner selbst an und prüft, ob der Ordner beschreibbar ist. Wenn nicht, steht eine klare Fehlermeldung im Protokoll und das Add-on startet nicht.

---

## Backup

Alles Dauerhafte liegt in **einem** Ordner:

```
/share/SocialGarbageCollector/
├── db/archiv.sqlite        ← Datenbank (Postingn, Personen, Accounts, Tags, Listen, Nutzer, Protokoll)
├── screenshots/            ← Beleg-Screenshots als WebP (Pfade in der DB sind relativ → Ordner ist verschiebbar)
├── authors/                ← Profilbilder der Verfasser (Name = Prüfsumme)
├── avatars/                ← Profilbilder der Mitglieder
├── backups/                ← tägliche DB-Sicherungen (sqlite backup, WAL-sicher)
├── gallery/                ← Galerie-Bilder (WebP, je Bild Ansicht + Vorschau)
├── media/                  ← Bilder, GIFs, Videos aus den Postings
```

- **Home-Assistant-Backup:** Beim Teil-Backup den Haken bei **„Share“** setzen. Ein volles Backup enthält `/share` ohnehin.
- **Von Hand:** Den ganzen Ordner kopieren. Für eine konsistente Datenbank entweder das Add-on vorher stoppen oder die neueste Datei aus `backups/` nehmen. Die App sichert die Datenbank täglich per `sqlite3.backup()`, und das ist auch bei laufendem Betrieb sicher.

---

## Suchbefehl-Generator: Hinweise zu den Operatoren

> ⚠️ **Nicht jeder Operator funktioniert dauerhaft oder für alle Konten.** X ändert seine Suche ohne Ankündigung. Beide Plattformen verlangen fürs Suchen inzwischen meist einen Login, und die Bluesky-Websuche geht ausgeloggt gar nicht mehr.

Die unterstützten Operatoren stehen **zentral** in:

- `app/services/search/operators_x.py`
- `app/services/search/operators_bluesky.py`

Die Erzeugungslogik (`builder.py`) ist von der Oberfläche getrennt und mit Unit-Tests abgedeckt (`tests/test_search_builder.py`).

**Bluesky (geprüft im Oktober 2026)** gegen den offiziellen Blogbeitrag [Tips and Tricks for Bluesky Search](https://bsky.social/about/blog/05-31-2024-search) und das Lexicon `app.bsky.feed.searchPosts`. Belegt und umgesetzt: Wörter, `"Phrase"`, `#tag`, `from:`, `mentions:`, `lang:`, `since:`/`until:`, `domain:`, URL.
**Bewusst weggelassen (TODO in `operators_bluesky.py`):** Ausschluss mit `-wort`, `OR`, Medien- und Antworten-Filter (in der App gibt es dafür Filterfelder, die Syntax ist aber nicht dokumentiert), Mindest-Likes (gibt es bei Bluesky nicht). Außerdem kennt der Such-Link **keine Sortierung**: Der Wechsel zwischen „Top“ und „Neueste“ auf bsky.app ändert die URL nicht. Nur die API kann `sort=top|latest`.

**X:** Sortierung über `&f=live` (Neueste) bzw. `&f=top`.

---

## Architektur und Dateistruktur

```
SocialGarbageCollector/                 ← Projektordner = Add-on-Repository (Name aus der Zeit vor 0.6)
├── repository.yaml
├── branding/                           ← Skript, das alle Icon-Größen zeichnet (+ alte Icon-Quelle bis 0.5)
├── README.md
└── social_garbage_collector/           ← das Add-on (kommt nach /addons/)
    ├── config.yaml                     ← HA: Name, Slug, Ingress, Port 8780, map share:rw, Optionen
    ├── Dockerfile                      ← python:3.12-slim-bookworm + Tesseract + Playwright-Chromium
    ├── run.sh                          ← options.json → Umgebungsvariablen → uvicorn
    ├── requirements.txt / requirements-dev.txt
    ├── pruefen.sh                      ← startet die Tests
    ├── app/
    │   ├── main.py                     ← App-Fabrik, Lifespan, Ingress-Middleware, Fehlerseiten
    │   ├── config.py                   ← Einstellungen, Datenordner-Prüfung, safe_path()
    │   ├── db.py                       ← Engine (WAL), Schema, FTS5 + Trigger, Backups
    │   ├── models.py                   ← SQLAlchemy-Modelle
    │   ├── security.py                 ← argon2, Sitzungen, CSRF, require_user/require_admin, Login-Bremse
    │   ├── templating.py               ← Jinja2, url() mit Ingress-Präfix
    │   ├── routers/                    ← auth, account, settings, posts, persons, lists, generator, admin
    │   ├── services/
    │   │   ├── platforms/              ← base.py (Schnittstelle), x.py, bluesky.py
    │   │   ├── search/                 ← operators_x.py, operators_bluesky.py, builder.py, presets.py
    │   │   ├── capture.py              ← Hintergrund-Worker (Screenshot → Text → Status)
    │   │   ├── ocr.py                  ← Tesseract mit Vorverarbeitung
    │   │   ├── posts.py                ← Hinzufügen, Duplikate, Tags, Archivsuche
    │   │   ├── accounts.py             ← Personen/Accounts: erkennen, Verlauf, zusammenführen, Profilbilder
    │   │   ├── citation.py             ← Quellenangabe und Archiv-Nummer
    │   │   ├── admin_log.py
    │   │   ├── gallery.py              ← Galerie: Bilder verkleinern, Kategorien
    │   │   └── bulk.py                 ← Massenimport
    │   ├── prefs.py                    ← persönliche Einstellungen (Werte, Standards, Prüfung)
    │   ├── changelog.py                ← Versionsverlauf (Einstellungen → Über)
    │   ├── templates/                  ← base.html + Seiten, partials/, settings/, admin/
    │   └── static/                     ← style.css (Design-System), app.js, htmx.min.js, brand/ (Icons)
    └── tests/                          ← pytest, ohne Netz/Browser
```

**Datenmodell:** `users` (Rolle, Status, argon2-Hash, Sperre, letzter Login, `prefs` als JSON), `sessions` (nur Token-Hash), `admin_log`, `persons` (Name, Beschreibung, `name_locked`), `accounts` (Plattform, feste ID, aktueller Handle/Name/Profilbild, Person), `account_changes` (Verlauf), `posts` = Postingn (Plattform, URL, `dedup_key`, Handle und Anzeigename **zum Zeitpunkt der Archivierung**, Profilbild-Stand, Account, Zeitpunkt, Wortlaut, Textquelle, Alt-Texte, Anmerkung, Beleg-Screenshot, Status), `tags`, `post_tags`, `lists`, `list_posts`, `saved_searches` und die virtuelle Tabelle `posts_fts`. Die Spalten `disco`, `seen_until`, `last_visit_at` sind seit 0.6 ungenutzt; die Tabelle `reactions` wird beim Start entfernt.

**Neue Plattform ergänzen:** Ein Modul in `services/platforms/` schreiben, das `PlatformService` aus `base.py` erfüllt (URL parsen, Duplikat-Schlüssel, Metadaten, Screenshot), und es in `platforms/__init__.py` eintragen. Worker, Suche und Oberfläche bleiben gleich.

**Sicherheit im Überblick:**
- Rechte werden zentral über `require_user` und `require_admin` geprüft. Der Admin-Router hängt komplett an `require_admin`, Nicht-Admins bekommen eine neutrale 404.
- CSRF-Token für **alle** schreibenden Anfragen. htmx schickt es als Header mit.
- Sitzungen liegen serverseitig mit Ablaufzeit, im Cookie steht nur ein Zufallstoken (`httponly`, `samesite=lax`).
- Nach `login_max_attempts` Fehlversuchen wird das Konto gesperrt, dazu kommt eine Bremse pro IP.
- Screenshots und Profilbilder werden nur über `safe_path()` ausgeliefert, und nur aus `screenshots/`, `authors/` bzw. `avatars/`.
- Profilbilder der Verfasser lädt die App nur von den Bild-Servern der Plattformen (`pbs.twimg.com`, `cdn.bsky.app`) und speichert sie neu kodiert.

---

## Entwicklung und Tests

```bash
cd social_garbage_collector
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
./pruefen.sh
```

Die Tests brauchen weder Netz noch Chromium noch Tesseract: Worker und DID-Lookup sind dort abgeschaltet. Sie decken unter anderem ab:
- Nutzer erreichen keine Admin-Routen, auch keine htmx-Teilstücke.
- Nur der Admin legt Benutzer an.
- Den letzten Admin kann niemand löschen oder herabstufen.
- Passwörter liegen nur als argon2-Hash vor – niemand kann sie einsehen, auch kein Admin.
- CSRF, Login-Sperre, Ablauf von Sitzungen, Schutz vor Pfad-Manipulation.
- Generator für beide Plattformen: Sonderzeichen, leere Felder, OR, Ausschlüsse, Plattformwechsel.

Lokal starten (Daten in einen Testordner):

```bash
SGC_BASE_PATH=./testdaten uvicorn app.main:app --port 8780
```

---

## Bekannte Grenzen

- **X:** Ohne Login zeigt x.com fast immer eine Login-Wand. Die App fällt dann automatisch auf das offizielle Embed-Widget zurück, und das klappt zuverlässig. Geschützte oder gelöschte Beiträge bleiben als Eintrag mit Fehlerstatus erhalten.
- **Chromium auf dem Pi** braucht beim Screenshot kurz ~300 MB RAM. Beiträge werden deshalb nacheinander abgearbeitet, und der Browser schließt sich, sobald die Warteschlange leer ist. Ein Beitrag dauert etwa 5–25 Sekunden.
- **Ganze Accounts archivieren** (alle Beiträge eines Accounts auf einmal) ist für Bluesky geplant (öffentliche API). Für X geht das nur mit einer kostenpflichtigen X-API und ist deshalb nicht vorgesehen: X bleibt bei einzelnen Links und Screenshot-Uploads.
- **X-Wortlaut** kommt aus dem inoffiziellen Embed-Backend. Ändert X das, fällt die App auf oEmbed und Texterkennung zurück.
- **Rechtliches:** Für eine geschlossene Gruppe auf dem eigenen Pi unkritisch. Öffentlich betrieben bräuchte es Impressum, eine Datenschutz-Grundlage und einen Weg, Einträge auf Wunsch zu löschen.
