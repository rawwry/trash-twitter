"""URL-Erkennung und API-Auswertung der Plattformen (ohne Netz)."""

from __future__ import annotations

import pytest

from app.services.platforms import detect
from app.services.platforms.bluesky import BlueskyService, metadata_from_post_view
from app.services.platforms.x import XService, _text_from_oembed_html
from app.services.platforms.base import safe_filename


@pytest.mark.parametrize("url, handle, pid", [
    ("https://x.com/jack/status/20", "jack", "20"),
    ("https://twitter.com/jack/status/20?s=20&t=abc", "jack", "20"),
    ("x.com/Some_User/status/1234567890123456789/photo/1", "Some_User", "1234567890123456789"),
    ("https://mobile.twitter.com/jack/statuses/20", "jack", "20"),
    ("https://x.com/i/web/status/42", "", "42"),
])
def test_x_urls(url, handle, pid):
    p = XService().parse_url(url)
    assert p and p.author_handle == handle and p.post_id == pid
    assert p.canonical_url.startswith("https://x.com/")


@pytest.mark.parametrize("url", [
    "https://x.com/jack", "https://x.com/jack/status/abc", "https://evil.com/jack/status/1",
    "https://x.com.evil.com/jack/status/1", "javascript:alert(1)", "",
])
def test_x_rejects(url):
    assert XService().parse_url(url) is None


def test_x_dedup_ignores_handle():
    s = XService()
    assert s.dedup_key(s.parse_url("https://x.com/a/status/5")) == s.dedup_key(s.parse_url("https://twitter.com/b/status/5"))


@pytest.mark.parametrize("url, handle, did, rkey", [
    ("https://bsky.app/profile/Alice.bsky.social/post/3kabc123", "alice.bsky.social", None, "3kabc123"),
    ("https://bsky.app/profile/did:plc:z72i7hdynmk6r22z27h6tvur/post/3k", "", "did:plc:z72i7hdynmk6r22z27h6tvur", "3k"),
    ("bsky.app/profile/example.com/post/3xyz?ref=1", "example.com", None, "3xyz"),
    ("at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.post/3abc", "", "did:plc:z72i7hdynmk6r22z27h6tvur", "3abc"),
])
def test_bluesky_urls(url, handle, did, rkey):
    p = BlueskyService().parse_url(url)
    assert p and p.author_handle == handle and p.author_did == did and p.post_id == rkey


@pytest.mark.parametrize("url", [
    "https://bsky.app/profile/alice.bsky.social",
    "https://bsky.app/profile/nodot/post/3k",
    "https://bsky.app/profile/alice.bsky.social/feed/abc",
    "https://bsky.evil/profile/alice.bsky.social/post/3k",
])
def test_bluesky_rejects(url):
    assert BlueskyService().parse_url(url) is None


def test_detect_picks_platform():
    assert detect("https://x.com/a/status/1")[0].name == "x"
    assert detect("https://bsky.app/profile/a.bsky.social/post/3k")[0].name == "bluesky"
    assert detect("https://mastodon.social/@a/1") is None


def test_bluesky_metadata_parsing():
    view = {
        "author": {"did": "did:plc:abc", "handle": "Alice.bsky.social", "displayName": "Alice"},
        "record": {"text": "Hallo Welt", "createdAt": "2026-10-08T15:00:23.966Z"},
        "embed": {"$type": "app.bsky.embed.recordWithMedia#view",
                  "media": {"$type": "app.bsky.embed.images#view",
                            "images": [{"alt": "Eine Katze"}, {"alt": ""}, {"alt": " Kaffee "}]}},
    }
    m = metadata_from_post_view(view)
    assert m.text == "Hallo Welt"
    assert m.display_name == "Alice" and m.handle == "alice.bsky.social" and m.did == "did:plc:abc"
    assert m.posted_at.isoformat().startswith("2026-10-08T15:00:23")
    assert m.alt_texts == ["Eine Katze", "Kaffee"]


def test_oembed_text_extraction():
    html = '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">just setting up my twttr<br>&amp; more <a href="#">#x</a></p>&mdash; jack</blockquote>'
    assert _text_from_oembed_html(html) == "just setting up my twttr\n& more #x"


def test_safe_filename_has_no_path_parts():
    name = safe_filename("../../etc", "pass/wd", "did:plc:abc")
    assert "/" not in name and ".." not in name
