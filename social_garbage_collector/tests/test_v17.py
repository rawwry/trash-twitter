"""0.17.0: Kommentare unter Postings, Markierung in der Uebersicht, Benachrichtigungen."""

from __future__ import annotations

from app.models import Comment, Notification, Post



def _add(client, url):
    assert client.post("/posts", data={"url": url, "csrf_token": client.csrf}).status_code == 303


def test_comment_flow_and_notifications(user_client, admin_client, harness):
    _add(user_client, "https://x.com/jack/status/20")  # anna archiviert
    # chef kommentiert -> anna bekommt eine Benachrichtigung
    r = admin_client.post("/posts/1/kommentare", data={"body": "Zu witzig 😂 https://example.org", "csrf_token": admin_client.csrf},
                          headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="kommentare"' in r.text and "Zu witzig" in r.text
    assert 'href="https://example.org"' in r.text  # Links klickbar
    with harness.db() as db:
        assert db.get(Post, 1).comment_count == 1
        note = db.query(Notification).one()
        assert note.user_id == harness.get_user("anna").id and note.read_at is None
    # Glocke zeigt 1, Uebersicht zeigt die Markierung
    page = user_client.get("/").text
    assert 'class="bell-badge">1<' in page and 'class="cm-badge"' in page
    notes = user_client.get("/benachrichtigungen").text
    assert "hat dein archiviertes Posting kommentiert" in notes and "Zu witzig" in notes
    # anna antwortet -> chef (hat mitkommentiert) wird benachrichtigt, anna selbst nicht
    user_client.post("/posts/1/kommentare", data={"body": "Ja, oder? 😄", "csrf_token": user_client.csrf})
    with harness.db() as db:
        rec = sorted(n.user_id for n in db.query(Notification))
        assert rec == sorted([harness.get_user("anna").id, harness.get_user("chef").id])
    # Posting oeffnen = gelesen
    detail = user_client.get("/posts/1").text
    assert "Ja, oder?" in detail and "Zu witzig" in detail and "2 Kommentare" in detail
    assert 'class="bell-badge"' not in user_client.get("/").text


def test_comment_permissions_edit_delete(user_client, admin_client, harness):
    _add(user_client, "https://x.com/jack/status/20")
    user_client.post("/posts/1/kommentare", data={"body": "Erster", "csrf_token": user_client.csrf})
    with harness.db() as db:
        cid = db.query(Comment).one().id
    # fremde Person darf nicht bearbeiten, Admin darf loeschen
    assert admin_client.post(f"/kommentare/{cid}", data={"body": "gehackt", "csrf_token": admin_client.csrf}).status_code == 403
    user_client.post(f"/kommentare/{cid}", data={"body": "Erster (korrigiert)", "csrf_token": user_client.csrf})
    with harness.db() as db:
        c = db.get(Comment, cid)
        assert c.body == "Erster (korrigiert)" and c.edited_at is not None
    assert admin_client.post(f"/kommentare/{cid}/loeschen", data={"csrf_token": admin_client.csrf}).status_code == 303
    with harness.db() as db:
        assert db.query(Comment).count() == 0 and db.get(Post, 1).comment_count == 0
    # leerer Kommentar wird nicht gespeichert
    user_client.post("/posts/1/kommentare", data={"body": "   ", "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(Comment).count() == 0


def test_notification_open_and_mark_all(user_client, admin_client, harness):
    _add(user_client, "https://x.com/jack/status/20")
    for i in range(3):
        admin_client.post("/posts/1/kommentare", data={"body": f"Nr {i}", "csrf_token": admin_client.csrf})
    with harness.db() as db:
        nid = db.query(Notification).order_by(Notification.id).first().id
    r = user_client.get(f"/benachrichtigungen/{nid}")
    assert r.status_code == 303 and "/posts/1#kommentar-" in r.headers["location"]
    assert admin_client.get(f"/benachrichtigungen/{nid}").status_code == 404  # fremde Benachrichtigung
    user_client.post("/benachrichtigungen/gelesen", data={"csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(Notification).filter(Notification.read_at.is_(None)).count() == 0
    # Posting loeschen raeumt Kommentare und Benachrichtigungen mit auf
    user_client.post("/posts/bulk/delete", data={"ids": ["1"], "csrf_token": user_client.csrf})
    with harness.db() as db:
        assert db.query(Comment).count() == 0 and db.query(Notification).count() == 0
