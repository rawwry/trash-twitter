"""0.20.0: Automatische Tags (Regeln) unter "Tags organisieren"."""

from __future__ import annotations

from app.models import AutoTag, Post, Tag, TagRule
from app.services import autotag
from app.services import posts as post_service
from app.services import tags as tag_service


def _add(client, url):
    assert client.post("/posts", data={"url": url, "csrf_token": client.csrf}).status_code == 303


TEXTS = ["Heute ist meine Bekannte verstorben. Covid.",          # 1
         "Mein Kater schläft auf dem Bett.",                      # 2
         "Wieder sind Pakete nicht angekommen.",                  # 3
         "Der unverstorbene Witz des Tages",                      # 4  (kein ganzes Wort)
         "Ein Freund ist gestorben, ganz plötzlich.",             # 5
         "Die verstorbene Nachbarin im Film",                     # 6
         ]


def _seed(harness, client):
    for i, _ in enumerate(TEXTS):
        _add(client, f"https://x.com/jack/status/{100 + i}")
    _add(client, "https://x.com/elon/status/200")
    with harness.db() as db:
        for i, text in enumerate(TEXTS, start=1):
            p = db.get(Post, i)
            p.text, p.status = text, "done"
        other = db.get(Post, 7)
        other.text, other.status = "Elon: jemand ist verstorben", "done"
        manual = Tag(name="bekannte")
        db.add(manual)
        p1 = db.get(Post, 1)
        p1.tags = [manual]
        db.commit()
        return db.get(Post, 1).account.person_id, db.get(Post, 7).account.person_id


def test_matcher_rules():
    m = autotag.Matcher(autotag.parse_terms("verstorb*\ngestorben, ist tot"))
    assert m("Er ist VERSTORBEN.") and m("die Verstorbene") and m("ist gestorben") and m("sie ist   tot!")
    assert not m("unverstorben") and not m("gestorbenes") and not m("totale Ruhe")
    assert autotag.Matcher(["*katze"])("Die Hauskatze") and not autotag.Matcher(["katze"])("Hauskatze")
    assert autotag.Matcher(["müll"])("So ein Müll.")  # Umlaut + Grossschreibung
    both = autotag.Matcher(["kater", "bett"], match="all")
    assert both("Kater im Bett") and not both("Kater im Garten")
    ex = autotag.Matcher(["verstorb*"], exclude=["film"])
    assert ex("ist verstorben") and not ex("verstorbene im Film")
    assert autotag.parse_terms(" A ,b\n\n a ;**c**") == ["a", "b", "*c*"]
    assert autotag.Matcher([])("irgendwas") is False


def test_rule_flow_preview_apply_undo(user_client, harness):
    jack, elon = _seed(harness, user_client)
    page = user_client.get("/settings/tags/regeln")
    assert page.status_code == 200 and "Erste Regel anlegen" in page.text and "Automatisch taggen" in page.text
    pv = user_client.get("/settings/tags/regeln/vorschau", params={"tag": "todesfall", "terms": "verstorb*\ngestorben",
                                                                    "match": "any", "exclude": "film"}).text
    assert "<b>3</b> passend" in pv and "<mark>verstorben</mark>" in pv and "Film" not in pv
    r = user_client.post("/settings/tags/regeln", data={"tag": "#Todesfall", "terms": "verstorb*\ngestorben", "match": "any",
                                                        "exclude": "film", "person": str(jack), "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        rule = db.query(TagRule).one()
        assert rule.tag.name == "todesfall" and rule.term_list == ["verstorb*", "gestorben"] and rule.person_id == jack
        assert not db.query(AutoTag).count()          # Speichern vergibt noch nichts
    listing = user_client.get("/settings/tags/regeln").text
    assert "verstorb*" in listing and "#todesfall" in listing and "Auf 2 vorhandene anwenden" in listing
    apply_page = user_client.get(f"/settings/tags/regeln/{rule.id}/anwenden").text
    assert "Nur die 1 noch ganz ohne Tag" in apply_page and "Alle 2 passenden" in apply_page
    # erst nur ungetaggte
    user_client.post(f"/settings/tags/regeln/{rule.id}/anwenden", data={"scope": "untagged", "csrf_token": user_client.csrf})
    with harness.db() as db:
        names = lambda i: sorted(t.name for t in db.get(Post, i).tags)
        assert names(5) == ["todesfall"] and names(1) == ["bekannte"] and names(6) == [] and names(7) == []
    # dann alle - Posting 1 behaelt sein Hand-Tag und bekommt todesfall dazu; elon ist ausserhalb der Person
    user_client.post(f"/settings/tags/regeln/{rule.id}/anwenden", data={"scope": "all", "csrf_token": user_client.csrf})
    with harness.db() as db:
        names = lambda i: sorted(t.name for t in db.get(Post, i).tags)
        assert names(1) == ["bekannte", "todesfall"] and names(7) == []
        assert db.query(AutoTag).count() == 2
    # von Hand vergebenes todesfall an Posting 4 bleibt beim Rueckgaengig
    with harness.db() as db:
        p4 = db.get(Post, 4)
        p4.tags.append(db.query(Tag).filter_by(name="todesfall").one())
        db.commit()
    r = user_client.post(f"/settings/tags/regeln/{rule.id}/rueckgaengig", data={"csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        names = lambda i: sorted(t.name for t in db.get(Post, i).tags)
        assert names(1) == ["bekannte"] and names(5) == [] and names(4) == ["todesfall"]
        assert db.query(AutoTag).count() == 0 and db.query(TagRule).count() == 1


def test_new_posts_and_manual_text_get_tags(user_client, harness):
    jack, _ = _seed(harness, user_client)
    with harness.db() as db:
        tag = post_service.get_or_create_tags(db, ["pakete"])[0]
        db.add(TagRule(tag=tag, terms="paket*", match="any"))
        paused = post_service.get_or_create_tags(db, ["tiere"])[0]
        db.add(TagRule(tag=paused, terms="kater", active=False))
        db.commit()
        post = db.get(Post, 3)
        assert autotag.apply_to_post(db, post) == ["pakete"]       # so ruft es der Archivierer auf
        assert autotag.apply_to_post(db, post) == []               # nicht doppelt
        assert autotag.apply_to_post(db, db.get(Post, 2)) == []    # pausierte Regel greift nicht
        db.commit()
    # Wortlaut von Hand korrigiert -> Regel greift
    r = user_client.post("/posts/2/text", data={"text": "Neue Pakete für den Kater", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert [t.name for t in db.get(Post, 2).tags] == ["pakete"]
    # Tag von Hand entfernt -> auto_tags vergisst es
    user_client.post("/posts/2/note", data={"note": "", "tags": "", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(AutoTag).filter_by(post_id=2).count() == 0


def test_rule_tags_survive_cleanup_and_merge(user_client, harness):
    _seed(harness, user_client)
    r = user_client.post("/settings/tags/regeln", data={"tag": "ganzneu", "terms": "zebra", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        post_service.remove_orphan_tags(db)
        db.commit()
        assert db.query(Tag).filter_by(name="ganzneu").one()        # Tag ohne Postings, aber mit Regel bleibt
        target = Tag(name="ziel")
        db.add(target); db.flush()
        tag_service.merge_into(db, db.query(Tag).filter_by(name="ganzneu").one(), target)
        db.commit()
        assert db.query(TagRule).one().tag.name == "ziel"           # Regel wandert beim Zusammenfuehren mit


def test_rule_validation_toggle_delete_words(user_client, harness):
    _seed(harness, user_client)
    r = user_client.post("/settings/tags/regeln", data={"tag": "", "terms": "x", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "Bitte ein Tag angeben" in r.text
    r = user_client.post("/settings/tags/regeln", data={"tag": "a-tag", "terms": " , ", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "mindestens einen Begriff" in r.text
    user_client.post("/settings/tags/regeln", data={"tag": "bekannte", "terms": "bekannte", "csrf_token": user_client.csrf})
    with harness.db() as db:
        rid = db.query(TagRule).one().id
    user_client.post(f"/settings/tags/regeln/{rid}/aktiv", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.get(TagRule, rid).active is False
    edit = user_client.get(f"/settings/tags/regeln/{rid}").text
    assert "Regel bearbeiten" in edit and "pausiert" in edit
    r = user_client.post(f"/settings/tags/regeln/{rid}", data={"tag": "bekannte", "terms": "bekannt*\nfreund", "match": "all",
                                                               "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.get(TagRule, rid).match == "all" and db.get(TagRule, rid).term_list == ["bekannt*", "freund"]
    words = user_client.get("/settings/tags/regeln/woerter", params={"tag": "bekannte"}).text
    assert "Noch zu wenige Postings" in words or "data-add-term" in words
    assert user_client.get("/settings/tags/regeln/999").status_code == 404
    user_client.post(f"/settings/tags/regeln/{rid}/loeschen", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(TagRule).count() == 0 and db.query(Tag).filter_by(name="bekannte").one()
    assert 'Automatisch taggen' in user_client.get("/settings/tags").text


def test_word_hints_ignore_untagged():
    from types import SimpleNamespace as NS
    # direkt die Zaehllogik: ungetaggte Postings zaehlen nicht gegen ein Wort
    tag = NS(id=1)
    posts = [NS(id=i, text="x verstorben", tags=[tag]) for i in range(5)] + \
            [NS(id=10 + i, text="y verstorben", tags=[]) for i in range(20)] + [NS(id=99, text="verstorben z", tags=[NS(id=2)])]

    class FakeDB:
        pass
    orig = autotag._candidates
    autotag._candidates = lambda db, person_id: posts
    try:
        hints = autotag.word_hints(FakeDB(), tag)
    finally:
        autotag._candidates = orig
    h = next(h for h in hints if h.word == "verstorben")
    assert (h.in_tag, h.tagged, h.untagged, h.precision) == (5, 6, 20, 83)


def test_apply_all_untagged_lets_several_rules_hit_one_post(user_client, harness):
    """0.20.1: "Alle auf ungetaggte anwenden" - auch die zweite Regel greift bei einem
    Posting, das erst durch die erste Regel ein Tag bekommen hat."""
    _seed(harness, user_client)
    for tag, terms in (("tiere", "kater"), ("schlaf", "bett"), ("todesfall", "verstorb*")):
        user_client.post("/settings/tags/regeln", data={"tag": tag, "terms": terms, "csrf_token": user_client.csrf})
    page = user_client.get("/settings/tags/regeln").text
    assert "Alle auf ungetaggte anwenden" in page and "<b>3</b> aktive Regeln" in page
    r = user_client.post("/settings/tags/regeln/alle-anwenden", data={"csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        names = lambda i: sorted(t.name for t in db.get(Post, i).tags)
        assert names(2) == ["schlaf", "tiere"]          # beide Regeln am selben Posting
        assert names(1) == ["bekannte"]                 # hatte schon ein Tag -> unberuehrt
        assert names(6) == ["todesfall"] and names(7) == ["todesfall"]
    assert 'class="tg-auto"' in user_client.get("/settings/tags").text


def test_persons_sorting(user_client, harness):
    _seed(harness, user_client)  # jack: 6 Postings, elon: 1
    page = user_client.get("/personen").text
    assert page.index("jack") < page.index("elon") and 'value="posts" selected' in page
    page = user_client.get("/personen?sort=name").text
    assert page.index("elon") < page.index("jack") and 'value="name" selected' in page
