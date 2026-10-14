# TrashTwitter

Quellenarchiv für öffentliche Aussagen von X und Bluesky: Wortlaut, Verfasser, Datum und Beleg, nach Personen geordnet und durchsuchbar. Die ausführliche Anleitung steht in der `README.md` im Projektordner.

Bis 0.5 hieß das Add-on SocialGarbageCollector. Slug und Datenordner sind gleich geblieben, deine Daten bleiben erhalten.

## Erster Start

- **Mit Option:** `admin_username` und `admin_password` setzen und starten. Danach das Passwort beim ersten Login ändern und die Option wieder leeren.
- **Ohne Option:** Starten und im **Protokoll** den **Einrichtungscode** suchen. Dann die Oberfläche öffnen und mit dem Code den Admin anlegen.

## Notfall: Niemand kommt mehr rein

Passwort vergessen oder Konto nach Fehlversuchen gesperrt:

1. Add-on → **Konfiguration**: `reset_password` einschalten, bei `admin_username` deinen Benutzernamen und bei `admin_password` ein neues Passwort (mind. 5 Zeichen) eintragen. Speichern.
2. Add-on **neu starten**. Im **Protokoll** steht „NOTFALL-RESET“ und welche Admin-Konten es gibt.
3. Anmelden, ein eigenes Passwort vergeben.
4. **Wichtig:** `reset_password` wieder ausschalten und `admin_password` leeren.

## Zugriff

- Für dich: über die HA-Seitenleiste (Ingress).
- Für Mitglieder ohne HA-Konto: `http://homeassistant.local:8780`. Nicht ungeschützt ins Internet freigeben. Wenn du von unterwegs zugreifen willst, nimm einen Reverse-Proxy mit HTTPS und setz `cookie_secure: true`.

## Aufs Handy

- iPhone: in Safari Teilen → „Zum Home-Bildschirm“.
- Teilen direkt aus X oder Bluesky: In der App unter Einstellungen → Teilen & Kürzel steht, wie es geht.

## Daten und Backup

Alles liegt unter `/share/SocialGarbageCollector` (`db/`, `screenshots/`, `authors/`, `avatars/`, `gallery/`, `backups/`). Beim HA-Backup **„Share“** mitsichern.

## Suchgenerator

Nicht jeder Such-Operator funktioniert dauerhaft oder für alle Konten. Die Operatoren stehen zentral in `app/services/search/operators_x.py` und `operators_bluesky.py`.
