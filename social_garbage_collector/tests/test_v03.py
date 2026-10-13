"""0.3.0: Darstellungen im Archiv, Profil (Name + Bild), Passwortlaenge, Screenshot-Masse."""

from __future__ import annotations

import io

from PIL import Image

from app.models import Post, User
from app.prefs import get_prefs
from app.security import password_problem
from app.services import shots

from .conftest import USER_PW, csrf_from


def _add(client, url):
    return client.post("/posts", data={"url": url, "csrf_token": client.csrf})


def _png(w=800, h=600, color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


# --- Darstellungen -----------------------------------------------------------------

def test_views_render_and_are_remembered(user_client, harness):
    """Seit 0.6: Karten, Liste, Zeitachse (Raster/Mosaik zeigten Screenshots)."""
    for i in range(3):
        _add(user_client, f"https://x.com/a/status/{100 + i}")
    for view, marker in (("cards", 'class="quote '), ("timeline", 'class="tl-month'), ("list", 'class="qrow')):
        page = user_client.get(f"/?view={view}").text
        assert marker in page, view
        assert get_prefs(harness.get_user("anna"))["archive_view"] == view
    # ohne Parameter bleibt die gemerkte Darstellung
    assert 'class="tl-month' not in user_client.get("/").text
    user_client.get("/?view=timeline")
    assert 'class="tl-month' in user_client.get("/").text
    # ungueltige (auch alte) Ansicht wird ignoriert
    user_client.get("/?view=mosaic")
    assert get_prefs(harness.get_user("anna"))["archive_view"] == "timeline"


def test_load_more_uses_oob_and_no_duplicate_month(user_client, harness):
    user_client.post("/settings/prefs", data={"per_page": "24", "csrf_token": user_client.csrf})
    for i in range(26):
        _add(user_client, f"https://x.com/b/status/{200 + i}")
    page = user_client.get("/?view=timeline").text
    assert 'id="load-more"' in page and "Mehr laden" in page
    more = user_client.get("/?page=2&more=1&after_group=" + _month(harness), headers={"HX-Request": "true"}).text
    assert 'hx-swap-oob="true"' in more
    assert more.count('data-post="') == 2
    assert "tl-month" not in more  # gleicher Monat wie auf Seite 1 -> keine neue Ueberschrift


def _month(harness):
    from app.templating import _monthkey
    with harness.db() as db:
        return _monthkey(db.query(Post).first().said_at)


# --- Screenshot-Masse -----------------------------------------------------------------

def test_measure_and_backfill(harness, tmp_path):
    shot = harness.settings.screenshot_dir / "x" / "2026" / "m.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(_png(1000, 400, (21, 32, 43)))
    assert shots.measure(shot) == (1000, 400, "#15202b")
    with harness.db() as db:
        db.add(Post(platform="x", url="https://x.com/m/status/1", dedup_key="x:1", post_id="1",
                    screenshot_path="screenshots/x/2026/m.png", status="done"))
        db.commit()
        assert shots.backfill(db, harness.settings) == 1
        p = db.query(Post).one()
        assert p.shot_is_wide and p.shot_bg == "#15202b"


def test_recapture_all_admin_only(user_client, admin_client, harness):
    _add(admin_client, "https://x.com/d/status/400")
    with harness.db() as db:
        db.query(Post).update({"status": "done"})
        db.commit()
    assert user_client.post("/admin/system/recapture-all", data={"csrf_token": user_client.csrf}).status_code == 404
    r = admin_client.post("/admin/system/recapture-all", data={"csrf_token": admin_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        assert db.query(Post).one().status == "pending"


# --- Passwortlaenge ----------------------------------------------------------------------

def test_password_min_length_is_12(user_client, harness):
    assert password_problem("12345678901") and not password_problem("123456789012")
    r = user_client.post("/settings/konto/passwort", data={"current": USER_PW, "new": "kurz5", "new2": "kurz5",
                                                          "csrf_token": user_client.csrf})
    assert r.status_code == 400
    r = user_client.post("/settings/konto/passwort", data={"current": USER_PW, "new": "langes-passwort-12",
                         "new2": "langes-passwort-12", "csrf_token": user_client.csrf})
    assert r.status_code == 200


# --- Profil ---------------------------------------------------------------------------------

def test_display_name_shown_instead_of_username(user_client, harness):
    r = user_client.post("/settings/konto/profil", data={"display_name": "  Anna  Banana ", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    assert harness.get_user("anna").display_name == "Anna Banana"
    _add(user_client, "https://x.com/e/status/500")
    with harness.db() as db:
        pid = db.query(Post).one().id
    assert "von Anna Banana" in user_client.get(f"/posts/{pid}").text
    # Login-Name bleibt
    assert harness.get_user("anna").username == "anna"


def test_avatar_upload_resize_and_serve(user_client, harness):
    files = {"avatar": ("ich.png", _png(1200, 800), "image/png")}
    r = user_client.post("/settings/konto/profil", data={"display_name": "", "csrf_token": user_client.csrf}, files=files)
    assert r.status_code == 303
    user = harness.get_user("anna")
    assert user.avatar_path and user.avatar_path.endswith(".webp")
    file = harness.settings.base_path / user.avatar_path
    with Image.open(file) as img:
        assert img.size == (256, 256) and img.format == "WEBP"
    assert user_client.get("/" + user.avatar_path).status_code == 200
    assert f'src="/{user.avatar_path}"' in user_client.get("/settings/konto").text
    # Bild ersetzen loescht das alte
    old = file
    user_client.post("/settings/konto/profil", data={"csrf_token": user_client.csrf},
                     files={"avatar": ("b.png", _png(300, 300, (0, 0, 255)), "image/png")})
    assert not old.exists()
    # Entfernen
    user_client.post("/settings/konto/profil", data={"remove_avatar": "1", "csrf_token": user_client.csrf})
    assert harness.get_user("anna").avatar_path is None


def test_avatar_rejects_non_images_and_traversal(user_client, harness):
    r = user_client.post("/settings/konto/profil", data={"csrf_token": user_client.csrf},
                         files={"avatar": ("boese.png", b"<?php echo 1; ?>", "image/png")})
    assert r.status_code == 400 and "kein lesbares Bild" in r.text
    assert harness.get_user("anna").avatar_path is None
    assert user_client.get("/avatars/..%2Fdb%2Farchiv.sqlite").status_code == 404
    assert user_client.get("/avatars/x.png").status_code == 404


def test_avatar_requires_login(harness):
    with harness.client() as c:
        assert c.get("/avatars/1-abc.webp").status_code == 303


def test_profile_form_needs_csrf(user_client):
    assert user_client.post("/settings/konto/profil", data={"display_name": "x"}).status_code == 403


# --- 0.3.2: weisse Randstreifen unter Screenshots -------------------------------------------

def _img(path, w=600, h=300, bg=(21, 32, 43), bottom=None, rows=2, content_at_edge=False):
    img = Image.new("RGB", (w, h), bg)
    if bottom:
        for y in range(h - rows, h):
            for x in range(w):
                img.putpixel((x, y), bottom)
    if content_at_edge:  # echter Inhalt (z. B. Bild) bis an den Rand - nicht einfarbig
        for y in range(h - 30, h):
            for x in range(w):
                img.putpixel((x, y), ((x * 7) % 255, (y * 3) % 255, 120))
    img.save(path)
    return path


def test_trim_removes_white_line(tmp_path):
    p = _img(tmp_path / "a.png", bottom=(255, 255, 255), rows=2)
    assert shots.trim_edges(p) is True
    with Image.open(p) as im:
        assert im.size == (600, 298)
        assert im.convert("RGB").getpixel((300, 297)) == (21, 32, 43)


def test_trim_leaves_clean_and_content_edges(tmp_path):
    clean = _img(tmp_path / "b.png")
    assert shots.trim_edges(clean) is False
    content = _img(tmp_path / "c.png", content_at_edge=True)
    assert shots.trim_edges(content) is False
    with Image.open(content) as im:
        assert im.size == (600, 300)


def test_trim_keeps_thick_bands(tmp_path):
    """Breite einfarbige Streifen sind Inhalt (z. B. Fusszeile), kein Rundungsrest."""
    p = _img(tmp_path / "d.png", bottom=(255, 255, 255), rows=20)
    assert shots.trim_edges(p) is False
    with Image.open(p) as im:
        assert im.size == (600, 300)


def test_cleanup_existing_runs_once(harness):
    shot = harness.settings.screenshot_dir / "x" / "2026" / "w.png"
    shot.parent.mkdir(parents=True)
    _img(shot, bottom=(255, 255, 255))
    # Beim Start lief die Bereinigung schon (leerer Ordner) - fuer den Test zuruecksetzen
    (harness.settings.screenshot_dir / ".rand-bereinigt-v1").unlink()
    with harness.db() as db:
        db.add(Post(platform="x", url="https://x.com/w/status/9", dedup_key="x:9", post_id="9",
                    screenshot_path="screenshots/x/2026/w.png", status="done", shot_w=600, shot_h=300))
        db.commit()
        shots.backfill(db, harness.settings)
        p = db.query(Post).one()
        assert (p.shot_w, p.shot_h) == (600, 298)  # neu vermessen
    assert shots.cleanup_existing(harness.settings) == 0  # Marker: kein zweiter Lauf
