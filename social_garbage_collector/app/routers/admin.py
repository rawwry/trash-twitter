"""Admin-Bereich: Benutzerverwaltung und Protokoll.

Die Rechtepruefung haengt am ROUTER (dependencies=[Depends(require_admin)]),
gilt also fuer jede Route hier automatisch. Nicht-Admins bekommen eine
neutrale 404 - auch fuer htmx-Teilstuecke.
"""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..db import backup_database
from ..models import ROLE_ADMIN, ROLES, STATUS_DONE, STATUS_ERROR, STATUS_PENDING, AdminLog, Post, User
from ..security import (
    count_active_admins,
    destroy_user_sessions,
    find_user_by_name,
    generate_password,
    get_db,
    get_settings,
    password_problem,
    require_admin,
    set_password,
)
from ..services import admin_log
from ..templating import redirect, render

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    return user


def _users_page(request: Request, db: Session, settings: Settings, status_code: int = 200, **extra):
    users = list(db.scalars(select(User).order_by(User.username)))
    return render(request, "admin/users.html", status_code=status_code, users=users, roles=ROLES, section="benutzer",
                  **extra)


def _would_lose_last_admin(db: Session, target: User) -> bool:
    """True, wenn target der letzte aktive Admin ist."""
    return target.is_admin and count_active_admins(db) <= 1


@router.get("/users")
def users(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return _users_page(request, db, settings)


@router.get("/users/generate-password", response_class=HTMLResponse)
def generate(request: Request):
    """Liefert ein neues Zufallspasswort als Eingabefeld (htmx tauscht es ein)."""
    name = request.query_params.get("name", "password")
    if name not in ("password", "new_password"):
        name = "password"
    return render(request, "partials/password_input.html", name=name, value=generate_password())


@router.post("/users")
def create_user(request: Request, username: str = Form(""), role: str = Form("user"), password: str = Form(""),
                admin: User = Depends(require_admin), db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings)):
    username = username.strip()
    error = None
    if not username or len(username) > 64:
        error = "Bitte einen Namen (bis 64 Zeichen) angeben."
    elif role not in ROLES:
        error = "Unbekannte Rolle."
    elif find_user_by_name(db, username):
        error = f"Den Namen „{username}“ gibt es schon."
    else:
        error = password_problem(password)
    if error:
        return _users_page(request, db, settings, status_code=400, error=error,
                           form={"username": username, "role": role})
    user = User(username=username, role=role)
    # Anfangspasswort: beim ersten Login muss der Nutzer es aendern.
    set_password(settings, user, password, must_change=True)
    db.add(user)
    db.flush()
    admin_log.record(db, admin, "user_create", user.username, f"Rolle: {role}")
    db.commit()
    return redirect(request, "/admin/users", toast=f"{user.username} angelegt")


@router.post("/users/{user_id}/role")
def change_role(request: Request, user_id: int, role: str = Form(""), admin: User = Depends(require_admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    target = _get_user(db, user_id)
    if role not in ROLES:
        raise HTTPException(status_code=400)
    if role != ROLE_ADMIN and target.id == admin.id:
        return _users_page(request, db, settings, status_code=400,
                           error="Du kannst dich nicht selbst herabstufen.")
    if role != ROLE_ADMIN and _would_lose_last_admin(db, target):
        return _users_page(request, db, settings, status_code=400,
                           error="Es muss immer mindestens einen aktiven Admin geben.")
    if target.role != role:
        old = target.role
        target.role = role
        admin_log.record(db, admin, "user_role", target.username, f"{old} → {role}")
        db.commit()
    return redirect(request, "/admin/users", toast=f"Rolle von {target.username} gespeichert")


@router.post("/users/{user_id}/active")
def toggle_active(request: Request, user_id: int, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    target = _get_user(db, user_id)
    if target.is_active:
        if target.id == admin.id:
            return _users_page(request, db, settings, status_code=400,
                               error="Du kannst dich nicht selbst deaktivieren.")
        if _would_lose_last_admin(db, target):
            return _users_page(request, db, settings, status_code=400,
                               error="Es muss immer mindestens einen aktiven Admin geben.")
        target.is_active = False
        destroy_user_sessions(db, target.id)
        admin_log.record(db, admin, "user_deactivate", target.username)
    else:
        target.is_active = True
        admin_log.record(db, admin, "user_activate", target.username)
    db.commit()
    state = "aktiviert" if target.is_active else "deaktiviert"
    return redirect(request, "/admin/users", toast=f"{target.username} {state}")


@router.post("/users/{user_id}/reset-password")
def reset_password(request: Request, user_id: int, new_password: str = Form(""),
                   admin: User = Depends(require_admin), db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)):
    target = _get_user(db, user_id)
    error = password_problem(new_password)
    if error:
        return _users_page(request, db, settings, status_code=400, error=f"{target.username}: {error}")
    # Eigenes Passwort ueber die Verwaltung: keine Pflicht zur Aenderung.
    set_password(settings, target, new_password, must_change=target.id != admin.id)
    if target.id != admin.id:
        destroy_user_sessions(db, target.id)
    admin_log.record(db, admin, "password_reset", target.username)
    db.commit()
    return redirect(request, "/admin/users", toast=f"Neues Passwort für {target.username} gesetzt")


@router.get("/users/{user_id}/delete")
def delete_confirm(request: Request, user_id: int, db: Session = Depends(get_db)):
    return render(request, "admin/confirm_user_delete.html", target=_get_user(db, user_id), section="benutzer")


@router.post("/users/{user_id}/delete")
def delete_user(request: Request, user_id: int, confirm: str = Form(""), admin: User = Depends(require_admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    target = _get_user(db, user_id)
    if target.id == admin.id:
        return _users_page(request, db, settings, status_code=400, error="Du kannst dich nicht selbst löschen.")
    if _would_lose_last_admin(db, target):
        return _users_page(request, db, settings, status_code=400,
                           error="Es muss immer mindestens einen aktiven Admin geben.")
    if confirm != "ja":
        return redirect(request, f"/admin/users/{target.id}/delete")
    name = target.username
    db.delete(target)  # Beitraege bleiben, "hinzugefuegt von" wird leer.
    admin_log.record(db, admin, "user_delete", name)
    db.commit()
    return redirect(request, "/admin/users", toast=f"{name} gelöscht")


@router.get("/log")
def log_page(request: Request, db: Session = Depends(get_db)):
    entries = list(db.scalars(select(AdminLog).order_by(AdminLog.created_at.desc(), AdminLog.id.desc()).limit(500)))
    return render(request, "admin/log.html", entries=entries, labels=admin_log.ACTION_LABELS, section="protokoll")


# --- System: Warteschlange, Speicher, Sicherungen -----------------------------------

def _dir_size(path) -> tuple[int, int]:
    total = count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                pass
    return total, count


@router.get("/system")
def system(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    by_status = {status: n for status, n in db.execute(select(Post.status, func.count()).group_by(Post.status))}
    shots_bytes, shots_count = _dir_size(settings.screenshot_dir)
    db_bytes = sum(p.stat().st_size for p in settings.db_dir.glob("archiv.sqlite*") if p.is_file())
    backups = sorted([*settings.backup_dir.glob("archiv-*.sqlite"),
                      *settings.backup_dir.glob("pre-upgrade-*.sqlite")], key=lambda p: p.stat().st_mtime, reverse=True)
    disk = shutil.disk_usage(settings.base_path)
    worker = getattr(request.app.state, "worker", None)
    failed = list(db.scalars(select(Post).where(Post.status == STATUS_ERROR).order_by(Post.updated_at.desc()).limit(20)))
    return render(request, "admin/system.html", section="system", by_status=by_status, failed=failed,
                  shots_bytes=shots_bytes, shots_count=shots_count, db_bytes=db_bytes, backups=backups,
                  disk=disk, worker_on=worker is not None, queue_size=worker.queue.qsize() if worker else 0,
                  options=_visible_options(settings))


def _visible_options(settings: Settings) -> list[tuple[str, str]]:
    """Add-on-Optionen zum Nachschauen. Geheimnisse werden nie angezeigt."""
    return [
        ("Datenordner", str(settings.base_path)),
        ("Sitzungsdauer", f"{settings.session_hours} Std."),
        ("Cookies nur über HTTPS", "ja" if settings.cookie_secure else "nein"),
        ("Login-Sperre", f"nach {settings.login_max_attempts} Fehlversuchen für {settings.login_lock_minutes} Min."),
        ("Automatische Sicherungen", f"{settings.backup_keep} behalten" if settings.backup_keep else "aus"),
        ("Screenshots", "dunkel" if settings.screenshot_theme != "light" else "hell"),
    ]


@router.post("/system/retry-failed")
def retry_failed(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    failed = list(db.scalars(select(Post).where(Post.status == STATUS_ERROR)))
    worker = getattr(request.app.state, "worker", None)
    for post in failed:
        post.status = STATUS_PENDING
        post.status_message = ""
        post.capture_generation = (post.capture_generation or 0) + 1
    db.commit()
    if worker:
        for post in failed:
            worker.enqueue(post.id)
    return redirect(request, "/admin/system", toast=f"{len(failed)} Aussagen neu eingereiht")


@router.post("/system/recapture-all")
def recapture_all(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Alle Screenshots neu aufnehmen (z. B. nach dem Wechsel auf den Dark Mode).
    Von Hand korrigierte Texte bleiben unangetastet."""
    posts = list(db.scalars(select(Post).where(Post.status.in_((STATUS_DONE, STATUS_ERROR)))))
    for post in posts:
        post.status = STATUS_PENDING
        post.status_message = ""
        post.capture_generation = (post.capture_generation or 0) + 1
    db.commit()
    worker = getattr(request.app.state, "worker", None)
    if worker:
        for post in posts:
            worker.enqueue(post.id)
    return redirect(request, "/admin/system", toast=f"{len(posts)} Beleg-Screenshots werden neu erstellt")


@router.post("/system/backup")
def backup_now(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    target = backup_database(settings.db_path, settings.backup_dir, max(settings.backup_keep, 1))
    admin_log.record(db, admin, "backup", target.name if target else "")
    db.commit()
    return redirect(request, "/admin/system", toast="Sicherung erstellt" if target else "Sicherung fehlgeschlagen",
                    kind="ok" if target else "error")


@router.get("/backups/{name}")
def download_backup(name: str, settings: Settings = Depends(get_settings)):
    try:
        path = safe_path(settings.backup_dir, name)
    except UnsafePathError:
        raise HTTPException(status_code=404)
    if not path.is_file() or not path.name.startswith(("archiv-", "pre-upgrade-")) or path.suffix != ".sqlite":
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name)
