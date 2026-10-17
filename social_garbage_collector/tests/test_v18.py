"""0.18.0: Netzwerk - das Archiv als Graph (Personen, Tags, Listen, Recherche)."""

from __future__ import annotations

from app.models import ListPost, Post, PostList, ResearchNote, Tag
from app.routers.graph import build_graph


def _add(client, url):
    assert client.post("/posts", data={"url": url, "csrf_token": client.csrf}).status_code == 303


def _seed(harness, user_client):
    _add(user_client, "https://x.com/jack/status/20")
    _add(user_client, "https://x.com/jack/status/21")
    _add(user_client, "https://x.com/elon/status/22")
    _add(user_client, "https://x.com/dritte/status/23")
    with harness.db() as db:
        energie = Tag(name="energie", is_group=True)
        db.add(energie); db.flush()
        kern = Tag(name="kernkraft", parent_id=energie.id)
        solo = Tag(name="nurdritte")
        db.add_all([kern, solo]); db.flush()
        p1, p2, p3, p4 = (db.get(Post, i) for i in (1, 2, 3, 4))
        p1.tags = [kern]; p2.tags = [kern]; p3.tags = [kern]; p4.tags = [solo]
        pl = PostList(title="Atom")
        db.add(pl); db.flush()
        db.add(ListPost(list_id=pl.id, post_id=1))
        note = ResearchNote(title="Widerspruch Kernkraft", kind="widerspruch")
        note.persons = [p1.account.person]
        note.posts = [p1]
        db.add(note)
        db.commit()
        return {i: db.get(Post, i).account.person_id for i in (1, 3, 4)}


def test_graph_data_full(user_client, harness):
    persons = _seed(harness, user_client)
    with harness.db() as db:
        g = build_graph(db, "")
    ids = {n["id"]: n for n in g["nodes"]}
    kinds = {}
    for l in g["links"]:
        kinds.setdefault(l["kind"], set()).add((l["source"], l["target"]))
    jack, elon = f"p{persons[1]}", f"p{persons[3]}"
    assert ids[jack]["type"] == "person" and ids[jack]["n"] == 2 and ids[jack]["url"].endswith(f"/personen/{persons[1]}")
    assert ids["g1"]["type"] == "group" and ids["g2"]["type"] == "tag" and ids["g2"]["label"] == "#kernkraft"
    assert ("g2", "g1") in kinds["tag-group"]
    assert {("t1", jack), ("t2", jack), ("t3", elon)} <= kinds["post-person"]
    assert ("t1", "g2") in kinds["post-tag"] and ("t1", "l1") in kinds["post-list"]
    assert (f"r1", jack) in kinds["research-person"] and ("r1", "t1") in kinds["research-post"]
    assert ids["r1"]["kind"] == "widerspruch"
    # Personen sind nie direkt verbunden
    assert not any(l["source"].startswith("p") and l["target"].startswith("p") for l in g["links"])
    assert g["focus"] is None and len(g["years"]) in (0, 2)


def test_graph_local_shows_shared_topics_only(user_client, harness):
    persons = _seed(harness, user_client)
    with harness.db() as db:
        g = build_graph(db, "", persons[1])
    ids = {n["id"] for n in g["nodes"]}
    assert g["focus"] == f"p{persons[1]}"
    assert f"p{persons[3]}" in ids          # teilt #kernkraft
    assert f"p{persons[4]}" not in ids      # nur eigenes Thema -> nicht in der Umgebung
    assert "g3" not in ids and "t4" not in ids
    assert {"g1", "g2", "l1", "r1"} <= ids


def test_graph_pages(user_client, harness):
    persons = _seed(harness, user_client)
    page = user_client.get("/netzwerk")
    assert page.status_code == 200 and "data-graph" in page.text and "force-graph-1.51.4.min.js" in page.text
    assert 'aria-current="page">Netzwerk' in page.text
    r = user_client.get("/netzwerk/daten")
    assert r.status_code == 200 and r.headers["cache-control"].startswith("private")
    assert {n["type"] for n in r.json()["nodes"]} >= {"person", "tag", "group", "list", "research", "post"}
    local = user_client.get(f"/netzwerk/daten?person={persons[1]}").json()
    assert local["focus"] == f"p{persons[1]}"
    person_page = user_client.get(f"/personen/{persons[1]}").text
    assert "Themen-Netz" in person_page and f"/netzwerk?fokus=p{persons[1]}" in person_page
    assert user_client.get("/netzwerk/daten?person=999").json()["nodes"] == []
    assert user_client.get("/static/vendor/force-graph-1.51.4.min.js").status_code == 200


def test_graph_requires_login(harness):
    c = harness.client()
    assert c.get("/netzwerk/daten", follow_redirects=False).status_code in (303, 401)
    assert c.get("/netzwerk", follow_redirects=False).status_code in (303, 401)


def test_graph_empty_archive(user_client):
    r = user_client.get("/netzwerk/daten").json()
    assert r == {"nodes": [], "links": [], "years": [], "focus": None}
    assert user_client.get("/netzwerk").status_code == 200
