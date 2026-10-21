#!/bin/bash
# Startskript des Add-ons: HA-Optionen -> Umgebungsvariablen -> uvicorn.
set -euo pipefail

OPTIONS=/data/options.json

# /data/options.json schreibt der Supervisor bei jedem Speichern neu.
# shlex.quote sorgt dafuer, dass auch Passwoerter mit Sonderzeichen ankommen.
# Ausserhalb von Home Assistant (lokaler Test) fehlt die Datei: dann gelten
# die Standardwerte aus app/config.py.
if [ -f "${OPTIONS}" ]; then
  eval "$(python3 - <<'PY'
import json, shlex

with open("/data/options.json", encoding="utf-8") as f:
    o = json.load(f)

def setze(name, key, default):
    value = o.get(key, default)
    if value is None:
        value = default
    if isinstance(value, bool):
        value = "true" if value else "false"
    print(f"export {name}={shlex.quote(str(value))}")

setze("SGC_BASE_PATH",           "base_path",           "/share/SocialGarbageCollector")
setze("SGC_ADMIN_USERNAME",      "admin_username",      "admin")
setze("SGC_ADMIN_PASSWORD",      "admin_password",      "")
setze("SGC_RESET_PASSWORD",      "reset_password",      False)
setze("SGC_SESSION_HOURS",       "session_hours",       168)
setze("SGC_COOKIE_SECURE",       "cookie_secure",       False)
setze("SGC_LOGIN_MAX_ATTEMPTS",  "login_max_attempts",  5)
setze("SGC_LOGIN_LOCK_MINUTES",  "login_lock_minutes",  15)
setze("SGC_BACKUP_KEEP",         "backup_keep",         7)
setze("SGC_SCREENSHOT_THEME",    "screenshot_theme",    "dark")
setze("SGC_SAVE_MEDIA",          "save_media",          True)
setze("SGC_MEDIA_MAX_MB",        "media_max_mb",        150)
setze("TZ",                      "timezone",            "Europe/Berlin")
setze("SGC_LOG_LEVEL",           "log_level",           "info")
PY
)"
fi

export TZ="${TZ:-Europe/Berlin}"
export PYTHONPATH=/opt/sgc

echo "[sgc] TrashTwitter startet"
echo "[sgc] Datenordner: ${SGC_BASE_PATH:-/share/SocialGarbageCollector}"
echo "[sgc] Zeitzone:    ${TZ} (aktuell $(date '+%d.%m.%Y %H:%M'))"

cd /opt/sgc
# uvicorn per exec: Prozess 1, bekommt das Stopp-Signal direkt.
# --proxy-headers: echte Besucher-IP aus X-Forwarded-For, aber nur von
# vertrauten Proxys. Standard ist der Ingress-Proxy des Supervisors
# (172.30.32.2). Auf dem VPS kommt alles ueber den Cloudflare-Tunnel; dort
# setzt compose.yaml SGC_FORWARDED_ALLOW_IPS="*", sonst saehen alle Anfragen
# wie eine IP aus und die Login-Sperre traefe alle gleichzeitig.
exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips "${SGC_FORWARDED_ALLOW_IPS:-172.30.32.2}" \
  --log-level "${SGC_LOG_LEVEL:-info}"
