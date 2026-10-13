"""0.8.0: Massenimport vieler Links - mit Duplikat-Erkennung."""

from __future__ import annotations

import json

from app.models import ImportBatch, ListPost, Post
from app.services.bulk import extract


def _import(client, links, **extra):
    data = {"links": links, "csrf_token": client.csrf}
    data.update(extra)
    return client.post("/import", data=data)


def test_extract_links_from_free_text():
    raw = """https://x.com/a/status/1
    Schau mal: twitter.com/b/status/2?s=46 und x.com/c/status/3.
    https://bsky.app/profile/alice.bsky.social/post/3kabc
    https://www.tagesschau.de/artikel
    nur Text ohne Link
    """
    found, invalid = extract(raw)
    assert [c.url for c in found] == ["https://x.com/a/status/1", "twitter.com/b/status/2?s=46", "x.com/c/status/3",
                                      "https://bsky.app/profile/alice.bsky.social/post/3kabc"]
    assert invalid == ["https://www.tagesschau.de/artikel", "nur Text ohne Link"]


def test_bulk_import_creates_and_skips_duplicates(user_client, harness):
    # schon im Archiv
    user_client.post("/posts", data={"url": "https://x.com/alt/status/100", "csrf_token": user_client.csrf})
    links = "\n".join([
        "https://x.com/a/status/1",
        "https://twitter.com/a/status/1?s=20",      # gleicher Tweet, andere Schreibweise
        "https://x.com/jemand/status/100",          # schon im Archiv (Handle egal)
        "https://x.com/b/status/2",
        "https://bsky.app/profile/alice.bsky.social/post/3kabc",
        "https://bsky.app/profile/Alice.bsky.social/post/3kabc",  # gleicher Bluesky-Beitrag
        "https://example.com/quatsch",
    ])
    r = _import(user_client, links, tags="energie, import")
    assert r.status_code == 303
    batch_id = r.headers["location"].rsplit("/", 1)[-1]
    with harness.db() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.total_links == 6 and batch.created_count == 3
        assert len(json.loads(batch.existing)) == 1 and len(json.loads(batch.repeated)) == 2
        assert json.loads(batch.invalid) == ["https://example.com/quatsch"]
        new = db.query(Post).filter(Post.import_batch == batch_id).all()
        assert sorted(p.post_id for p in new) == ["1", "2", "3kabc"]
        assert all(p.status == "pending" and p.account_id for p in new)
        assert all(sorted(t.name for t in p.tags) == ["energie", "import"] for p in new)
    page = user_client.get(f"/import/{batch_id}").text
    assert "neu archiviert" in page and "Schon im Archiv" in page and "Doppelt eingefügt" in page
    assert 'hx-trigger="every 4s"' in page  # laeuft noch
    # zweiter Import derselben Links: nichts Neues
    r = _import(user_client, links)
    batch2 = r.headers["location"].rsplit("/", 1)[-1]
    with harness.db() as db:
        assert db.get(ImportBatch, batch2).created_count == 0


def test_bulk_import_into_new_list_and_progress(user_client, harness):
    r = _import(user_client, "https://x.com/a/status/11\nhttps://x.com/a/status/12", new_list="Energiedebatte")
    batch_id = r.headers["location"].rsplit("/", 1)[-1]
    with harness.db() as db:
        assert db.query(ListPost).count() == 2
        db.query(Post).update({"status": "done"})
        db.commit()
    prog = user_client.get(f"/import/{batch_id}/progress").text
    assert "Fertig" in prog and "every 4s" not in prog and "2 von 2" in prog
    assert batch_id in user_client.get("/import").text


def test_thread_part_counts_as_duplicate(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/a/status/50", "csrf_token": user_client.csrf,
                                     "thread_extra": "https://x.com/a/status/51"})
    with harness.db() as db:
        p = db.query(Post).one()
        p.thread_parts = json.dumps([{"url": "https://x.com/a/status/50", "post_id": "50"},
                                     {"url": "https://x.com/a/status/52", "post_id": "52"}])
        db.commit()
    r = _import(user_client, "https://x.com/a/status/51\nhttps://x.com/a/status/52\nhttps://x.com/a/status/53")
    batch_id = r.headers["location"].rsplit("/", 1)[-1]
    with harness.db() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.created_count == 1 and len(json.loads(batch.existing)) == 2
    # auch beim einzelnen Hinzufuegen
    r = user_client.post("/posts", data={"url": "https://x.com/a/status/52", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "schon im Archiv" in r.text


def test_bulk_import_limits_and_errors(user_client, harness):
    r = _import(user_client, "")
    assert r.status_code == 400 and "Links einfügen" in r.text
    many = "\n".join(f"https://x.com/a/status/{i}" for i in range(1, 502))
    r = _import(user_client, many)
    assert r.status_code == 400 and "Höchstens 500" in r.text
    with harness.db() as db:
        assert db.query(Post).count() == 0
    assert user_client.post("/import", data={"links": "https://x.com/a/status/1"}).status_code == 403
    assert user_client.get("/import/gibtsnicht").status_code == 404


def test_bulk_tab_in_add_sheet(user_client):
    page = user_client.get("/add?mode=bulk").text
    assert 'data-add-panel="bulk"' in page and 'action="/import"' in page
    assert 'data-add-tab="bulk"' in user_client.get("/").text


def test_import_requires_login(harness):
    with harness.client() as c:
        assert c.get("/import").status_code == 303
