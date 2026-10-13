# TrashTwitter

Quellenarchiv für öffentliche Aussagen von X und Bluesky: Wortlaut, Verfasser, Datum und Beleg, nach Personen geordnet und durchsuchbar. Die ausführliche Anleitung steht in der `README.md` im Projektordner.

Bis 0.5 hieß das Add-on SocialGarbageCollector. Slug und Datenordner sind gleich geblieben, deine Daten bleiben erhalten.

## Erster Start

- **Mit Option:** `admin_username` und `admin_password` setzen und starten. Danach das Passwort beim ersten Login ändern und die Option wieder leeren.
- **Ohne Option:** Starten und im **Protokoll** den **Einrichtungscode** suchen. Dann die Oberfläche öffnen und mit dem Code den Admin anlegen.

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
