"""0.22.0: Hinzufuegen mit offenen Tags und Vorschlaegen, Collage-Studio und JPG-Export."""

from __future__ import annotations

import re
from datetime import datetime

from app.models import Post, Tag, TagRule
from app.services import add_hints
from app.services import collage as svc


def _add(client, url, tags=""):
    assert client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf}).status_code == 303


def _done(harness, texts, author="jack", start=300):
    ids = []
    with harness.db() as db:
        for i, text in enumerate(texts):
            p = db.query(Post).filter_by(post_id=str(start + i)).one()
            p.text, p.status, p.posted_at = text, "done", datetime(2020 + i, 3, 1)
            ids.append(p.id)
        db.commit()
    return ids


# --- Hinzufuegen -----------------------------------------------------------------------------------

def test_add_dialog_shows_tags_directly(user_client, harness):
    _add(user_client, "https://x.com/jack/status/300", tags="todesfall")
    page = user_client.get("/add").text
    form = page[page.index('data-add-panel="link"'):page.index('data-add-panel="thread"')]
    assert "data-tag-picker" in form and "Anmerkung &amp; Tags (optional)" not in form
    assert 'id="tag-quick-p"' in form and 'data-tag-add="todesfall"' in form and "+ Anmerkung" in form
    check = user_client.get("/posts/check", params={"url": "https://x.com/jack/status/999", "slot": "p"}).text
    assert "/posts/preview?url=" in check and "slot=p" in check


def test_preview_suggests_tags(user_client, harness, monkeypatch):
    _add(user_client, "https://x.com/jack/status/300", tags="todesfall")
    _add(user_client, "https://x.com/jack/status/301", tags="katzen")
    _done(harness, ["Meine Bekannte ist verstorben.", "Der Kater schläft."])
    with harness.db() as db:
        db.add(TagRule(tag=db.query(Tag).filter_by(name="todesfall").one(), terms="verstorb*"))
        db.commit()

    class Meta:
        text, display_name = "Schon wieder ist ein Freund verstorben.", "Jack"

    async def fake_fetch(service, parsed):
        return Meta(), False
    monkeypatch.setattr(add_hints, "fetch_preview", fake_fetch)
    monkeypatch.setattr(harness.settings, "network_enabled", True)
    html = user_client.get("/posts/preview", params={"url": "https://x.com/jack/status/555", "slot": "d"}).text
    assert "Schon wieder ist ein Freund verstorben." in html and 'id="tag-quick-d"' in html and 'hx-swap-oob="true"' in html
    assert "Kommt automatisch" in html and "#todesfall ✓" in html          # Regel
    assert 'data-tag-add="katzen"' in html and "Passend zu" in html          # haeufig bei der Person
    assert user_client.get("/posts/preview", params={"url": "quatsch"}).text == ""


# --- Collage ---------------------------------------------------------------------------------------------

def test_collage_options_and_helpers():
    o = svc.Options.from_params({"format": "story", "stil": "dark", "inhalt": "shots", "titel": "  Ein   Titel ", "datum": "0"})
    assert o.size == (2160, 3840) and o.style == "dark" and o.mode == "shots" and o.title == "Ein Titel" and o.dates is False
    assert svc.Options.from_params({"format": "kaputt", "stil": "x"}).fmt == "portrait"
    assert svc.parse_ids("3, 1,abc,3,2") == [3, 1, 2]
    assert len(svc.parse_ids(",".join(str(i) for i in range(200)))) == svc.MAX_POSTS
    assert svc.export_name(o, datetime(2026, 10, 25)) == "ein-titel-2026-10-25.jpg"
    assert "@font-face" in svc.font_faces(True, "") and "data:font/woff2;base64," in svc.font_faces(True, "")


def test_collage_studio_from_search_and_selection(user_client, harness):
    for i in range(3):
        _add(user_client, f"https://x.com/jack/status/{300 + i}", tags="todesfall")
    _add(user_client, "https://x.com/elon/status/310")
    ids = _done(harness, ["Bekannte verstorben", "Freund verstorben", "Onkel verstorben"])
    _done(harness, ["Anderes Thema"], author="elon", start=310)
    page = user_client.get("/collage?tags=todesfall")
    assert page.status_code == 200
    html = page.text
    assert "data-collage-studio" in html and 'value="#todesfall"' in html and "3 Postings" in html
    assert "Anderes Thema" not in html and "collage_studio.js" in html
    sel = user_client.get(f"/collage?ids={ids[2]},{ids[0]}").text
    assert sel.index("Onkel verstorben") < sel.index("Bekannte verstorben") or "data-idx" in sel
    assert "Keine Postings für eine Collage" in user_client.get("/collage?q=gibtesnicht").text
    # Einstiege
    assert f"/collage?" in user_client.get("/?tags=todesfall").text and "data-bulk-collage" in user_client.get("/").text


def test_collage_preview_and_export(user_client, harness, monkeypatch):
    _add(user_client, "https://x.com/jack/status/300")
    _add(user_client, "https://x.com/jack/status/301")
    ids = _done(harness, ["Meine Bekannte ist verstorben <b>!</b>", "Paket verschwunden"])
    q = f"ids={ids[0]},{ids[1]}&titel=Test&markieren=verstorbene&format=square&stil=paper"
    html = user_client.get(f"/collage/vorschau?{q}").text
    assert 'class="s-paper"' in html and "width: 2160px" in html and "<h1 class=\"c-title\">Test</h1>" in html
    assert "<mark>verstorben</mark>" in html and "&lt;b&gt;" in html            # markiert, aber escaped
    assert html.count('class="c-card"') == 2 and "__collageReady" in html

    seen = {}

    async def fake_render(app, page_html, width, height):
        seen.update(html=page_html, size=(width, height))
        return b"\xff\xd8JPEGDATA"
    monkeypatch.setattr(svc, "render_with_browser", fake_render)
    r = user_client.get(f"/collage/bild.jpg?{q}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == b"\xff\xd8JPEGDATA"
    assert 'attachment; filename="test-' in r.headers["content-disposition"]
    assert seen["size"] == (2160, 2160) and "data:font/woff2;base64," in seen["html"]
    assert "/static/vendor/fonts" not in seen["html"]                         # Export ohne Server-Zugriff
    assert user_client.get("/collage/bild.jpg?ids=").status_code == 400

    async def broken(*a):
        raise RuntimeError("kein Chromium")
    monkeypatch.setattr(svc, "render_with_browser", broken)
    assert user_client.get(f"/collage/bild.jpg?{q}").status_code == 503


def test_collage_requires_login(harness):
    with harness.client() as c:
        assert c.get("/collage", follow_redirects=False).status_code in (303, 401)
        assert c.get("/collage/bild.jpg?ids=1", follow_redirects=False).status_code in (303, 401)
