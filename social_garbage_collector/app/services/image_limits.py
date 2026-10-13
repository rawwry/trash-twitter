"""Explizite Bildgrenzen vor dem Dekodieren, ohne globale Pillow-Einstellungen."""

import asyncio

MAX_PIXELS = 24_000_000
MAX_EDGE = 16_000  # auch unterhalb der WebP-Grenze
MAX_CANVAS_PIXELS = 12_000_000


def validate_size(width: int, height: int, *, pixels: int = MAX_PIXELS) -> None:
    if min(width, height) < 1 or max(width, height) > MAX_EDGE or width * height > pixels:
        raise ValueError(f"Bild zu groß: maximal {MAX_EDGE} Pixel je Seite und {pixels // 1_000_000} Megapixel.")


async def run_image_job(func, *args):
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise
