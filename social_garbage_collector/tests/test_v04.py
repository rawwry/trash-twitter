"""0.4.0: Mehrfachauswahl -> Liste, Threads (Erkennung + Zusammenkleben), WebP-Speicherung."""

from __future__ import annotations

import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.models import ListPost, Post, PostList
from app.services import capture as capture_mod
from app.services import shots
from app.services.capture import CaptureWorker
from app.services.platforms.base import CaptureResult, ParsedPost, PostMetadata
from app.services.platforms.bluesky import BlueskyService
from app.services.platforms.x import XService, _syndication_token

from .conftest import Harness, make_settings


def _add(client, url, **extra):
    return client.post("/posts", data={"url": url, "csrf_token": client.csrf, **extra})


def _ids(harness):
    with harness.db() as db:
        return [p.id for p in db.query(Post).order_by(Post.id)]


# --- Mehrfachauswahl ---------------------------------------------------------------------

def test_bulk_add_to_existing_and_new_list(user_client, harness):
    for i in range(3):
        _add(user_client, f"https://x.com/a/status/{700 + i}")
    ids = _ids(harness)
    user_client.post("/lists", data={"title": "Humor", "csrf_token": user_client.csrf})
    with harness.db() as db:
        lid = db.query(PostList).one().id
    r = user_client.post("/posts/bulk/list", data={"ids": [str(i) for i in ids[:2]], "list_id": lid,
                                                   "back": "/?view=grid", "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith("/?view=grid")
    # nochmal alle drei: zwei sind schon drin
    user_client.post("/posts/bulk/list", data={"ids": [str(i) for i in ids] + ["99999"], "list_id": lid,
                                               "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(ListPost).filter_by(list_id=lid).count() == 3
    # neue Liste direkt aus der Auswahl
    user_client.post("/posts/bulk/list", data={"ids": [str(ids[0])], "list_id": "0", "new_list": "  Beste  ",
                                               "csrf_token": user_client.csrf})
    with harness.db() as db:
        neu = db.query(PostList).filter_by(title="Beste").one()
        assert [lp.post_id for lp in neu.post_links] == [ids[0]]


def test_bulk_validation(user_client, harness):
    _add(user_client, "https://x.com/a/status/710")
    r = user_client.post("/posts/bulk/list", data={"list_id": "1", "csrf_token": user_client.csrf})
    assert r.status_code == 303  # ohne Auswahl: zurueck mit Hinweis
    r = user_client.post("/posts/bulk/list", data={"ids": [str(_ids(harness)[0])], "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.query(ListPost).count() == 0
    # keine offene Weiterleitung
    r = user_client.post("/posts/bulk/list", data={"ids": ["1"], "new_list": "X", "back": "//evil.example",
                                                   "csrf_token": user_client.csrf})
    assert r.headers["location"] in ("/", "http://testserver/")
    assert user_client.post("/posts/bulk/list", data={"ids": ["1"], "new_list": "Y"}).status_code == 403


def test_archive_has_select_ui(user_client):
    _add(user_client, "https://x.com/a/status/720")
    for view in ("grid", "mosaic", "timeline", "list"):
        page = user_client.get(f"/?view={view}").text
        assert 'form="bulk-form"' in page and 'id="bulk-form"' in page, view


# --- Thread-Erkennung: Bluesky ------------------------------------------------------------

DID = "did:plc:" + "a" * 24
OTHER = "did:plc:" + "b" * 24


def _bsky_post(rkey, did=DID, created="2026-10-01T10:00:00Z"):
    return {"uri": f"at://{did}/app.bsky.feed.post/{rkey}", "author": {"did": did, "handle": "anna.bsky.social"},
            "record": {"createdAt": created, "text": rkey}}


def test_bluesky_thread_chain_both_directions():
    # Thread: r1 -> r2 -> r3 (Selbst-Antworten), dazu eine fremde Antwort auf r2
    def handler(request: httpx.Request):
        uri = request.url.params["uri"]
        if request.url.params["parentHeight"] != "0":   # Aufruf "nach oben" ab r2
            assert uri.endswith("/r2")
            return httpx.Response(200, json={"thread": {"post": _bsky_post("r2"),
                                                        "parent": {"post": _bsky_post("r1")}}})
        assert uri.endswith("/r1")                       # Aufruf "nach unten" ab dem Anfang
        return httpx.Response(200, json={"thread": {"post": _bsky_post("r1"), "replies": [
            {"post": _bsky_post("r2"), "replies": [
                {"post": _bsky_post("x9", did=OTHER, created="2026-10-01T10:01:00Z")},
                {"post": _bsky_post("r3", created="2026-10-01T10:02:00Z")}]}]}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            parsed = ParsedPost("bluesky", "r2", "anna.bsky.social", "https://bsky.app/profile/x/post/r2", DID)
            return await BlueskyService().thread_chain(parsed, client)

    chain = asyncio.run(run())
    assert [p.post_id for p in chain] == ["r1", "r2", "r3"]
    assert all(p.author_did == DID for p in chain)


def test_bluesky_thread_chain_falls_back_on_errors():
    async def run():
        transport = httpx.MockTransport(lambda r: httpx.Response(500))
        async with httpx.AsyncClient(transport=transport) as client:
            parsed = ParsedPost("bluesky", "r1", "a.bsky.social", "u", DID)
            return await BlueskyService().thread_chain(parsed, client)
    assert [p.post_id for p in asyncio.run(run())] == ["r1"]


# --- Thread-Erkennung: X (rueckwaerts ueber das Embed-Backend) -------------------------------

def test_x_thread_chain_walks_back_to_start():
    tweets = {
        "3": {"user": {"screen_name": "naval"}, "in_reply_to_status_id_str": "2", "in_reply_to_screen_name": "naval"},
        "2": {"user": {"screen_name": "naval"}, "in_reply_to_status_id_str": "1", "in_reply_to_screen_name": "naval"},
        "1": {"user": {"screen_name": "naval"}, "in_reply_to_status_id_str": "0", "in_reply_to_screen_name": "jemand"},
    }

    def handler(request: httpx.Request):
        tid = request.url.params["id"]
        assert request.url.params["token"] == _syndication_token(tid)
        return httpx.Response(200, json=tweets[tid]) if tid in tweets else httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await XService().thread_chain(XService().parse_url("https://x.com/naval/status/3"), client)

    chain = asyncio.run(run())
    assert [p.post_id for p in chain] == ["1", "2", "3"]
    assert chain[0].canonical_url == "https://x.com/naval/status/1"


def test_syndication_token_shape():
    tok = _syndication_token("1002103497725173760")
    assert tok and "." not in tok and tok.isalnum()


# --- Thread zusammenkleben im Worker -----------------------------------------------------------

class ThreadService:
    name = "bluesky"
    label = "Bluesky"
    prefers_api_text = True

    def __init__(self, chain_ids, heights=(300, 200, 250)):
        self.chain_ids, self.heights = chain_ids, heights

    def parse_url(self, url):
        return ParsedPost("bluesky", url.rsplit("/", 1)[-1], "anna.bsky.social", url, DID)

    def dedup_key(self, parsed):
        return f"bluesky:{parsed.author_did}:{parsed.post_id}"

    async def resolve(self, parsed, client):
        return parsed

    async def thread_chain(self, parsed, client):
        return [ParsedPost("bluesky", i, "anna.bsky.social", f"https://bsky.app/profile/{DID}/post/{i}", DID)
                for i in self.chain_ids]

    async def fetch_metadata(self, parsed, client):
        return PostMetadata(text=f"Teil {parsed.post_id}", handle="anna.bsky.social", did=DID)

    async def capture(self, parsed, browser, target, dark=True):
        h = self.heights[self.chain_ids.index(parsed.post_id) % len(self.heights)]
        Image.new("RGB", (600, h), (0, 0, 0)).save(target)
        return CaptureResult(screenshot=target)


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        worker = CaptureWorker(h.settings, h.app.state.SessionLocal)

        async def fake_browser():
            return object()
        monkeypatch.setattr(worker, "_get_browser", fake_browser)
        yield h, worker


def _post(h, rkey="t2", mode="auto", extra=""):
    with h.db() as db:
        p = Post(platform="bluesky", url=f"https://bsky.app/profile/{DID}/post/{rkey}", post_id=rkey,
                 dedup_key=f"bluesky:{DID}:{rkey}", author_handle="anna.bsky.social", author_did=DID,
                 thread_mode=mode, thread_extra=extra)
        db.add(p)
        db.commit()
        return p.id


def test_worker_stitches_manual_thread_as_webp(worker_env, monkeypatch):
    """Seit 0.6.1 nur von Hand ergaenzte Teile - die werden geklebt wie frueher."""
    h, worker = worker_env
    extra = json.dumps([f"https://bsky.app/profile/{DID}/post/t2", f"https://bsky.app/profile/{DID}/post/t3"])
    pid = _post(h, "t1", mode="off", extra=extra)
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: ThreadService(["t1", "t2", "t3"]))
    asyncio.run(worker.process(pid))
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.status == "done", p.status_message
        assert p.thread_count == 3 and [x["post_id"] for x in p.thread_list] == ["t1", "t2", "t3"]
        assert p.text == "Teil t1\n\nTeil t2\n\nTeil t3"
        assert p.screenshot_path.endswith(".webp")
        with Image.open(h.settings.base_path / p.screenshot_path) as img:
            assert img.format == "WEBP"
            assert img.size == (600, 300 + 200 + 250 + 2 * shots.THREAD_GAP)
    # keine Rohdateien liegen geblieben
    assert not list(h.settings.screenshot_dir.rglob("*.teil*.png"))


def test_worker_ignores_old_auto_mode(worker_env, monkeypatch):
    """Alte Beitraege mit thread_mode "auto": keine automatische Suche mehr."""
    h, worker = worker_env
    pid = _post(h, "t2", mode="auto")
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: ThreadService(["t1", "t2", "t3"]))
    asyncio.run(worker.process(pid))
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.thread_count == 0 and p.post_id == "t2" and p.text == "Teil t2"


def test_worker_thread_off_takes_single_post(worker_env, monkeypatch):
    h, worker = worker_env
    pid = _post(h, "t2", mode="off")
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: ThreadService(["t1", "t2", "t3"]))
    asyncio.run(worker.process(pid))
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.thread_count == 0 and p.post_id == "t2" and p.text == "Teil t2"


def test_worker_manual_extra_parts(worker_env, monkeypatch):
    h, worker = worker_env
    extra = json.dumps([f"https://bsky.app/profile/{DID}/post/t5", f"https://bsky.app/profile/{DID}/post/t1"])
    pid = _post(h, "t1", mode="off", extra=extra)
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: ThreadService(["t1", "t5"]))
    asyncio.run(worker.process(pid))
    with h.db() as db:
        p = db.get(Post, pid)
        assert [x["post_id"] for x in p.thread_list] == ["t1", "t5"]  # Duplikat t1 ignoriert


# --- Hinzufuegen mit Thread-Optionen ----------------------------------------------------------

def test_add_with_manual_thread_parts(user_client, harness):
    r = _add(user_client, "https://x.com/naval/status/1",
             thread_extra="https://x.com/naval/status/2\n\nhttps://twitter.com/naval/status/3")
    assert r.status_code == 303
    with harness.db() as db:
        p = db.query(Post).one()
        assert p.thread_mode == "off"
        assert json.loads(p.thread_extra) == ["https://x.com/naval/status/2", "https://x.com/naval/status/3"]
    r = _add(user_client, "https://x.com/naval/status/10", thread_extra="https://bsky.app/profile/a.bsky.social/post/3k")
    assert r.status_code == 400 and "passen nicht" in r.text
    # Kein Kaestchen "automatisch erkennen" mehr im Formular
    assert 'name="thread_mode"' not in user_client.get("/add").text


def test_rethread_existing_post(user_client, harness):
    _add(user_client, "https://x.com/naval/status/30")
    pid = _ids(harness)[0]
    with harness.db() as db:
        db.get(Post, pid).status = "done"
        db.commit()
    r = user_client.post(f"/posts/{pid}/thread", data={"thread_extra": "https://x.com/naval/status/31",
                                                       "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        p = db.get(Post, pid)
        assert p.status == "pending" and p.thread_mode == "off" and "31" in p.thread_extra
    page = user_client.get(f"/posts/{pid}").text
    assert "Thread" in page and 'name="thread_mode"' not in page


def test_link_check_has_no_thread_lookup(user_client, harness, monkeypatch):
    harness.settings.network_enabled = True

    async def fake_chain(self, parsed, client):
        raise AssertionError("keine automatische Thread-Suche mehr")
    monkeypatch.setattr(XService, "thread_chain", fake_chain)
    html = user_client.get("/posts/check?url=https://x.com/naval/status/3").text
    assert "bereit" in html
    harness.settings.network_enabled = False


# --- WebP & Auslieferung ----------------------------------------------------------------------

def test_convert_existing_png_to_webp(harness):
    png = harness.settings.screenshot_dir / "x" / "2026" / "alt.png"
    png.parent.mkdir(parents=True)
    Image.new("RGB", (400, 200), (21, 32, 43)).save(png)
    with harness.db() as db:
        db.add(Post(platform="x", url="https://x.com/a/status/5", dedup_key="x:5", post_id="5",
                    screenshot_path="screenshots/x/2026/alt.png", status="done"))
        db.commit()
        (harness.settings.screenshot_dir / ".webp-v1").unlink()
        assert shots.convert_existing(db, harness.settings) == 1
        p = db.query(Post).one()
        assert p.screenshot_path == "screenshots/x/2026/alt.webp"
    assert not png.exists() and png.with_suffix(".webp").exists()


def test_media_serves_webp_and_jpeg(user_client, harness):
    f = harness.settings.screenshot_dir / "x" / "2026" / "m.webp"
    f.parent.mkdir(parents=True)
    Image.new("RGB", (300, 100), (200, 0, 0)).save(f, "WEBP")
    r = user_client.get("/media/screenshots/x/2026/m.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    r = user_client.get("/media/screenshots/x/2026/m.webp?as=jpg&download=1")
    assert r.headers["content-type"] == "image/jpeg" and 'filename="m.jpg"' in r.headers["content-disposition"]
    assert Image.open(io.BytesIO(r.content)).format == "JPEG"


def test_stitch_centers_narrow_parts():
    a = Image.new("RGB", (600, 100), (1, 2, 3))
    b = Image.new("RGB", (400, 50), (200, 200, 200))
    out = shots.stitch([a, b], gap=10)
    assert out.size == (600, 160)
    assert out.getpixel((50, 130)) == (1, 2, 3)        # Rand neben dem schmalen Teil = Hintergrund
    assert out.getpixel((300, 130)) == (200, 200, 200)
