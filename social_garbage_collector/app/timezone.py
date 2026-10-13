"""Lokale Zeitzone (aus TZ, Standard Europe/Berlin)."""

import os
from zoneinfo import ZoneInfo

try:
    LOCAL_TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
except Exception:  # pragma: no cover - ungueltige TZ-Angabe
    LOCAL_TZ = ZoneInfo("Europe/Berlin")
