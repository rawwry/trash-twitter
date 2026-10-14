"""X (ehemals Twitter).

Screenshot in drei Stufen, weil x.com ohne Login meist eine Login-Wand zeigt:
  1. Direkt die Beitragsseite auf x.com (klappt manchmal, dann am schoensten)
  2. Offizielle Embed-Seite platform.twitter.com/embed/Tweet.html (Widget)
  3. oEmbed (publish.twitter.com) -> Blockquote + widgets.js lokal rendern

Text und Verfasser: seit 0.6 woertlich aus dem Embed-Backend
(cdn.syndication.twimg.com) - fuer ein Quellenarchiv zaehlt der exakte
Wortlaut, OCR ist nur noch Rueckfall. Dort stehen auch die feste User-ID
(bleibt bei Umbenennungen gleich) und das Profilbild. Zweiter Rueckfall: oEmbed.
"""

from __future__ import annotations

import html as htmllib
import logging
import math
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ...models import PLATFORM_X
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

log = logging.getLogger("sgc.x")

_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com", "www.x.com", "www.twitter.com", "fxtwitter.com", "vxtwitter.com"}
_HANDLE = r"[A-Za-z0-9_]{1,15}"
# /<handle>/status/<id>  oder  /i/web/status/<id>  (auch "statuses")
_PATH = re.compile(rf"^/(?:(?P<handle>{_HANDLE})|i/web|i)/status(?:es)?/(?P<id>\d{{1,25}})(?:/.*)?$")

DIRECT_TIMEOUT_MS = 15_000

# Rahmen und 12px-Rundung des Embed-Containers weg -> sauberes Rechteck.
FLATTEN_CSS = (
    "div:has(> article){border:0!important;border-radius:0!important}"
    "article{border-radius:0!important}"
    "body{margin:0!important}"
)
EMBED_TIMEOUT_MS = 25_000

# Lange Beitraege: Das Embed zeigt nur den Anfang und "Mehr anzeigen" (nur ein
# Link zu x.com, aufklappen geht nicht). Auf Wunsch (Timo, 0.7.1) setzt die App
# den vollen Wortlaut in das Textfeld des Embeds und entfernt den Link. Der Beleg
# ist dann rekonstruiert und wird in der Oberflaeche so gekennzeichnet.
EXPAND_JS = """full => {
  const el = document.querySelector('[data-testid="tweetText"]');
  if (!el) return false;
  const root = el.closest('article') || document.body;
  for (const n of root.querySelectorAll('a, span, button, div')) {
    const t = (n.textContent || '').trim();
    if (/^(Mehr anzeigen|Show more|Mehr lesen|Read more)$/i.test(t) && !n.contains(el)) n.remove();
  }
  el.textContent = full;
  el.style.whiteSpace = 'pre-wrap';
  return true;
}"""


class XService:
    name = PLATFORM_X
    label = "X"
    prefers_api_text = True

    def parse_url(self, url: str) -> ParsedPost | None:
        parsed = urlparse(normalize_url_input(url))
        host = (parsed.hostname or "").lower()
        if host not in _HOSTS:
            return None
        m = _PATH.match(parsed.path)
        if not m:
            return None
        handle = m.group("handle") or ""
        if handle.lower() in {"i", "home", "search", "explore", "settings"}:
            handle = ""
        post_id = m.group("id")
        canonical = f"https://x.com/{handle}/status/{post_id}" if handle else f"https://x.com/i/web/status/{post_id}"
        return ParsedPost(platform=self.name, post_id=post_id, author_handle=handle, canonical_url=canonical)

    def dedup_key(self, parsed: ParsedPost) -> str:
        # Status-IDs sind bei X global eindeutig, der Handle ist egal.
        return f"x:{parsed.post_id}"

    async def resolve(self, parsed: ParsedPost, client: httpx.AsyncClient) -> ParsedPost:
        return parsed

    async def fetch_metadata(self, parsed: ParsedPost, client: httpx.AsyncClient) -> PostMetadata | None:
        """Erst das Embed-Backend (Wortlaut, User-ID, Profilbild), sonst oEmbed."""
        try:
            data = await _syndication(client, parsed.post_id)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Embed-Backend nicht erreichbar: %s", exc)
            data = None
        if data and data.get("__typename") == "TweetTombstone":
            raise PostNotFound("Beitrag nicht verfuegbar - geloescht oder geschuetzt.")
        meta = metadata_from_syndication(data) if data and data.get("user") else await self._fetch_oembed(parsed, client)
        if meta is not None and (meta.long_post or looks_truncated(meta.text)):
            await complete_long_text(client, parsed.post_id, meta)
        return meta

    async def _fetch_oembed(self, parsed: ParsedPost, client: httpx.AsyncClient) -> PostMetadata | None:
        """oEmbed: Anzeigename, Handle und Text, ohne Login (keine User-ID)."""
        try:
            resp = await client.get(
                "https://publish.twitter.com/oembed",
                params={"url": parsed.canonical_url, "omit_script": "1", "dnt": "true", "lang": "de"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.info("oEmbed nicht erreichbar: %s", exc)
            return None
        if resp.status_code == 404:
            raise PostNotFound("Beitrag nicht gefunden - geloescht, geschuetzt oder Konto gesperrt.")
        if resp.status_code != 200 or not resp.content:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        meta = PostMetadata(display_name=data.get("author_name", "") or "")
        author_url = data.get("author_url") or ""
        m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", author_url)
        if m:
            meta.handle = m.group(1)
        meta.text = _text_from_oembed_html(data.get("html", ""))
        return meta

    async def thread_chain(self, parsed: ParsedPost, client: httpx.AsyncClient) -> list[ParsedPost]:
        """Thread rueckwaerts bis zum Anfang einsammeln.

        Das Embed-Backend (cdn.syndication.twimg.com, ohne Login) nennt zu jedem
        Tweet den Vorgaenger. Solange der vom selben Konto stammt, gehoert er zum
        Thread. Vorwaerts geht es ohne Login nicht - spaetere Teile muessen von
        Hand ergaenzt werden (Feld im Hinzufuegen-Dialog).
        """
        chain = [parsed]
        author = ""
        current = parsed.post_id
        try:
            for _ in range(MAX_THREAD_PARTS - 1):
                data = await _syndication(client, current)
                if not data:
                    break
                user = ((data.get("user") or {}).get("screen_name") or "")
                author = author or user
                if not parsed.author_handle and user:
                    parsed.author_handle = user
                parent_id = data.get("in_reply_to_status_id_str")
                parent_user = data.get("in_reply_to_screen_name") or ""
                if not parent_id or not author or parent_user.lower() != author.lower():
                    break
                chain.insert(0, ParsedPost(platform=self.name, post_id=parent_id, author_handle=author,
                                           canonical_url=f"https://x.com/{author}/status/{parent_id}"))
                current = parent_id
        except (httpx.HTTPError, ValueError) as exc:
            log.info("X-Thread nicht ermittelbar: %s", exc)
        return chain

    async def capture(self, parsed: ParsedPost, browser, target: Path, dark: bool = True) -> CaptureResult:
        errors: list[str] = []
        for method in (self._capture_direct, self._capture_embed, self._capture_oembed):
            try:
                return await method(parsed, browser, target, dark)
            except PostNotFound:
                raise
            except Exception as exc:  # naechste Stufe probieren
                log.info("X-Screenshot per %s fehlgeschlagen: %s", method.__name__, exc)
                errors.append(f"{method.__name__.removeprefix('_capture_')}: {type(exc).__name__}")
        raise PlatformError("Screenshot nicht moeglich (" + "; ".join(errors) + "). Login-Wand oder Bot-Schutz?")

    # --- Stufe 1: x.com direkt ---------------------------------------------
    async def _capture_direct(self, parsed: ParsedPost, browser, target: Path, dark: bool) -> CaptureResult:
        context = await browser.new_context(
            viewport={"width": 700, "height": 1400}, device_scale_factor=2,
            locale="de-DE", user_agent=USER_AGENT, color_scheme="dark" if dark else "light",
        )
        try:
            page = await context.new_page()
            await page.goto(parsed.canonical_url, wait_until="domcontentloaded", timeout=DIRECT_TIMEOUT_MS)
            if "/login" in page.url or "/i/flow" in page.url:
                raise PlatformError("Login-Wand")
            # Der Hauptbeitrag ist das article, das auf genau diese Status-ID verlinkt.
            article = page.locator(
                f'article[data-testid="tweet"]:has(a[href*="/status/{parsed.post_id}"])'
            ).first
            await article.wait_for(state="visible", timeout=DIRECT_TIMEOUT_MS)
            await page.wait_for_timeout(800)  # Bilder nachladen lassen
            await fill_page_background(article)
            await article.screenshot(path=str(target))
            text_img = await _element_png(article.locator('[data-testid="tweetText"]').first)
            return CaptureResult(screenshot=target, text_image=text_img, method="x.com")
        finally:
            await context.close()

    # --- Stufe 2: offizielles Embed-Widget ---------------------------------
    async def _capture_embed(self, parsed: ParsedPost, browser, target: Path, dark: bool) -> CaptureResult:
        context = await browser.new_context(
            viewport={"width": 600, "height": 1200}, device_scale_factor=2, locale="de-DE", user_agent=USER_AGENT,
            color_scheme="dark" if dark else "light",
        )
        try:
            page = await context.new_page()
            theme = "dark" if dark else "light"
            # ⚠️ 0.4.0: ohne hideThread zeigt das Embed bei Antworten den Vorgaenger
            # mit an - und "article" first war dann der FALSCHE Tweet.
            url = (f"https://platform.twitter.com/embed/Tweet.html?id={parsed.post_id}"
                   f"&dnt=true&lang=de&theme={theme}&hideThread=true")
            await page.goto(url, wait_until="domcontentloaded", timeout=EMBED_TIMEOUT_MS)
            article = page.locator("article").first
            try:
                await article.wait_for(state="visible", timeout=EMBED_TIMEOUT_MS)
            except Exception:
                body = (await page.inner_text("body")).lower()
                if "unavailable" in body or "nicht verfügbar" in body or "doesn" in body:
                    raise PostNotFound("Beitrag nicht verfuegbar - geloescht oder geschuetzt.")
                raise
            await page.wait_for_load_state("networkidle", timeout=10_000)
            await page.add_style_tag(content=FLATTEN_CSS)
            reconstructed = False
            if parsed.full_text:
                reconstructed = bool(await page.evaluate(EXPAND_JS, parsed.full_text))
                await page.wait_for_timeout(150)
            await fill_page_background(article)
            await article.screenshot(path=str(target))
            text_img = await _element_png(page.locator('[data-testid="tweetText"]').first)
            return CaptureResult(screenshot=target, text_image=text_img, method="embed", reconstructed=reconstructed)
        finally:
            await context.close()

    # --- Stufe 3: oEmbed-HTML lokal rendern --------------------------------
    async def _capture_oembed(self, parsed: ParsedPost, browser, target: Path, dark: bool) -> CaptureResult:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(
                "https://publish.twitter.com/oembed",
                params={"url": parsed.canonical_url, "dnt": "true", "lang": "de",
                        "theme": "dark" if dark else "light"}, timeout=15,
            )
        if resp.status_code == 404:
            raise PostNotFound("Beitrag nicht gefunden.")
        resp.raise_for_status()
        snippet = resp.json().get("html", "")
        if not snippet:
            raise PlatformError("oEmbed ohne Inhalt")
        context = await browser.new_context(viewport={"width": 600, "height": 1200}, device_scale_factor=2)
        try:
            page = await context.new_page()
            bg = "#15202b" if dark else "#ffffff"  # Seitenrand = Farbe des Widgets
            await page.set_content(f"<!doctype html><html><body style='margin:0;background:{bg}'>{snippet}</body></html>",
                                   wait_until="domcontentloaded")
            frame = page.locator("iframe").first
            await frame.wait_for(state="visible", timeout=EMBED_TIMEOUT_MS)
            await page.wait_for_timeout(2500)
            await frame.screenshot(path=str(target))
            return CaptureResult(screenshot=target, method="oembed")
        finally:
            await context.close()


async def _element_png(locator) -> bytes | None:
    try:
        if await locator.count() == 0:
            return None
        return await locator.screenshot(timeout=5000)
    except Exception:
        return None


def metadata_from_syndication(data: dict) -> PostMetadata:
    """Zerlegt die Antwort von cdn.syndication.twimg.com/tweet-result."""
    user = data.get("user") or {}
    avatar = (user.get("profile_image_url_https") or "").strip()
    # "_normal" ist 48 px - fuers Archiv die 400er-Fassung.
    avatar = re.sub(r"_normal(\.\w+)$", r"_400x400\1", avatar)
    note = data.get("note_tweet")
    meta = PostMetadata(
        text=tweet_text(data),
        display_name=(user.get("name") or "").strip(),
        handle=(user.get("screen_name") or "").strip(),
        posted_at=_parse_created(data.get("created_at")),
        author_id=(user.get("id_str") or "").strip() or None,
        avatar_url=avatar,
    )
    meta.alt_texts = [m.get("ext_alt_text", "").strip() for m in data.get("mediaDetails") or []
                      if (m.get("ext_alt_text") or "").strip()]
    meta.media = x_media(data)
    if note:  # "note_tweet" = langer Beitrag; steckt der Text nicht mit drin, ist er gekuerzt
        has_full = bool((((note.get("note_tweet_results") or {}).get("result") or {}).get("text")))
        meta.long_post, meta.text_complete = True, has_full
    return meta


# Langer Beitrag (Premium, bis 25 000 Zeichen): Embed-Backend und oEmbed liefern
# nur die ersten ~280 Zeichen, das Embed zeigt "Mehr anzeigen". Den vollen Text
# holt fxtwitter (Open Source, oeffentliche API ohne Login) - nur in diesem Fall.
FXTWITTER_API = "https://api.fxtwitter.com/status/{id}"
TRUNCATION_MARKS = ("…", "...")


def looks_truncated(text: str) -> bool:
    """Gekuerzter Text: endet mit Auslassungszeichen oder ist auffaellig nah an 280."""
    t = (text or "").rstrip()
    return len(t) >= 270 or (len(t) > 200 and t.endswith(TRUNCATION_MARKS))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().rstrip("….").strip()


async def complete_long_text(client: httpx.AsyncClient, tweet_id: str, meta: PostMetadata) -> None:
    """Ersetzt den gekuerzten Anfang durch den vollen Wortlaut - aber nur, wenn
    der neue Text wirklich laenger ist und genauso anfaengt (keine Verwechslung)."""
    try:
        resp = await client.get(FXTWITTER_API.format(id=tweet_id), timeout=12)
        full = ((resp.json().get("tweet") or {}).get("text") or "").strip() if resp.status_code == 200 else ""
    except (httpx.HTTPError, ValueError) as exc:
        log.info("Langer Beitrag %s: voller Text nicht abrufbar (%s)", tweet_id, exc)
        full = ""
    head = _norm(meta.text)[:60]
    if full and len(_norm(full)) > len(_norm(meta.text)) and _norm(full).startswith(head):
        meta.text = htmllib.unescape(full)
        meta.long_post, meta.text_complete = True, True
    elif meta.long_post:
        meta.text_complete = False


def x_media(data: dict) -> list:
    """Bilder (Originalgroesse), Videos und GIFs (bei X: stumme MP4-Schleife)."""
    from .base import MediaRef

    out = []
    for m in data.get("mediaDetails") or []:
        kind = {"photo": "photo", "video": "video", "animated_gif": "gif"}.get(m.get("type"))
        info = m.get("original_info") or {}
        size = dict(width=info.get("width"), height=info.get("height"))
        alt = (m.get("ext_alt_text") or "").strip()
        if kind == "photo" and m.get("media_url_https"):
            out.append(MediaRef("photo", m["media_url_https"] + "?name=orig", alt, **size))
        elif kind in ("video", "gif"):
            mp4 = [v for v in (m.get("video_info") or {}).get("variants") or [] if v.get("content_type") == "video/mp4"]
            if mp4:
                best = max(mp4, key=lambda v: v.get("bitrate") or 0)
                out.append(MediaRef(kind, best["url"], alt, **size))
    return out


def tweet_text(data: dict) -> str:
    """Wortlaut ohne Technik-Reste: t.co-Links ausgeschrieben, Medien-Links und
    die automatisch vorangestellten @Antwort-Namen entfernt."""
    note = (((data.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")
    text = note or data.get("text") or ""
    rng = data.get("display_text_range")
    if not note and isinstance(rng, list) and len(rng) == 2:
        text = text[int(rng[0]):int(rng[1])]
    entities = data.get("entities") or {}
    for u in entities.get("urls") or []:
        if u.get("url"):
            text = text.replace(u["url"], u.get("expanded_url") or u.get("display_url") or u["url"])
    for m in entities.get("media") or []:
        if m.get("url"):
            text = text.replace(m["url"], "")
    return htmllib.unescape(text).strip()


def _parse_created(value: str | None):
    from datetime import datetime, timezone

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:  # altes Format: "Wed Oct 10 20:19:24 +0000 2018"
            dt = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _text_from_oembed_html(snippet: str) -> str:
    """Holt den Beitragstext aus dem <p> der oEmbed-Blockquote."""
    m = re.search(r"<p[^>]*>(.*?)</p>", snippet or "", re.S)
    if not m:
        return ""
    inner = re.sub(r"<br\s*/?>", "\n", m.group(1))
    inner = re.sub(r"<[^>]+>", "", inner)
    return htmllib.unescape(inner).strip()


def _syndication_token(tweet_id: str) -> str:
    """Token fuers Embed-Backend: (id / 1e15 * PI) in Basis 36, ohne Nullen und Punkt
    (dieselbe Rechnung wie im offiziellen Embed-Widget bzw. Vercels react-tweet)."""
    n = int(tweet_id) / 1e15 * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole, frac = int(n), n - int(n)
    out = ""
    while whole:
        out = digits[whole % 36] + out
        whole //= 36
    out = (out or "0") + "."
    for _ in range(12):
        frac *= 36
        d = int(frac)
        out += digits[d]
        frac -= d
    return re.sub(r"(0+|\.)", "", out)


async def _syndication(client: httpx.AsyncClient, tweet_id: str) -> dict | None:
    resp = await client.get(
        "https://cdn.syndication.twimg.com/tweet-result",
        params={"id": tweet_id, "lang": "de", "token": _syndication_token(tweet_id)}, timeout=10,
    )
    if resp.status_code != 200 or not resp.content:
        return None
    return resp.json()
