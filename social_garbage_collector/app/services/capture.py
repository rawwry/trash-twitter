"""Hintergrund-Worker: Screenshot + Text fuer neue Beitraege.

Bewusst schlicht: EINE asyncio-Warteschlange, EIN Beitrag nach dem anderen.
Chromium ist auf dem Pi der teuerste Teil; parallel wuerde nur der
Speicher knapp. Der Browser startet bei Bedarf und wird beendet, sobald die
Warteschlange leer ist.

Status je Beitrag: pending -> running -> done | error.
Ein Fehler loescht nie den Beitrag; Retry setzt ihn zurueck auf pending.
Nach einem Neustart werden alle offenen Beitraege wieder eingereiht.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings, UnsafePathError, safe_path
from ..models import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_RUNNING,
    TEXT_API,
    TEXT_MANUAL,
    TEXT_OCR,
    Post,
    utcnow,
)
from . import accounts, dates, ocr, shots
from .platforms import get_service
from .platforms.base import (
    MAX_THREAD_PARTS,
    USER_AGENT,
    CaptureResult,
    ParsedPost,
    PlatformError,
    PostMetadata,
    PostNotFound,
    safe_filename,
)

log = logging.getLogger("sgc.capture")

JOB_TIMEOUT_S = 180
# Kurze Pause zwischen zwei Beitraegen - bei Massenimporten sonst zu viele
# Anfragen in Folge an X/Bluesky (Rate-Limits).
JOB_PAUSE_S = 1.5


class CaptureWorker:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._queued: set[int] = set()
        self._task: asyncio.Task | None = None
        self._playwright = None
        self._browser = None

    # --- Steuerung ----------------------------------------------------------
    async def start(self) -> None:
        with self.session_factory() as db:
            # Was beim letzten Herunterfahren "lief", ist abgebrochen.
            db.execute(update(Post).where(Post.status == STATUS_RUNNING).values(status=STATUS_PENDING))
            db.commit()
            pending = list(db.scalars(select(Post.id).where(Post.status == STATUS_PENDING).order_by(Post.id)))
        for pid in pending:
            self.enqueue(pid)
        self._task = asyncio.create_task(self._run(), name="sgc-capture")
        self._refresh_task = asyncio.create_task(self._refresh_safe(), name="sgc-accounts")
        log.info("Screenshot-Worker gestartet (%d offene Beitraege).", len(pending))

    async def _refresh_safe(self) -> None:
        try:
            n = await self.fill_missing_dates()
            if n:
                log.info("Datum fuer %d Aussagen aus dem Screenshot gelesen.", n)
            n = await self.refresh_accounts()
            if n:
                log.info("%d Accounts nachgeschlagen (Profilbild, Name).", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Accounts nachschlagen fehlgeschlagen")

    async def stop(self) -> None:
        if getattr(self, "_refresh_task", None):
            self._refresh_task.cancel()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._close_browser()

    def enqueue(self, post_id: int) -> None:
        if post_id not in self._queued:
            self._queued.add(post_id)
            self.queue.put_nowait(post_id)

    # --- Schleife -----------------------------------------------------------
    async def _run(self) -> None:
        while True:
            post_id = await self.queue.get()
            try:
                await asyncio.wait_for(self.process(post_id), timeout=JOB_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._mark_error(post_id, "Zeitüberschreitung beim Verarbeiten. Bitte erneut versuchen.")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Worker darf nie sterben
                log.exception("Unerwarteter Fehler bei Beitrag %s", post_id)
                self._mark_error(post_id, f"Unerwarteter Fehler: {type(exc).__name__}")
            finally:
                self._queued.discard(post_id)
                self.queue.task_done()
            if self.queue.empty():
                await self._close_browser()
            else:
                await asyncio.sleep(JOB_PAUSE_S)

    def _mark_error(self, post_id: int, message: str) -> None:
        with self.session_factory() as db:
            post = db.get(Post, post_id)
            if post:
                post.status = STATUS_ERROR
                post.status_message = message
                db.commit()

    # --- Browser ------------------------------------------------------------
    async def _get_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright  # erst hier: Tests brauchen es nicht

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                # Im Container laeuft alles als root -> Sandbox geht nicht.
                # /dev/shm ist in Docker nur 64 MB gross -> nicht benutzen.
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
        return self._browser

    async def _close_browser(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:  # pragma: no cover
            log.debug("Browser liess sich nicht sauber schliessen", exc_info=True)
        finally:
            self._browser = None
            self._playwright = None

    # --- Ein Beitrag --------------------------------------------------------
    async def process(self, post_id: int) -> None:
        db = self.session_factory()
        try:
            post = db.get(Post, post_id)
            if post is None or post.status not in (STATUS_PENDING, STATUS_RUNNING):
                return
            post.status = STATUS_RUNNING
            post.status_message = ""
            post.attempts = (post.attempts or 0) + 1
            db.commit()

            if post.shot_source == "upload":
                await self._process_upload(db, post)
                return

            service = get_service(post.platform)
            parsed = ParsedPost(platform=post.platform, post_id=post.post_id, author_handle=post.author_handle,
                                canonical_url=post.url, author_did=post.author_did)
            problems: list[str] = []
            not_found: str | None = None

            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
                # 1) Thread-Teile bestimmen (automatisch + von Hand ergaenzt)
                parts = await self._thread_parts(service, parsed, post, client)
                main = parts[0]
                if main.post_id != post.post_id:
                    self._switch_main(db, service, post, main, problems)

                # 2) Metadaten/Text je Teil ueber die API (ohne Login)
                metas: list[PostMetadata | None] = []
                for i, part in enumerate(parts):
                    try:
                        metas.append(await service.fetch_metadata(part, client))
                    except PostNotFound as exc:
                        metas.append(None)
                        if i == 0:
                            not_found = str(exc)
                        else:
                            problems.append(f"Thread-Teil {i + 1} nicht gefunden.")
                    except PlatformError as exc:
                        metas.append(None)
                        problems.append(str(exc))
                    except httpx.HTTPError as exc:
                        metas.append(None)
                        problems.append(f"Netzwerkfehler: {type(exc).__name__}")
                if metas and metas[0]:
                    self._apply_metadata(db, post, main, metas[0])
                    if metas[0].long_post and not metas[0].text_complete:
                        problems.append("Langer Beitrag: X liefert nur den Anfang, der Wortlaut ist gekürzt – bitte ergänzen.")
                    # Wer hat das gesagt? Account + Profilbild sichern.
                    await accounts.apply_metadata(db, self.settings, client, post, metas[0])
            if post.account_id is None:
                accounts.ensure_for_post(db, post)
            alt = [a for m in metas if m for a in m.alt_texts]
            if len(parts) > 1 and alt:
                post.alt_texts = "\n".join(alt)

            # 3) Screenshots je Teil (roh als PNG), dann bereinigen/zusammenkleben -> WebP
            captures: list[CaptureResult | None] = []
            raws: list[Path] = []
            saved = False
            rel = self._screenshot_rel(post)
            target = safe_path(self.settings.base_path, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if not_found:
                    # Die API hat den Beitrag sicher nicht gefunden - die
                    # Screenshot-Versuche wuerden nur in Timeouts laufen.
                    raise PostNotFound(not_found)
                browser = await self._get_browser()
                dark = self.settings.screenshot_theme != "light"
                # Lange Beitraege mit vollstaendigem Wortlaut: ins Bild uebernehmen.
                for part, meta in zip(parts, metas):
                    if meta is not None and meta.long_post and meta.text_complete and meta.text:
                        part.full_text = meta.text
                for i, part in enumerate(parts):
                    raw = target.with_name(f"{target.stem}.teil{i}.png")
                    try:
                        captures.append(await service.capture(part, browser, raw, dark=dark))
                        raws.append(raw)
                    except (PlatformError, PostNotFound) as exc:
                        if i == 0:
                            raise
                        captures.append(None)
                        problems.append(f"Thread-Teil {i + 1}: {exc}")
                old = post.screenshot_path
                post.shot_reconstructed = any(c is not None and c.reconstructed for c in captures)
                shots.finalize(raws, target)
                saved = True
                post.screenshot_path = rel
                shots.apply(post, target)
                if old and old != rel:  # z. B. alte PNG aus Versionen vor 0.4.0
                    try:
                        safe_path(self.settings.base_path, old).unlink(missing_ok=True)
                    except UnsafePathError:
                        pass
            except PostNotFound as exc:
                not_found = not_found or str(exc)
            except PlatformError as exc:
                problems.append(str(exc))
            except Exception as exc:
                log.warning("Screenshot fuer Beitrag %s fehlgeschlagen: %s", post_id, exc)
                problems.append(f"Screenshot fehlgeschlagen: {type(exc).__name__}")
            finally:
                for raw in target.parent.glob(f"{target.stem}.teil*.png"):
                    raw.unlink(missing_ok=True)

            # Thread-Infos fuer die Oberflaeche
            done_parts = [p for p, c in zip(parts, captures) if c] if len(parts) > 1 else []
            post.thread_count = len(done_parts) if len(done_parts) > 1 else 0
            post.thread_parts = json.dumps([{"url": p.canonical_url, "post_id": p.post_id} for p in done_parts]) \
                if post.thread_count else ""

            # 4) Text - nie eine manuelle Korrektur ueberschreiben
            if post.text_source != TEXT_MANUAL:
                texts, sources = [], set()
                caps = captures if captures else [None] * len(metas)
                for meta, cap in zip(metas, caps):
                    if len(parts) > 1 and captures and cap is None:
                        continue  # Teil ohne Screenshot: nicht im Bild, also auch nicht im Text
                    text, source = await self._choose_text(service.prefers_api_text, meta, cap, problems)
                    if text:
                        texts.append(text)
                    if source:
                        sources.add(source)
                if texts or sources:
                    post.text = "\n\n".join(texts)
                    post.text_source = TEXT_OCR if TEXT_OCR in sources else (sources.pop() if sources else None)

            # 5) Kein Datum von der Plattform? Aus der ID, sonst aus dem Screenshot.
            await self._fill_date(post)

            # 6) Status
            if saved:
                post.status = STATUS_DONE
                post.status_message = "; ".join(dict.fromkeys(problems))
            else:
                post.status = STATUS_ERROR
                post.status_message = not_found or "; ".join(dict.fromkeys(problems)) or "Unbekannter Fehler."
            db.commit()
            log.info("Beitrag %s: %s (%d Teile) %s", post_id, post.status, max(1, post.thread_count),
                     post.status_message)
        finally:
            db.close()

    async def _process_upload(self, db: Session, post: Post) -> None:
        """Hochgeladener Screenshot: KEINE Aufnahme. Nur Metadaten (wenn ein Link
        da ist) und Text (API bzw. Texterkennung aus dem hochgeladenen Bild)."""
        service = get_service(post.platform)
        problems: list[str] = []
        meta: PostMetadata | None = None
        if post.url:
            parsed = ParsedPost(platform=post.platform, post_id=post.post_id, author_handle=post.author_handle,
                                canonical_url=post.url, author_did=post.author_did)
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
                try:
                    meta = await service.fetch_metadata(parsed, client)
                except PostNotFound:
                    problems.append("Original nicht mehr abrufbar – dein Screenshot bleibt erhalten.")
                except (PlatformError, httpx.HTTPError) as exc:
                    problems.append(f"Original nicht erreichbar ({type(exc).__name__}).")
                if meta:
                    self._apply_metadata(db, post, parsed, meta)
                    await accounts.apply_metadata(db, self.settings, client, post, meta)
        if post.account_id is None:
            accounts.ensure_for_post(db, post)
        if post.text_source != TEXT_MANUAL and post.screenshot_path:
            try:
                path = safe_path(self.settings.base_path, post.screenshot_path)
                text, source = await self._choose_text(service.prefers_api_text, meta,
                                                       CaptureResult(screenshot=path), problems)
                if text or source:
                    post.text, post.text_source = text, source
            except UnsafePathError:
                problems.append("Screenshot-Pfad ungültig.")
        await self._fill_date(post)
        post.status = STATUS_DONE
        post.status_message = "; ".join(problems)
        db.commit()
        log.info("Beitrag %s (Upload): fertig %s", post.id, post.status_message)

    async def _thread_parts(self, service, parsed: ParsedPost, post: Post,
                            client: httpx.AsyncClient) -> list[ParsedPost]:
        """Thread-Teile = der Beitrag selbst plus die von Hand ergaenzten Links.

        ⚠️ 0.6.1: Die automatische Erkennung (service.thread_chain) ist abgeschaltet,
        sie hat zu oft falsch gelegen. Der Code in platforms/ bleibt fuer spaeter."""
        parts = [parsed]
        seen = {p.post_id for p in parts}
        try:
            extra_urls = json.loads(post.thread_extra) if post.thread_extra else []
        except ValueError:
            extra_urls = []
        for url in extra_urls:
            extra = service.parse_url(url)
            if extra and extra.post_id not in seen:
                if post.platform == "bluesky":
                    extra = await service.resolve(extra, client)
                parts.append(extra)
                seen.add(extra.post_id)
        return parts[:MAX_THREAD_PARTS]

    def _switch_main(self, db: Session, service, post: Post, main: ParsedPost, problems: list[str]) -> None:
        """Der Thread beginnt frueher als der eingefuegte Beitrag -> der Anfang
        wird zum Hauptbeitrag (URL, ID, Duplikat-Schluessel)."""
        key = service.dedup_key(main)
        clash = db.scalar(select(Post.id).where(Post.dedup_key == key, Post.id != post.id))
        if clash:
            problems.append(f"Der Anfang dieses Threads ist schon im Archiv (Beitrag #{clash}).")
            return
        post.post_id, post.url, post.dedup_key = main.post_id, main.canonical_url, key
        if main.author_did:
            post.author_did = main.author_did

    def _apply_metadata(self, db: Session, post: Post, parsed: ParsedPost, meta: PostMetadata) -> None:
        if meta.display_name:
            post.author_display_name = meta.display_name[:255]
        if meta.handle:
            post.author_handle = meta.handle[:255]
        if meta.posted_at:
            dates.set_date(post, meta.posted_at, dates.DATE_API)
        if meta.alt_texts:
            post.alt_texts = "\n".join(meta.alt_texts)
        post.long_post = bool(meta.long_post)
        did = meta.did or parsed.author_did
        if did and not post.author_did:
            post.author_did = did
            new_key = f"{post.platform}:{did}:{post.post_id}"
            clash = db.scalar(select(Post.id).where(Post.dedup_key == new_key, Post.id != post.id))
            if clash is None:
                post.dedup_key = new_key
        parsed.author_did = post.author_did
        if post.author_handle:
            parsed.author_handle = post.author_handle

    async def _choose_text(self, prefers_api: bool, meta: PostMetadata | None,
                           capture: CaptureResult | None, problems: list[str]) -> tuple[str, str | None]:
        # Bluesky: API hat geantwortet -> deren Text gilt (auch wenn leer, z. B. reiner Bildbeitrag).
        if prefers_api and meta is not None:
            return meta.text, TEXT_API
        if capture:
            try:
                source = capture.text_image or capture.screenshot
                text = await asyncio.to_thread(ocr.ocr_image, source)
                if text:
                    return text, TEXT_OCR
            except ocr.OcrUnavailable as exc:
                problems.append(f"Texterkennung nicht verfügbar ({exc}).")
            except Exception as exc:
                problems.append(f"Texterkennung fehlgeschlagen ({type(exc).__name__}).")
        if meta is not None and meta.text:
            return meta.text, TEXT_API
        return "", None

    async def _fill_date(self, post: Post) -> None:
        """Datum fehlt: erst aus der Beitrags-ID (exakt), sonst per Texterkennung
        aus dem Screenshot. Fehlt Tesseract, bleibt es einfach leer."""
        if post.posted_at is not None or dates.fill_from_id(post) or not post.screenshot_path:
            return
        try:
            path = safe_path(self.settings.base_path, post.screenshot_path)
            text = await asyncio.to_thread(ocr.ocr_image, path, True)
        except (UnsafePathError, ocr.OcrUnavailable, OSError) as exc:
            log.info("Datum fuer Beitrag %s nicht lesbar: %s", post.id, exc)
            return
        except Exception as exc:  # OCR darf das Erfassen nie scheitern lassen
            log.warning("Texterkennung fuer das Datum von Beitrag %s fehlgeschlagen: %s", post.id, exc)
            return
        if not dates.fill_from_ocr_text(post, text):
            post.date_source = "none"  # gesucht, nichts gefunden - nicht bei jedem Start erneut

    async def fill_missing_dates(self, pause_s: float = 0.3) -> int:
        """Einmal im Hintergrund: Aussagen ohne Datum (z. B. aus der Zeit vor 0.6)
        aus ihrem Screenshot lesen. Die ID-Variante laeuft schon beim Start."""
        done = 0
        while True:
            with self.session_factory() as db:
                batch = list(db.scalars(select(Post).where(
                    Post.posted_at.is_(None), Post.date_source.is_(None), Post.screenshot_path.is_not(None),
                    Post.status != STATUS_RUNNING).order_by(Post.id).limit(20)))
                if not batch:
                    return done
                for post in batch:
                    await self._fill_date(post)
                    if post.date_source is None:  # z. B. Tesseract fehlt: nicht endlos versuchen
                        post.date_source = "none"
                    done += post.posted_at is not None
                    db.commit()
                    await asyncio.sleep(pause_s)

    async def refresh_accounts(self, pause_s: float = 1.0) -> int:
        """Accounts ohne Profilbild (z. B. aus der Zeit vor 0.6) einmal bei der
        Plattform nachschlagen - ueber ihre neueste Aussage mit Link."""
        done = 0
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            while True:
                with self.session_factory() as db:
                    batch = accounts.needing_refresh(db, limit=20)
                    if not batch:
                        return done
                    for acc in batch:
                        acc.checked_at = utcnow()
                        post = db.scalar(select(Post).where(Post.account_id == acc.id, Post.url != "")
                                         .order_by(Post.id.desc()).limit(1))
                        if post is None:
                            continue
                        service = get_service(post.platform)
                        parsed = ParsedPost(platform=post.platform, post_id=post.post_id,
                                            author_handle=post.author_handle, canonical_url=post.url,
                                            author_did=post.author_did)
                        try:
                            meta = await service.fetch_metadata(parsed, client)
                        except (PlatformError, httpx.HTTPError):
                            meta = None
                        if meta:
                            await accounts.apply_metadata(db, self.settings, client, post, meta)
                            done += 1
                        db.commit()
                        await asyncio.sleep(pause_s)
                    db.commit()

    @staticmethod
    def _screenshot_rel(post: Post) -> str:
        year = (post.created_at or datetime.now()).year
        name = safe_filename(post.author_handle or post.author_did or "unbekannt", post.post_id) + ".webp"
        return f"screenshots/{post.platform}/{year}/{name}"


def reset_for_retry(db: Session, post: Post) -> None:
    post.status = STATUS_PENDING
    post.status_message = ""
    post.updated_at = utcnow()
    db.commit()
