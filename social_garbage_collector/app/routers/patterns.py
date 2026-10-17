"""Muster (0.19): Bilanz, Chronik, Figuren und Themen-Netz je Person.

Loest die Netzwerk-Seite aus 0.18 ab - die zeigte Personen und Tags als Netz,
in einem Dossier-Archiv mit einer Hauptperson ist das nur ein Stern. Die
Berechnung steckt in services/patterns.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from ..models import TAG_KINDS, Person, Tag, User
from ..security import get_db, require_user
from ..services import patterns
from ..templating import redirect, render, root_path

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/muster")
def overview(request: Request, db: Session = Depends(get_db)):
    return render(request, "patterns.html", nav="patterns", people=patterns.overview(db))


@router.get("/netzwerk")
def old_network(request: Request):
    """0.18-Adresse, falls noch als Lesezeichen gespeichert."""
    return redirect(request, "/muster")


@router.get("/personen/{person_id}/muster")
def person_patterns(request: Request, person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404)
    pat = patterns.for_person(db, person)
    others = [s for s in patterns.overview(db) if s.person.id != person.id]
    return render(request, "pattern.html", nav="patterns", pat=pat, others=others,
                  chart=pat.chart_data(root_path(request)))


def _back(target: str, fallback: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else fallback


@router.post("/tags/{tag_id}/art")
def set_kind(request: Request, tag_id: int, kind: str = Form(""), weiter: str = Form(""),
             user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Tag als Figur oder Thema markieren (Muster-Seite und Tags organisieren)."""
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404)
    if kind not in TAG_KINDS:
        raise HTTPException(status_code=400, detail="Unbekannte Art.")
    tag.kind = kind
    db.commit()
    label = "Figur" if kind == "figur" else "Thema"
    return redirect(request, _back(weiter, "/settings/tags"), toast=f"#{tag.name} ist jetzt {label}")
