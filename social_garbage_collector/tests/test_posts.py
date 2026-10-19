"""Archiv: Hinzufuegen, Duplikate, Tags, Volltextsuche, Listen, Generator-Seite."""

from __future__ import annotations

from app.models import TEXT_MANUAL, Post, PostList, SavedSearch
from app.services.posts import fts_query, normalize_tag, parse_tag_input


def _add(client, url, note="", tags=""):
    return client.post("/posts", data={"url": url, "note": note, "tags": tags, "csrf_token": client.csrf})


def test_add_post_and_duplicate(user_client, harness):
    r = _add(user_client, "https://twitter.com/jack/status/20", note="Der Anfang", tags="Geschichte, #Humor")
    assert r.status_code == 303
    with harness.db() as db:
        post = db.query(Post).one()
        assert post.platform == "x" and post.post_id == "20" and post.author_handle == "jack"
        assert post.url == "https://x.com/jack/status/20"
        assert post.status == "pending"
        assert sorted(t.name for t in post.tags) == ["geschichte", "humor"]
    dup = _add(user_client, "https://x.com/jemand/status/20?s=1")
    assert dup.status_code == 400
    assert "schon im Archiv" in dup.text


def test_add_invalid_url(user_client):
    r = _add(user_client, "https://example.com/irgendwas")
    assert r.status_code == 400
    assert "kein unterstützter Beitrags-Link" in r.text


def test_bluesky_duplicate_by_handle_case(user_client):
    assert _add(user_client, "https://bsky.app/profile/alice.bsky.social/post/3kabc").status_code == 303
    assert _add(user_client, "https://bsky.app/profile/Alice.bsky.social/post/3kabc").status_code == 400


def test_post_detail_text_edit_and_source(user_client, harness):
    _add(user_client, "https://x.com/jack/status/21")
    with harness.db() as db:
        pid = db.query(Post).one().id
    page = user_client.get(f"/posts/{pid}")
    assert page.status_code == 200 and "wartend" in page.text
    user_client.post(f"/posts/{pid}/text", data={"text": "Korrigierter Text", "csrf_token": user_client.csrf})
    with harness.db() as db:
        post = db.get(Post, pid)
        assert post.text == "Korrigierter Text" and post.text_source == TEXT_MANUAL
    assert "<dt>Wortlaut</dt><dd>manuell</dd>" in user_client.get(f"/posts/{pid}").text.replace("\n", "")


def test_fulltext_search_and_filters(user_client, harness):
    _add(user_client, "https://x.com/jack/status/30", tags="humor")
    _add(user_client, "https://bsky.app/profile/bob.bsky.social/post/3kxyz", tags="politik")
    with harness.db() as db:
        x, b = db.query(Post).order_by(Post.id).all()
        x.text, x.text_source = "Die Katze trinkt Kaffee", "ocr"
        b.text, b.text_source = "Über Politik und Käse", "api"
        db.commit()
    r = user_client.get("/?q=katz")
    assert "Die Katze trinkt Kaffee" in r.text and "Käse" not in r.text
    r = user_client.get("/?q=kase")  # ohne Umlaut findet trotzdem (remove_diacritics)
    assert "Käse" in r.text
    assert "Käse" in user_client.get("/?platform=bluesky").text
    assert "Katze" not in user_client.get("/?platform=bluesky").text
    assert "Katze" in user_client.get("/?tags=humor").text
    assert "Katze" not in user_client.get("/?tags=humor,politik").text  # mehrere Tags = UND
    assert "Käse" in user_client.get("/?author=bob").text
    # Gefaehrliche FTS-Syntax fuehrt nicht zu einem Fehler
    assert user_client.get('/?q=" OR NEAR( * -:').status_code == 200


def test_fts_query_sanitising():
    assert fts_query("") is None
    assert fts_query("katze kaffee") == '"katz"* "kaffe"*'  # 0.21: Wortstamm als Praefix
    assert fts_query('"guten morgen" welt') == '"guten morgen" "welt"*'
    assert fts_query('NEAR( x" -y:') == '"NEAR"* "x"* "y"*'


def test_tag_normalisation():
    assert normalize_tag(" #Lustige Sachen ") == "lustige-sachen"
    assert parse_tag_input("a, A, b;c\n#d") == ["a", "b", "c", "d"]


def test_tag_suggest(user_client):
    _add(user_client, "https://x.com/jack/status/40", tags="humor, hund")
    r = user_client.get("/tags/suggest?tags=hu")
    assert "#humor" in r.text and "#hund" in r.text
    r = user_client.get("/tags/suggest?tags=humor, hu")
    assert "#humor" not in r.text and "#hund" in r.text


def test_lists_flow(user_client, harness):
    _add(user_client, "https://x.com/jack/status/50")
    with harness.db() as db:
        pid = db.query(Post).one().id
    user_client.post(f"/posts/{pid}/lists", data={"new_list": "Humor", "csrf_token": user_client.csrf})
    with harness.db() as db:
        pl = db.query(PostList).one()
        assert pl.title == "Humor" and len(pl.post_links) == 1
    assert "Humor" in user_client.get("/lists").text
    user_client.post(f"/lists/{pl.id}/rename", data={"title": "Lustig", "csrf_token": user_client.csrf})
    # Loeschen ohne Bestaetigung -> nur Weiterleitung zur Rueckfrage
    r = user_client.post(f"/lists/{pl.id}/delete", data={"csrf_token": user_client.csrf})
    assert r.headers["location"].endswith(f"/lists/{pl.id}/delete")
    r = user_client.post(f"/lists/{pl.id}/delete", data={"confirm": "ja", "csrf_token": user_client.csrf})
    assert r.headers["location"].endswith("/lists")
    with harness.db() as db:
        assert db.query(PostList).count() == 0
        assert db.query(Post).count() == 1  # Beitrag bleibt


def test_lists_editable_by_everyone(harness, user_client, admin_client):
    admin_client.post("/lists", data={"title": "Vom Admin", "csrf_token": admin_client.csrf})
    with harness.db() as db:
        lid = db.query(PostList).one().id
    r = user_client.post(f"/lists/{lid}/rename", data={"title": "Von Anna", "csrf_token": user_client.csrf})
    assert r.status_code == 303


def test_retry_resets_status(user_client, harness):
    _add(user_client, "https://x.com/jack/status/60")
    with harness.db() as db:
        post = db.query(Post).one()
        post.status, post.status_message = "error", "Beitrag nicht gefunden"
        db.commit()
        pid = post.id
    assert "Erneut versuchen" in user_client.get(f"/posts/{pid}").text
    user_client.post(f"/posts/{pid}/retry", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.get(Post, pid).status == "pending"


def test_delete_post(user_client, harness):
    _add(user_client, "https://x.com/jack/status/70", tags="weg")
    with harness.db() as db:
        pid = db.query(Post).one().id
    assert user_client.get(f"/posts/{pid}/delete").status_code == 200
    user_client.post(f"/posts/{pid}/delete", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(Post).count() == 0


def test_generator_pages(user_client, harness):
    assert user_client.get("/generator").status_code == 200
    assert user_client.get("/generator?platform=bluesky&preset=german_week").status_code == 200
    r = user_client.get("/generator/preview?platform=x&from_account=name&min_faves=100")
    assert "from:name min_faves:100" in r.text and "Auf X (Twitter) öffnen" in r.text
    r = user_client.get("/generator/preview?platform=bluesky&from_account=name&min_faves=100")
    assert "from:name.bsky.social" in r.text and "min_faves" not in r.text and "Auf Bluesky öffnen" in r.text
    r = user_client.post("/generator/save", data={"platform": "x", "search_name": "Katzen", "all_words": "katze",
                                                  "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        s = db.query(SavedSearch).one()
        assert s.platform == "x" and s.query == "katze"
    page = user_client.get(f"/generator?saved={s.id}")
    assert 'value="katze"' in page.text
