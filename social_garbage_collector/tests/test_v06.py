"""0.6.0: Quellenarchiv - Personen/Accounts, Zitatkarte, Quellenangabe, X-Wortlaut,
keine Social-Funktionen mehr."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.models import Account, AccountChange, AdminLog, Person, Post
from app.services import accounts
from app.services import capture as capture_mod
from app.services.capture import CaptureWorker
from app.services.citation import citation
from app.services.platforms.base import PostMetadata, PostNotFound
from app.services.platforms.x import XService, metadata_from_syndication, tweet_text

from .conftest import Harness, make_settings


def _add(client, url):
    return client.post("/posts", data={"url": url, "csrf_token": client.csrf})


# --- Accounts: feste ID, Verlauf, Aufwerten ------------------------------------------

def test_handle_only_account_upgraded_and_changes_recorded(harness):
    with harness.db() as db:
        a = accounts.resolve(db, "x", None, "@altername", "Alter Name")
        assert a.stable_id is None and a.person.name == "Alter Name"
        # Spaeter kennt die App die feste ID - derselbe Datensatz wird aufgewertet.
        b = accounts.resolve(db, "x", "12345", "altername", "Alter Name")
        assert b.id == a.id and b.stable_id == "12345"
        # Umbenennung: gleicher Account, Verlauf waechst, Person heisst mit
        c = accounts.resolve(db, "x", "12345", "neuername", "Neuer Name")
        assert c.id == a.id and c.handle == "neuername"
        fields = sorted(ch.field for ch in db.query(AccountChange))
        assert fields == ["display_name", "handle"]
        assert c.person.name == "Neuer Name"
        assert db.query(Account).count() == 1 and db.query(Person).count() == 1


def test_locked_person_name_is_kept(harness):
    with harness.db() as db:
        a = accounts.resolve(db, "bluesky", "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", "a.bsky.social", "A")
        accounts.rename_person(a.person, "Annette Beispiel", "Ministerin")
        accounts.resolve(db, "bluesky", "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", "a.bsky.social", "A (Urlaub)")
        assert a.person.name == "Annette Beispiel" and a.person.name_locked


def test_unbound_duplicate_is_merged_into_known_account(harness):
    """Erst per Upload (nur Handle), dann per Link (mit ID) - am Ende EIN Account."""
    with harness.db() as db:
        known = accounts.resolve(db, "x", "777", "jemand", "Jemand")
        loose = accounts.resolve(db, "x", None, "jemand_alt", "")
        p = Post(platform="x", url="", dedup_key="upload:1", post_id="u1", author_handle="jemand_alt")
        db.add(p)
        db.flush()
        accounts.attach(db, p, loose)
        # Die Plattform verraet: jemand_alt hat die ID 777 (alter Handle)
        accounts.resolve(db, "x", "777", "jemand_alt", "Jemand")
        db.commit()
        assert db.query(Account).count() == 1
        assert db.get(Post, p.id).account_id == known.id
        assert db.query(Person).count() == 1


def test_ensure_for_post_and_startup_backfill(tmp_path):
    """Alte Daten (vor 0.6): Aussagen ohne Account bekommen beim Start einen."""
    settings = make_settings(tmp_path)
    h = Harness(settings)
    with TestClient(h.app):
        with h.db() as db:
            db.add_all([
                Post(platform="x", url="https://x.com/a/status/1", dedup_key="x:1", post_id="1", author_handle="a"),
                Post(platform="x", url="https://x.com/a/status/2", dedup_key="x:2", post_id="2", author_handle="A"),
                Post(platform="bluesky", url="https://bsky.app/profile/did:plc:bbbbbbbbbbbbbbbbbbbbbbbb/post/3k",
                     dedup_key="b:1", post_id="3k", author_did="did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"),
            ])
            db.commit()
    with TestClient(h.app):  # zweiter Start: backfill
        with h.db() as db:
            assert db.query(Post).filter(Post.account_id.is_(None)).count() == 0
            # X-Handles ohne Ruecksicht auf Gross-/Kleinschreibung -> ein Account
            assert db.query(Account).filter_by(platform="x").count() == 1
            assert db.query(Account).filter_by(platform="bluesky").one().stable_id.startswith("did:plc:")


def test_new_post_gets_account_immediately(user_client, harness):
    _add(user_client, "https://x.com/jack/status/20")
    with harness.db() as db:
        post = db.query(Post).one()
        assert post.account is not None and post.account.handle == "jack"
        assert post.account.person.name == "@jack"


# --- Personen: Seiten, Zusammenfuehren, Trennen --------------------------------------

def _two_people(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    _add(user_client, "https://bsky.app/profile/olaf.bsky.social/post/3kabc")
    with harness.db() as db:
        x = db.query(Account).filter_by(platform="x").one()
        b = db.query(Account).filter_by(platform="bluesky").one()
        return x.person_id, b.person_id, x.id, b.id


def test_persons_pages_and_merge(user_client, admin_client, harness):
    px, pb, ax, ab = _two_people(user_client, harness)
    assert px != pb
    overview = user_client.get("/personen").text
    assert "@olaf" in overview and "@olaf.bsky.social" in overview
    assert "@olaf.bsky.social" in user_client.get("/personen?q=bsky", headers={"HX-Request": "true"}).text
    page = user_client.get(f"/personen/{px}").text
    assert "Zusammenführen" in page and "Feste Konto-ID noch unbekannt" in page
    r = user_client.post(f"/personen/{pb}/zusammenfuehren", data={"target_id": px, "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/personen/{px}")
    with harness.db() as db:
        assert db.get(Person, pb) is None
        assert {a.id for a in db.get(Person, px).accounts} == {ax, ab}
        assert db.query(AdminLog).filter_by(action="merge_persons").count() == 1
    # Archiv-Filter nach Person: beide Aussagen
    archive = user_client.get(f"/?person={px}").text
    assert archive.count('data-post="') == 2 and "Person:" in archive
    # Wieder trennen: eigener Account -> neue Person
    r = user_client.post(f"/accounts/{ab}/person", data={"person_id": "neu", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.get(Account, ab).person_id != px
        assert db.query(Person).count() == 2


def test_move_account_cleans_up_empty_person(user_client, harness):
    px, pb, ax, ab = _two_people(user_client, harness)
    user_client.post(f"/accounts/{ab}/person", data={"person_id": str(px), "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.get(Person, pb) is None  # automatisch angelegt, nie bearbeitet -> weg


def test_person_edit_and_merge_errors(user_client, harness):
    px, pb, *_ = _two_people(user_client, harness)
    user_client.post(f"/personen/{px}/bearbeiten", data={"name": "  Olaf   Beispiel ", "note": "Politiker",
                                                         "csrf_token": user_client.csrf})
    with harness.db() as db:
        p = db.get(Person, px)
        assert p.name == "Olaf Beispiel" and p.note == "Politiker" and p.name_locked
    r = user_client.post(f"/personen/{px}/zusammenfuehren", data={"target_id": px, "csrf_token": user_client.csrf})
    assert "zusammenfuehren" in r.headers["location"]
    assert user_client.get("/personen/9999").status_code == 404
    assert user_client.post("/accounts/9999/person", data={"person_id": "neu", "csrf_token": user_client.csrf}).status_code == 404
    # ohne CSRF nichts
    assert user_client.post(f"/personen/{px}/bearbeiten", data={"name": "x"}).status_code == 403


def test_persons_require_login(harness):
    with harness.client() as c:
        assert c.get("/personen").status_code == 303
        assert c.get("/authors/abc.webp").status_code == 303


def test_author_avatar_route_is_safe(user_client, harness):
    d = harness.settings.author_dir
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10)).save(d / "abc.webp", "WEBP")
    assert user_client.get("/authors/abc.webp").status_code == 200
    assert user_client.get("/authors/..%2Fdb%2Farchiv.sqlite").status_code == 404
    assert user_client.get("/authors/abc.png").status_code == 404


# --- Zitatkarte und Quellenangabe ---------------------------------------------------

def test_quote_card_and_citation(user_client, harness):
    _add(user_client, "https://x.com/jack/status/20")
    with harness.db() as db:
        p = db.query(Post).one()
        p.text, p.author_display_name, p.status = "just setting up my twttr", "jack", "done"
        p.posted_at = datetime(2006, 3, 21, 20, 50)
        db.commit()
        pid = p.id
    page = user_client.get("/?view=timeline").text
    assert 'class="quote ' in page and "just setting up my twttr" in page and "Nr. 000001" in page
    detail = user_client.get(f"/posts/{pid}").text
    assert "Quellenangabe" in detail and "Archiv-Nr." in detail
    with harness.db() as db:
        text = citation(db.get(Post, pid))
    assert text.startswith("jack (@jack): „just setting up my twttr“.")
    assert "X (Twitter), 21.03.2006" in text and "https://x.com/jack/status/20" in text and "Archiv-Nr. 000001" in text


def test_citation_without_link_or_date(harness):
    p = Post(id=7, platform="bluesky", url="", text="", author_handle="", created_at=datetime(2026, 1, 2, 10))
    text = citation(p)
    assert text.startswith("Unbekannt.") and "Datum unbekannt" in text and "Originallink unbekannt" in text


def test_sorted_and_filtered_by_date_of_statement(user_client, harness):
    _add(user_client, "https://x.com/a/status/1")
    _add(user_client, "https://x.com/a/status/2")
    with harness.db() as db:
        p1, p2 = db.query(Post).order_by(Post.id).all()
        p1.posted_at, p2.posted_at = datetime(2024, 5, 1), datetime(2019, 5, 1)
        p1.text, p2.text = "neuere Aussage", "aeltere Aussage"
        db.commit()
    page = user_client.get("/?sort=posted").text  # nach Datum der Aussage, neueste zuerst
    assert page.index("neuere Aussage") < page.index("aeltere Aussage")
    page = user_client.get("/").text  # 0.12: Standard = zuletzt archiviert
    assert page.index("aeltere Aussage") < page.index("neuere Aussage")
    page = user_client.get("/?sort=posted_old").text
    assert page.index("aeltere Aussage") < page.index("neuere Aussage")
    page = user_client.get("/?from=2019-01-01&to=2019-12-31").text
    assert "aeltere Aussage" in page and "neuere Aussage" not in page


# --- Social-Funktionen sind weg ------------------------------------------------------

def test_social_features_removed(user_client, harness):
    _add(user_client, "https://x.com/a/status/1")
    assert user_client.get("/random").status_code == 404
    assert user_client.post("/seen", data={"csrf_token": user_client.csrf}).status_code in (404, 405)
    assert user_client.post("/account/disco", data={"csrf_token": user_client.csrf}).status_code in (404, 405)
    assert user_client.post("/posts/1/react/lol", data={"csrf_token": user_client.csrf}).status_code in (404, 405)
    html = user_client.get("/").text + user_client.get("/posts/1").text + user_client.get("/settings").text
    for word in ("Tonne", "Zufallsfund", "neu für dich", "disco", "data-version", "Reaktion"):
        assert word not in html, word
    # Kein verstecktes Easter Egg mehr an der Versionsnummer
    assert "data-version" not in user_client.get("/settings/info").text


def test_old_database_drops_reactions(tmp_path):
    settings = make_settings(tmp_path)
    settings.db_dir.mkdir(parents=True)
    con = sqlite3.connect(settings.db_path)
    con.execute("CREATE TABLE reactions (post_id INTEGER, user_id INTEGER, kind VARCHAR(16))")
    con.commit()
    con.close()
    with TestClient(Harness(settings).app):
        tables = {r[0] for r in sqlite3.connect(settings.db_path).execute("SELECT name FROM sqlite_master")}
        assert "reactions" not in tables and {"persons", "accounts", "account_changes"} <= tables


# --- X: Wortlaut und Verfasser aus dem Embed-Backend ---------------------------------

SYNDICATION = {
    "__typename": "Tweet",
    "text": "@vorgaenger Das ist der Kern &amp; mehr: https://t.co/abc https://t.co/media",
    "display_text_range": [12, 77],
    "entities": {"urls": [{"url": "https://t.co/abc", "expanded_url": "https://beispiel.de/artikel"}],
                 "media": [{"url": "https://t.co/media"}]},
    "user": {"id_str": "783214", "name": "Beispiel Konto", "screen_name": "beispiel",
             "profile_image_url_https": "https://pbs.twimg.com/profile_images/1/abc_normal.jpg"},
    "created_at": "2023-02-06T12:34:56.000Z",
    "mediaDetails": [{"ext_alt_text": "Ein Diagramm"}],
}


def test_x_syndication_metadata():
    meta = metadata_from_syndication(SYNDICATION)
    assert meta.text == "Das ist der Kern & mehr: https://beispiel.de/artikel"
    assert meta.author_id == "783214" and meta.handle == "beispiel" and meta.display_name == "Beispiel Konto"
    assert meta.avatar_url.endswith("abc_400x400.jpg")
    assert meta.posted_at == datetime(2023, 2, 6, 12, 34, 56)
    assert meta.alt_texts == ["Ein Diagramm"]


def test_x_long_note_tweet_wins():
    data = dict(SYNDICATION, note_tweet={"note_tweet_results": {"result": {"text": "Sehr langer Text"}}})
    assert tweet_text(data) == "Sehr langer Text"


class _FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.content = data, status, b"x"

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    async def get(self, url, **kw):
        return _FakeResp(self.data, self.status)


def test_x_fetch_metadata_prefers_syndication_and_detects_tombstone():
    from app.services.platforms.x import XService as S

    svc = S()
    parsed = svc.parse_url("https://x.com/beispiel/status/123")
    meta = asyncio.run(svc.fetch_metadata(parsed, _FakeClient(SYNDICATION)))
    assert meta.author_id == "783214"
    with pytest.raises(PostNotFound):
        asyncio.run(svc.fetch_metadata(parsed, _FakeClient({"__typename": "TweetTombstone"})))
    assert XService.prefers_api_text is True


# --- Worker: Account + Profilbild ----------------------------------------------------

class MetaOnlyService:
    name = "x"
    label = "X"
    prefers_api_text = True

    async def thread_chain(self, parsed, client):
        return [parsed]

    async def fetch_metadata(self, parsed, client):
        return PostMetadata(text="Wortlaut", display_name="Neu", handle="neuer_handle", author_id="555",
                            avatar_url="https://pbs.twimg.com/profile_images/1/a_400x400.jpg")

    async def capture(self, parsed, browser, target, dark=True):
        from app.services.platforms.base import PlatformError

        raise PlatformError("kein Browser im Test")


def test_worker_assigns_account_and_avatar(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path))
    client = TestClient(h.app)
    client.__enter__()
    with h.db() as db:
        p = Post(platform="x", url="https://x.com/alter_handle/status/9", dedup_key="x:9", post_id="9",
                 author_handle="alter_handle", status="pending")
        db.add(p)
        db.commit()
        accounts.ensure_for_post(db, p)
        db.commit()
        pid = p.id

    async def fake_download(client, settings, url):
        settings.author_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(settings.author_dir / "f00.webp", "WEBP")
        return "authors/f00.webp"

    monkeypatch.setattr(capture_mod, "get_service", lambda _p: MetaOnlyService())
    monkeypatch.setattr(accounts, "download_avatar", fake_download)

    async def no_browser(self):
        return None

    monkeypatch.setattr(CaptureWorker, "_get_browser", no_browser)
    asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).process(pid))
    with h.db() as db:
        post = db.get(Post, pid)
        acc = post.account
        assert acc.stable_id == "555" and acc.handle == "neuer_handle"
        assert acc.avatar_path == "authors/f00.webp" and post.author_avatar_path == "authors/f00.webp"
        assert post.text == "Wortlaut"
        # Der alte Handle-Account wurde aufgewertet, nicht doppelt angelegt
        assert db.query(Account).count() == 1
        assert any(c.field == "handle" and c.old_value == "alter_handle" for c in acc.changes)
    client.__exit__(None, None, None)


def test_avatar_download_only_from_platform_hosts(harness):
    async def run(url):
        return await accounts.download_avatar(_FakeClient({}), harness.settings, url)

    assert asyncio.run(run("https://evil.example/a.jpg")) is None
    assert asyncio.run(run("http://pbs.twimg.com/a.jpg")) is None


# --- 0.6.2: OCR-Zeilen zu Absaetzen ----------------------------------------------------

def test_reflow_joins_ocr_lines():
    from app.services.ocr import reflow

    raw = ("Es darf auch noch Nein gesagt werden, wenn man schon\n"
           "gemeinsam nackt im Bett liegt. Ein Nein ist ein Nein und\n"
           "bedarf keiner Begrün-\ndung.\n\nZweiter Absatz\n- Punkt eins\n- Punkt zwei")
    out = reflow(raw)
    assert out == ("Es darf auch noch Nein gesagt werden, wenn man schon gemeinsam nackt im Bett liegt. "
                   "Ein Nein ist ein Nein und bedarf keiner Begründung.\n\n"
                   "Zweiter Absatz\n- Punkt eins\n- Punkt zwei")
    assert reflow(out) == out  # mehrfach anwenden aendert nichts
    assert reflow("E-\nMail") == "E- Mail"  # Grossbuchstabe danach: kein Trennstrich-Zusammenziehen


def test_existing_ocr_texts_reflowed_on_start(tmp_path):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        with h.db() as db:
            db.add_all([
                Post(platform="x", url="https://x.com/a/status/1", dedup_key="x:1", post_id="1",
                     text="eins\nzwei", text_source="ocr"),
                Post(platform="x", url="https://x.com/a/status/2", dedup_key="x:2", post_id="2",
                     text="bleibt\nso", text_source="manual"),
            ])
            db.commit()
    with TestClient(h.app):  # zweiter Start
        with h.db() as db:
            texts = {p.post_id: p.text for p in db.query(Post)}
    assert texts == {"1": "eins zwei", "2": "bleibt\nso"}
