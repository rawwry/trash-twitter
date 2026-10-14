"""0.11.0: Teilen per Kurzbefehl (API-Schluessel), Hilfe/FAQ, Ideen, Medien in der Uebersicht."""

from __future__ import annotations

import asyncio
import io
import re

from PIL import Image

from app.models import FeatureIdea, IdeaVote, Post, PostMedia, User
from app.services import media
from app.services.platforms.base import MediaRef


def _token(client) -> str:
    html = client.post("/settings/schluessel", data={"csrf_token": client.csrf}).text
    return re.search(r'id="token-value" readonly value="([^"]+)"', html).group(1)


# --- Schluessel + Schnittstelle --------------------------------------------------------------

def test_api_token_lifecycle(user_client, harness):
    token = _token(user_client)
    assert token.startswith("tt_") and len(token) > 30
    u = harness.get_user("anna")
    assert u.api_token_hash and token not in (u.api_token_hash or "") and u.api_token_hint == token[-4:]
    page = user_client.get("/hilfe").text
    assert "Schlüssel aktiv" in page and token not in page  # Klartext nur einmal
    user_client.post("/settings/schluessel/loeschen", data={"csrf_token": user_client.csrf})
    assert harness.get_user("anna").api_token_hash is None


def test_share_api_archives_and_detects_duplicates(user_client, harness):
    token = _token(user_client)
    with harness.client() as c:  # ohne Login-Cookie, wie ein Kurzbefehl
        r = c.post("/api/teilen", data={"url": "Schau mal https://x.com/jack/status/20?s=20 lol"},
                   headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201 and r.text.startswith("Archiviert: @jack (Nr. 000001)")
        r = c.post("/api/teilen?format=json", json={"url": "https://twitter.com/jack/status/20"},
                   headers={"Authorization": f"Bearer {token}"})
        assert r.json() == {"ok": False, "message": "Schon im Archiv (Nr. 000001).", "id": 1}
        r = c.post("/api/teilen", data={"text": "nur Text"}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400 and "Kein Link" in r.text
        assert c.post("/api/teilen", data={"url": "https://x.com/a/status/2"}, headers={"Authorization": "Bearer tt_falsch"}).status_code == 401
        assert c.post("/api/teilen", data={"url": "https://x.com/a/status/2"}).status_code == 403  # ohne Schluessel: CSRF greift
    with harness.db() as db:
        post = db.query(Post).one()
        assert post.added_by.username == "anna"


def test_share_api_rejects_inactive_user(user_client, harness):
    token = _token(user_client)
    with harness.db() as db:
        db.query(User).filter_by(username="anna").one().is_active = False
        db.commit()
    with harness.client() as c:
        assert c.post("/api/teilen", data={"url": "https://x.com/a/status/2"},
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_help_page_shows_direct_address(user_client):
    page = user_client.get("/hilfe").text
    assert "/api/teilen" in page and "Kurzbefehle" in page and "HTTP Shortcuts" in page and 'id="faq"' in page
    ingress = user_client.get("/hilfe", headers={"X-Ingress-Path": "/api/hassio_ingress/tok", "Host": "homeassistant.local"}).text
    assert "http://homeassistant.local:8780/api/teilen" in ingress and "Seitenleiste" in ingress


# --- Ideen -----------------------------------------------------------------------------------

def test_ideas_create_vote_status_delete(user_client, admin_client, harness):
    r = user_client.post("/ideen", data={"title": "PDF-Export", "body": "Listen als PDF", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        idea = db.query(FeatureIdea).one()
        assert db.query(IdeaVote).count() == 1  # eigene Stimme
        iid = idea.id
    r = admin_client.post(f"/ideen/{iid}/stimme", headers={"HX-Request": "true", "X-CSRF-Token": admin_client.csrf})
    assert 'aria-pressed="true"' in r.text and "<strong>2</strong>" in r.text
    # Stand setzen nur Admin
    assert user_client.post(f"/ideen/{iid}/status", data={"status": "geplant", "csrf_token": user_client.csrf}).status_code == 404
    admin_client.post(f"/ideen/{iid}/status", data={"status": "umgesetzt", "answer": "Ist drin!", "csrf_token": admin_client.csrf})
    assert "PDF-Export" not in user_client.get("/ideen").text            # nicht mehr "offen"
    assert "Ist drin!" in user_client.get("/ideen?zeige=umgesetzt").text
    # Loeschen: Verfasser:in ja, andere nicht
    harness.add_user("bert", "bert-12345")
    from .conftest import login
    with harness.client() as bert:
        bert.csrf = login(bert, "bert", "bert-12345")
        assert bert.post(f"/ideen/{iid}/loeschen", data={"csrf_token": bert.csrf}).status_code == 403
    assert user_client.post(f"/ideen/{iid}/loeschen", data={"csrf_token": user_client.csrf}).status_code == 303
    with harness.db() as db:
        assert db.query(FeatureIdea).count() == 0 and db.query(IdeaVote).count() == 0
    assert user_client.post("/ideen", data={"title": "x", "csrf_token": user_client.csrf}).status_code == 303


# --- Medien in der Uebersicht ------------------------------------------------------------------

def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), (200, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


def test_media_thumbs_and_archive_strip(user_client, harness, monkeypatch):
    user_client.post("/posts", data={"url": "https://x.com/a/status/1", "csrf_token": user_client.csrf})

    async def fake_download(client, url, max_bytes, hops=3):
        return (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50, "video/mp4") if url.endswith(".mp4") else (_jpg(), "image/jpeg")

    monkeypatch.setattr(media, "_download", fake_download)
    with harness.db() as db:
        post = db.query(Post).one()
        asyncio.run(media.save_media(db, harness.settings, None, post, [
            MediaRef("photo", "https://pbs.twimg.com/media/a.jpg?name=orig"),
            MediaRef("video", "https://video.twimg.com/v.mp4", poster="https://pbs.twimg.com/poster.jpg")]))
        db.commit()
        items = db.query(PostMedia).order_by(PostMedia.position).all()
        assert all(m.thumb_path and m.thumb_path.endswith(".thumb.webp") for m in items)
        with Image.open(harness.settings.base_path / items[0].thumb_path) as im:
            assert max(im.size) == 720
        thumbs = [m.thumb_path for m in items]
    for view in ("cards", "timeline"):
        page = user_client.get(f"/?view={view}").text
        assert 'class="q-media n2"' in page and thumbs[0] in page and "q-play" in page, view
    assert "qtile-" in user_client.get("/?view=raster").text


def test_backfill_thumbs_for_old_media(harness):
    folder = harness.settings.media_dir / "x" / "2026"
    folder.mkdir(parents=True)
    (folder / "alt.jpg").write_bytes(_jpg())
    with harness.db() as db:
        post = Post(platform="x", url="https://x.com/a/status/5", dedup_key="x:5", post_id="5")
        db.add(post)
        db.flush()
        post.media.append(PostMedia(kind="photo", path="media/x/2026/alt.jpg", mime="image/jpeg"))
        db.commit()
        assert media.backfill_thumbs(db, harness.settings) == 1
        assert db.query(PostMedia).one().thumb_path == "media/x/2026/alt.thumb.webp"
