"""0.21.0: Wiederholt erzaehlt, Geloescht-Waechter, Tags per Mehrfachauswahl, Suche mit Wortformen."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.models import Notification, Post, Tag, utcnow
from app.services import origin, repeats
from app.services.posts import fts_query, search_stem


def _add(client, url):
    assert client.post("/posts", data={"url": url, "csrf_token": client.csrf}).status_code == 303


def _texts(harness, client, texts, author="jack", start=100):
    for i, _ in enumerate(texts):
        _add(client, f"https://x.com/{author}/status/{start + i}")
    with harness.db() as db:
        ids = []
        for i, text in enumerate(texts):
            p = db.query(Post).filter_by(post_id=str(start + i)).one()
            p.text, p.status, p.posted_at = text, "done", datetime(2020 + i % 5, 1 + i % 12, 3)
            ids.append(p.id)
        db.commit()
        return ids


# --- Suche -------------------------------------------------------------------------------------

def test_search_stems():
    assert search_stem("Pakete") == "paket" and search_stem("verstorbene") == "verstorben"
    assert search_stem("Wohnungen") == "wohn" and search_stem("Kater") == "Kater"   # zu kurzer Stamm
    assert fts_query('"genau so" Hunde') == '"genau so" "hund"*'


def test_search_finds_word_forms(user_client, harness):
    _texts(harness, user_client, ["Wieder ein Paket verschwunden.", "Die Nachbarin ist verstorben."])
    assert "Paket verschwunden" in user_client.get("/?q=Pakete").text
    assert "Nachbarin ist verstorben" in user_client.get("/?q=verstorbene").text
    assert "Paket verschwunden" not in user_client.get('/?q="Pakete"').text   # Anfuehrungszeichen = exakt


# --- Tags per Mehrfachauswahl --------------------------------------------------------------------

def test_bulk_tags_add_and_remove(user_client, harness):
    ids = _texts(harness, user_client, ["eins", "zwei", "drei"])
    page = user_client.get("/").text
    assert 'data-bulk-tags' in page and 'id="bulk-tags-dialog"' in page
    r = user_client.post("/posts/bulk/tags", data={"ids": ids[:2], "tags": "neu, Zweites", "mode": "add",
                                                   "back": "/?q=x", "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith("/?q=x")
    with harness.db() as db:
        names = lambda i: sorted(t.name for t in db.get(Post, i).tags)
        assert names(ids[0]) == ["neu", "zweites"] and names(ids[2]) == []
    user_client.post("/posts/bulk/tags", data={"ids": ids, "tags": "neu", "mode": "remove", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert sorted(t.name for t in db.get(Post, ids[0]).tags) == ["zweites"]
        assert db.query(Tag).filter_by(name="neu").first() is None      # verwaist -> weg
    r = user_client.post("/posts/bulk/tags", data={"ids": ids, "tags": "", "csrf_token": user_client.csrf})
    assert r.status_code == 303


# --- Geloescht-Waechter -------------------------------------------------------------------------

def test_origin_record_needs_two_misses(user_client, harness):
    ids = _texts(harness, user_client, ["Original"])
    with harness.db() as db:
        post = db.get(Post, ids[0])
        assert post in origin.due(db)                       # noch nie geprueft
        assert origin.record(db, post, origin.GONE) is False and post.origin_state == ""
        assert origin.record(db, post, origin.GONE) is True and post.origin_state == "gone"
        assert db.query(Notification).filter_by(kind="gone", post_id=post.id).count() == 1
        db.commit()
        assert post not in origin.due(db)                   # gerade geprueft
        post.origin_checked_at = utcnow() - timedelta(days=8)
        assert post in origin.due(db)                       # weg: ab und zu nachsehen
        assert origin.record(db, post, origin.ONLINE) is False
        assert post.origin_state == "online" and post.origin_gone_at is None and post.origin_misses == 0
        assert origin.record(db, post, None) is False and post.origin_state == "online"   # keine Aussage
        db.commit()


def test_origin_probe_and_views(user_client, harness, monkeypatch):
    from app.services.platforms.base import PlatformError, PostNotFound

    class Fake:
        def __init__(self, exc=None):
            self.exc = exc

        async def fetch_metadata(self, parsed, client):
            if self.exc:
                raise self.exc
            return object()

    ids = _texts(harness, user_client, ["Bald weg", "Bleibt"])
    with harness.db() as db:
        post = db.get(Post, ids[0])
        monkeypatch.setattr(origin, "get_service", lambda p: Fake(PostNotFound("weg")))
        assert asyncio.run(origin.probe(post, None)) == origin.GONE
        monkeypatch.setattr(origin, "get_service", lambda p: Fake(PlatformError("Bot-Wand")))
        assert asyncio.run(origin.probe(post, None)) is None
        monkeypatch.setattr(origin, "get_service", lambda p: Fake())
        assert asyncio.run(origin.probe(post, None)) == origin.ONLINE
    # Knopf "Jetzt pruefen" - zweimal weg (im Test ist das Netz sonst aus)
    monkeypatch.setattr(harness.settings, "network_enabled", True)
    monkeypatch.setattr(origin, "get_service", lambda p: Fake(PostNotFound("weg")))
    r = user_client.post(f"/posts/{ids[0]}/original", data={"csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith("#original")
    user_client.post(f"/posts/{ids[0]}/original", data={"csrf_token": user_client.csrf})
    detail = user_client.get(f"/posts/{ids[0]}").text
    assert "Original nicht mehr online" in detail and 'id="original"' in detail
    assert user_client.get(f"/posts/{ids[1]}").text.count("Original noch nicht geprüft") == 1
    weg = user_client.get("/?original=weg&view=raster").text
    assert "Bald weg" in weg and "Bleibt" not in weg and 'class="q-gone"' in weg and "Original nicht mehr online" in weg
    notes = user_client.get("/benachrichtigungen").text
    assert "Original nicht mehr online" in notes


# --- Wiederholt erzaehlt -----------------------------------------------------------------------------

STORIES = [
    "Und wenn eine Frau nackt in meinem Bett liegt, darf sie immer noch NEIN sagen. Dann kuscheln wir halt.",
    "Bei mir darf eine Frau jederzeit Stopp sagen, auch wenn wir schon nackt im Bett liegen.",
    "Ein NEIN bleibt ein NEIN, auch wenn man schon nackt zusammen im Bett liegt.",
    "Ich wünsche mir die DVD vom Sommernachtstraum in der deutschen Fassung.",
    "Hat jemand den Sommernachtstraum auf DVD für mich? Gerne deutsche Fassung.",
    "Heute ist meine Bekannte aus Köln verstorben, sie wurde nur 70.",
    "Ein Kollege vom Sportverein ist gestern verstorben, ganz plötzlich.",
    "Mein Onkel in Bremen ist verstorben, die Beerdigung ist am Freitag.",
    "Der Igel im Garten frisst wieder fleißig sein Futter.",
    "Neue Kamera bestellt, hoffentlich kommt sie heil an.",
]


def test_find_repeats_not_themes():
    items = [repeats.Item(i, datetime(2020 + i % 4, 1, 1), t) for i, t in enumerate(STORIES)]
    clusters = repeats.find(items)
    groups = sorted(sorted(c.ids) for c in clusters)
    assert [0, 1, 2] in groups and [3, 4] in groups
    assert not any({5, 6} <= set(g) or {6, 7} <= set(g) for g in groups)   # nur gleiches Thema "verstorben"
    big = next(c for c in clusters if 0 in c.ids)
    assert "nackt" in big.words and big.span


def test_repeats_on_person_and_post_page(user_client, harness):
    ids = _texts(harness, user_client, STORIES)
    with harness.db() as db:
        pid = db.get(Post, ids[0]).account.person_id
    page = user_client.get(f"/personen/{pid}").text
    assert "Wiederholt erzählt" in page and "3×" in page and "2×" in page and "Festhalten" in page
    detail = user_client.get(f"/posts/{ids[1]}").text
    assert "Auch so erzählt" in detail and "dieses Posting" in detail and f'/posts/{ids[0]}' in detail
    assert 'id="post-repeat-title"' not in user_client.get(f"/posts/{ids[9]}").text
    form = user_client.get(f"/recherche/neu?posts={ids[3]},{ids[4]}&titel=Wiederholt").text
    assert f'name="post_ids" value="{ids[3]}"' in form and 'value="Wiederholt"' in form
