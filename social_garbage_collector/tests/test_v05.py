"""0.5.0: Eigene Screenshots hochladen (neuer Beitrag oder Ersatz fuer einen vorhandenen)."""

from __future__ import annotations

import asyncio
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.models import Post
from app.services import capture as capture_mod
from app.services import ocr
from app.services.capture import CaptureWorker
from app.services.platforms.base import PostMetadata, PostNotFound

from .conftest import Harness, make_settings


def _png(w=600, h=300, color=(21, 32, 43), exif_gps=False) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {2: (52.0, 13.0, 0.0)}  # GPS-Block
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def _upload(client, files, **data):
    data.setdefault("csrf_token", client.csrf)
    return client.post("/posts/upload", data=data,
                       files=[("files", (f"bild{i}.png", b, "image/png")) for i, b in enumerate(files)])


def _post(harness):
    with harness.db() as db:
        return db.query(Post).order_by(Post.id.desc()).first()


def test_upload_without_link(user_client, harness):
    r = _upload(user_client, [_png()], platform="x", handle="@Witzbold", posted="2023-02-06",
                note="Gelöscht, aber gerettet", tags="humor")
    assert r.status_code == 303
    p = _post(harness)
    assert p.shot_source == "upload" and p.platform == "x" and p.url == ""
    assert p.author_handle == "Witzbold" and p.posted_at.date().isoformat() == "2023-02-06"
    assert p.dedup_key.startswith("upload:") and p.post_id.startswith("u")
    assert p.screenshot_path.endswith(".webp") and (p.shot_w, p.shot_h) == (600, 300)
    with Image.open(harness.settings.base_path / p.screenshot_path) as img:
        assert img.format == "WEBP"
    # Detailseite ohne Link: keine "Original öffnen"-Knoepfe, aber Upload-Bereich
    page = user_client.get(f"/posts/{p.id}").text
    assert "Original öffnen" not in page and "Anderen Screenshot hochladen" in page
    assert "Originallink unbekannt" in page  # Quellenangabe sagt ehrlich, dass der Link fehlt


def test_upload_multiple_images_are_stitched(user_client, harness):
    _upload(user_client, [_png(600, 200), _png(600, 300)], platform="bluesky")
    p = _post(harness)
    from app.services import shots
    assert (p.shot_w, p.shot_h) == (600, 500 + shots.THREAD_GAP)


def test_upload_requires_platform_or_link_and_valid_image(user_client, harness):
    r = _upload(user_client, [_png()])
    assert r.status_code == 400 and "X oder Bluesky" in r.text
    r = _upload(user_client, [b"kein bild"], platform="x")
    assert r.status_code == 400 and "kein lesbares Bild" in r.text
    r = _upload(user_client, [], platform="x")
    assert r.status_code == 400 and "mindestens ein Bild" in r.text
    r = _upload(user_client, [_png()], platform="x", link="https://example.com/x")
    assert r.status_code == 400 and "kein Beitrags-Link" in r.text
    with harness.db() as db:
        assert db.query(Post).count() == 0
    assert user_client.post("/posts/upload", data={"platform": "x"},
                            files=[("files", ("a.png", _png(), "image/png"))]).status_code == 403


def test_upload_duplicate_image_and_link(user_client, harness):
    img = _png(color=(1, 2, 3))
    assert _upload(user_client, [img], platform="x").status_code == 303
    r = _upload(user_client, [img], platform="x")
    assert r.status_code == 400 and "schon hochgeladen" in r.text
    # mit Link: Duplikat ueber den Link
    assert _upload(user_client, [_png(color=(9, 9, 9))], link="https://x.com/jack/status/20").status_code == 303
    p = _post(harness)
    assert p.url == "https://x.com/jack/status/20" and p.dedup_key == "x:20" and p.shot_source == "upload"
    r = user_client.post("/posts", data={"url": "https://twitter.com/jack/status/20", "csrf_token": user_client.csrf})
    assert r.status_code == 400 and "schon im Archiv" in r.text


def test_upload_strips_metadata_and_shrinks(user_client, harness):
    _upload(user_client, [_png(3000, 1000, exif_gps=True)], platform="x")
    p = _post(harness)
    with Image.open(harness.settings.base_path / p.screenshot_path) as img:
        assert img.width == 1400 and not img.getexif().get(0x8825)


def test_manual_text_is_kept(user_client, harness):
    _upload(user_client, [_png()], platform="x", text="Mein eigener Text")
    p = _post(harness)
    assert p.text == "Mein eigener Text" and p.text_source == "manual"


def test_replace_screenshot_of_failed_post(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/weg/status/77", "csrf_token": user_client.csrf})
    p = _post(harness)
    with harness.db() as db:
        db.get(Post, p.id).status = "error"
        db.commit()
    assert "Eigenen Screenshot hochladen" in user_client.get(f"/posts/{p.id}").text
    r = user_client.post(f"/posts/{p.id}/screenshot", data={"csrf_token": user_client.csrf},
                         files=[("files", ("s.png", _png(), "image/png"))])
    assert r.status_code == 303
    p = _post(harness)
    assert p.shot_source == "upload" and p.screenshot_path.endswith(".webp") and p.status == "pending"
    # zurueck zur automatischen Aufnahme
    user_client.post(f"/posts/{p.id}/auto", data={"csrf_token": user_client.csrf})
    assert _post(harness).shot_source == "auto"


def test_add_page_upload_tab(user_client):
    page = user_client.get("/add?mode=upload").text
    assert 'data-add-panel="upload"' in page and 'action="/posts/upload"' in page
    # im Archiv-Sheet sind beide Reiter da, "Link" ist vorne
    archive = user_client.get("/").text
    assert 'data-add-tab="upload"' in archive


# --- Worker: hochgeladene Bilder werden nie selbst aufgenommen -------------------------------

class NoCaptureService:
    name = "x"
    label = "X"
    prefers_api_text = False

    def __init__(self, meta=None, exc=None):
        self.meta, self.exc = meta, exc

    async def fetch_metadata(self, parsed, client):
        if self.exc:
            raise self.exc
        return self.meta

    async def capture(self, *a, **kw):  # darf nie aufgerufen werden
        raise AssertionError("Upload-Beitrag wurde automatisch aufgenommen")

    async def thread_chain(self, parsed, client):
        raise AssertionError("Upload-Beitrag sucht keinen Thread")


def _worker_post(tmp_path, monkeypatch, service, url=""):
    h = Harness(make_settings(tmp_path))
    client = TestClient(h.app)
    client.__enter__()
    shot = h.settings.screenshot_dir / "x" / "2026" / "u.webp"
    shot.parent.mkdir(parents=True)
    Image.new("RGB", (400, 200)).save(shot, "WEBP")
    with h.db() as db:
        p = Post(platform="x", url=url, dedup_key="upload:abc", post_id="uabc", shot_source="upload",
                 screenshot_path="screenshots/x/2026/u.webp", status="pending")
        db.add(p)
        db.commit()
        pid = p.id
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: service)
    monkeypatch.setattr(ocr, "ocr_image", lambda src: "Text per OCR")
    asyncio.run(CaptureWorker(h.settings, h.app.state.SessionLocal).process(pid))
    with h.db() as db:
        post = db.get(Post, pid)
    client.__exit__(None, None, None)
    return post


def test_worker_upload_ocr_only(tmp_path, monkeypatch):
    p = _worker_post(tmp_path, monkeypatch, NoCaptureService())
    assert p.status == "done" and p.text == "Text per OCR" and p.text_source == "ocr"
    assert p.screenshot_path == "screenshots/x/2026/u.webp"


def test_worker_upload_with_deleted_original(tmp_path, monkeypatch):
    p = _worker_post(tmp_path, monkeypatch, NoCaptureService(exc=PostNotFound("weg")),
                     url="https://x.com/a/status/1")
    assert p.status == "done" and "Screenshot bleibt" in p.status_message


def test_worker_upload_uses_metadata(tmp_path, monkeypatch):
    p = _worker_post(tmp_path, monkeypatch, NoCaptureService(meta=PostMetadata(display_name="Jack", handle="jack")),
                     url="https://x.com/jack/status/20")
    assert p.author_display_name == "Jack" and p.author_handle == "jack"
