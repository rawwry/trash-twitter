"""Suchbefehl-Generator: reine Logik, beide Plattformen."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.services.search.builder import build_query, shared_keys


# --- X -----------------------------------------------------------------------

def test_x_example_from_spec():
    r = build_query("x", {"from_account": "@name", "min_faves": "100", "since": "2025-01-01", "replies": "exclude"})
    assert r.query == "from:name min_faves:100 since:2025-01-01 -filter:replies"
    assert r.summary == "Beiträge von @name mit mindestens 100 Likes seit 01.01.2025, ohne Antworten"


def test_empty_fields_give_empty_query():
    for platform in ("x", "bluesky"):
        r = build_query(platform, {"all_words": "  ", "phrase": "", "min_faves": "0", "lang": ""})
        assert r.query == ""
        assert r.empty
        assert "Noch keine Kriterien" in r.summary


def test_or_words_get_parentheses():
    r = build_query("x", {"any_words": "hund katze maus"})
    assert r.query == "(hund OR katze OR maus)"
    assert "„hund“, „katze“ oder „maus“" in r.summary


def test_single_or_word_has_no_parentheses():
    assert build_query("x", {"any_words": "hund"}).query == "hund"


def test_exclusions():
    r = build_query("x", {"all_words": "kaffee", "none_words": "werbung, gewinnspiel"})
    assert r.query == "kaffee -werbung -gewinnspiel"
    assert "ohne „werbung“ oder „gewinnspiel“" in r.summary


def test_phrase_is_quoted_and_inner_quotes_removed():
    r = build_query("x", {"phrase": 'sag  "hallo"  welt'})
    assert r.query == '"sag hallo welt"'


def test_special_characters_are_neutralised():
    r = build_query("x", {"all_words": 'foo:bar OR -minus (klammer) "zwei worte"'})
    # Doppelpunkt, OR, fuehrendes Minus und Klammern duerfen nicht als Operator wirken.
    assert r.query == '"foo:bar" "OR" "-minus" "(klammer)" "zwei worte"'


def test_umlauts_and_apostrophes_stay_plain():
    assert build_query("x", {"all_words": "Käse don't"}).query == "Käse don't"


def test_hashtags_normalised_and_invalid_dropped():
    r = build_query("x", {"hashtags": "#eins zwei #drei! "})
    assert r.query == "#eins #zwei"
    assert any("drei!" in w for w in r.warnings)


def test_accounts_strip_at_and_accept_profile_urls():
    r = build_query("x", {"from_account": "https://x.com/jack", "to_account": "@a_b", "mention": "c"})
    assert r.query == "from:jack to:a_b @c"


def test_invalid_x_account_is_dropped_with_warning():
    r = build_query("x", {"from_account": "viel-zu-lang-und-mit-minus"})
    assert r.query == ""
    assert r.warnings


def test_media_and_reply_filters():
    assert build_query("x", {"media": "images"}).query == "filter:images"
    assert build_query("x", {"media": "videos"}).query == "filter:videos"
    assert build_query("x", {"media": "links"}).query == "filter:links"
    assert build_query("x", {"replies": "only"}).query == "filter:replies"
    assert build_query("x", {"media": "quatsch"}).query == ""


def test_min_values_validate():
    r = build_query("x", {"min_faves": "abc", "min_retweets": "1.000", "min_replies": "-3"})
    assert r.query == "min_retweets:1000"
    assert len(r.warnings) == 2


def test_dates_and_empty_range_warning():
    r = build_query("x", {"since": "2025-02-01", "until": "2025-01-01"})
    assert r.query == "until:2025-01-01 since:2025-02-01"
    assert any("Zeitraum" in w for w in r.warnings)
    bad = build_query("x", {"since": "01.01.2025"})
    assert bad.query == "" and bad.warnings


def test_x_url_contains_encoded_query_and_sort():
    r = build_query("x", {"phrase": "a & b", "lang": "de"})
    latest = urlparse(r.url("latest"))
    assert latest.netloc == "x.com" and latest.path == "/search"
    qs = parse_qs(latest.query)
    assert qs["q"] == ['"a & b" lang:de']
    assert qs["f"] == ["live"]
    assert parse_qs(urlparse(r.url("top")).query)["f"] == ["top"]
    assert "%20" in r.url() and "+" not in r.url()


# --- Bluesky -----------------------------------------------------------------

def test_bluesky_basic():
    r = build_query("bluesky", {"all_words": "kaffee", "from_account": "@Timo.bsky.social", "lang": "de",
                                "since": "2025-01-01", "domain": "https://www.spiegel.de/artikel"})
    assert r.query == "kaffee from:timo.bsky.social domain:spiegel.de lang:de since:2025-01-01"
    assert r.summary.startswith("Beiträge von @timo.bsky.social mit")
    assert "auf Deutsch seit 01.01.2025" in r.summary


def test_bluesky_handle_without_dot_gets_default_suffix():
    r = build_query("bluesky", {"mention": "anna"})
    assert r.query == "mentions:anna.bsky.social"
    assert r.warnings


def test_bluesky_accepts_did():
    r = build_query("bluesky", {"from_account": "did:plc:z72i7hdynmk6r22z27h6tvur"})
    assert r.query == "from:did:plc:z72i7hdynmk6r22z27h6tvur"


def test_bluesky_url_has_no_sort_param():
    r = build_query("bluesky", {"hashtags": "kunst"})
    url = urlparse(r.url("top"))
    assert url.netloc == "bsky.app" and url.path == "/search"
    assert parse_qs(url.query) == {"q": ["#kunst"]}


def test_bluesky_link_field():
    r = build_query("bluesky", {"link_url": "https://example.com/a?b=1"})
    assert r.query == "https://example.com/a?b=1"
    assert build_query("bluesky", {"link_url": "kein link"}).query == ""


def test_bluesky_ignores_x_only_operators():
    """Umschalten X -> Bluesky: X-only-Felder fliessen nicht in den Befehl."""
    values = {"all_words": "katze", "from_account": "jack", "min_faves": "100", "replies": "exclude",
              "media": "images", "any_words": "a b", "none_words": "c", "to_account": "z"}
    r = build_query("bluesky", values)
    assert "min_faves" not in r.query
    assert "filter:" not in r.query
    assert " OR " not in r.query and "-c" not in r.query and "to:" not in r.query
    assert r.query == "katze from:jack.bsky.social"


def test_platform_switch_keeps_shared_fields():
    shared = shared_keys()
    for key in ("all_words", "phrase", "hashtags", "from_account", "mention", "lang", "since", "until"):
        assert key in shared
    assert "min_faves" not in shared and "domain" not in shared
    values = {"all_words": "kaffee", "phrase": "guten morgen", "lang": "de", "since": "2025-01-01"}
    x = build_query("x", values)
    b = build_query("bluesky", values)
    for part in ('kaffee', '"guten morgen"', 'lang:de', 'since:2025-01-01'):
        assert part in x.query and part in b.query


def test_unknown_platform_falls_back_to_x():
    assert build_query("myspace", {"all_words": "a"}).platform == "x"
