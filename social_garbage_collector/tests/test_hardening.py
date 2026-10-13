"""Regressionen fuer Archivintegritaet, kurze Transaktionen und Ressourcenbudgets."""

import asyncio
import io
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import main
from app.db import init_db, make_engine, make_sessionmaker
from app.maintenance import inspect_media
from app.models import AccountChange, ArchiveNumber, GalleryImage, Post, PostRevision, User
from app.services import accounts, avatars, capture, dates, gallery, posts, uploads
from app.services.capture import reset_for_retry
from app.services.platforms import get_service
from app.services.platforms.base import PostMetadata

from .conftest import Harness, make_settings, csrf_from
from .test_capture import env, FakeService, _run


def _png(width=120, height=80, color="red"):
    out = io.BytesIO()
    with Image.new("RGB", (width, height), color) as image:
        image.save(out, "PNG")
    return out.getvalue()


def _write_during_io(harness):
    # Sehr kurzer Timeout: ein offener SQLite-Writer waere hier sofort sichtbar.
    with sqlite3.connect(harness.settings.db_path, timeout=0.15) as con:
        con.execute("UPDATE users SET display_name = display_name")


def test_capture_preserves_concurrent_manual_edits_and_releases_writer(env, monkeypatch):
    h, worker, pid = env

    class EditingService(FakeService):
        async def capture(self, *args, **kwargs):
            _write_during_io(h)
            with h.db() as db:
                post = db.get(Post, pid)
                post.text, post.text_source = "Manuell während der Aufnahme", "manual"
                dates.set_date(post, datetime(2020, 2, 3), "manual", False)
                db.commit()
            return await super().capture(*args, **kwargs)

    async def avatar(*args):
        _write_during_io(h)
        return None

    monkeypatch.setattr(accounts, "download_avatar", avatar)
    meta = PostMetadata(text="API", display_name="Original", avatar_url="https://cdn.bsky.app/avatar",
                        posted_at=datetime(2021, 1, 1))
    _run(worker, pid, EditingService(meta=meta), monkeypatch)
    with h.db() as db:
        post = db.get(Post, pid)
        assert post.status == "done" and post.text == "Manuell während der Aufnahme"
        assert post.posted_at == datetime(2020, 2, 3) and post.date_source == "manual"


def test_capture_cannot_replace_upload_made_during_capture(env, monkeypatch):
    h, worker, pid = env
    replacement = []

    class UploadingService(FakeService):
        async def capture(self, *args, **kwargs):
            result = await super().capture(*args, **kwargs)
            prepared = uploads.PreparedUpload([Image.new("RGB", (50, 50), "blue")], "test")
            try:
                with h.db() as db:
                    post = db.get(Post, pid)
                    await posts.replace_screenshot(db, h.settings, post, prepared)
                    replacement.append(post.screenshot_path)
            finally:
                prepared.close()
            return result

    _run(worker, pid, UploadingService(meta=PostMetadata(text="API")), monkeypatch)
    with h.db() as db:
        post = db.get(Post, pid)
        assert post.shot_source == "upload" and post.screenshot_path == replacement[0]
        assert post.status == "pending" and post.capture_generation == 1
    assert len(list(h.settings.screenshot_dir.rglob("*.webp"))) == 1


def test_recapture_freezes_snapshot_but_refreshes_account(env, monkeypatch):
    h, worker, pid = env
    meta = PostMetadata(text="Text", display_name="Damals", handle="damals.bsky.social", author_id="stable")
    _run(worker, pid, FakeService(meta=meta), monkeypatch)
    with h.db() as db:
        post = db.get(Post, pid)
        first_path = post.screenshot_path
        dates.set_date(post, None, "manual")
        reset_for_retry(db, post)
    meta = PostMetadata(text="Text", display_name="Heute", handle="heute.bsky.social", author_id="stable",
                        posted_at=datetime(2022, 1, 1))
    _run(worker, pid, FakeService(meta=meta), monkeypatch)
    with h.db() as db:
        post = db.get(Post, pid)
        assert post.author_display_name == "Damals" and post.author_handle == "damals.bsky.social"
        assert post.account.display_name == "Heute" and post.account.handle == "heute.bsky.social"
        assert post.posted_at is None and post.date_source == "manual"
        assert post.screenshot_path != first_path
        assert db.scalar(select(PostRevision)).action == "capture"
    assert (h.settings.base_path / first_path).exists()


def test_capture_keeps_raw_screenshot_until_ocr_finishes(env, monkeypatch):
    h, worker, pid = env
    service = FakeService(meta=PostMetadata(text="API-Fallback"))
    service.prefers_api_text = False

    def ocr(path, *args):
        assert Path(path).is_file()
        return "Text aus dem Screenshot"

    monkeypatch.setattr(capture.ocr, "ocr_image", ocr)
    _run(worker, pid, service, monkeypatch)
    with h.db() as db:
        assert db.get(Post, pid).text == "Text aus dem Screenshot"
    assert not list(h.settings.screenshot_dir.rglob("*.png"))


def test_deletion_during_capture_does_not_resurrect_post(env, monkeypatch):
    h, worker, pid = env

    class DeletingService(FakeService):
        async def capture(self, *args, **kwargs):
            result = await super().capture(*args, **kwargs)
            with h.db() as db:
                db.delete(db.get(Post, pid))
                db.commit()
            return result

    _run(worker, pid, DeletingService(meta=PostMetadata(text="Text")), monkeypatch)
    with h.db() as db:
        assert db.get(Post, pid) is None
    assert not list(h.settings.screenshot_dir.rglob("*.webp"))


def test_archive_numbers_and_history_survive_deletion(user_client, harness):
    user_client.post("/posts", data={"url": "https://x.com/a/status/1", "csrf_token": user_client.csrf})
    with harness.db() as db:
        pid = db.scalar(select(Post.id))
    user_client.post(f"/posts/{pid}/text", data={"text": "Historischer Text", "csrf_token": user_client.csrf})
    user_client.post(f"/posts/{pid}/delete", data={"csrf_token": user_client.csrf})
    user_client.post("/posts", data={"url": "https://x.com/a/status/2", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.scalar(select(Post.id)) > pid
        assert db.get(ArchiveNumber, pid) is not None
        revision = db.scalars(select(PostRevision).where(PostRevision.action == "delete")).one()
        assert revision.actor_name == "anna" and json.loads(revision.snapshot)["text"] == "Historischer Text"
    page = user_client.get(f"/posts/{pid}")
    assert page.status_code == 410 and "Historischer Text" in page.text
    with harness.client() as anon:
        assert anon.get(f"/posts/{pid}/history").status_code == 303


def test_bulk_resolves_before_creating_list_or_posts(user_client, harness, monkeypatch):
    harness.settings.network_enabled = True
    seen = []

    async def resolve(self, parsed, client):
        _write_during_io(harness)
        seen.append(parsed.post_id)
        return parsed

    monkeypatch.setattr(type(get_service("x")), "resolve", resolve)
    response = user_client.post("/import", data={"links": "\n".join(f"https://x.com/a/status/{i}" for i in range(1, 4)),
                                                "new_list": "Neue Liste", "csrf_token": user_client.csrf})
    assert response.status_code == 303 and len(seen) == 3
    with harness.db() as db:
        assert db.query(Post).count() == 3


def test_gallery_processing_does_not_hold_writer(user_client, harness, monkeypatch):
    process = gallery._process

    def checked(data):
        _write_during_io(harness)
        return process(data)

    monkeypatch.setattr(gallery, "_process", checked)
    response = user_client.post("/galerie/hochladen", data={"neue_kategorien": "Neu", "csrf_token": user_client.csrf},
                                files=[("files", ("a.png", _png(), "image/png")),
                                       ("files", ("b.png", _png(color="blue"), "image/png"))])
    assert response.status_code == 303
    with harness.db() as db:
        assert db.query(GalleryImage).count() == 2


def test_upload_limits_reject_tall_and_aggregate_images(user_client, harness, monkeypatch):
    response = user_client.post("/posts/upload", data={"platform": "x", "csrf_token": user_client.csrf},
                                files=[("files", ("tall.png", _png(1, 16001), "image/png"))])
    assert response.status_code == 400
    monkeypatch.setattr(uploads, "MAX_TOTAL_BYTES", len(_png()) + 1)
    response = user_client.post("/posts/upload", data={"platform": "x", "csrf_token": user_client.csrf},
                                files=[("files", ("a.png", _png(), "image/png")),
                                       ("files", ("b.png", _png(color="blue"), "image/png"))])
    assert response.status_code == 400 and "Zusammen" in response.text
    with harness.db() as db:
        assert db.query(Post).count() == 0


def test_gallery_rolls_back_files_on_aggregate_limit(harness, monkeypatch):
    monkeypatch.setattr(gallery, "MAX_TOTAL_BYTES", len(_png()) + 1)
    with harness.db() as db:
        user = db.scalar(select(User))
        with pytest.raises(gallery.GalleryError):
            gallery.add_images(db, harness.settings, user, iter([("a", _png()), ("b", _png(color="blue"))]), [])
        assert db.query(GalleryImage).count() == 0
    assert not list(harness.settings.gallery_dir.rglob("*.webp"))


def test_preupgrade_backup_can_be_restored_and_numbers_stay_reserved(tmp_path):
    path = tmp_path / "legacy.sqlite"
    engine = make_engine(path)
    init_db(engine)
    with make_sessionmaker(engine)() as db:
        db.add(Post(id=42, platform="x", url="https://x.com/a/status/1", dedup_key="x:1", post_id="1",
                    author_display_name="Archiviert", status="done"))
        db.commit()
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA user_version=7")
        conn.exec_driver_sql("DROP TRIGGER posts_reserve_number")
        conn.exec_driver_sql("DROP TABLE archive_numbers")
        conn.exec_driver_sql("DROP TABLE post_revisions")
        conn.exec_driver_sql("ALTER TABLE posts DROP COLUMN snapshot_at")
        conn.exec_driver_sql("ALTER TABLE posts DROP COLUMN capture_generation")
    init_db(engine, tmp_path / "backups")
    backups = list((tmp_path / "backups").glob("pre-upgrade-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 7
        assert con.execute("SELECT author_display_name FROM posts WHERE id=42").fetchone()[0] == "Archiviert"
    with make_sessionmaker(engine)() as db:
        assert db.get(Post, 42).snapshot_at is not None
        db.delete(db.get(Post, 42))
        db.commit()
        replacement = Post(platform="x", url="", dedup_key="x:2", post_id="2")
        db.add(replacement)
        db.commit()
        assert replacement.id > 42
    init_db(engine, tmp_path / "backups")
    assert len(list((tmp_path / "backups").glob("pre-upgrade-*.sqlite"))) == 1
    engine.dispose()
    restored = tmp_path / "restored.sqlite"
    shutil.copy2(backups[0], restored)
    restored_engine = make_engine(restored)
    init_db(restored_engine, tmp_path / "restore-backups")
    with make_sessionmaker(restored_engine)() as db:
        assert db.get(Post, 42).author_display_name == "Archiviert"
    restored_engine.dispose()


def test_health_reports_database_failure(user_client, harness, monkeypatch):
    assert user_client.get("/health").status_code == 200

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("Unavailable")

    monkeypatch.setattr(harness.app.state.engine, "connect", broken)
    response = user_client.get("/health")
    assert response.status_code == 503 and response.json()["checks"]["database"] is False


def test_setup_long_code_and_throttle(tmp_path):
    h = Harness(make_settings(tmp_path, login_max_attempts=1))
    with TestClient(h.app) as client:
        code = h.app.state.setup_code
        assert len(code) == 32
        page = client.get("/setup")
        assert 'maxlength="32"' in page.text
        token = csrf_from(page.text)
        data = {"code": "falsch-ä", "username": "admin", "password": "langes-passwort", "password2": "langes-passwort",
                "csrf_token": token}
        for _ in range(3):
            assert client.post("/setup", data=data).status_code == 400
        data["code"] = code
        assert client.post("/setup", data=data).status_code == 429


def test_request_size_limit_with_and_without_content_length(user_client, monkeypatch):
    monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 100)
    assert user_client.post("/posts", content=b"x" * 101).status_code == 413
    response = user_client.post("/posts", content=iter([b"x" * 60, b"y" * 60]),
                                headers={"content-type": "application/x-www-form-urlencoded", "x-csrf-token": user_client.csrf})
    assert response.status_code == 413


def test_gallery_pages_keep_category_filter(user_client, harness):
    with harness.db() as db:
        for i in range(gallery.PAGE_SIZE + 1):
            db.add(GalleryImage(path=f"gallery/{i}.webp", thumb_path=f"gallery/{i}.thumb.webp",
                                width=50, height=50, sha256=str(i)))
        db.commit()
    first = user_client.get("/galerie?k=ohne")
    assert first.text.count("data-gal-item") == gallery.PAGE_SIZE
    assert "k=ohne&amp;page=2" in first.text
    second = user_client.get("/galerie?k=ohne&page=2")
    assert second.text.count("data-gal-item") == 1


def test_maximum_date_filter_does_not_overflow(user_client):
    assert user_client.get("/?to=9999-12-31").status_code == 200


def test_avatar_commit_failure_preserves_previous_file(harness, monkeypatch):
    with harness.db() as db:
        user = db.scalar(select(User))
        avatars.save(harness.settings, user, _png())
        db.commit()
        old = user.avatar_path
        avatars.save(harness.settings, user, _png(color="blue"))
        new = user.avatar_path

        def fail():
            raise RuntimeError("Commit failed")

        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError, match="Commit failed"):
            avatars.commit_change(db, harness.settings, old, new)
        assert user.avatar_path == old
        assert (harness.settings.base_path / old).is_file()
        assert not (harness.settings.base_path / new).exists()


def test_media_audit_keeps_revision_evidence_and_never_deletes(harness):
    evidence = harness.settings.screenshot_dir / "historical.webp"
    orphan = harness.settings.screenshot_dir / "unused.webp"
    old_avatar = harness.settings.author_dir / "historical-avatar.webp"
    for path in (evidence, orphan, old_avatar):
        with Image.new("RGB", (20, 20)) as image:
            image.save(path, "WEBP")
    with harness.db() as db:
        account = accounts.resolve(db, "x", None, "anna", "Anna")
        db.add(AccountChange(account_id=account.id, field="avatar_path", old_value="authors/historical-avatar.webp",
                             new_value="authors/historical-avatar.webp"))
        db.add(PostRevision(post_id=99, actor_name="anna", action="delete",
                            snapshot=json.dumps({"screenshot_path": "screenshots/historical.webp"})))
        db.commit()
    report = inspect_media(harness.settings)
    assert report == {"missing": [], "invalid": [], "unreferenced": ["screenshots/unused.webp"]}
    assert evidence.is_file() and orphan.is_file()


def test_health_reports_dead_worker(user_client, harness, monkeypatch):
    monkeypatch.setattr(harness.settings, "worker_enabled", True)
    monkeypatch.setattr(harness.app.state, "worker", SimpleNamespace(_task=SimpleNamespace(done=lambda: True)))
    response = user_client.get("/health")
    assert response.status_code == 503 and response.json()["checks"]["worker"] is False
    # TestClient beendet den Lifespan vor dem monkeypatch-Teardown.
    monkeypatch.setattr(harness.app.state, "worker", None)


def test_avatar_download_does_not_follow_redirects_or_exceed_budget(harness, monkeypatch):
    calls = []

    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(redirect), follow_redirects=True) as client:
            assert await accounts.download_avatar(client, harness.settings, "https://cdn.bsky.app/avatar") is None
        monkeypatch.setattr(accounts, "AVATAR_MAX_BYTES", 20)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 21))) as client:
            assert await accounts.download_avatar(client, harness.settings, "https://cdn.bsky.app/avatar") is None

    asyncio.run(check())
    assert calls == ["https://cdn.bsky.app/avatar"]
    assert not list(harness.settings.author_dir.iterdir())
