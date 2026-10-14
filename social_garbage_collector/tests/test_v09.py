"""0.9.0: Passwort-Anzeige entfernt, Passwort selbst aendern, Listen-Auswahl, Galerie."""

from __future__ import annotations

import io
import sqlite3

from fastapi.testclient import TestClient
from PIL import Image

from app.models import GalleryCategory, GalleryImage, ListPost, Post, PostList

from .conftest import Harness, USER_PW, make_settings


def _jpg(w=800, h=600, color=(200, 80, 40), exif_gps=False) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {2: (52.0, 13.0, 0.0)}
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


# --- Passwoerter -------------------------------------------------------------------------------

def test_password_view_is_gone(admin_client, harness):
    users = admin_client.get("/admin/users").text
    assert "reveal" not in users and "Passwort-Anzeige" not in admin_client.get("/admin/system").text
    uid = harness.get_user("anna").id
    assert admin_client.post(f"/admin/users/{uid}/password/reveal", data={"csrf_token": admin_client.csrf}).status_code in (404, 405)


def test_old_password_copies_and_key_removed(tmp_path):
    settings = make_settings(tmp_path)
    settings.db_dir.mkdir(parents=True)
    key = settings.base_path / "secrets" / "fernet.key"
    key.parent.mkdir(parents=True)
    key.write_text("geheim")
    con = sqlite3.connect(settings.db_path)
    con.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE, role VARCHAR(16),
                   is_active BOOLEAN, password_hash VARCHAR(255), password_enc TEXT, must_change_password BOOLEAN,
                   disco BOOLEAN, failed_logins INTEGER, locked_until DATETIME, created_at DATETIME, last_login_at DATETIME)""")
    con.execute("INSERT INTO users (username, role, is_active, password_hash, password_enc, must_change_password) "
                "VALUES ('alt', 'admin', 1, 'x', 'VERSCHLUESSELT', 0)")
    con.commit()
    con.close()
    with TestClient(Harness(settings).app):
        cols = {r[1] for r in sqlite3.connect(settings.db_path).execute("PRAGMA table_info(users)")}
    assert "password_enc" not in cols
    assert not key.exists() and not key.parent.exists()


def test_every_user_can_change_own_password(user_client, harness):
    assert "/settings/konto#passwort" in user_client.get("/").text  # im Kontomenue
    assert "Passwort ändern" in user_client.get("/settings/konto").text
    r = user_client.post("/settings/konto/passwort", data={"current": USER_PW, "new": "neu-12345", "new2": "neu-12345",
                                                           "csrf_token": user_client.csrf})
    assert r.status_code == 200 and "Passwort geändert" in r.text


# --- Listen-Auswahl ------------------------------------------------------------------------------

def _post_id(client, harness, url="https://x.com/a/status/1"):
    client.post("/posts", data={"url": url, "csrf_token": client.csrf})
    with harness.db() as db:
        return db.query(Post).filter(Post.url == url).one().id


def test_list_picker_toggle_and_create(user_client, harness):
    pid = _post_id(user_client, harness)
    picker = user_client.get(f"/lists/picker?post={pid}").text
    assert "data-list-filter" in picker and "Noch keine Listen" in picker
    r = user_client.post("/lists/picker/new", data={"title": "  Energie  Politik ", "post": pid, "csrf_token": user_client.csrf})
    assert r.status_code == 200 and 'aria-pressed="true"' in r.text and 'id="post-lists"' in r.text
    with harness.db() as db:
        pl = db.query(PostList).one()
        assert pl.title == "Energie Politik" and db.query(ListPost).count() == 1
    # gleicher Name (andere Schreibweise) -> keine zweite Liste
    user_client.post("/lists/picker/new", data={"title": "energie politik", "post": pid, "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(PostList).count() == 1
    # Antippen nimmt heraus und legt wieder hinein
    r = user_client.post(f"/posts/{pid}/lists/{pl.id}/toggle", data={"csrf_token": user_client.csrf})
    assert 'aria-pressed="false"' in r.text and "In keiner Liste" in r.text
    r = user_client.post(f"/posts/{pid}/lists/{pl.id}/toggle", data={"csrf_token": user_client.csrf})
    assert 'aria-pressed="true"' in r.text
    assert "Listen wählen" in user_client.get(f"/posts/{pid}").text


def test_bulk_picker_and_list_tiles(user_client, harness):
    a = _post_id(user_client, harness, "https://x.com/a/status/1")
    b = _post_id(user_client, harness, "https://x.com/a/status/2")
    assert "data-bulk-target" not in user_client.get("/lists/picker").text  # noch keine Listen
    r = user_client.post("/posts/bulk/list", data={"ids": [a, b], "list_id": "0", "new_list": "Sammlung",
                                                   "csrf_token": user_client.csrf})
    assert r.status_code == 303
    assert "data-bulk-target" in user_client.get("/lists/picker").text
    archive = user_client.get("/").text
    assert "data-bulk-list-id" in archive and "<select name=\"list_id\"" not in archive
    with harness.db() as db:
        lid = db.query(PostList).one().id
    user_client.post(f"/lists/{lid}/describe", data={"description": "Worum es geht", "csrf_token": user_client.csrf})
    tiles = user_client.get("/lists").text
    assert 'class="list-tile"' in tiles and "Worum es geht" in tiles and "2</strong> Postings" in tiles


# --- Galerie ---------------------------------------------------------------------------------------

def _upload(client, files, **data):
    data.setdefault("csrf_token", client.csrf)
    return client.post("/galerie/hochladen", data=data,
                       files=[("files", (f"b{i}.jpg", blob, "image/jpeg")) for i, blob in enumerate(files)])


def test_gallery_upload_categories_filter(user_client, harness):
    assert "Die Galerie ist noch leer" in user_client.get("/galerie").text
    r = _upload(user_client, [_jpg(3000, 2000, exif_gps=True), _jpg(600, 900, (10, 120, 200))],
                neue_kategorien="Urlaub, Familie")
    assert r.status_code == 303
    with harness.db() as db:
        imgs = db.query(GalleryImage).order_by(GalleryImage.id).all()
        cats = {c.name: c.id for c in db.query(GalleryCategory)}
        assert len(imgs) == 2 and set(cats) == {"Urlaub", "Familie"}
        big = imgs[0]
        assert (big.width, big.height) == (2400, 1600) and big.color.startswith("#")
        assert sorted(c.name for c in big.categories) == ["Familie", "Urlaub"]
        full = harness.settings.base_path / big.path
        thumb = harness.settings.base_path / big.thumb_path
    with Image.open(full) as im:
        assert im.format == "WEBP" and not im.getexif().get(0x8825)
    with Image.open(thumb) as im:
        assert im.height == 720
    # gleiches Bild nochmal -> erkannt
    r = _upload(user_client, [_jpg(3000, 2000, exif_gps=True)])
    with harness.db() as db:
        assert db.query(GalleryImage).count() == 2
    # dritter ohne Kategorie, dann filtern
    _upload(user_client, [_jpg(500, 500, (0, 0, 0))])
    page = user_client.get("/galerie").text
    assert page.count("data-gal-item") == 3 and "Ohne Kategorie" in page
    assert user_client.get(f"/galerie?k={cats['Urlaub']}").text.count("data-gal-item") == 2
    assert user_client.get("/galerie?k=ohne").text.count("data-gal-item") == 1
    hx = user_client.get(f"/galerie?k={cats['Urlaub']}", headers={"HX-Request": "true", "HX-Target": "gallery-body"}).text
    assert hx.startswith('<div id="gallery-body">') or 'id="gallery-body"' in hx[:200]
    # Grid ohne weitere Infos: keine Titel/Kategorien sichtbar, nur in data-Attributen fuer die Vollansicht
    assert "gal-caption" not in page


def test_gallery_edit_delete_and_permissions(user_client, admin_client, harness):
    _upload(admin_client, [_jpg()], neue_kategorien="Natur")
    with harness.db() as db:
        img = db.query(GalleryImage).one()
        iid, path = img.id, img.path
    form = user_client.get(f"/galerie/bild/{iid}/bearbeiten?back=/galerie?k=1").text
    assert "Bild bearbeiten" in form and "Bild löschen" not in form  # Anna hat es nicht hochgeladen
    r = user_client.post(f"/galerie/bild/{iid}", data={"title": "Abendlicht", "note": "am See", "neue_kategorien": "Urlaub",
                                                       "back": "https://evil.example", "csrf_token": user_client.csrf})
    assert r.status_code == 303 and r.headers["location"].endswith("/galerie")
    with harness.db() as db:
        img = db.get(GalleryImage, iid)
        assert img.title == "Abendlicht" and [c.name for c in img.categories] == ["Urlaub"]
    assert user_client.post(f"/galerie/bild/{iid}/loeschen", data={"csrf_token": user_client.csrf}).status_code == 403
    assert admin_client.post(f"/galerie/bild/{iid}/loeschen", data={"csrf_token": admin_client.csrf}).status_code == 303
    assert not (harness.settings.base_path / path).exists()


def test_gallery_categories_manage(user_client, harness):
    _upload(user_client, [_jpg()], neue_kategorien="Reise, Urlaub")
    with harness.db() as db:
        cats = {c.name: c.id for c in db.query(GalleryCategory)}
    # Umbenennen auf vorhandenen Namen = zusammenfuehren
    r = user_client.post(f"/galerie/kategorien/{cats['Reise']}/umbenennen", data={"name": "urlaub", "csrf_token": user_client.csrf})
    assert r.status_code == 200
    with harness.db() as db:
        assert [c.name for c in db.query(GalleryCategory)] == ["Urlaub"]
    user_client.post("/galerie/kategorien", data={"name": "Familie", "csrf_token": user_client.csrf})
    user_client.post(f"/galerie/kategorien/{cats['Urlaub']}/loeschen", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert [c.name for c in db.query(GalleryCategory)] == ["Familie"]
        assert db.query(GalleryImage).count() == 1  # Bild bleibt


def test_gallery_files_safe_and_login_only(user_client, harness):
    _upload(user_client, [_jpg()])
    with harness.db() as db:
        img = db.query(GalleryImage).one()
    assert user_client.get(f"/galerie/datei/{img.thumb_path}").status_code == 200
    assert user_client.get("/galerie/datei/db/archiv.sqlite").status_code == 404
    assert user_client.get("/galerie/datei/gallery/..%2F..%2Fdb%2Farchiv.sqlite").status_code == 404
    with harness.client() as anon:
        assert anon.get(f"/galerie/datei/{img.thumb_path}").status_code == 303
        assert anon.get("/galerie").status_code == 303


def test_gallery_rejects_non_images_and_csrf(user_client, harness):
    r = _upload(user_client, [b"kein bild"])
    assert r.status_code == 303
    with harness.db() as db:
        assert db.query(GalleryImage).count() == 0
    assert user_client.post("/galerie/hochladen", files=[("files", ("a.jpg", _jpg(), "image/jpeg"))]).status_code == 403
    r = _upload(user_client, [])
    assert r.status_code == 303 and "galerie" in r.headers["location"]
