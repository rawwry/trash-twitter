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
