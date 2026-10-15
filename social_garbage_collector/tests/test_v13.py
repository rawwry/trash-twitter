"""0.13.0: Videos in der Galerie."""

from __future__ import annotations

import io
import json

from PIL import Image

from app.models import GalleryImage

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 4000


def _png(w=640, h=360, color=(200, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _post(client, files, posters=(), info=None):
    multipart = [("files", f) for f in files] + [("posters", p) for p in posters]
    data = {"csrf_token": client.csrf}
    if info is not None:
        data["video_info"] = json.dumps(info)
    return client.post("/galerie/hochladen", data=data, files=multipart)


def test_video_upload_with_browser_poster(user_client, harness):
    r = _post(user_client, [("bild.png", _png(), "image/png"), ("clip.mp4", FAKE_MP4, "video/mp4")],
              posters=[("1.jpg", _png(1280, 720, (10, 200, 10)), "image/jpeg")], info={"1": 75.4})
    assert r.status_code == 303
    with harness.db() as db:
        img, vid = db.query(GalleryImage).order_by(GalleryImage.id).all()
        assert img.kind == "image" and vid.kind == "video"
        assert vid.path.endswith(".mp4") and vid.mime == "video/mp4" and vid.bytes == len(FAKE_MP4)
        assert (vid.width, vid.height) == (1280, 720) and vid.duration == 75.4 and vid.duration_label == "1:15"
        base = harness.settings.base_path
        assert (base / vid.path).read_bytes() == FAKE_MP4  # Original, unveraendert
        assert (base / vid.poster_path).exists() and (base / vid.thumb_path).exists()
        vid_id, path, poster = vid.id, vid.path, vid.poster_path
    page = user_client.get("/galerie").text
    assert 'data-kind="video"' in page and "gal-play" in page and "1:15" in page
    # Abspielen mit Spulen (Range) und Herunterladen
    r = user_client.get(f"/galerie/datei/{path}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp4" and len(r.content) == 100
    assert user_client.get(f"/galerie/datei/{poster}").status_code == 200
    # gleiches Video nochmal -> erkannt
    _post(user_client, [("nochmal.mp4", FAKE_MP4, "video/mp4")])
    with harness.db() as db:
        assert db.query(GalleryImage).count() == 2
    # Loeschen entfernt Video, Standbild und Vorschau
    user_client.post(f"/galerie/bild/{vid_id}/loeschen", data={"csrf_token": user_client.csrf})
    assert not (base / path).exists() and not (base / poster).exists()


def test_video_without_poster_gets_placeholder(user_client, harness, monkeypatch):
    from app.services import gallery
    monkeypatch.setattr(gallery, "_ffmpeg_poster", lambda *a: None)
    assert _post(user_client, [("clip.mov", b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 100, "video/quicktime")]).status_code == 303
    with harness.db() as db:
        vid = db.query(GalleryImage).one()
        assert vid.path.endswith(".mov") and vid.mime == "video/quicktime" and (vid.width, vid.height) == (1280, 720)
        assert vid.duration is None


def test_fake_video_and_size_limit_rejected(user_client, harness):
    r = _post(user_client, [("boese.mp4", b"<script>alert(1)</script>" * 10, "video/mp4")])
    assert r.status_code == 303
    harness.settings.media_max_mb = 1
    _post(user_client, [("gross.mp4", FAKE_MP4 + b"\x00" * (1024 * 1024 + 10), "video/mp4")])
    with harness.db() as db:
        assert db.query(GalleryImage).count() == 0
    left = list((harness.settings.gallery_dir).rglob("*"))
    assert not [p for p in left if p.is_file()]  # keine Reste (.part, Videodatei)


def test_upload_form_accepts_videos(user_client):
    page = user_client.get("/galerie").text
    assert "video/mp4" in page and "Bilder &amp; Videos hinzufügen" in page and "data-lb-video" in page
