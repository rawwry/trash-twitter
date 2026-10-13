"""Gemeinsame Test-Hilfen.

Jeder Test bekommt einen frischen Datenordner in tmp_path. Kein Netz, kein
Playwright, kein Tesseract: Worker und DID-Lookup sind abgeschaltet.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import ROLE_ADMIN, ROLE_USER, User  # noqa: E402
from app.security import set_password  # noqa: E402

ADMIN_PW = "admin-passwort-123"
USER_PW = "nutzer-passwort-123"

_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(base_path=tmp_path / "data", worker_enabled=False, network_enabled=False,
                admin_password="", backup_keep=0)
    base.update(overrides)
    return Settings(**base)


class Harness:
    """App + Hilfsfunktionen zum Anlegen und Einloggen von Benutzern."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.app = create_app(settings)

    def client(self) -> TestClient:
        return TestClient(self.app, follow_redirects=False)

    def db(self):
        return self.app.state.SessionLocal()

    def add_user(self, name: str, password: str, role: str = ROLE_USER, must_change: bool = False) -> int:
        with self.db() as db:
            user = User(username=name, role=role)
            set_password(self.settings, user, password, must_change=must_change)
            db.add(user)
            db.commit()
            return user.id

    def get_user(self, name: str) -> User:
        with self.db() as db:
            return db.query(User).filter(User.username == name).one()


def csrf_from(html: str) -> str:
    m = _CSRF_RE.search(html)
    assert m, "kein CSRF-Token im HTML"
    return m.group(1)


def login(client: TestClient, username: str, password: str) -> str:
    """Loggt ein und gibt das CSRF-Token der Sitzung zurueck."""
    page = client.get("/login")
    token = csrf_from(page.text)
    resp = client.post("/login", data={"username": username, "password": password, "csrf_token": token})
    assert resp.status_code == 303, resp.text
    return session_csrf(client)


def session_csrf(client: TestClient) -> str:
    return csrf_from(client.get("/settings/konto").text)


@pytest.fixture
def harness(tmp_path):
    h = Harness(make_settings(tmp_path))
    with TestClient(h.app):  # Lifespan: Ordner, DB, Schema
        h.add_user("chef", ADMIN_PW, role=ROLE_ADMIN)
        h.add_user("anna", USER_PW, role=ROLE_USER)
        yield h


@pytest.fixture
def admin_client(harness):
    with harness.client() as c:
        c.csrf = login(c, "chef", ADMIN_PW)
        yield c


@pytest.fixture
def user_client(harness):
    with harness.client() as c:
        c.csrf = login(c, "anna", USER_PW)
        yield c
