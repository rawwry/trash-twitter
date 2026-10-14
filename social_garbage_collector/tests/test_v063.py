"""0.6.3: Datum nachtraeglich bestimmen - aus der Beitrags-ID, aus dem Screenshot, von Hand."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient
from PIL import Image

from app.models import Post
from app.services import capture as capture_mod
from app.services import dates, ocr
from app.services.capture import CaptureWorker

from .conftest import Harness, make_settings


def test_date_from_x_snowflake():
    # bekannter Tweet: 28.10.2022, 03:49:11 UTC
    assert dates.from_x_id("1585841080431321088").replace(microsecond=0) == datetime(2022, 10, 28, 3, 49, 11)
    assert dates.from_x_id("20") is None          # vor Nov. 2010: keine Zeit in der ID
    assert dates.from_x_id("u1a2b3c") is None     # Upload ohne Link


def test_date_from_bluesky_tid():
    assert dates.from_bluesky_tid("3l3qo2vutsw2b").date().isoformat() == "2024-09-09"
    assert dates.from_bluesky_tid("3kabc") is None
    assert dates.from_bluesky_tid("zzzzzzzzzzzzz") is None


def test_date_from_screenshot_text():
    # Ortszeit Europe/Berlin -> UTC
    assert dates.from_text("10:12 vorm. · 4. März 2019") == (datetime(2019, 3, 4, 9, 12), True)
    assert dates.from_text("10:12 AM · Mar 4, 2019") == (datetime(2019, 3, 4, 9, 12), True)
    assert dates.from_text("09:03 · 09.01.24") == (datetime(2024, 1, 9, 8, 3), True)
    assert dates.from_text("March 4, 2019 at 10:12 PM") == (datetime(2019, 3, 4, 21, 12), True)
    assert dates.from_text("4. Marz 2019 um 22:05")[0] == datetime(2019, 3, 4, 21, 5)  # OCR ohne Umlaut
    # Im Text erwaehntes Datum verliert gegen den Zeitstempel mit Uhrzeit
    text = "Am 1. Mai 2017 habe ich das schon gesagt.\n\n18:40 · 18. Juli 2022"
    assert dates.from_text(text) == (datetime(2022, 7, 18, 16, 40), True)
    # nur ein Tag, keine Uhrzeit
    when, has_time = dates.from_text("Gepostet 5. Februar 2021")
    assert when.date().isoformat() == "2021-02-05" and has_time is False
    assert dates.from_text("Kein Datum, nur 2035 und 10:12") is None
    assert dates.from_text("31.02.2020 12:00") is None  # gibt es nicht
    assert dates.from_text("1. Januar 1999 10:00") is None  # vor dem ersten Tweet


def test_startup_fills_dates_from_ids(tmp_path):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        with h.db() as db:
            db.add_all([
                Post(platform="x", url="https://x.com/a/status/1585841080431321088", dedup_key="x:1",
                     post_id="1585841080431321088"),
                Post(platform="x", url="https://x.com/jack/status/20", dedup_key="x:20", post_id="20"),
                Post(platform="x", url="https://x.com/a/status/9", dedup_key="x:9", post_id="1585841080431321999",
                     posted_at=datetime(2020, 1, 1)),
            ])
            db.commit()
    with TestClient(h.app):
        with h.db() as db:
            got = {p.dedup_key: (p.posted_at, p.date_source) for p in db.query(Post)}
    assert got["x:1"][0].date().isoformat() == "2022-10-28" and got["x:1"][1] == "id"
    assert got["x:20"] == (None, None)                      # bleibt fuer den Screenshot
    assert got["x:9"] == (datetime(2020, 1, 1), "api")      # vorhandenes Datum bleibt


def test_worker_reads_date_from_screenshot(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        shot = h.settings.screenshot_dir / "x" / "2026" / "a.webp"
        shot.parent.mkdir(parents=True)
        Image.new("RGB", (100, 50)).save(shot, "WEBP")
        with h.db() as db:
            db.add_all([
                Post(platform="x", url="https://x.com/jack/status/20", dedup_key="x:20", post_id="20",
                     screenshot_path="screenshots/x/2026/a.webp", status="done"),
                Post(platform="x", url="", dedup_key="upload:b", post_id="ub", shot_source="upload",
                     screenshot_path="screenshots/x/2026/a.webp", status="done"),
            ])
            db.commit()
        texts = iter(["just setting up my twttr\n22:50 · 21. März 2006", "Nur Text ohne Datum"])
        monkeypatch.setattr(ocr, "ocr_image", lambda src, raw=False: next(texts))
        worker = CaptureWorker(h.settings, h.app.state.SessionLocal)
        assert asyncio.run(worker.fill_missing_dates(pause_s=0)) == 1
        with h.db() as db:
            a, b = db.query(Post).order_by(Post.id).all()
        assert a.posted_at == datetime(2006, 3, 21, 21, 50) and a.date_source == "ocr" and a.date_has_time
        assert b.posted_at is None and b.date_source == "none"  # nicht bei jedem Start erneut
        # zweiter Lauf: nichts mehr zu tun
        assert asyncio.run(worker.fill_missing_dates(pause_s=0)) == 0


def test_manual_date_on_detail_page(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/jack/status/20", "csrf_token": user_client.csrf})
    with harness.db() as db:
        pid = db.query(Post).one().id
    page = user_client.get(f"/posts/{pid}").text
    assert "Eintragen" in page and 'name="day"' in page
    r = user_client.post(f"/posts/{pid}/date", data={"day": "2006-03-21", "clock": "21:50", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        p = db.get(Post, pid)
        assert p.posted_at == datetime(2006, 3, 21, 20, 50) and p.date_source == "manual" and not p.date_only
    assert "21.03.2006, 21:50" in user_client.get(f"/posts/{pid}").text
    assert "von Hand eingetragen" in user_client.get(f"/posts/{pid}").text
    # nur der Tag
    user_client.post(f"/posts/{pid}/date", data={"day": "2006-03-22", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.get(Post, pid).date_only
    # Unsinn und Zukunft werden abgelehnt, leeres Feld entfernt
    r = user_client.post(f"/posts/{pid}/date", data={"day": "2099-01-01", "csrf_token": user_client.csrf})
    assert "datum" in r.headers["location"]
    r = user_client.post(f"/posts/{pid}/date", data={"day": "kaputt", "csrf_token": user_client.csrf})
    assert "datum" in r.headers["location"]
    user_client.post(f"/posts/{pid}/date", data={"day": "", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.get(Post, pid).posted_at is None
    assert user_client.post(f"/posts/{pid}/date", data={"day": "2020-01-01"}).status_code == 403


def test_upload_date_is_manual_and_day_only(user_client, harness):
    import io

    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 20, 30)).save(buf, "PNG")
    user_client.post("/posts/upload", data={"platform": "x", "posted": "2023-02-06", "csrf_token": user_client.csrf},
                     files=[("files", ("a.png", buf.getvalue(), "image/png"))])
    with harness.db() as db:
        p = db.query(Post).one()
        assert p.date_source == "manual" and p.date_only


# --- 0.7.0: lange X-Beitraege -------------------------------------------------------------

class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.content = data, status, b"x"

    def json(self):
        return self._d


class _Client:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def get(self, url, **kw):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return _Resp({}, 404)


LONG = ("Ich finde meinen Flaschenöffner nicht mehr..... Kann mich aber auch nicht erinnern, wo ich ihn zuletzt "
        "gesehen oder gebraucht habe, da ich ihn eh sehr selten nutze.\n\nWenn ich jetzt morgen einen neuen kaufe, "
        "wie hoch ist die Wahrscheinlichkeit, dass er mir wieder vor die Füße fällt?")


def _synd(text, note=True):
    d = {"__typename": "Tweet", "text": text, "display_text_range": [0, len(text)], "entities": {},
         "user": {"id_str": "1", "name": "Hedwig", "screen_name": "GryffindorKatze"}, "created_at": "2026-10-11T14:38:00.000Z"}
    if note:
        d["note_tweet"] = {"id": "abc"}
    return d


def test_long_x_post_gets_full_text():
    from app.services.platforms.x import XService

    svc = XService()
    parsed = svc.parse_url("https://x.com/GryffindorKatze/status/1977000000000000000")
    short = LONG[:240]
    client = _Client({"syndication": _Resp(_synd(short)), "fxtwitter": _Resp({"tweet": {"text": LONG}})})
    meta = asyncio.run(svc.fetch_metadata(parsed, client))
    assert meta.text == LONG and meta.long_post and meta.text_complete


def test_long_x_post_rejects_foreign_text_and_flags_incomplete():
    from app.services.platforms.x import XService

    svc = XService()
    parsed = svc.parse_url("https://x.com/a/status/1977000000000000000")
    client = _Client({"syndication": _Resp(_synd(LONG[:240])), "fxtwitter": _Resp({"tweet": {"text": "Ganz was anderes " * 30}})})
    meta = asyncio.run(svc.fetch_metadata(parsed, client))
    assert meta.text == LONG[:240] and meta.long_post and not meta.text_complete


def test_short_x_post_does_not_call_fxtwitter():
    from app.services.platforms.x import XService

    svc = XService()
    parsed = svc.parse_url("https://x.com/a/status/1977000000000000000")
    client = _Client({"syndication": _Resp(_synd("Kurz und gut.", note=False))})
    meta = asyncio.run(svc.fetch_metadata(parsed, client))
    assert meta.text == "Kurz und gut." and not meta.long_post
    assert not any("fxtwitter" in c for c in client.calls)


def test_long_post_hint_on_detail_page(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/a/status/1977000000000000000", "csrf_token": user_client.csrf})
    with harness.db() as db:
        p = db.query(Post).one()
        p.long_post, p.text = True, LONG
        db.commit()
        pid = p.id
    assert "Langer Beitrag" in user_client.get(f"/posts/{pid}").text


# --- 0.7.0: Personen bearbeiten (nur Darstellung) -------------------------------------------

def _png():
    import io

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_person_photo_subtitle_and_tiles(user_client, harness):
    from app.models import Person

    user_client.post("/posts", data={"url": "https://x.com/olaf/status/1977000000000000000", "csrf_token": user_client.csrf})
    with harness.db() as db:
        post = db.query(Post).one()
        pid, person_id = post.id, post.account.person_id
    assert 'class="person-tiles"' in user_client.get("/personen").text  # Kacheln sind Standard
    r = user_client.post(f"/personen/{person_id}/bearbeiten",
                         data={"name": "Olaf Beispiel", "subtitle": "Bundesminister a. D.", "note": "", "csrf_token": user_client.csrf},
                         files={"photo": ("o.png", _png(), "image/png")})
    assert r.status_code == 303
    with harness.db() as db:
        p = db.get(Person, person_id)
        assert p.subtitle == "Bundesminister a. D." and p.photo_path.startswith("avatars/p")
        photo = p.photo_path
        # Die Aussage behaelt ihr Original (kein Profilbild gesetzt -> bleibt leer)
        assert db.get(Post, pid).author_avatar_path is None
    with Image.open(harness.settings.base_path / photo) as img:
        # 0.10.0: hochkant 4:5 fuer die Kachel, kleine Bilder werden nicht aufgeblasen
        assert img.size == (240, 300) and img.format == "WEBP"
    tiles = user_client.get("/personen").text
    assert "Bundesminister a. D." in tiles and photo in tiles
    # Liste umschalten wird gemerkt
    assert 'class="person-list"' in user_client.get("/personen?view=list").text
    assert 'class="person-list"' in user_client.get("/personen").text
    # Foto entfernen loescht die Datei
    user_client.post(f"/personen/{person_id}/bearbeiten", data={"name": "Olaf Beispiel", "subtitle": "", "note": "",
                                                               "remove_photo": "1", "csrf_token": user_client.csrf})
    assert not (harness.settings.base_path / photo).exists()
    # kein Bild -> Fehler, nichts gespeichert
    r = user_client.post(f"/personen/{person_id}/bearbeiten", data={"name": "X", "csrf_token": user_client.csrf},
                         files={"photo": ("b.png", b"kein bild", "image/png")})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.get(Person, person_id).name == "Olaf Beispiel"


# --- 0.7.1: Volltext langer Beitraege im Beleg -------------------------------------------

class LongPostService:
    name = "x"
    label = "X"
    prefers_api_text = True

    def __init__(self, complete=True):
        self.complete, self.seen_full_text = complete, None

    def parse_url(self, url):
        return None

    async def fetch_metadata(self, parsed, client):
        from app.services.platforms.base import PostMetadata

        return PostMetadata(text=LONG if self.complete else LONG[:240], handle="GryffindorKatze",
                            long_post=True, text_complete=self.complete)

    async def capture(self, parsed, browser, target, dark=True):
        from app.services.platforms.base import CaptureResult

        self.seen_full_text = parsed.full_text
        Image.new("RGB", (600, 400)).save(target)
        return CaptureResult(screenshot=target, reconstructed=bool(parsed.full_text))


def _run_long(tmp_path, monkeypatch, service):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        worker = CaptureWorker(h.settings, h.app.state.SessionLocal)

        async def fake_browser():
            return object()
        monkeypatch.setattr(worker, "_get_browser", fake_browser)
        monkeypatch.setattr(capture_mod, "get_service", lambda _p: service)
        with h.db() as db:
            p = Post(platform="x", url="https://x.com/GryffindorKatze/status/1977000000000000000",
                     dedup_key="x:1977000000000000000", post_id="1977000000000000000", author_handle="GryffindorKatze")
            db.add(p)
            db.commit()
            pid = p.id
        asyncio.run(worker.process(pid))
        with h.db() as db:
            return db.get(Post, pid)


def test_long_post_full_text_goes_into_screenshot(tmp_path, monkeypatch):
    svc = LongPostService(complete=True)
    post = _run_long(tmp_path, monkeypatch, svc)
    assert svc.seen_full_text == LONG
    assert post.shot_reconstructed and post.long_post and post.text == LONG


def test_incomplete_long_post_is_not_reconstructed(tmp_path, monkeypatch):
    svc = LongPostService(complete=False)
    post = _run_long(tmp_path, monkeypatch, svc)
    assert svc.seen_full_text is None and not post.shot_reconstructed
    assert "gekürzt" in post.status_message


def test_reconstructed_hint_and_upload_resets(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/a/status/1977000000000000000", "csrf_token": user_client.csrf})
    with harness.db() as db:
        p = db.query(Post).one()
        p.long_post = p.shot_reconstructed = True
        db.commit()
        pid = p.id
    assert "Text ergänzt" in user_client.get(f"/posts/{pid}").text
    user_client.post(f"/posts/{pid}/screenshot", data={"csrf_token": user_client.csrf},
                     files=[("files", ("s.png", _png(), "image/png"))])
    with harness.db() as db:
        assert db.get(Post, pid).shot_reconstructed is False
