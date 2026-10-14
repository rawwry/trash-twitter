"""Ideen fuer neue Funktionen sammeln: alle schreiben und stimmen mit, Admins setzen den Stand."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import IDEA_STATUSES, FeatureIdea, IdeaVote, User
from ..security import get_db, require_user
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

FILTERS = {"offen": ("neu", "geplant"), "umgesetzt": ("umgesetzt",), "alle": tuple(IDEA_STATUSES)}


def _idea(db: Session, idea_id: int) -> FeatureIdea:
    idea = db.get(FeatureIdea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404)
    return idea


@router.get("/ideen")
def ideas(request: Request, zeige: str = "offen", user: User = Depends(require_user), db: Session = Depends(get_db)):
    zeige = zeige if zeige in FILTERS else "offen"
    votes = func.count(IdeaVote.user_id)
    rows = db.execute(
        select(FeatureIdea, votes).outerjoin(IdeaVote).where(FeatureIdea.status.in_(FILTERS[zeige]))
        .options(selectinload(FeatureIdea.created_by))
        .group_by(FeatureIdea.id).order_by(votes.desc(), FeatureIdea.created_at.desc())
    ).all()
    mine = set(db.scalars(select(IdeaVote.idea_id).where(IdeaVote.user_id == user.id)))
    counts = dict(db.execute(select(FeatureIdea.status, func.count()).group_by(FeatureIdea.status)).all())
    return render(request, "ideas.html", nav="ideas", rows=rows, mine=mine, zeige=zeige, counts=counts,
                  statuses=IDEA_STATUSES)


@router.post("/ideen")
def create(request: Request, title: str = Form(""), body: str = Form(""), user: User = Depends(require_user),
           db: Session = Depends(get_db)):
    title = " ".join(title.split())[:140]
    if len(title) < 3:
        return redirect(request, "/ideen", toast="Bitte einen kurzen Titel für die Idee angeben.", kind="error")
    idea = FeatureIdea(title=title, body=body.strip()[:4000], created_by_id=user.id)
    db.add(idea)
    db.flush()
    db.add(IdeaVote(idea_id=idea.id, user_id=user.id))  # wer sie aufschreibt, will sie auch
    db.commit()
    return redirect(request, f"/ideen#idee-{idea.id}", toast="Danke! Deine Idee steht jetzt auf der Liste.")


@router.post("/ideen/{idea_id}/stimme")
def vote(request: Request, idea_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    idea = _idea(db, idea_id)
    existing = db.get(IdeaVote, (idea.id, user.id))
    if existing:
        db.delete(existing)
    else:
        db.add(IdeaVote(idea_id=idea.id, user_id=user.id))
    db.commit()
    n = db.scalar(select(func.count()).select_from(IdeaVote).where(IdeaVote.idea_id == idea.id)) or 0
    if request.headers.get("hx-request"):
        return render(request, "partials/idea_vote.html", idea=idea, n=n, voted=existing is None)
    return redirect(request, f"/ideen#idee-{idea.id}")


@router.post("/ideen/{idea_id}/status")
def set_status(request: Request, idea_id: int, status: str = Form(""), answer: str = Form(""),
               user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(status_code=404)
    idea = _idea(db, idea_id)
    if status in IDEA_STATUSES:
        idea.status = status
    idea.answer = answer.strip()[:2000]
    db.commit()
    return redirect(request, f"/ideen?zeige=alle#idee-{idea.id}", toast="Stand gespeichert")


@router.post("/ideen/{idea_id}/loeschen")
def delete(request: Request, idea_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    idea = _idea(db, idea_id)
    if not (user.is_admin or idea.created_by_id == user.id):
        raise HTTPException(status_code=403, detail="Nur wer die Idee geschrieben hat (oder ein Admin) kann sie löschen.")
    db.delete(idea)
    db.commit()
    return redirect(request, "/ideen", toast="Idee gelöscht")
