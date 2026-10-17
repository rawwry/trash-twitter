"""0.14.0: Recherche, Tags mit Oberbegriffen, Thread-Reiter, Hilfe, Neu-Fenster, X (Twitter)."""

from __future__ import annotations

import json

from app.changelog import release_notice
from app.models import Person, Post, ResearchNote, Tag
from app.services import accounts

from .conftest import ADMIN_PW, login


def _add(client, url, tags=""):
    r = client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf})
    assert r.status_code == 303, r.text
    return r


def _tag(harness, name):
    with harness.db() as db:
        return db.query(Tag).filter_by(name=name).one().id


# --- Benennung ---------------------------------------------------------------------------

def test_idiotarium_and_x_twitter_label(user_client, harness):
    _add(user_client, "https://x.com/jack/status/20")
    page = user_client.get("/").text
    assert "<h1>Das Idiotarium</h1>" in page and "<title>Das Idiotarium" in page
    assert "<span>X (Twitter)</span>" in page  # Plattform-Filter
    assert "X (Twitter)" in user_client.get("/posts/1").text


# --- Tags -------------------------------------------------------------------------------------

def test_tag_suggest_prefers_existing_and_similar(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="klima, energie")
    r = user_client.get("/tags/suggest", params={"tq": "kli", "tags": ""}).text
    assert 'data-tag-add="klima"' in r and "data-tag-new" in r  # vorhanden zuerst, neu nur als Extra
    r = user_client.get("/tags/suggest", params={"tq": "klma", "tags": ""}).text
    assert "Meintest du" in r and 'data-tag-add="klima" data-similar' in r
    r = user_client.get("/tags/suggest", params={"tq": "klima", "tags": ""}).text
    assert "data-tag-new" not in r  # gibt es schon
    r = user_client.get("/tags/suggest", params={"tq": "", "tags": "klima"}).text
    assert "Häufig verwendet" in r and 'data-tag-add="klima"' not in r  # schon gewaehlt


def test_groups_filter_and_cleanup(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="klima")
    _add(user_client, "https://x.com/a/status/2", tags="energie")
    _add(user_client, "https://x.com/a/status/3", tags="verkehr")
    csrf = user_client.csrf
    assert user_client.post("/settings/tags/group", data={"name": "Umwelt", "csrf_token": csrf}).status_code == 303
    umwelt = _tag(harness, "umwelt")
    r = user_client.post("/settings/tags/bulk", data={"ids": [_tag(harness, "klima"), _tag(harness, "energie")],
                                                       "action": "move", "parent": str(umwelt), "csrf_token": csrf})
    assert r.status_code == 303
    page = user_client.get("/?tags=umwelt").text
    assert page.count('data-post="') == 2  # Oberbegriff findet Unter-Tags
    assert 'class="tag-pill is-group"' in page and 'id="tag-panel"' in page
    # Oberbegriff ohne eigene Postings bleibt beim Aufraeumen bestehen
    user_client.post("/posts/3/note", data={"note": "", "tags": "", "csrf_token": csrf})
    with harness.db() as db:
        names = {t.name for t in db.query(Tag)}
        assert "umwelt" in names and "verkehr" not in names
    # Zwei Ebenen: ein Oberbegriff laesst sich nicht unterordnen
    user_client.post("/settings/tags/group", data={"name": "politik", "csrf_token": csrf})
    r = user_client.post(f"/settings/tags/{umwelt}/move", data={"parent": str(_tag(harness, "politik")), "csrf_token": csrf})
    with harness.db() as db:
        assert db.get(Tag, umwelt).parent_id is None
    page = user_client.get("/settings/tags").text
    assert "Neuer Oberbegriff" in page and "#umwelt" in page
    # Aufloesen: Unter-Tags bleiben, ohne Oberbegriff
    user_client.post(f"/settings/tags/{umwelt}/ungroup", data={"csrf_token": csrf})
    with harness.db() as db:
        assert db.query(Tag).filter_by(name="umwelt").first() is None
        assert db.query(Tag).filter_by(name="klima").one().parent_id is None


def test_bulk_merge_keeps_posts(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="klimawandel")
    _add(user_client, "https://x.com/a/status/2", tags="klimakrise")
    ids = [_tag(harness, "klimawandel"), _tag(harness, "klimakrise")]
    user_client.post("/settings/tags/bulk", data={"ids": ids, "action": "merge", "name": "Klima", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert [t.name for t in db.query(Tag)] == ["klima"]
        assert all([t.name for t in p.tags] == ["klima"] for p in db.query(Post))


# --- Thread-Reiter ---------------------------------------------------------------------------

def test_thread_tab_creates_one_post(user_client, harness):
    assert "Als Thread hinzufügen" in user_client.get("/add").text
    assert 'data-add-panel="thread"' in user_client.get("/add?mode=thread").text
    r = user_client.post("/posts/thread", data={"thread_url": ["https://x.com/a/status/10", "https://x.com/a/status/11 https://x.com/a/status/12", ""],
                                                 "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        p = db.query(Post).one()
        assert p.post_id == "10" and json.loads(p.thread_extra) == ["https://x.com/a/status/11", "https://x.com/a/status/12"]
    r = user_client.post("/posts/thread", data={"thread_url": ["https://x.com/a/status/99"], "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "mindestens zwei Links" in r.text


# --- Recherche --------------------------------------------------------------------------------

def _person_of(harness, post_id):
    with harness.db() as db:
        return db.get(Post, post_id).account.person_id


def test_research_create_link_and_show(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    _add(user_client, "https://x.com/olaf/status/2")
    person_id = _person_of(harness, 1)
    form = user_client.get("/recherche/neu?post=1").text
    assert f'name="person_ids" value="{person_id}"' in form and 'name="post_ids" value="1"' in form
    r = user_client.post("/recherche", data={"title": "Hat es selbst zugegeben", "kind": "widerspruch",
                                             "body": "Erst so, dann so: https://example.org/beleg",
                                             "sources": "https://example.org/beleg\nZeitung, 3.4.2026",
                                             "posts": "000001, 2", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        note = db.query(ResearchNote).one()
        assert [p.id for p in note.persons] == [person_id]  # aus den Postings uebernommen
        assert sorted(p.id for p in note.posts) == [1, 2] and note.source_list[1] == "Zeitung, 3.4.2026"
        nid = note.id
    detail = user_client.get(f"/recherche/{nid}").text
    assert 'href="https://example.org/beleg"' in detail and "Widerspruch" in detail and "Dazugehörige Postings" in detail
    assert "Hat es selbst zugegeben" in user_client.get(f"/personen/{person_id}").text
    assert "Recherche dazu" in user_client.get("/posts/1").text
    overview = user_client.get(f"/recherche?person={person_id}&q=zugegeben").text
    assert "Hat es selbst zugegeben" in overview
    assert "Hat es selbst zugegeben" not in user_client.get("/recherche?art=fakt").text


def test_research_validation_and_permissions(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    r = user_client.post("/recherche", data={"title": "Ohne Person", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "mindestens eine Person" in r.text
    r = user_client.post("/recherche", data={"title": "Falsche Nummer", "posts": "999", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "000999" in r.text
    person_id = _person_of(harness, 1)
    user_client.post("/recherche", data={"title": "Eintrag von Anna", "person_ids": [person_id], "csrf_token": user_client.csrf})
    with harness.db() as db:
        nid = db.query(ResearchNote).one().id
    with harness.client() as other:
        harness.add_user("bert", "bert-passwort-123")
        other.csrf = login(other, "bert", "bert-passwort-123")
        # bearbeiten duerfen alle, loeschen nur Anlegerin oder Admin
        r = other.post(f"/recherche/{nid}", data={"title": "Von Bert ergänzt", "person_ids": [person_id], "csrf_token": other.csrf})
        assert r.status_code == 303
        assert other.post(f"/recherche/{nid}/loeschen", data={"csrf_token": other.csrf}).status_code == 403
    with harness.db() as db:
        note = db.get(ResearchNote, nid)
        assert note.title == "Von Bert ergänzt" and note.updated_by.username == "bert"
    assert user_client.post(f"/recherche/{nid}/loeschen", data={"csrf_token": user_client.csrf}).status_code == 303


def test_research_follows_person_merge(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    _add(user_client, "https://x.com/olaf_privat/status/2")
    a, b = _person_of(harness, 1), _person_of(harness, 2)
    user_client.post("/recherche", data={"title": "Zu Person B", "person_ids": [b], "csrf_token": user_client.csrf})
    with harness.db() as db:
        accounts.merge_persons(db, db.get(Person, b), db.get(Person, a))
        db.commit()
        assert [p.id for p in db.query(ResearchNote).one().persons] == [a]


# --- Hilfe + Neu-Fenster ---------------------------------------------------------------------

def test_help_is_prominent_and_explains_basics(user_client):
    page = user_client.get("/").text
    assert 'class="hdr-help' in page and 'class="fab"' in page and 'href="/galerie"' in page
    help_page = user_client.get("/hilfe").text
    assert 'id="grundlagen"' in help_page and "Oberbegriffe &amp; Figuren" in help_page and "Recherche" in help_page


def test_release_notice_once_per_minor(user_client, harness):
    assert "data-release-dialog" in user_client.get("/").text
    r = user_client.post("/neuigkeiten/gesehen", data={"csrf_token": user_client.csrf}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 204
    assert "data-release-dialog" not in user_client.get("/").text
    from app import VERSION
    assert harness.get_user("anna").release_seen == ".".join(VERSION.split(".")[:2])
    # Patch-Versionen zeigen nichts Neues, alte Versionen ohne highlights auch nicht
    assert release_notice("0.14.3", "0.14") is None
    assert release_notice("0.13.0", "") is None
    assert release_notice("0.14.0", "0.13")[0] == "0.14"


def test_release_notice_waits_for_password_change(harness):
    harness.add_user("neu", "neu-passwort-123", must_change=True)
    with harness.client() as c:
        login(c, "chef", ADMIN_PW)
        assert "data-release-dialog" in c.get("/").text
