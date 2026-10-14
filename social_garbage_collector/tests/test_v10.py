"""0.10.0: Tags antippen, leere Personen weg, Hinzufuegen-Knopf, Raster, Medien, Schnell-Loeschen."""

from __future__ import annotations

import asyncio
import json

from PIL import Image

from app.models import Account, Person, Post, PostMedia
from app.services import media
from app.services.platforms.base import MediaRef
from app.services.platforms.bluesky import bluesky_media
from app.services.platforms.x import x_media


def _add(client, url, tags=""):
    return client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf})


def _ids(harness):
    with harness.db() as db:
        return [p.id for p in db.query(Post).order_by(Post.id)]


# --- Tags antippen ------------------------------------------------------------------------

def test_tag_bar_and_quick_pick(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="energie, klima")
    _add(user_client, "https://x.com/a/status/2", tags="energie")
    page = user_client.get("/").text
    assert 'data-tag-toggle="energie"' in page and 'data-tag-toggle="klima"' in page
    assert page.index('data-tag-toggle="energie"') < page.index('data-tag-toggle="klima"')  # haeufigste zuerst
    assert 'aria-pressed="true"' in user_client.get("/?tags=klima").text
    assert user_client.get("/?tags=energie,klima").text.count('data-post="') == 1
    pid = _ids(harness)[0]
    detail = user_client.get(f"/posts/{pid}").text
    assert 'data-tag-quick="energie"' in detail


# --- Personen ohne Postings ---------------------------------------------------------------

def test_person_disappears_after_deleting_last_post(user_client, harness):
    _add(user_client, "https://x.com/olaf/status/1")
    pid = _ids(harness)[0]
    assert "@olaf" in user_client.get("/personen").text
    user_client.post(f"/posts/{pid}/delete", data={"csrf_token": user_client.csrf})
    assert "@olaf" not in user_client.get("/personen").text
    with harness.db() as db:
        assert db.query(Account).count() == 0 and db.query(Person).count() == 0


# --- Hinzufuegen-Knopf -------------------------------------------------------------------

def test_add_button_follows_section(user_client):
    archive = user_client.get("/").text
    assert 'data-open="add-dialog"' in archive and "Posting</button>" in archive
    gallery = user_client.get("/galerie").text
    assert 'class="btn sm btn-add" type="button" data-open="gallery-upload"' in gallery
    assert gallery.count('data-open="gallery-upload"') >= 2  # Kopfzeile + Plus unten


# --- Raster -------------------------------------------------------------------------------

def test_raster_view_is_clean(user_client, harness):
    _add(user_client, "https://x.com/a/status/1", tags="energie")
    page = user_client.get("/?view=raster").text
    assert 'class="qtile"' in page
    tile = page[page.index('class="qtile"'):page.index("</article>", page.index('class="qtile"'))]
    assert "Original" not in tile and "#energie" not in tile and "Nr." not in tile.split("aria-label")[0]


# --- Schnell-Loeschen ---------------------------------------------------------------------

def test_quick_delete_via_htmx_and_bulk(user_client, harness):
    for i in range(1, 4):
        _add(user_client, f"https://x.com/a/status/{i}")
    a, b, c = _ids(harness)
    page = user_client.get("/").text
    assert "q-del" in page and 'hx-confirm="Posting Nr.' in page and 'id="confirm-dialog"' in page
    r = user_client.post(f"/posts/{a}/delete", headers={"HX-Request": "true", "HX-Target": f"post-{a}",
                                                       "X-CSRF-Token": user_client.csrf})
    assert r.status_code == 200 and r.text == "" and "toast" in r.headers["HX-Trigger"]
    r = user_client.post("/posts/bulk/delete", data={"ids": [b, c], "back": "/?view=list", "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith("/?view=list")
    assert _ids(harness) == []
    assert user_client.post("/posts/bulk/delete", data={"ids": [1]}).status_code == 403


# --- Medien: auslesen -----------------------------------------------------------------------

def test_x_media_extraction():
    data = {"mediaDetails": [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/A.jpg", "ext_alt_text": "Grafik",
         "original_info": {"width": 1200, "height": 800}},
        {"type": "video", "video_info": {"variants": [
            {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/x.m3u8"},
            {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/low.mp4"},
            {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/high.mp4"}]}},
        {"type": "animated_gif", "video_info": {"variants": [{"content_type": "video/mp4", "bitrate": 0,
                                                              "url": "https://video.twimg.com/gif.mp4"}]}},
    ]}
    refs = x_media(data)
    assert [(r.kind, r.url) for r in refs] == [("photo", "https://pbs.twimg.com/media/A.jpg?name=orig"),
                                               ("video", "https://video.twimg.com/high.mp4"),
                                               ("gif", "https://video.twimg.com/gif.mp4")]
    assert refs[0].alt == "Grafik" and refs[0].width == 1200


def test_bluesky_media_extraction():
    did = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa"
    video = {"$type": "app.bsky.embed.video#view", "cid": "bafyvideo", "alt": "Clip", "aspectRatio": {"width": 16, "height": 9}}
    assert [(r.kind, r.did, r.cid) for r in bluesky_media(video, did)] == [("video", did, "bafyvideo")]
    rwm = {"$type": "app.bsky.embed.recordWithMedia#view", "media": {"$type": "app.bsky.embed.images#view",
           "images": [{"fullsize": "https://cdn.bsky.app/img/a@jpeg", "alt": "A"}]}}
    assert [r.url for r in bluesky_media(rwm, did)] == ["https://cdn.bsky.app/img/a@jpeg"]
    gif = {"$type": "app.bsky.embed.external#view", "external": {"uri": "https://media.tenor.com/abc/katze.gif", "title": "Katze"}}
    assert [(r.kind, r.url) for r in bluesky_media(gif, did)] == [("gif", "https://media.tenor.com/abc/katze.gif")]
    link = {"$type": "app.bsky.embed.external#view", "external": {"uri": "https://www.tagesschau.de/x"}}
    assert bluesky_media(link, did) == []


# --- Medien: sichern, ausliefern, loeschen --------------------------------------------------

def _png_bytes():
    import io

    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100


def test_save_media_and_serve(user_client, harness, monkeypatch):
    _add(user_client, "https://x.com/a/status/1")
    pid = _ids(harness)[0]

    async def fake_download(client, url, max_bytes, hops=3):
        return (MP4, "application/octet-stream") if url.endswith(".mp4") or "getBlob" in url else (_png_bytes(), "image/png")

    async def fake_blob(client, did, cid):
        return "https://pds.example/xrpc/com.atproto.sync.getBlob?cid=" + cid

    monkeypatch.setattr(media, "_download", fake_download)
    monkeypatch.setattr(media, "pds_blob_url", fake_blob)
    refs = [MediaRef("photo", "https://pbs.twimg.com/media/A.jpg?name=orig", "Grafik"),
            MediaRef("video", "https://video.twimg.com/v.mp4"),
            MediaRef("photo", "https://evil.example/x.png"),        # fremder Server -> ignoriert
            MediaRef("video", "", did="did:plc:x", cid="bafy")]      # Bluesky-Blob
    with harness.db() as db:
        post = db.get(Post, pid)
        problems = asyncio.run(media.save_media(db, harness.settings, None, post, refs))
        db.commit()
        items = db.query(PostMedia).order_by(PostMedia.position).all()
        assert problems == [] and [(m.kind, m.mime) for m in items] == [("photo", "image/png"), ("video", "video/mp4"), ("video", "video/mp4")]
        assert items[0].width == 30 and items[0].alt == "Grafik" and db.get(Post, pid).media_checked
        paths = [m.path for m in items]
    page = user_client.get(f"/posts/{pid}").text
    assert "Medien" in page and "<video" in page and "Grafik" in page
    assert "▶ 2 Videos" in user_client.get("/").text
    r = user_client.get("/medien/" + paths[1], headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10  # Spulen in Videos
    assert user_client.get("/medien/db/archiv.sqlite").status_code == 404
    user_client.post(f"/posts/{pid}/delete", data={"csrf_token": user_client.csrf})
    assert not any((harness.settings.base_path / p).exists() for p in paths)


def test_media_size_limit_and_switch(harness, monkeypatch):
    harness.settings.media_max_mb = 1

    async def huge(client, url, max_bytes, hops=3):
        raise media.MediaError("zu groß")

    monkeypatch.setattr(media, "_download", huge)
    with harness.db() as db:
        post = Post(platform="x", url="https://x.com/a/status/9", dedup_key="x:9", post_id="9")
        db.add(post)
        db.flush()
        problems = asyncio.run(media.save_media(db, harness.settings, None, post, [MediaRef("video", "https://video.twimg.com/v.mp4")]))
        assert problems and "zu groß" in problems[0] and post.media_checked
        harness.settings.save_media = False
        post2 = Post(platform="x", url="https://x.com/a/status/10", dedup_key="x:10", post_id="10")
        db.add(post2)
        db.flush()
        assert asyncio.run(media.save_media(db, harness.settings, None, post2, [MediaRef("photo", "https://pbs.twimg.com/a.jpg")])) == []
        assert post2.media == []


def test_media_hosts_and_private_pds():
    assert media._host_ok("https://pbs.twimg.com/media/a.jpg")
    assert not media._host_ok("http://pbs.twimg.com/media/a.jpg")
    assert not media._host_ok("https://evil.example/a.jpg")
    assert asyncio.run(media._public_host("localhost")) is False
    assert asyncio.run(media._public_host("127.0.0.1")) is False
