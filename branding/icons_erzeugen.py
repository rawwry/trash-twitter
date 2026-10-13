"""Erzeugt alle Icons fuer TrashTwitter (ab 0.6) - ohne Quellbild, direkt gezeichnet.

Motiv: ein typografisches Anfuehrungszeichen in Papierfarbe auf Tinte.
Schrift: Iowan Old Style (liegt auf jedem Mac), Rueckfall Georgia.

Aufruf (braucht pillow):
    python3 branding/icons_erzeugen.py /tmp/icons
Danach die PNGs nach social_garbage_collector/app/static/brand/ kopieren,
icon.png und logo.png nach social_garbage_collector/.

Das iOS-Icon ist randlos und deckend - iOS rundet die Ecken selbst ab.
(Bis 0.5 entstanden die Icons aus branding/icon-quelle.webp, der Glow-Muelltonne.)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/icons")
out.mkdir(parents=True, exist_ok=True)

INK = (29, 36, 51)        # #1d2433
PAPER = (246, 245, 241)   # #f6f5f1
FONTS = ["/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"]


def font(size: int, index: int = 1) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size, index=index if path.endswith(".ttc") else 0)
        except OSError:
            continue
    raise SystemExit("Keine Serifenschrift gefunden")


def glyph_layer(size: int, ratio: float) -> Image.Image:
    """Das Zeichen "“" plus eine Grundlinie ("hier steht der Wortlaut"),
    als Gruppe optisch mittig. Gemessen wird die echte Form (getbbox), nicht
    die Schriftmetrik - die enthaelt Ober- und Unterlaengen."""
    big = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(big).text((size, size), "\u201c", font=font(size * 2), fill=255)
    mark = big.crop(big.getbbox())
    mark = mark.resize((round(size * ratio), round(mark.height * size * ratio / mark.width)), Image.Resampling.LANCZOS)
    # Zwei Textzeilen (lang, kurz), linksbuendig unter dem Zeichen - liest sich
    # als "Zitat", nicht als Gesicht (eine mittige Linie wirkte wie ein Mund).
    line_h = max(2, round(size * 0.034))
    gap, lead = round(size * 0.10), round(size * 0.075)
    widths = (round(size * ratio * 1.25), round(size * ratio * 0.8))
    group_h = mark.height + gap + line_h + lead
    top = round((size - group_h) / 2)
    left = round((size - widths[0]) / 2)
    layer = Image.new("L", (size, size), 0)
    layer.paste(mark, (left, top))
    d = ImageDraw.Draw(layer)
    for i, w in enumerate(widths):
        y = top + mark.height + gap + i * lead
        d.rounded_rectangle((left, y, left + w, y + line_h), radius=line_h / 2, fill=150)
    return layer


def app_icon(size: int, ratio: float) -> Image.Image:
    img = Image.new("RGB", (size, size), INK)
    img.paste(Image.new("RGB", (size, size), PAPER), (0, 0), glyph_layer(size, ratio))
    return img


def rounded(img: Image.Image, radius_ratio: float = 0.22) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.width - 1, img.height - 1), round(img.width * radius_ratio), fill=255)
    rgba = img.convert("RGBA")
    rgba.putalpha(m)
    return rgba


master = app_icon(1024, 0.50)
master.save(out / "icon-1024.png")
for s, name in [(180, "apple-touch-icon.png"), (167, "apple-touch-icon-167.png"), (152, "apple-touch-icon-152.png"),
                (192, "icon-192.png"), (512, "icon-512.png")]:
    master.resize((s, s), Image.Resampling.LANCZOS).save(out / name, optimize=True)
mask = app_icon(1024, 0.40)  # Android schneidet bis zu 20 % rundum ab
for s in (192, 512):
    mask.resize((s, s), Image.Resampling.LANCZOS).save(out / f"icon-maskable-{s}.png", optimize=True)
fav = rounded(app_icon(256, 0.62))
for s in (32, 48):
    fav.resize((s, s), Image.Resampling.LANCZOS).save(out / f"favicon-{s}.png", optimize=True)
fav.resize((48, 48), Image.Resampling.LANCZOS).save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
logo = rounded(app_icon(384, 0.54))
for s in (64, 96, 192):
    logo.resize((s, s), Image.Resampling.LANCZOS).save(out / f"logo-{s}.png", optimize=True)

# Home-Assistant-Add-on: icon.png (128) und logo.png (250x100, Bild + Schriftzug)
master.resize((128, 128), Image.Resampling.LANCZOS).save(out / "icon.png", optimize=True)
wide = Image.new("RGBA", (500, 200), (0, 0, 0, 0))
wide.alpha_composite(logo.resize((160, 160), Image.Resampling.LANCZOS), (10, 20))
d = ImageDraw.Draw(wide)
d.text((196, 100), "TrashTwitter", font=font(52, 0), fill=INK + (255,), anchor="lm")
wide.resize((250, 100), Image.Resampling.LANCZOS).save(out / "logo.png", optimize=True)
print("ok", out)
