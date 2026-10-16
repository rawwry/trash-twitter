"""0.12.0: Screenshots verstehen, Tags umbenennen, Archiv-Leiste, Raster, Galerie-Sortierung, Detailseite."""

from __future__ import annotations

import asyncio
import io
from datetime import datetime

import httpx
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.models import Account, GalleryImage, Post, Tag
from app.services import capture as capture_mod
from app.services import dates, ocr, screenshot
from app.services.capture import CaptureWorker
from app.services.ocr import Layout, Line
from app.services.platforms import bluesky

from .conftest import Harness, make_settings


def _ln(text, top, left=40, height=30, para=(1, 1), words=None):
    words = words or []
    if not words:
        x = left
        for w in text.split():
            words.append((w, x, x + 12 * len(w), 95))
            x += 12 * len(w) + 10
    return Line(text, left, top, left + 12 * len(text), top + height, para, words)


def _x_layout():
    """Wie ein X-Screenshot im Dark Mode: Profilbild links liest Tesseract als Muell."""
    head1 = _ln("DJ Furzipups der Knatterdrache", 50, left=184,
                words=[("DJ", 184, 214, 92), ("Furzipups", 225, 380, 91), ("der", 390, 440, 92), ("Knatterdrache", 450, 700, 91)])
    head2 = _ln("oe @Jukischx64 - Folgen", 100, left=30,
                words=[("oe", 30, 60, 20), ("@Jukischx64", 184, 430, 89), ("-", 440, 450, 50), ("Folgen", 460, 560, 90)])
    body = [
        _ln("am meisten hab ich angst davor längst", 190, height=49, para=(2, 1)),
        _ln("genauso ein arschloch geworden zu sein,", 256, height=49, para=(2, 1)),
        _ln("ich auch so scheiße baue.®", 322, height=49, para=(2, 1)),
    ]
    foot = [_ln("22:10 : 22 Jan. 25: 78 Mal angezeigt", 473, para=(2, 2)),
            _ln("O24k (64 D 408", 520, para=(3, 1))]
    return Layout([head1, head2, *body, *foot], 1080, 600)


# --- Texterkennung: Kopf, Wortlaut, Fuss ------------------------------------------------------

def test_parse_x_screenshot():
    info = screenshot.parse(_x_layout())
    assert info.platform == "x" and info.handle == "Jukischx64"
    assert info.display_name == "DJ Furzipups der Knatterdrache"   # nicht "oe" vom Profilbild
    assert info.text == "am meisten hab ich angst davor längst genauso ein arschloch geworden zu sein, ich auch so scheiße baue."
    assert info.posted_at == datetime(2025, 1, 22, 21, 10) and info.has_time  # 22:10 Berlin = 21:10 UTC


def test_parse_bluesky_screenshot_and_more_link():
    lay = Layout([
        _ln("Dr. Lena Schmidt", 40),
        _ln("@forscherin.bsky.social", 80),
        _ln("Die Erwärmung der Ozeane liegt deutlich über", 140, para=(2, 1)),
        _ln("den Modellannahmen. Mehr anzeigen", 176, para=(2, 1)),
        _ln("8. Okt. 2026 um 17:00", 240, para=(3, 1)),
        _ln("12 Reposts 40 Gefällt mir", 280, para=(4, 1)),
    ], 900, 400)
    info = screenshot.parse(lay)
    assert info.platform == "bluesky" and info.handle == "forscherin.bsky.social"
    assert info.display_name == "Dr. Lena Schmidt"
    assert info.text == "Die Erwärmung der Ozeane liegt deutlich über den Modellannahmen."
    assert info.posted_at == datetime(2026, 10, 8, 15, 0)


def test_parse_without_header_keeps_text():
    info = screenshot.parse(Layout([_ln("Nur ein Satz ohne Kopf.", 10)], 400, 100))
    assert info.text == "Nur ein Satz ohne Kopf." and info.handle == "" and info.platform is None


def test_two_digit_years():
    assert dates.from_text("22:10 · 22 Jan. 25 · 78 Mal angezeigt")[0] == datetime(2025, 1, 22, 21, 10)
    assert dates.from_text("am 4 Mai 20:30 Uhr") is None  # Uhrzeit ist kein Jahr


def test_crop_avatar():
    img = Image.new("RGB", (600, 300), (0, 0, 0))
    ImageDraw.Draw(img).ellipse((20, 30, 130, 140), fill=(230, 120, 60))
    header = [Line("Name", 160, 40, 400, 80), Line("@name", 160, 90, 300, 125)]
    data = screenshot.crop_avatar(img, header)
    assert data
    with Image.open(io.BytesIO(data)) as av:
        assert abs(av.width - 110) <= 4 and av.width == av.height
    blank = Image.new("RGB", (600, 300), (0, 0, 0))
    assert screenshot.crop_avatar(blank, header) is None


# --- Upload ohne Plattform + Worker -------------------------------------------------------------

def _png(color=(21, 32, 43)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 300), color).save(buf, "PNG")
    return buf.getvalue()


def _upload(client, **data):
    data.setdefault("csrf_token", client.csrf)
    return client.post("/posts/upload", data=data, files=[("files", ("s.png", data.pop("blob", _png()), "image/png"))])


def test_upload_without_platform_is_auto(user_client, harness):
    assert _upload(user_client).status_code == 303
    assert _upload(user_client, blob=_png((9, 9, 9)), handle="@jemand.bsky.social").status_code == 303
    assert _upload(user_client, blob=_png((8, 8, 8)), platform="x").status_code == 303
    with harness.db() as db:
        a, b, c = db.query(Post).order_by(Post.id).all()
        assert (a.platform, a.platform_auto) == ("x", True)
        assert (b.platform, b.platform_auto) == ("bluesky", True)
        assert (c.platform, c.platform_auto) == ("x", False)
    form = user_client.get("/add?mode=upload").text
    assert "Automatisch" in form and "liest Verfasser" in form


def _run_worker(tmp_path, monkeypatch, layout, platform="x", auto=True, handle=""):
    h = Harness(make_settings(tmp_path))
    client = TestClient(h.app)
    client.__enter__()
    shot = h.settings.screenshot_dir / "x" / "2026" / "u.webp"
    shot.parent.mkdir(parents=True)
    img = Image.new("RGB", (1080, 600), (0, 0, 0))
    ImageDraw.Draw(img).ellipse((35, 40, 145, 150), fill=(230, 120, 60))
    img.save(shot, "WEBP")
    with h.db() as db:
        p = Post(platform=platform, url="", dedup_key="upload:abc", post_id="uabc", shot_source="upload",
                 screenshot_path="screenshots/x/2026/u.webp", status="pending", platform_auto=auto, author_handle=handle)
        db.add(p)
        db.commit()
        pid = p.id
    monkeypatch.setattr(ocr, "ocr_layout", lambda src: (layout, img))
    asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).process(pid))
    db = h.db()
    post = db.get(Post, pid)
    client.__exit__(None, None, None)
    return h, db, post


def test_worker_reads_screenshot_like_a_link(tmp_path, monkeypatch):
    h, db, p = _run_worker(tmp_path, monkeypatch, _x_layout())
    assert p.status == "done" and p.shot_parsed
    assert p.author_handle == "Jukischx64" and p.author_display_name == "DJ Furzipups der Knatterdrache"
    assert p.text_source == "ocr" and p.text.endswith("baue.")
    assert p.posted_at == datetime(2025, 1, 22, 21, 10) and p.date_source == "ocr" and p.date_has_time
    assert p.account is not None and p.account.handle == "Jukischx64"
    assert p.author_avatar_path and (h.settings.base_path / p.author_avatar_path).exists()
    assert p.account.avatar_path == p.author_avatar_path
    db.close()


def test_worker_keeps_manual_choices(tmp_path, monkeypatch):
    """Von Hand Bluesky gewaehlt: ein X-Handle aus dem Bild passt nicht und wird nicht uebernommen."""
    h, db, p = _run_worker(tmp_path, monkeypatch, _x_layout(), platform="bluesky", auto=False)
    assert p.platform == "bluesky" and p.author_handle == "" and p.text.startswith("am meisten")
    db.close()


def test_worker_uses_known_account_avatar(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path / "pre"))
    with TestClient(h.app):
        pass
    # Account existiert schon (z. B. aus einem Link-Posting) -> dessen Profilbild, nicht der Ausschnitt
    def layout_with_known():
        return _x_layout()
    h2, db, p = _run_worker(tmp_path, monkeypatch, layout_with_known())
    acc = db.query(Account).filter_by(handle="Jukischx64").one()
    assert p.account_id == acc.id
    db.close()


def test_reparse_old_uploads(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        shot = h.settings.screenshot_dir / "x" / "2026" / "old.webp"
        shot.parent.mkdir(parents=True)
        img = Image.new("RGB", (1080, 600), (0, 0, 0))
        img.save(shot, "WEBP")
        with h.db() as db:
            db.add(Post(platform="x", url="", dedup_key="upload:old", post_id="uold", shot_source="upload",
                        screenshot_path="screenshots/x/2026/old.webp", status="done", text_source="ocr",
                        text="DJ Furzipups der Knatterdrache @Jukischx64 am meisten … 22:10 : 22 Jan. 25"))
            db.add(Post(platform="x", url="", dedup_key="upload:man", post_id="uman", shot_source="upload",
                        screenshot_path="screenshots/x/2026/old.webp", status="done", text_source="manual",
                        text="Von Hand"))
            db.commit()
        monkeypatch.setattr(ocr, "ocr_layout", lambda src: (_x_layout(), img))
        n = asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).reparse_uploads(pause_s=0))
        assert n == 2
        with h.db() as db:
            old, manual = db.query(Post).order_by(Post.id).all()
            assert old.author_handle == "Jukischx64" and old.text.startswith("am meisten") and old.posted_at
            assert manual.text == "Von Hand" and manual.author_handle == "Jukischx64"
        assert asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).reparse_uploads(pause_s=0)) == 0


# --- Bluesky: Original zum Screenshot finden ----------------------------------------------------

def test_bluesky_find_post_by_text():
    feed = {"feed": [
        {"post": {"uri": "at://did:plc:a/app.bsky.feed.post/1", "record": {"text": "Etwas ganz anderes heute", "createdAt": "2026-10-08T15:00:00Z"}}},
        {"reason": {"$type": "repost"}, "post": {"uri": "at://did:plc:b/app.bsky.feed.post/9",
                                                  "record": {"text": "i rebooted minesweeper as a AAA shooter. loot boxes coming soon"}}},
        {"post": {"uri": "at://did:plc:a/app.bsky.feed.post/2",
                  "record": {"text": "i rebooted minesweeper as a AAA shooter. loot boxes coming soon minesweeper.example.com",
                             "createdAt": "2026-10-08T15:00:23Z"}}},
    ]}

    def handler(request):
        assert request.url.path.endswith("getAuthorFeed")
        return httpx.Response(200, json=feed)

    async def run(text):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await bluesky.find_post(c, "did:plc:a", text, datetime(2026, 10, 8, 15, 0), max_pages=1)

    hit = asyncio.run(run("i rebooted minesweeper as a AAA shooter. loot boxes coming soon"))
    assert hit["uri"].endswith("/2")
    assert asyncio.run(run("Komplett anderer Text, der nirgends vorkommt.")) is None
    assert asyncio.run(run("kurz")) is None  # zu kurz fuer einen sicheren Treffer


# --- Archiv: Leiste, Standard-Sortierung, Chips -----------------------------------------------------

def _add(harness, n=3):
    with harness.db() as db:
        for i in range(n):
            db.add(Post(platform="x" if i % 2 == 0 else "bluesky", url=f"https://x.com/a/status/{i + 1}",
                        dedup_key=f"x:{i + 1}", post_id=str(i + 1), author_handle="a", text=f"Text {i}",
                        posted_at=datetime(2020 - i, 1, 1), status="done"))
        db.commit()


def test_archive_toolbar_default_sort_and_chips(user_client, harness):
    _add(harness)
    page = user_client.get("/").text
    assert 'class="atb"' in page and 'value="new" selected' in page  # Standard: zuletzt archiviert
    # Plattform steckt jetzt im Filter und zaehlt dort mit
    assert page.index('name="platform"') > page.index('id="filter-panel"')
    order = [m for m in ("Text 0", "Text 1", "Text 2") if m in page]
    assert page.index("Text 2") < page.index("Text 0")  # neueste Archivierung zuerst
    filtered = user_client.get("/?platform=bluesky&q=Text").text
    assert 'class="count-badge">1<' in filtered
    assert 'href="/?q=Text" title="Filter entfernen"' in filtered  # x am Plattform-Chip entfernt nur die Plattform
    assert 'class="view-icons"' in page and "data-select-toggle" in page
    assert order


def test_raster_shows_full_text(user_client, harness):
    _add(harness, 1)
    page = user_client.get("/?view=raster").text
    assert 'class="posts view-raster"' in page and "qtile-text" in page


# --- Tags umbenennen ---------------------------------------------------------------------------------

def test_tag_rename_and_merge_for_everyone(user_client, harness):
    with harness.db() as db:
        p = Post(platform="x", url="https://x.com/a/status/1", dedup_key="x:1", post_id="1", author_handle="a", status="done")
        p.tags = [Tag(name="klma"), Tag(name="klima")]
        q = Post(platform="x", url="https://x.com/a/status/2", dedup_key="x:2", post_id="2", author_handle="a", status="done")
        db.add_all([p, q])
        db.commit()
        q.tags = [db.query(Tag).filter_by(name="klma").one()]
        db.commit()
        tid = db.query(Tag).filter_by(name="klma").one().id
    assert "Tags organisieren" in user_client.get("/").text  # Menue + Stift in der Tag-Leiste
    page = user_client.get("/settings/tags").text
    assert f'data-edit-form="tag-{tid}"' in page
    r = user_client.post(f"/settings/tags/{tid}/rename", data={"name": "#Klima", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert [t.name for t in db.query(Tag)] == ["klima"]
        assert all([t.name for t in post.tags] == ["klima"] for post in db.query(Post))


# --- Galerie -------------------------------------------------------------------------------------------

def _jpg(color, taken=None) -> bytes:
    img = Image.new("RGB", (400, 300), color)
    buf = io.BytesIO()
    exif = Image.Exif()
    if taken:
        exif[306] = taken
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_gallery_sort_and_taken_at(user_client, harness):
    for i, taken in enumerate(["2019:05:01 10:00:00", None, "2024:01:02 08:00:00"]):
        user_client.post("/galerie/hochladen", data={"csrf_token": user_client.csrf},
                         files=[("files", (f"b{i}.jpg", _jpg((i * 60, 10, 10), taken), "image/jpeg"))])
    with harness.db() as db:
        imgs = db.query(GalleryImage).order_by(GalleryImage.id).all()
        assert imgs[0].taken_at == datetime(2019, 5, 1, 10) and imgs[1].taken_at is None
        ids = [i.id for i in imgs]
    page = user_client.get("/galerie").text
    assert 'value="zufall" selected' in page and "Neu mischen" in page and "data-gal-size" in page
    newest = user_client.get("/galerie?sort=neu").text
    pos = [newest.index(f"/galerie/bild/{i}/bearbeiten") for i in ids]
    assert pos[2] < pos[1] < pos[0]
    shot = user_client.get("/galerie?sort=aufnahme").text
    pos = [shot.index(f"/galerie/bild/{i}/bearbeiten") for i in ids]
    assert pos[1] < pos[2] < pos[0]  # ohne Aufnahmedatum zaehlt "hinzugefuegt" (heute)
    assert "sort=neu" in user_client.get("/galerie?sort=neu").text  # Kategorie-Links behalten die Sortierung


# --- Detailseite, Listen ---------------------------------------------------------------------------------

def test_detail_page_folds_secondary_info(user_client, harness):
    _add(harness, 1)
    page = user_client.get("/posts/1").text
    assert 'class="lead-actions"' in page and "Zitieren" in page
    assert '<details class="card fold" id="angaben"' in page and "Quellenangabe" in page
    assert page.index('class="lead-actions"') < page.index('id="angaben"')
    assert "Medien <span" not in page and "citation-card" not in page


def test_lists_add_button_opens_dialog(user_client):
    page = user_client.get("/lists").text
    assert 'data-open="list-new"' in page and '<dialog class="sheet" id="list-new"' in page
    r = user_client.post("/lists", data={"title": "Klima", "csrf_token": user_client.csrf})
    assert r.status_code == 303 and "Klima" in user_client.get("/lists").text
