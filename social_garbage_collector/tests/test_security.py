"""Rechtepruefung, Login, CSRF, Sitzungen, Pfadschutz."""

from __future__ import annotations

import pytest

from app.config import UnsafePathError, safe_path
from app.models import ROLE_ADMIN, User

from .conftest import ADMIN_PW, USER_PW, csrf_from, login

ADMIN_GET_ROUTES = [
    "/admin/users",
    "/admin/log",
    "/admin/users/generate-password",
    "/admin/users/1/delete",
]


def _admin_post_routes(user_id: int) -> list[tuple[str, dict]]:
    return [
        ("/admin/users", {"username": "eindringling", "role": "admin", "password": "x" * 12}),
        (f"/admin/users/{user_id}/role", {"role": "user"}),
        (f"/admin/users/{user_id}/active", {}),
        (f"/admin/users/{user_id}/reset-password", {"new_password": "y" * 12}),
        (f"/admin/users/{user_id}/delete", {"confirm": "ja"}),
        (f"/admin/users/{user_id}/password/reveal", {}),
    ]


# --- Nicht-Admins sehen und erreichen nichts ---------------------------------

@pytest.mark.parametrize("path", ADMIN_GET_ROUTES)
def test_user_gets_neutral_404_on_admin_pages(user_client, path):
    resp = user_client.get(path)
    assert resp.status_code == 404
    assert "Benutzerverwaltung" not in resp.text


def test_user_gets_404_on_admin_posts(user_client, harness):
    admin_id = harness.get_user("chef").id
    for path, data in _admin_post_routes(admin_id):
        resp = user_client.post(path, data={**data, "csrf_token": user_client.csrf})
        assert resp.status_code == 404, path
    # ... und nichts hat sich geaendert
    chef = harness.get_user("chef")
    assert chef.role == ROLE_ADMIN and chef.is_active
    with harness.db() as db:
        assert db.query(User).filter(User.username == "eindringling").count() == 0


def test_htmx_admin_fragment_is_404_for_user(user_client, harness):
    admin_id = harness.get_user("chef").id
    resp = user_client.post(f"/admin/users/{admin_id}/password/reveal",
                            headers={"HX-Request": "true", "X-CSRF-Token": user_client.csrf})
    assert resp.status_code == 404
    assert ADMIN_PW not in resp.text


def test_anonymous_gets_404_on_admin(harness):
    with harness.client() as c:
        assert c.get("/admin/users").status_code == 404


def test_admin_link_hidden_for_users(user_client, admin_client):
    assert "/admin/users" not in user_client.get("/").text
    assert "/admin/users" in admin_client.get("/").text


def test_only_admin_can_create_users(admin_client, harness):
    resp = admin_client.post("/admin/users", data={
        "username": "bernd", "role": "user", "password": "bernds-start-pw", "csrf_token": admin_client.csrf})
    assert resp.status_code == 303
    bernd = harness.get_user("bernd")
    assert bernd.must_change_password is True
    assert bernd.password_hash != "bernds-start-pw"


def test_duplicate_username_rejected(admin_client):
    resp = admin_client.post("/admin/users", data={
        "username": "ANNA", "role": "user", "password": "irgendwas-langes", "csrf_token": admin_client.csrf})
    assert resp.status_code == 400
    assert "gibt es schon" in resp.text


# --- Mindestens ein aktiver Admin --------------------------------------------

def test_admin_cannot_delete_or_demote_self(admin_client, harness):
    me = harness.get_user("chef").id
    r1 = admin_client.post(f"/admin/users/{me}/delete", data={"confirm": "ja", "csrf_token": admin_client.csrf})
    r2 = admin_client.post(f"/admin/users/{me}/role", data={"role": "user", "csrf_token": admin_client.csrf})
    r3 = admin_client.post(f"/admin/users/{me}/active", data={"csrf_token": admin_client.csrf})
    assert {r1.status_code, r2.status_code, r3.status_code} == {400}
    chef = harness.get_user("chef")
    assert chef.role == ROLE_ADMIN and chef.is_active


def test_last_admin_not_deletable_even_by_other_admin(harness):
    # Zweiter Admin, der aber deaktiviert ist -> chef bleibt einziger aktiver Admin.
    other_id = harness.add_user("vize", "vize-passwort-1", role=ROLE_ADMIN)
    with harness.client() as c:
        csrf = login(c, "vize", "vize-passwort-1")
        chef_id = harness.get_user("chef").id
        # vize darf chef degradieren, solange vize selbst aktiver Admin ist ...
        resp = c.post(f"/admin/users/{chef_id}/role", data={"role": "user", "csrf_token": csrf})
        assert resp.status_code == 303
        # ... aber jetzt ist vize der letzte und kann sich nicht selbst loeschen.
        resp = c.post(f"/admin/users/{other_id}/delete", data={"confirm": "ja", "csrf_token": csrf})
        assert resp.status_code == 400
    assert harness.get_user("vize").is_admin


def test_admin_can_delete_regular_user(admin_client, harness):
    anna = harness.get_user("anna").id
    resp = admin_client.post(f"/admin/users/{anna}/delete", data={"confirm": "ja", "csrf_token": admin_client.csrf})
    assert resp.status_code == 303
    with harness.db() as db:
        assert db.get(User, anna) is None


def test_deactivated_user_is_logged_out(harness, admin_client):
    with harness.client() as anna:
        login(anna, "anna", USER_PW)
        assert anna.get("/").status_code == 200
        anna_id = harness.get_user("anna").id
        admin_client.post(f"/admin/users/{anna_id}/active", data={"csrf_token": admin_client.csrf})
        resp = anna.get("/")
        assert resp.status_code == 303 and resp.headers["location"].endswith("/login")


def test_admin_actions_are_logged(admin_client, harness):
    admin_client.post("/admin/users", data={
        "username": "carla", "role": "user", "password": "carlas-start-pw", "csrf_token": admin_client.csrf})
    log = admin_client.get("/admin/log").text
    assert "Benutzer angelegt" in log and "carla" in log
    assert "carlas-start-pw" not in log


# --- Login, Sperre, Sitzungen, CSRF ------------------------------------------

def test_login_wrong_password(harness):
    with harness.client() as c:
        token = csrf_from(c.get("/login").text)
        resp = c.post("/login", data={"username": "anna", "password": "falsch", "csrf_token": token})
        assert resp.status_code == 401
        assert "falsch" in resp.text


def test_lockout_after_failed_logins(harness):
    with harness.client() as c:
        token = csrf_from(c.get("/login").text)
        for _ in range(harness.settings.login_max_attempts):
            c.post("/login", data={"username": "anna", "password": "falsch", "csrf_token": token})
        # Jetzt hilft auch das richtige Passwort nicht mehr.
        resp = c.post("/login", data={"username": "anna", "password": USER_PW, "csrf_token": token})
        assert resp.status_code == 401
        assert "Zu viele Fehlversuche" in resp.text


def test_post_without_csrf_is_rejected(user_client):
    resp = user_client.post("/lists", data={"title": "Ohne Token"})
    assert resp.status_code == 403


def test_post_with_wrong_csrf_is_rejected(user_client):
    resp = user_client.post("/lists", data={"title": "Falsches Token", "csrf_token": "abc"})
    assert resp.status_code == 403


def test_csrf_header_works_for_htmx(user_client):
    resp = user_client.post("/lists", data={"title": "Per Header"},
                            headers={"X-CSRF-Token": user_client.csrf})
    assert resp.status_code == 303


def test_pages_require_login(harness):
    with harness.client() as c:
        for path in ("/", "/lists", "/generator", "/posts/1", "/media/screenshots/x.png"):
            resp = c.get(path)
            assert resp.status_code == 303, path
            assert "/login" in resp.headers["location"]


def test_first_login_forces_password_change(harness, admin_client):
    admin_client.post("/admin/users", data={
        "username": "dora", "role": "user", "password": "doras-start-pw", "csrf_token": admin_client.csrf})
    with harness.client() as c:
        page = c.get("/login")
        resp = c.post("/login", data={"username": "dora", "password": "doras-start-pw",
                                      "csrf_token": csrf_from(page.text)})
        assert resp.headers["location"].endswith("/settings/konto?pflicht=1")
        # Andere Seiten leiten zur Passwortaenderung um.
        assert c.get("/").headers["location"].endswith("/settings/konto?pflicht=1")
        csrf = csrf_from(c.get("/settings/konto").text)
        resp = c.post("/settings/konto/passwort", data={"current": "doras-start-pw", "new": "doras-eigenes-pw",
                                                        "new2": "doras-eigenes-pw", "csrf_token": csrf})
        assert resp.status_code == 303
        assert c.get("/").status_code == 200


def test_session_expiry(tmp_path):
    from fastapi.testclient import TestClient

    from .conftest import Harness, make_settings

    h = Harness(make_settings(tmp_path, session_hours=1))
    with TestClient(h.app):
        h.add_user("eva", "evas-passwort-1")
        with h.client() as c:
            login(c, "eva", "evas-passwort-1")
            assert c.get("/").status_code == 200
            # Sitzung kuenstlich altern lassen
            from datetime import timedelta

            from app.models import UserSession, utcnow
            with h.db() as db:
                for s in db.query(UserSession):
                    s.expires_at = utcnow() - timedelta(minutes=1)
                db.commit()
            assert c.get("/").status_code == 303


# --- Ersteinrichtung -----------------------------------------------------------

def test_setup_requires_code(tmp_path):
    from fastapi.testclient import TestClient

    from .conftest import Harness, make_settings

    h = Harness(make_settings(tmp_path))
    with TestClient(h.app), h.client() as c:
        code = h.app.state.setup_code
        assert code
        resp = c.get("/")
        assert resp.headers["location"].endswith("/setup")
        token = csrf_from(c.get("/setup").text)
        bad = c.post("/setup", data={"code": "FALSCH", "username": "boss", "password": "boss-passwort",
                                     "password2": "boss-passwort", "csrf_token": token})
        assert bad.status_code == 400
        ok = c.post("/setup", data={"code": code, "username": "boss", "password": "boss-passwort",
                                    "password2": "boss-passwort", "csrf_token": token})
        assert ok.status_code == 303
        assert h.get_user("boss").role == ROLE_ADMIN
        assert c.get("/setup").headers["location"].endswith("/login")


def test_admin_from_option(tmp_path):
    from fastapi.testclient import TestClient

    from .conftest import Harness, make_settings

    h = Harness(make_settings(tmp_path, admin_username="timo", admin_password="option-passwort"))
    with TestClient(h.app):
        assert h.app.state.setup_code is None
        timo = h.get_user("timo")
        assert timo.is_admin and timo.must_change_password


# --- Pfadschutz ----------------------------------------------------------------

def test_safe_path_blocks_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert safe_path(root, "screenshots/a.png") == (root / "screenshots/a.png").resolve()
    for evil in ("../geheim", "/etc/passwd", "a/../../b", "", "x\x00y", "~/x"):
        with pytest.raises(UnsafePathError):
            safe_path(root, evil)


def test_media_route_blocks_traversal(user_client, harness):
    db_file = harness.settings.db_path
    assert db_file.exists()
    for path in ("/media/../db/archiv.sqlite", "/media/db/archiv.sqlite",
                 "/media/screenshots/../db/archiv.sqlite", "/media/%2e%2e/db/archiv.sqlite"):
        assert user_client.get(path).status_code == 404, path


def test_media_route_serves_screenshot(user_client, harness):
    shot = harness.settings.screenshot_dir / "x" / "2026" / "test.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    resp = user_client.get("/media/screenshots/x/2026/test.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_health_needs_no_login(harness):
    with harness.client() as c:
        assert c.get("/health").json()["status"] == "ok"


def test_ingress_prefix_in_links(user_client):
    resp = user_client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
    assert 'href="/api/hassio_ingress/abc123/lists"' in resp.text
