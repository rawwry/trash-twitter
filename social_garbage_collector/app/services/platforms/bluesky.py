"""Bluesky (AT Protocol).

Text kommt bevorzugt direkt ueber die oeffentliche AppView-API (ohne Login):
  - com.atproto.identity.resolveHandle   Handle -> DID
  - app.bsky.feed.getPosts               Text, Anzeigename, Zeit, Alt-Texte
OCR nur als Rueckfall, falls die API nicht antwortet.

Screenshot bevorzugt ueber die offizielle Embed-Seite (embed.bsky.app),
Rueckfall: oeffentliche Beitragsseite auf bsky.app.

Wir speichern die DID mit, weil sich Handles aendern koennen.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from ...models import PLATFORM_BLUESKY
from .base import (
    USER_AGENT,
    CaptureResult,
    fill_page_background,
    ParsedPost,
    MAX_THREAD_PARTS,
    PlatformError,
    PostMetadata,
    PostNotFound,
    normalize_url_input,
)

log = logging.getLogger("sgc.bluesky")

API = "https://public.api.bsky.app/xrpc"
_HOSTS = {"bsky.app", "www.bsky.app", "staging.bsky.app"}
_HANDLE = re.compile(r"^(?=.{3,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]*$")
_DID = re.compile(r"^did:(plc:[a-z2-7]{24}|web:[A-Za-z0-9.:%-]+)$")
_RKEY = re.compile(r"^[A-Za-z0-9._:~-]{1,512}$")
_AT_URI = re.compile(r"^at://(?P<repo>[^/]+)/app\.bsky\.feed\.post/(?P<rkey>[^/?#]+)$")

TIMEOUT_MS = 25_000

# Eigenen blauen Rahmen und 32px-Rundung der Embed-Karte entfernen ->
# sauberes Rechteck, die Ecken rundet die App einheitlich.
FLATTEN_CSS = (
    "#app>div{border:0!important;border-radius:0!important;max-width:none!important}"
    "#app>div [class*='rounded-[30px]']{border-radius:0!important}"
)


def is_did(value: str) -> bool:
    return bool(_DID.match(value or ""))


def is_handle(value: str) -> bool:
    return bool(_HANDLE.match(value or ""))


class BlueskyService:
    name = PLATFORM_BLUESKY
    label = "Bluesky"
    prefers_api_text = True

    def parse_url(self, url: str) -> ParsedPost | None:
        raw = (url or "").strip()
        m = _AT_URI.match(raw)
        if m:
            repo, rkey = m.group("repo"), m.group("rkey")
        else:
            parsed = urlparse(normalize_url_input(raw))
            if (parsed.hostname or "").lower() not in _HOSTS:
                return None
            parts = [unquote(p) for p in parsed.path.split("/") if p]
            # profile/<handle oder DID>/post/<rkey>
            if len(parts) < 4 or parts[0] != "profile" or parts[2] != "post":
                return None
            repo, rkey = parts[1], parts[3]
        repo = repo.strip().lstrip("@")
        if not _RKEY.match(rkey):
            return None
        if is_did(repo):
            did, handle = repo, ""
        elif is_handle(repo):
            did, handle = None, repo.lower()
        else:
            return None
        return ParsedPost(
            platform=self.name, post_id=rkey, author_handle=handle, author_did=did,
            canonical_url=f"https://bsky.app/profile/{did or handle}/post/{rkey}",
        )

    def dedup_key(self, parsed: ParsedPost) -> str:
        # rkeys sind nur pro Konto eindeutig. Die DID ist stabil, der Handle nicht.
        return f"bluesky:{parsed.author_did or parsed.author_handle}:{parsed.post_id}"

    async def resolve(self, parsed: ParsedPost, client: httpx.AsyncClient) -> ParsedPost:
        if parsed.author_did:
            return parsed
        try:
            resp = await client.get(f"{API}/com.atproto.identity.resolveHandle",
                                    params={"handle": parsed.author_handle}, timeout=8)
        except httpx.HTTPError as exc:
            log.info("Handle %s nicht aufloesbar (Netz): %s", parsed.author_handle, exc)
            return parsed
        if resp.status_code == 200:
            did = resp.json().get("did")
            if did and is_did(did):
                parsed.author_did = did
        return parsed

    async def fetch_metadata(self, parsed: ParsedPost, client: httpx.AsyncClient) -> PostMetadata | None:
        parsed = await self.resolve(parsed, client)
        if not parsed.author_did:
            raise PostNotFound("Profil nicht gefunden - Handle geaendert oder Konto geloescht?")
        uri = f"at://{parsed.author_did}/app.bsky.feed.post/{parsed.post_id}"
        try:
            resp = await client.get(f"{API}/app.bsky.feed.getPosts", params={"uris": uri}, timeout=15)
        except httpx.HTTPError as exc:
            raise PlatformError(f"Bluesky-API nicht erreichbar ({type(exc).__name__}).") from exc
        if resp.status_code >= 500:
            raise PlatformError(f"Bluesky-API antwortet mit Fehler {resp.status_code}.")
        if resp.status_code != 200:
            raise PostNotFound(f"Bluesky-API: Beitrag nicht abrufbar ({resp.status_code}).")
        posts = resp.json().get("posts") or []
        if not posts:
            raise PostNotFound("Beitrag nicht gefunden - geloescht oder nicht oeffentlich.")
        return metadata_from_post_view(posts[0])

    async def thread_chain(self, parsed: ParsedPost, client: httpx.AsyncClient) -> list[ParsedPost]:
        """Ganzen Selbst-Thread finden - in beide Richtungen.

        1. Vom eingefuegten Beitrag die Eltern hoch, solange sie vom selben
           Konto sind -> Thread-Anfang.
        2. Vom Anfang die Antworten runter, jeweils die frueheste Selbst-Antwort.
        """
        try:
            parsed = await self.resolve(parsed, client)
            if not parsed.author_did:
                return [parsed]
            did = parsed.author_did
            uri = f"at://{did}/app.bsky.feed.post/{parsed.post_id}"
            up = await self._get_thread(client, uri, depth=0, parent_height=MAX_THREAD_PARTS)
            if up is None:
                return [parsed]
            node, root_uri = up, uri
            while True:
                parent = node.get("parent") or {}
                if (parent.get("post") or {}).get("author", {}).get("did") != did:
                    break
                node, root_uri = parent, parent["post"]["uri"]
            down = await self._get_thread(client, root_uri, depth=MAX_THREAD_PARTS, parent_height=0)
            if down is None:
                return [parsed]
            chain, node = [down["post"]], down
            while len(chain) < MAX_THREAD_PARTS:
                kids = [r for r in node.get("replies") or []
                        if (r.get("post") or {}).get("author", {}).get("did") == did]
                if not kids:
                    break
                node = min(kids, key=lambda r: (r["post"].get("record") or {}).get("createdAt", ""))
                chain.append(node["post"])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.info("Bluesky-Thread nicht ermittelbar: %s", exc)
            return [parsed]
        handle = parsed.author_handle or (chain[0].get("author") or {}).get("handle", "")
        out = []
        for post in chain:
            rkey = post["uri"].rsplit("/", 1)[-1]
            out.append(ParsedPost(platform=self.name, post_id=rkey, author_handle=handle, author_did=did,
                                  canonical_url=f"https://bsky.app/profile/{did}/post/{rkey}"))
        return out or [parsed]

    @staticmethod
    async def _get_thread(client: httpx.AsyncClient, uri: str, depth: int, parent_height: int) -> dict | None:
        resp = await client.get(f"{API}/app.bsky.feed.getPostThread",
                                params={"uri": uri, "depth": depth, "parentHeight": parent_height}, timeout=15)
        if resp.status_code != 200:
            return None
        thread = resp.json().get("thread") or {}
        return thread if thread.get("post") else None

    async def capture(self, parsed: ParsedPost, browser, target: Path, dark: bool = True) -> CaptureResult:
        errors = []
        for method in (self._capture_embed, self._capture_public):
            try:
                return await method(parsed, browser, target, dark)
            except Exception as exc:
                log.info("Bluesky-Screenshot per %s fehlgeschlagen: %s", method.__name__, exc)
                errors.append(f"{method.__name__.removeprefix('_capture_')}: {type(exc).__name__}")
        raise PlatformError("Screenshot nicht moeglich (" + "; ".join(errors) + ").")

    async def _capture_embed(self, parsed: ParsedPost, browser, target: Path, dark: bool) -> CaptureResult:
        if not parsed.author_did:
            raise PlatformError("Embed braucht die DID")
        context = await browser.new_context(
            viewport={"width": 600, "height": 1400}, device_scale_factor=2, locale="de-DE",
            user_agent=USER_AGENT, color_scheme="dark" if dark else "light",
        )
        try:
            page = await context.new_page()
            # colorMode steuert das Embed (Klasse "dark" an <html>), nicht prefers-color-scheme.
            mode = "dark" if dark else "light"
            url = f"https://embed.bsky.app/embed/{parsed.author_did}/app.bsky.feed.post/{parsed.post_id}?colorMode={mode}"
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            # Die Embed-Seite rendert genau eine Karte in #app.
            card = page.locator("#app > div").first
            await card.wait_for(state="visible", timeout=TIMEOUT_MS)
            if await page.locator(f'#app a[href*="/post/{parsed.post_id}"]').count() == 0:
                raise PlatformError("Embed zeigt keinen Beitrag")
            await page.wait_for_load_state("networkidle", timeout=10_000)
            await page.add_style_tag(content=FLATTEN_CSS)
            await fill_page_background(card)
            await card.screenshot(path=str(target))
            return CaptureResult(screenshot=target, method="embed")
        finally:
            await context.close()

    async def _capture_public(self, parsed: ParsedPost, browser, target: Path, dark: bool) -> CaptureResult:
        context = await browser.new_context(
            viewport={"width": 700, "height": 1400}, device_scale_factor=2, locale="de-DE",
            user_agent=USER_AGENT, color_scheme="dark" if dark else "light",
        )
        try:
            page = await context.new_page()
            await page.goto(parsed.canonical_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            item = page.locator('[data-testid^="postThreadItem-by-"]').first
            await item.wait_for(state="visible", timeout=TIMEOUT_MS)
            await page.wait_for_timeout(1000)
            await fill_page_background(item)
            await item.screenshot(path=str(target))
            return CaptureResult(screenshot=target, method="bsky.app")
        finally:
            await context.close()


def metadata_from_post_view(post: dict) -> PostMetadata:
    """Zerlegt einen PostView aus app.bsky.feed.getPosts."""
    author = post.get("author") or {}
    record = post.get("record") or {}
    meta = PostMetadata(
        text=(record.get("text") or "").strip(),
        display_name=(author.get("displayName") or "").strip(),
        handle=(author.get("handle") or "").strip().lower(),
        did=author.get("did"),
        posted_at=_parse_dt(record.get("createdAt")),
        author_id=author.get("did"),
        avatar_url=(author.get("avatar") or "").strip(),
    )
    meta.alt_texts = _collect_alt_texts(post.get("embed"))
    return meta


def _collect_alt_texts(embed: dict | None) -> list[str]:
    """Alt-Texte aus Bild-, Video- und Zitat-mit-Medien-Embeds."""
    if not embed:
        return []
    out: list[str] = []
    etype = embed.get("$type", "")
    if etype.startswith("app.bsky.embed.images"):
        out += [img.get("alt", "") for img in embed.get("images") or []]
    elif etype.startswith("app.bsky.embed.video"):
        out.append(embed.get("alt", ""))
    elif etype.startswith("app.bsky.embed.recordWithMedia"):
        out += _collect_alt_texts(embed.get("media"))
    return [a.strip() for a in out if a and a.strip()]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
