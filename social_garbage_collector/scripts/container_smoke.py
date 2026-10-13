"""Offline-Pruefung im gebauten Add-on-Image (keine produktiven Daten)."""

import asyncio
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.services.capture import CaptureWorker


async def main():
    with tempfile.TemporaryDirectory(prefix="trashtwitter-smoke-") as directory:
        settings = Settings(base_path=Path(directory), network_enabled=False, worker_enabled=False, backup_keep=0)
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/health")
                assert response.status_code == 200 and response.json()["status"] == "ok"
                assert (await client.get("/setup")).status_code == 200
            worker = CaptureWorker(settings, app.state.SessionLocal)
            try:
                browser = await worker._get_browser()
                page = await browser.new_page()
                await page.set_content("<h1>TrashTwitter offline smoke test</h1>")
                screenshot = settings.base_path / "smoke.png"
                await page.screenshot(path=str(screenshot))
                assert screenshot.stat().st_size > 0
                recognized = subprocess.run(["tesseract", str(screenshot), "stdout", "-l", "deu+eng"],
                                            check=True, capture_output=True, text=True).stdout
                assert "offline smoke test" in recognized.lower(), recognized
            finally:
                await worker._close_browser()
        languages = subprocess.run(["tesseract", "--list-langs"], check=True, capture_output=True, text=True).stdout
        assert "deu" in languages and "eng" in languages
    print("Container smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
