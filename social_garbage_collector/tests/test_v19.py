"""0.19.0: Muster (Bilanz, Chronik, Figuren, Themen-Netz) und neues "Tags organisieren"."""

from __future__ import annotations

import json
import re

from app.models import Post, Tag
from app.services import patterns
from app.services import tags as tag_service


def _add(client, url):
    assert client.post("/posts", data={"url": url, "csrf_token": client.csrf}).status_code == 303


def _seed(harness, client):
    for i in range(20, 26):
        _add(client, f"https://x.com/jack/status/{i}")
    _add(client, "https://x.com/elon/status/30")
    with harness.db() as db:
        t = {n: Tag(name=n) for n in ("todesfall", "bekannte", "paulaner", "wohnen", "wohnung", "leer", "spender")}
        db.add_all(t.values()); db.flush()
        posts = [db.get(Post, i) for i in range(1, 8)]
        for p in posts:
            p.status = "done"
        posts[0].tags = [t["todesfall"], t["bekannte"]]
        posts[1].tags = [t["todesfall"], t["bekannte"], t["spender"]]
        posts[2].tags = [t["todesfall"], t["paulaner"], t["spender"]]
        posts[3].tags = [t["paulaner"], t["todesfall"], t["spender"]]
        posts[4].tags = [t["wohnen"]]
        posts[6].tags = [t["wohnung"]]   # elon
        db.commit()
        return posts[0].account.person_id, {n: tag.id for n, tag in t.items()}


def test_patterns_bilanz_pairs_figures(user_client, harness):
    pid, ids = _seed(harness, user_client)
    with harness.db() as db:
        from app.models import Person
        pat = patterns.for_person(db, db.get(Person, pid))
        assert pat.total == 6 and pat.tagged == 5 and pat.untagged == 1
        top = pat.bilanz[0]
        assert top.tag.name == "todesfall" and top.count == 4
        partners = dict((t.name, n) for t, n in top.partners)
        assert partners["spender"] == 3 and partners["bekannte"] == 2 and partners["paulaner"] == 2
        pairs = {(a.name, b.name): n for a, b, n in pat.pairs}
        assert (pairs.get(("spender", "todesfall")) or pairs.get(("todesfall", "spender"))) == 3
        assert pat.figures == []
        db.get(Tag, ids["paulaner"]).kind = "figur"
        db.commit()
        pat = patterns.for_person(db, db.get(Person, pid))
        fig = pat.figures[0]
        assert fig.stat.tag.name == "paulaner" and len(fig.posts) == 2
        assert dict((t.name, n) for t, n in fig.events)["todesfall"] == 2
        data = pat.chart_data("")
        assert len(data["posts"]) == 6 and {"id", "t", "s", "g"} <= set(data["posts"][0])


def test_pattern_pages(user_client, harness):
    pid, ids = _seed(harness, user_client)
    over = user_client.get("/muster").text
    assert 'aria-current="page">Muster' in over and f"/personen/{pid}/muster" in over and "#todesfall" in over
    page = user_client.get(f"/personen/{pid}/muster")
    assert page.status_code == 200
    html = page.text
    for part in ("Bilanz", "Chronik", "Figuren", "Themen-Netz", "Häufigste Kombinationen", "ohne Tag", "muster.js"):
        assert part in html
    assert f"?person={pid}&tags=todesfall%2Cspender" in html  # Partner-Link fuehrt zu genau diesen Postings
    data = json.loads(re.search(r'<script type="application/json" id="muster-data">(.*?)</script>', html, re.S).group(1))
    assert data["person"] == pid and len(data["pairs"]) >= 3
    # Figur per Klick markieren
    r = user_client.post(f"/tags/{ids['paulaner']}/art", data={"kind": "figur", "weiter": f"/personen/{pid}/muster#figuren",
                                                               "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/personen/{pid}/muster#figuren")
    html = user_client.get(f"/personen/{pid}/muster").text
    assert 'id="figur-' in html and "Als Recherche festhalten" in html and "Ist doch keine Figur" in html
    assert user_client.post(f"/tags/{ids['paulaner']}/art", data={"kind": "quatsch", "csrf_token": user_client.csrf}).status_code == 400
    assert user_client.post("/tags/999/art", data={"kind": "figur", "csrf_token": user_client.csrf}).status_code == 404
    # fremde Weiterleitung wird ignoriert
    r = user_client.post(f"/tags/{ids['paulaner']}/art", data={"kind": "thema", "weiter": "//evil.example", "csrf_token": user_client.csrf})
    assert r.headers["location"].endswith("/settings/tags")
    assert user_client.get("/personen/999/muster").status_code == 404
    assert "Muster" in user_client.get(f"/personen/{pid}").text


def test_old_network_redirects(user_client):
    r = user_client.get("/netzwerk", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/muster")


def test_archive_untagged_filter_and_research_prefill(user_client, harness):
    pid, _ = _seed(harness, user_client)
    page = user_client.get(f"/?person={pid}&ohne_tag=1").text
    assert "Ohne Tag" in page and re.search(r"<strong>1</strong> Posting\b", page)
    form = user_client.get(f"/recherche/neu?posts=3,4&titel=Lebenslauf%20%23paulaner").text
    assert 'value="Lebenslauf #paulaner"' in form
    assert 'name="post_ids" value="3"' in form and 'name="post_ids" value="4"' in form
    assert f'name="person_ids" value="{pid}"' in form


def test_tag_cleanup_and_page(user_client, harness):
    _, ids = _seed(harness, user_client)
    with harness.db() as db:
        c = tag_service.cleanup(db)
        assert [t.name for t in c.unused] == ["leer"]
        assert {(k.name, d.name) for k, d, *_ in c.similar} <= {("wohnen", "wohnung"), ("wohnung", "wohnen")} and c.similar
        assert ("spender", "todesfall") in {(t.name, o.name) for t, o, *_ in c.shadows}
    page = user_client.get("/settings/tags").text
    for part in ("Aufräum-Vorschläge", "Ähnlich geschrieben", "Vermutlich ein Unterfall", "Ungenutzt", "Unter #todesfall einordnen",
                 'data-tg-filter="figur"', "höchstens 1 Posting", 'data-tg-row', "Was ist was?"):
        assert part in page
    # Mehrfachauswahl: als Figur markieren
    r = user_client.post("/settings/tags/bulk", data={"ids": [ids["paulaner"], ids["bekannte"]], "action": "figur", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.get(Tag, ids["paulaner"]).kind == "figur" and db.get(Tag, ids["bekannte"]).kind == "figur"
    # Unterfall einordnen -> todesfall wird Oberbegriff, beide bleiben
    r = user_client.post(f"/settings/tags/{ids['spender']}/move", data={"parent": ids["todesfall"], "csrf_token": user_client.csrf})
    assert r.headers["location"].endswith(f"#tag-{ids['spender']}")
    with harness.db() as db:
        assert db.get(Tag, ids["todesfall"]).is_group and db.get(Tag, ids["spender"]).parent_id == ids["todesfall"]
    page = user_client.get("/settings/tags").text
    assert "Oberbegriff · 1 Unter-Tag" in page
