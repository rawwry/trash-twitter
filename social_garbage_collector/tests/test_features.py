"""Funktionen ab 0.2.0: Linkpruefung, Teilen, Einstellungen, Tags verwalten, System-Seite,
Manifest, Login-Ruecksprung, Migration. (Reaktionen, "Neu fuer dich" und Zufallsfund
gibt es seit 0.6 nicht mehr - siehe test_v06.py.)"""

from __future__ import annotations

import json
import sqlite3
from fastapi.testclient import TestClient

from app.models import Post, Tag
from app.prefs import get_prefs

from .conftest import USER_PW, Harness, csrf_from, login, make_settings


def _add(client, url, tags=""):
    return client.post("/posts", data={"url": url, "tags": tags, "csrf_token": client.csrf})


def _post_id(harness, post_id_str):
    with harness.db() as db:
        return db.query(Post).filter(Post.post_id == post_id_str).one().id


# --- Live-Pruefung und Teilen-Ziel -----------------------------------------------------

def test_link_check(user_client):
    assert "bereit" in user_client.get("/posts/check?url=https://x.com/jack/status/20").text
    assert "Kein Beitrags-Link" in user_client.get("/posts/check?url=https://example.com").text
    _add(user_client, "https://x.com/jack/status/20")
    dup = user_client.get("/posts/check?url=https://twitter.com/jack/status/20").text
    assert "Schon im Archiv" in dup and "anna" in dup


def test_share_target_extracts_link_from_text(user_client):
    r = user_client.get("/teilen", params={"text": "Haha schau mal https://x.com/jack/status/20?s=46 lol"})
    assert r.status_code == 200
    assert 'value="https://x.com/jack/status/20?s=46"' in r.text
    assert "Geteiltes Posting archivieren" in r.text


def test_login_next_redirect_and_open_redirect_blocked(harness):
    with harness.client() as c:
        r = c.get("/teilen?url=https://x.com/a/status/9")
        assert "/login?next=" in r.headers["location"]
        token = csrf_from(c.get("/login").text)
        r = c.post("/login", data={"username": "anna", "password": USER_PW, "csrf_token": token,
                                   "next": "/teilen?url=https://x.com/a/status/9"})
        assert r.headers["location"].endswith("/teilen?url=https://x.com/a/status/9")
    with harness.client() as c:
        token = csrf_from(c.get("/login").text)
        for evil in ("https://evil.example", "//evil.example", "/\\evil.example"):
            r = c.post("/login", data={"username": "anna", "password": USER_PW, "csrf_token": token, "next": evil})
            assert r.headers["location"] in ("/", "http://testserver/"), evil
            c.post("/logout", data={"csrf_token": csrf_from(c.get("/settings/konto").text)})
            token = csrf_from(c.get("/login").text)


# --- Einstellungen ---------------------------------------------------------------------

def test_prefs_save_validate_and_apply(user_client, harness):
    for section in ("darstellung", "archiv", "suchgenerator", "teilen"):
        assert user_client.get(f"/settings/{section}").status_code == 200
    assert user_client.get("/settings/gibtsnicht").status_code == 404
    r = user_client.post("/settings/prefs", data={"theme": "dark", "accent": "green", "per_page": "999",
                                                  "archive_view": "list", "evil": "x", "csrf_token": user_client.csrf},
                         headers={"HX-Request": "true"})
    assert r.status_code == 204 and "toast" in r.headers["HX-Trigger"]
    prefs = get_prefs(harness.get_user("anna"))
    assert prefs["theme"] == "dark" and prefs["accent"] == "green" and prefs["archive_view"] == "list"
    assert prefs["per_page"] == "24"  # ungueltiger Wert ignoriert
    page = user_client.get("/").text
    assert 'data-theme="dark"' in page and 'data-accent="green"' in page


def test_generator_uses_pref_defaults(user_client):
    user_client.post("/settings/prefs", data={"gen_platform": "bluesky", "csrf_token": user_client.csrf})
    page = user_client.get("/generator").text
    assert 'value="bluesky" checked' in page


def test_settings_nav_hides_admin_for_users(user_client, admin_client):
    for path in ("/settings", "/settings/konto", "/settings/info"):
        html = user_client.get(path).text
        assert "/admin/" not in html, path
    assert "/admin/system" in admin_client.get("/settings").text


# --- Tags verwalten --------------------------------------------------------------------

def test_tag_rename_merge_delete(user_client, harness):
    _add(user_client, "https://x.com/a/status/11", tags="humr")
    _add(user_client, "https://x.com/a/status/12", tags="humor, humr")
    with harness.db() as db:
        typo = db.query(Tag).filter_by(name="humr").one().id
    r = user_client.post(f"/settings/tags/{typo}/rename", data={"name": "Humor", "csrf_token": user_client.csrf})
    assert r.status_code == 303
    with harness.db() as db:
        names = [t.name for t in db.query(Tag)]
        assert names == ["humor"]
        tag = db.query(Tag).one()
        assert len(tag.posts) == 2
        tid = tag.id
    user_client.post(f"/settings/tags/{tid}/delete", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(Tag).count() == 0 and db.query(Post).count() == 2


# --- System-Seite (Admin) ----------------------------------------------------------------

def test_system_page_admin_only(user_client, admin_client, harness):
    assert user_client.get("/admin/system").status_code == 404
    assert user_client.post("/admin/system/backup", data={"csrf_token": user_client.csrf}).status_code == 404
    assert admin_client.get("/admin/system").status_code == 200
    r = admin_client.post("/admin/system/backup", data={"csrf_token": admin_client.csrf})
    assert r.status_code == 303
    backups = list(harness.settings.backup_dir.glob("archiv-*.sqlite"))
    assert len(backups) == 1
    assert admin_client.get(f"/admin/backups/{backups[0].name}").status_code == 200
    assert user_client.get(f"/admin/backups/{backups[0].name}").status_code == 404
    assert admin_client.get("/admin/backups/..%2Fdb%2Farchiv.sqlite").status_code == 404


def test_retry_failed(admin_client, harness):
    _add(admin_client, "https://x.com/a/status/21")
    with harness.db() as db:
        db.query(Post).update({"status": "error", "status_message": "kaputt"})
        db.commit()
    admin_client.post("/admin/system/retry-failed", data={"csrf_token": admin_client.csrf})
    with harness.db() as db:
        assert db.query(Post).one().status == "pending"


# --- Manifest & Icons ----------------------------------------------------------------------

def test_manifest_and_icons(harness):
    with harness.client() as c:
        m = c.get("/manifest.webmanifest")
        assert m.status_code == 200
        data = json.loads(m.text)
        assert data["display"] == "standalone" and data["share_target"]["action"] == "/teilen"
        assert any(i["purpose"] == "maskable" for i in data["icons"])
        assert c.get("/static/brand/apple-touch-icon.png").status_code == 200
        login = c.get("/login").text
        assert 'rel="apple-touch-icon"' in login and "apple-mobile-web-app-capable" in login


def test_manifest_respects_ingress(harness):
    with harness.client() as c:
        data = c.get("/manifest.webmanifest", headers={"X-Ingress-Path": "/api/hassio_ingress/tok"}).json()
        assert data["start_url"] == "/api/hassio_ingress/tok/"


# --- Migration einer 0.1.0-Datenbank ----------------------------------------------------------

def test_migration_adds_columns(tmp_path):
    settings = make_settings(tmp_path)
    settings.db_dir.mkdir(parents=True)
    con = sqlite3.connect(settings.db_path)
    con.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE, role VARCHAR(16),
                   is_active BOOLEAN, password_hash VARCHAR(255), password_enc TEXT, must_change_password BOOLEAN,
                   disco BOOLEAN, failed_logins INTEGER, locked_until DATETIME, created_at DATETIME, last_login_at DATETIME)""")
    con.commit()
    con.close()
    h = Harness(settings)
    with TestClient(h.app):
        cols = {r[1] for r in sqlite3.connect(settings.db_path).execute("PRAGMA table_info(users)")}
        assert {"prefs", "seen_until", "last_visit_at"} <= cols
        h.add_user("neu", "neues-passwort-1")
        with h.client() as c:
            login(c, "neu", "neues-passwort-1")
            assert c.get("/").status_code == 200
