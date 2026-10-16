"""0.15.0: Tags als Knopf + "#tag" in der Suche, Recherche-Arbeitsplatz, einheitliche Seitenkoepfe."""

from __future__ import annotations

import json

from app.models import ResearchNote
from app.routers.research import auto_title
from app.services.posts import split_hashtags


def _add(client, url, tags=""):
    assert client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf}).status_code == 303


def _person_of(harness, post_id):
    from app.models import Post
    with harness.db() as db:
        return db.get(Post, post_id).account.person_id


# --- Tags im Idiotarium ------------------------------------------------------------------------

def test_hashtags_in_search():
    assert split_hashtags("energie #Klima  #verkehr-wende") == ("energie", ["klima", "verkehr-wende"])
    assert split_hashtags("ohne") == ("ohne", [])


def test_tag_button_panel_and_hash_search(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="klima")
    _add(user_client, "https://x.com/a/status/2", tags="energie")
    page = user_client.get("/").text
    assert 'data-toggle="tag-panel"' in page and 'id="tag-panel"' in page and "data-tag-bar" not in page
    hits = user_client.get("/?q=%23klima").text
    assert hits.count('data-post="') == 1 and "chip-off" in hits
    # x am Tag-Chip entfernt auch das "#klima" aus der Suche
    assert 'href="/?" title="Filter entfernen"' in hits
    pick = user_client.get("/tags/suggest", params={"tq": "kl", "mode": "pick"}).text
    assert 'data-tag-pick="klima"' in pick and "data-tag-new" not in pick


# --- Recherche-Arbeitsplatz ----------------------------------------------------------------------

def test_research_hub_pane_and_index(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    pid = _person_of(harness, 1)
    hub = user_client.get("/recherche").text
    assert 'id="rs-index"' in hub and 'id="rs-pane"' in hub and "Was habt ihr herausgefunden?" in hub
    # im Arbeitsplatz anlegen (htmx, rechts): Titel aus der ersten Zeile
    r = user_client.post("/recherche", data={"body": "Erst dafür, dann dagegen. Belegt durch zwei Postings.",
                                             "post_ids": ["1"], "kind": "widerspruch", "csrf_token": user_client.csrf},
                         headers={"HX-Request": "true", "HX-Target": "rs-pane"})
    assert r.status_code == 200 and "rs-read" in r.text
    assert "research-changed" in json.loads(r.headers["HX-Trigger"]) and "id=" in r.headers["HX-Push-Url"]
    with harness.db() as db:
        note = db.query(ResearchNote).one()
        assert note.title == "Erst dafür, dann dagegen." and [p.id for p in note.persons] == [pid]
        nid = note.id
    # Fehler im Arbeitsplatz: Formular bleibt (200, damit htmx tauscht)
    r = user_client.post("/recherche", data={"body": "", "csrf_token": user_client.csrf},
                         headers={"HX-Request": "true", "HX-Target": "rs-pane"})
    assert r.status_code == 200 and "mindestens einen Satz" in r.text
    # Liste links und Detail rechts einzeln abrufbar
    idx = user_client.get("/recherche?ansicht=personen", headers={"HX-Request": "true", "HX-Target": "rs-index"}).text
    assert idx.startswith('\n<div class="rs-index"') or 'class="rs-index"' in idx[:200]
    assert "rs-group-head" in idx
    pane = user_client.get(f"/recherche/{nid}", headers={"HX-Request": "true", "HX-Target": "rs-pane"}).text
    assert "<html" not in pane and "Erst dafür" in pane
    editor = user_client.get(f"/recherche/{nid}/bearbeiten", headers={"HX-Request": "true", "HX-Target": "rs-pane"}).text
    assert f'hx-post="/recherche/{nid}"' in editor and 'name="post_ids" value="1"' in editor
    assert "Erst dafür" in user_client.get(f"/recherche?id={nid}").text


def test_research_pickers(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    persons = user_client.get("/recherche/suche/personen", params={"q": "ola"}).text
    assert "data-picker-add" in persons and "@olaf" in persons
    posts = user_client.get("/recherche/suche/postings", params={"q": "000001"}).text
    assert 'data-id="1"' in posts


def test_auto_title():
    assert auto_title("Kurz. Und mehr.") == "Kurz."
    assert auto_title("\n\nZweite Zeile zuerst") == "Zweite Zeile zuerst"
    assert auto_title("wort " * 40).endswith(" …") and len(auto_title("wort " * 40)) <= 112


# --- Seitenkoepfe --------------------------------------------------------------------------------

def test_unified_page_headers(user_client, harness):
    for path in ("/", "/personen", "/lists", "/galerie", "/ideen", "/generator", "/recherche"):
        assert 'class="page-header' in user_client.get(path).text, path
    user_client.post("/lists", data={"title": "Klima", "csrf_token": user_client.csrf})
    page = user_client.get("/lists/1").text
    assert 'class="page-header list-header"' in page and 'data-edit="title"' in page


# --- 0.16: Fehlerseite statt "Internal Server Error" -----------------------------------------------

def test_server_error_page(harness, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.routers import lists as lists_router
    from .conftest import USER_PW, login

    def boom(*a, **kw):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    from fastapi.testclient import TestClient

    with TestClient(harness.app, follow_redirects=False, raise_server_exceptions=False) as c:
        login(c, "anna", USER_PW)
        monkeypatch.setattr(lists_router, "render", boom)
        r = c.get("/lists")
        assert r.status_code == 503 and "gerade beschäftigt" in r.text and "Noch einmal versuchen" in r.text
        r = c.get("/lists", headers={"HX-Request": "true"})
        assert r.status_code == 503 and "toast" in r.headers["HX-Trigger"]


def test_worker_keeps_no_write_lock_during_downloads(tmp_path, monkeypatch):
    """Waehrend Medien laden darf SQLite nicht gesperrt sein - sonst warten
    Web-Anfragen bis zum Timeout und enden in Fehler 500."""
    import asyncio

    from PIL import Image

    from app.models import Post
    from app.services import capture as capture_mod
    from app.services import media
    from app.services.capture import CaptureWorker
    from app.services.platforms.base import PostMetadata
    from fastapi.testclient import TestClient

    from .conftest import Harness, make_settings

    class Service:
        name, label, prefers_api_text = "x", "X", True

        async def fetch_metadata(self, parsed, client):
            return PostMetadata(display_name="Jack", handle="jack", text="hallo", author_id="12")

    seen = []

    async def fake_save_media(db, settings, client, post, refs):
        raw = db.connection().connection.dbapi_connection
        seen.append(raw.in_transaction)
        return []

    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        shot = h.settings.screenshot_dir / "x" / "2026" / "u.webp"
        shot.parent.mkdir(parents=True)
        Image.new("RGB", (40, 40)).save(shot, "WEBP")
        with h.db() as db:
            p = Post(platform="x", url="https://x.com/jack/status/20", dedup_key="x:20", post_id="20",
                     shot_source="upload", screenshot_path="screenshots/x/2026/u.webp", status="pending")
            db.add(p)
            db.commit()
            pid = p.id
        monkeypatch.setattr(capture_mod, "get_service", lambda _p: Service())
        monkeypatch.setattr(media, "save_media", fake_save_media)
        asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).process(pid))
    assert seen == [False]


def test_error_pages_do_not_leak_db_connections(user_client, harness):
    """0.16: Jede 404/403-Seite liess eine DB-Verbindung offen - nach 15 Stueck
    war der Pool leer und alles lief in Fehler 500."""
    pool = harness.app.state.SessionLocal.kw["bind"].pool
    for i in range(40):
        assert user_client.get(f"/posts/{900000 + i}").status_code == 404
        assert user_client.get(f"/recherche/{900000 + i}").status_code == 404
    assert pool.checkedout() == 0
    assert user_client.get("/").status_code == 200


# --- 0.16: Herzen, Listen-Ansichten, Thread-Belege ----------------------------------------------

def test_hearts_and_herzstuecke(user_client, admin_client, harness):
    from app.models import Post
    _add(user_client, "https://x.com/a/status/1")
    _add(user_client, "https://x.com/a/status/2")
    r = user_client.post("/posts/2/herz", data={"csrf_token": user_client.csrf}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'aria-pressed="true"' in r.text and "is-on" in r.text
    admin_client.post("/posts/2/herz", data={"csrf_token": admin_client.csrf}, headers={"HX-Request": "true"})
    admin_client.post("/posts/1/herz", data={"csrf_token": admin_client.csrf}, headers={"HX-Request": "true"})
    with harness.db() as db:
        assert db.get(Post, 2).hearts == 2 and db.get(Post, 1).hearts == 1
    page = user_client.get("/lists/herzstuecke").text
    assert page.index('data-post="2"') < page.index('data-post="1"')  # meiste Herzen zuerst
    assert "Herzstücke" in user_client.get("/lists").text
    assert user_client.get("/?sort=herzen").text.count('data-post="') == 2
    # zuruecknehmen
    r = user_client.post("/posts/2/herz", data={"csrf_token": user_client.csrf}, headers={"HX-Request": "true"})
    assert 'aria-pressed="false"' in r.text
    with harness.db() as db:
        assert db.get(Post, 2).hearts == 1


def test_list_views(user_client, harness):
    from app.prefs import get_prefs
    _add(user_client, "https://x.com/a/status/1")
    user_client.post("/lists", data={"title": "Klima", "csrf_token": user_client.csrf})
    user_client.post("/posts/1/lists/1/toggle", data={"csrf_token": user_client.csrf})
    assert 'class="qtile"' in user_client.get("/lists/1").text  # Standard: Raster
    assert 'class="qrow"' in user_client.get("/lists/1?view=list").text
    assert get_prefs(harness.get_user("anna"))["list_view"] == "list"
    assert 'class="list-rows"' in user_client.get("/lists?ansicht=rows").text
    assert 'class="list-tiles"' in user_client.get("/lists?ansicht=tiles").text
    assert 'view=cards' not in user_client.get("/").text  # Karten-Ansicht entfallen


def test_thread_parts_know_their_position():
    from app.services.platforms import bluesky, x
    from app.services.platforms.base import ParsedPost
    assert ParsedPost("x", "1", "a", "u").thread_index == 0
    assert "tweetText" in x.CLEAN_JS and "Folgen" in x.CLEAN_JS
    assert "#app p" in bluesky.CLEAN_JS
