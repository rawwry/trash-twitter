"""Einfaches Protokoll der Admin-Aktionen und Archiv-Eingriffe (nur fuer Admins sichtbar)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AdminLog, User


def record(db: Session, actor: User | None, action: str, target: str = "", details: str = "") -> None:
    """Haengt einen Eintrag an. Niemals Passwoerter in details schreiben!"""
    db.add(AdminLog(
        actor_id=actor.id if actor else None,
        actor_name=actor.username if actor else "System",
        action=action,
        target=target[:128],
        details=details,
    ))


ACTION_LABELS = {
    "user_create": "Benutzer angelegt",
    "user_delete": "Benutzer gelöscht",
    "user_role": "Rolle geändert",
    "user_rename": "Benutzer umbenannt",
    "user_activate": "Benutzer aktiviert",
    "user_deactivate": "Benutzer deaktiviert",
    "password_reset": "Passwort zurückgesetzt",
    "password_reveal": "Passwort eingeblendet (bis 0.8)",
    "setup_admin": "Erster Admin eingerichtet",
    "backup": "Sicherung erstellt",
    "merge_persons": "Personen zusammengeführt",
    "move_account": "Account zugeordnet",
}
