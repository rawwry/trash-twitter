"""Hintergrund-Worker mit einer Fake-Plattform (kein Netz, kein Browser)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.models import STATUS_DONE, STATUS_ERROR, TEXT_API, TEXT_MANUAL, Post
from app.services import capture as capture_mod
from app.services.capture import CaptureWorker
from app.services.platforms.base import CaptureResult, PlatformError, PostMetadata, PostNotFound

from .conftest import Harness, make_settings


class FakeService:
    name = "bluesky"
    label = "Bluesky"
    prefers_api_text = True

    def __init__(self, meta=None, meta_exc=None, capture_exc=None):
        self.meta, self.meta_exc, self.capture_exc = meta, meta_exc, capture_exc
        self.captured = False

    async def thread_chain(self, parsed, client):
        return [parsed]

    async def fetch_metadata(self, parsed, client):
        if self.meta_exc:
            raise self.meta_exc
        return self.meta

    async def capture(self, parsed, browser, target, dark=True):
        self.dark = dark
        self.captured = True
        if self.capture_exc:
            raise self.capture_exc
        from PIL import Image
        Image.new("RGB", (600, 200), (21, 32, 43)).save(target)
        return CaptureResult(screenshot=target, method="fake")


@pytest.fixture
def env(tmp_path, monkeypatch):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):
        with h.db() as db:
            post = Post(platform="bluesky", url="https://bsky.app/profile/a.bsky.social/post/3k",
                        dedup_key="bluesky:a.bsky.social:3k", post_id="3k", author_handle="a.bsky.social")
            db.add(post)
            db.commit()
            pid = post.id
        worker = CaptureWorker(h.settings, h.app.state.SessionLocal)

        async def fake_browser():
            return object()
        monkeypatch.setattr(worker, "_get_browser", fake_browser)
        yield h, worker, pid


def _run(worker, pid, service, monkeypatch):
    monkeypatch.setattr(capture_mod, "get_service", lambda _p: service)
    asyncio.run(worker.process(pid))


def test_success_uses_api_text_and_updates_did(env, monkeypatch):
    h, worker, pid = env
    meta = PostMetadata(text="Hallo", display_name="A", handle="a.bsky.social", did="did:plc:" + "a" * 24,
                        alt_texts=["Bild"])
    _run(worker, pid, FakeService(meta=meta), monkeypatch)
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.status == STATUS_DONE and p.text == "Hallo" and p.text_source == TEXT_API
        assert p.author_did == "did:plc:" + "a" * 24
        assert p.dedup_key == f"bluesky:did:plc:{'a' * 24}:3k"
        assert p.alt_texts == "Bild"
        assert p.screenshot_path.startswith("screenshots/bluesky/")
        assert (h.settings.base_path / p.screenshot_path).exists()


def test_deleted_post_keeps_entry_and_skips_screenshot(env, monkeypatch):
    h, worker, pid = env
    service = FakeService(meta_exc=PostNotFound("Beitrag nicht gefunden - geloescht."))
    _run(worker, pid, service, monkeypatch)
    assert service.captured is False
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.status == STATUS_ERROR and "nicht gefunden" in p.status_message
        assert p.attempts == 1


def test_network_error_marks_error_with_message(env, monkeypatch):
    h, worker, pid = env
    service = FakeService(meta_exc=PlatformError("Bluesky-API nicht erreichbar (ConnectError)."),
                          capture_exc=PlatformError("Screenshot nicht moeglich."))
    _run(worker, pid, service, monkeypatch)
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.status == STATUS_ERROR
        assert "nicht erreichbar" in p.status_message and "Screenshot" in p.status_message


def test_manual_text_is_never_overwritten(env, monkeypatch):
    h, worker, pid = env
    with h.db() as db:
        p = db.get(Post, pid)
        p.text, p.text_source = "Meine Korrektur", TEXT_MANUAL
        db.commit()
    _run(worker, pid, FakeService(meta=PostMetadata(text="API-Text")), monkeypatch)
    with h.db() as db:
        p = db.get(Post, pid)
        assert p.text == "Meine Korrektur" and p.text_source == TEXT_MANUAL


def test_restart_requeues_running_posts(env):
    h, worker, pid = env
    with h.db() as db:
        db.get(Post, pid).status = "running"
        db.commit()

    async def go():
        worker._run = lambda: asyncio.sleep(0)  # Schleife nicht wirklich starten
        await worker.start()
        return worker.queue.qsize()

    assert asyncio.run(go()) == 1
    with h.db() as db:
        assert db.get(Post, pid).status == "pending"
