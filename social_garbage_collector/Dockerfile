# TrashTwitter (bis 0.5: SocialGarbageCollector) - Home-Assistant-Add-on
#
# Basis: python:3.12-slim-bookworm (Debian 12), gibt es fuer aarch64 und amd64.
# Bewusst "bookworm" festgenagelt statt "slim" (= wechselnde Debian-Version):
# Playwright pflegt fuer jede Debian-Version eine eigene Paketliste fuer
# "install-deps". Mit einer festen Version bleibt der Build reproduzierbar.
#
# Chromium auf arm64: Playwright laedt seit Jahren eigene linux-arm64-Builds.
# Wir nehmen nur die "headless shell" (--only-shell): kein Fenster-Chromium,
# deutlich kleiner, reicht fuer Screenshots voellig.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/opt/sgc

# tzdata: sonst rechnet der Container in UTC.
# tesseract-ocr + Sprachpakete Deutsch/Englisch fuer die Texterkennung.
# fonts-noto-color-emoji + fonts-noto-cjk: damit Emojis und Sonderzeichen im
# Screenshot nicht als Kaestchen erscheinen.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tzdata \
      tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng \
      fonts-noto-color-emoji fonts-noto-cjk fonts-dejavu-core \
      sqlite3 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Chromium (headless shell) + alle Systembibliotheken, die er braucht.
# --with-deps ruft apt-get selbst auf; danach Listen wieder aufraeumen.
RUN playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*

# Code liegt IM Abbild, Daten unter /share. Ein Update tauscht nur den Code.
COPY app /opt/sgc/app
COPY run.sh /run.sh
RUN chmod +x /run.sh

WORKDIR /opt/sgc
CMD [ "/run.sh" ]
