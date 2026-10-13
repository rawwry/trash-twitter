#!/bin/bash
# Startet alle Tests. Ohne Netz, ohne Chromium, ohne Tesseract.
# Vorher einmalig: pip install -r requirements-dev.txt
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pytest -q "$@"
