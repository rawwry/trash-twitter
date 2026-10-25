"""0.23.0: Bedienbarkeit - Navigation, Suche ueberall, alle Treffer waehlen, Rueckgaengig,
ruhigere Detailseite, gemerkte Suchen, Tempo, Handy, weniger Einstellungen, Kontraste."""

from __future__ import annotations

import base64
import json
from datetime import datetime

from app.models import PinnedSearch, Post, Tag
from app.prefs import PREFS, section_prefs


def _add(client, url, tags=""):
    assert client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf}).status_code == 303


def _done(harness, texts, start=500):
    ids = []
    with harness.db() as db:
        for i, text in enumerate(texts):
            p = db.query(Post).filter_by(post_id=str(start + i)).one()
            p.text, p.status, p.posted_at = text, "done", datetime(2021 + i, 1, 1)
            ids.append(p.id)
        db.commit()
    return ids


def _toast(response) -> dict:
    raw = response.cookies.get("sgc_toast") or ""
    return json.loads(base64.urlsafe_b64decode(raw.encode())) if raw else {}


def test_navigation_trimmed_and_network_gone(user_client):
    page = user_client.get("/").text
    nav = page[page.index('class="nav-tabs"'):page.index("</nav>", page.index('class="nav-tabs"'))]
    assert nav.count("<a href=") == 5 + 4          # 5 Bereiche + 4 Werkzeuge im Menue
    assert "Werkzeuge" in nav and "Suchgenerator" in nav and "Netzwerk" not in page
    r = user_client.get("/netzwerk", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/")
    assert user_client.get("/netzwerk/daten").status_code == 404


def test_palette_finds_everything(user_client, harness):
    _add(user_client, "https://x.com/jack/status/500", tags="todesfall")
    _done(harness, ["Mein Kater ist verstorben"])
    page = user_client.get("/").text
    assert 'id="palette"' in page and 'data-open="palette"' in page
    empty = user_client.get("/suche/schnell").text
    assert "Posting hinzufügen" in empty and 'data-open="add-dialog"' in empty
    res = user_client.get("/suche/schnell", params={"q": "tod"}).text
    assert "#todesfall" in res and "Collage aus „tod“" in res
    res = user_client.get("/suche/schnell", params={"q": "Kater"}).text
    assert "Mein Kater ist verstorben" in res and "/posts/" in res
    res = user_client.get("/suche/schnell", params={"q": "jack"}).text
    assert "Personen" in res and "/personen/" in res
    none = user_client.get("/suche/schnell", params={"q": "xyzxyzxyz"}).text
    assert "Im Idiotarium nach „xyzxyzxyz“ suchen" in none and "Personen" not in none   # Suche als Ausweg


def test_select_all_results_ids(user_client, harness):
    for i in range(3):
        _add(user_client, f"https://x.com/jack/status/{500 + i}", tags="todesfall" if i < 2 else "")
    page = user_client.get("/?tags=todesfall").text
    assert 'data-total="2"' in page and "data-select-results" in page
    ids = user_client.get("/posts/ids?tags=todesfall").json()["ids"]
    assert len(ids) == 2


def test_undo_for_bulk_tags_and_deferred_delete(user_client, harness):
    for i in range(2):
        _add(user_client, f"https://x.com/jack/status/{500 + i}")
    ids = _done(harness, ["eins", "zwei"])
    r = user_client.post("/posts/bulk/tags", data={"ids": ids, "tags": "neu", "mode": "add", "back": "/", "csrf_token": user_client.csrf})
    undo = _toast(r)["u"]
    assert undo["url"] == "/posts/bulk/tags" and undo["fields"]["mode"] == "remove" and sorted(undo["fields"]["ids"]) == sorted(ids)
    page = user_client.get("/").text
    assert "Rückgängig" in page and 'name="mode" value="remove"' in page
    user_client.post("/posts/bulk/tags", data={**undo["fields"], "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert all(not db.get(Post, i).tags for i in ids)
    # teilweise schon vorhanden -> kein Rueckgaengig (wuerde zu viel abnehmen)
    with harness.db() as db:
        p = db.get(Post, ids[0]); p.tags = [Tag(name="a")]; db.commit()
    r = user_client.post("/posts/bulk/tags", data={"ids": ids, "tags": "a, b", "mode": "add", "csrf_token": user_client.csrf})
    assert "u" not in _toast(r)
    # Loeschen im Idiotarium ohne Rueckfrage (das Rueckgaengig macht der Browser)
    page = user_client.get("/").text
    assert "data-defer-delete=" in page and 'data-delete-url="/posts/bulk/delete"' in page and "hx-confirm" not in page


def test_detail_page_calmer_and_inline_tags(user_client, harness):
    _add(user_client, "https://x.com/jack/status/500", tags="alt")
    [pid] = _done(harness, ["Text"])
    html = user_client.get(f"/posts/{pid}").text
    actions = html[html.index('class="lead-actions"'):html.index("</details>", html.index('class="lead-actions"'))]
    assert actions.count('class="act"') == 4 and "heart" in actions and "Mehr" in actions   # Herz + 4 and "Wortlaut korrigieren" in actions
    assert 'data-edit="tags"' in html and f'action="/posts/{pid}/tags"' in html and "danger-zone" not in html
    r = user_client.post(f"/posts/{pid}/tags", data={"tags": "neu, zwei", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert sorted(t.name for t in db.get(Post, pid).tags) == ["neu", "zwei"]
    assert "Wortlaut korrigieren" in html and 'class="detail-layout"' in html


def test_pinned_searches(user_client, harness):
    _add(user_client, "https://x.com/jack/status/500", tags="todesfall")
    _done(harness, ["eins"])
    page = user_client.get("/?tags=todesfall&view=raster").text
    assert "Merken" in page and 'name="query" value="tags=todesfall"' in page
    r = user_client.post("/suchen/merken", data={"query": "tags=todesfall&view=list&page=2", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        s = db.query(PinnedSearch).one()
        assert s.query == "tags=todesfall" and s.name == "#todesfall"
        sid = s.id
        s.seen_at = datetime(2000, 1, 1)
        db.commit()
    page = user_client.get("/").text
    assert 'class="saved-bar"' in page and "#todesfall" in page and 'class="saved-new"' in page
    assert "Gemerkt" in user_client.get("/?tags=todesfall").text
    r = user_client.get(f"/suchen/{sid}", follow_redirects=False)
    assert r.headers["location"].endswith("/?tags=todesfall")
    assert 'class="saved-new"' not in user_client.get("/").text                  # gesehen
    r = user_client.post(f"/suchen/{sid}/loeschen", data={"csrf_token": user_client.csrf})
    assert _toast(r)["u"]["url"] == "/suchen/merken"
    with harness.db() as db:
        assert db.query(PinnedSearch).count() == 0
    assert user_client.get("/suchen/9999", follow_redirects=False).status_code == 404


def test_pinned_search_is_personal(user_client, admin_client, harness):
    user_client.post("/suchen/merken", data={"query": "q=x", "csrf_token": user_client.csrf})
    with harness.db() as db:
        sid = db.query(PinnedSearch).one().id
    assert admin_client.get(f"/suchen/{sid}", follow_redirects=False).status_code == 404
    assert 'class="saved-bar"' not in admin_client.get("/").text


def test_speed_mobile_settings_contrast(user_client):
    page = user_client.get("/").text
    assert 'type="speculationrules"' in page and '"/suchen/*"' in page
    css = user_client.get("/static/style.css").text
    assert "@view-transition" in css and "--text-3: light-dark(#666970, #9a9ca3)" in css
    shown = [p.key for p in PREFS if p.shown]
    assert len(shown) == 8 and "archive_view" not in shown and "theme" in shown
    assert all(p.shown for p in section_prefs("archiv"))
    settings = user_client.get("/settings/archiv").text
    assert "Postings pro Seite" not in settings
