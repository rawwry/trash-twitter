# Ooze → Rawwry: Archivintegrität und Stabilität

Stand: 13.10.2026. Ausgangsbasis: `a8cadb5`, TrashTwitter 0.9.0. Vorgeschlagene Add-on-Version: 0.10.0, weiterhin `experimental`.

## Was sich ändert

Die bestehende Architektur bleibt erhalten. Die Änderungen konzentrieren sich auf konkrete Datenverlust-, Sperr- und Ressourcenprobleme sowie deren Regressionstests.

| Bereich | Ergebnis |
| --- | --- |
| Capture-Worker | Netzwerk, Browser, OCR und Bildaufbereitung laufen ohne offene Schreibtransaktion. Erst der abschließende kurze Abschnitt reserviert den SQLite-Writer und lädt den aktuellen Datensatz. |
| Gleichzeitige Bearbeitung | Manuelle Texte und Datumsangaben werden aus dem aktuellen Stand übernommen. Eine neue Capture-Generation verhindert, dass ein älterer Job neue Uploads, Thread-Einstellungen oder Retries überschreibt. |
| Historischer Snapshot | Name und Handle bleiben nach der ersten Erfassung erhalten. Account-Namen und Handle-Verlauf können sich unabhängig davon weiterentwickeln. Auch ein bewusst entferntes Datum bleibt manuell. |
| OCR | Rohbilder werden erst nach der Texterkennung entfernt; zuvor konnte der OCR-Dateipfad bereits verschwunden sein. |
| Archivnummer | Eine separate monotone Reservierungstabelle verhindert die Wiederverwendung nach dem Entfernen des höchsten Datensatzes. Bestehende IDs/Zitate bleiben erhalten. |
| Historie | Text, Datum, Notiz/Tags, Thread- und Screenshotänderungen erhalten einen vorherigen Stand mit Bearbeiter und Zeit. Recapture erhält frühere Screenshots. |
| Import | URL-Auflösung vor allen Inserts, höchstens vier parallele Lookups und 45 Sekunden Gesamtbudget. Fortschritt enthält alle maximal 500 neuen Aussagen. |
| Bilder | Sequenzielle Verarbeitung, Gesamtbudgets, explizite Pixel-/Seitenlängenlimits und CPU-Arbeit außerhalb des Event-Loops. Keine global wechselnden Pillow-Grenzwerte. |
| Datenbank/Dateien | Neue Belege bekommen neue Pfade. Fehlgeschlagene Commits räumen neue Dateien auf. Galerie- und Avatar-Löschungen erfolgen erst nach dem Commit. |
| Betrieb | Separates Backup vor Schema-Upgrades, Integritäts-/Fremdschlüsselprüfung, Health-Check für Datenbank, Speicher und Worker. |
| Oberfläche | Galerie und Listen mit 60 Einträgen je Seite, gebündeltes Laden verknüpfter Datensätze, sichtbarer Änderungsverlauf. |
| Sicherheit | Neue Passwörter mindestens 12 Zeichen, 128-Bit-Setup-Code mit Versuchsbremse, weitere CSP-Regeln, sichere Bookmarklet-Kodierung, begrenzte Requests inklusive Chunked-Uploads. |
| Qualität | Linux-/Windows-CI, optionaler Container-Smoke-Test, read-only Medienprüfung, bereinigte Dev-Abhängigkeiten und konsistente Dokumentation. |

## Bewusste Verhaltensänderungen

- **Entfernen ist ab jetzt nachvollziehbar:** Die Aussage verschwindet aus Suche und Listen. Der alte Link liefert einen Löschvermerk mit HTTP 410 und Zugriff auf den Verlauf. Text und Belege bleiben gespeichert; es gibt keinen automatischen endgültigen Löschlauf und noch keinen Wiederherstellen-Knopf.
- Historie enthält sensible Archivdaten genauso wie das aktive Archiv und bleibt hinter derselben Anmeldung. Frühere Screenshots erhöhen den Speicherbedarf.
- Bestehende Passwörter funktionieren weiter. Die längere Mindestlänge gilt beim Neuanlegen oder Ändern.
- Uploads und zusammengesetzte Threads können an den neuen, dokumentierten Größenlimits scheitern. Galerie-Blättern gilt jeweils für die aktuell geladene Seite.
- Alte Archivnummern, die bereits vor dieser Migration gelöscht oder wiederverwendet wurden, können nicht nachträglich rekonstruiert werden.

## Migration und Rückweg

Das Schema steigt von Version 7 auf 8. Ergänzt werden `archive_numbers`, `post_revisions`, `posts.capture_generation` und `posts.snapshot_at`. Bestehende Tabellen und IDs werden nicht neu aufgebaut. Bereits erfasste Beiträge werden als historische Snapshots markiert.

Vor dem Upgrade wird die vorhandene Datenbank mit `sqlite3.backup()` nach `backups/pre-upgrade-*.sqlite` gesichert, bevor `create_all` oder Migrationen laufen. Drei solche Sicherungen bleiben unabhängig von den Tagesbackups erhalten. `integrity_check` und `foreign_key_check` prüfen das Migrationsergebnis; ein Downgrade mit neuerer Datenbank wird abgelehnt.

Für Rollback: Add-on stoppen, aktuellen Datenordner separat sichern und ältere App zusammen mit dem dazugehörigen Vorab-Backup und passenden Medien wiederherstellen. Datenbankbackups ersetzen kein HA-Backup von „Share“.

## Prüfung

Lokale Prüfung unter Windows mit Python 3.12 in einer isolierten Umgebung:

| Prüfung | Ergebnis |
| --- | --- |
| Gesamte Pytest-Suite | **223 bestanden**, darunter 20 neue Regressionstests |
| Python-Syntax (`compileall`, App und Smoke-Skript) | Erfolgreich |
| JavaScript-Syntax (`node --check app/static/app.js`) | Erfolgreich |
| Installierte Test-Abhängigkeiten (`pip check`) | Keine defekten Abhängigkeiten |
| Patch-Format (`git diff --check`) | Keine Fehler |

Eine Warnung bleibt: Der Starlette-Testclient meldet die künftige Ablösung seines `httpx`-Backends durch `httpx2`. Es wurde dafür keine ungetestete Abhängigkeitsumstellung vorgenommen. Die Tests nutzen keine produktiven Daten und keine Live-Plattformkonten. Grüne Tests sind kein Nachweis, dass alle möglichen Regressionen ausgeschlossen sind.

Reproduzierbar aus dem Repository-Verzeichnis nach Installation von `social_garbage_collector/requirements-dev.txt`:

```sh
python -m pytest social_garbage_collector/tests -q
python -m compileall -q social_garbage_collector/app social_garbage_collector/scripts
node --check social_garbage_collector/app/static/app.js
python -m pip check
git diff --check
```

Neue Regressionstests decken insbesondere SQLite-Schreibzugriffe während Capture/Import/Galerie-Verarbeitung, parallele manuelle Änderungen, einen während Capture hochgeladenen Beleg, Löschung während Capture, Snapshot-Treue, Verfügbarkeit der OCR-Rohbilder, Nummernreservierung, Historie, Upload-Budgets, Upgrade/Restore und fehlerhafte Health-Checks ab. Zusätzlich geprüft: Avatar-Commit-Rollback, Redirect-/Byte-Grenzen für externe Profilbilder und eine rein lesende Medienprüfung, die historische Belege und Account-Profilbilder berücksichtigt.

## Noch nicht auf dem Zielsystem verifiziert

- Kein Docker/HA-System in dieser Entwicklungsumgebung: Image-Build, Supervisor-Ingress, echter Chromium/Tesseract-Lauf und ARM64/Pi-Lastverhalten müssen auf dem Zielsystem beziehungsweise mit dem beigefügten Container-Smoke-Test geprüft werden.
- Plattformtests verwenden Fakes; Live-X/Bluesky-Verfügbarkeit wurde nicht getestet.
- Chromium läuft weiterhin mit der bisherigen Container-Konfiguration (Root, `--no-sandbox`). Ein Wechsel auf einen unprivilegierten Benutzer benötigt einen eigenen HA-/Dateirechte-/Browser-Test und wird hier nicht ungetestet erzwungen.
- Es gibt keine vollständige aktuelle CVE-Prüfung aller Abhängigkeiten. Eine transitive Testclient-Deprecation wird separat benannt; sie ist kein bestandener Sicherheitsnachweis.
- SQLite und Dateisystem haben weiterhin keine gemeinsame Transaktion. Bei hartem Prozessabbruch sind unreferenzierte Dateien möglich. `python -m app.maintenance --base-path ...` meldet diese nur; es löscht nichts.
- Die Lizenzwahl bleibt beim Repository-Inhaber; es wurde keine Lizenz eigenmächtig hinzugefügt.

## Vor einer produktiven Aktualisierung

Ein HA-Backup einschließlich „Share“ anlegen. Anschließend im Test-Add-on Login/Setup, Upload, Import, Recapture, Historie, Löschvermerk und Ingress durchgehen. Die `experimental`-Kennzeichnung bleibt bestehen.
