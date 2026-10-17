"""Kommentare (0.17) und Benachrichtigungen.

Bewusst schlicht: flache Kommentare mit Namen unter jedem Posting. Wer das
Posting archiviert hat und wer schon mitkommentiert hat, bekommt eine
Benachrichtigung (Glocke oben). Bearbeiten darf nur, wer geschrieben hat;
loeschen auch ein Admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..models import Comment, Notification, Post, User, utcnow
from ..security import get_db, require_user
from ..templating import redirect, render, toast_header

router = APIRouter(dependencies=[Depends(require_user)])

MAX_COMMENT = 4000


def comments_for(db: Session, post_id: int) -> list[Comment]:
    return list(db.scalars(select(Comment).where(Comment.post_id == post_id)
                           .options(selectinload(Comment.user)).order_by(Comment.created_at, Comment.id)))


def _recount(db: Session, post: Post) -> None:
    post.comment_count = db.scalar(select(func.count()).select_from(Comment).where(Comment.post_id == post.id)) or 0


def _section(request: Request, db: Session, post: Post, user: User, toast: str = "", focus: bool = False):
    response = render(request, "partials/comments.html", post=post, comments=comments_for(db, post.id), me=user,
                      focus_new=focus)
    return toast_header(response, toast) if toast else response


def _notify(db: Session, post: Post, comment: Comment, author: User) -> None:
    """Archivierende Person + bisher Kommentierende, ausser der Person selbst."""
    recipients = {post.added_by_id} if post.added_by_id else set()
    recipients |= set(db.scalars(select(Comment.user_id).where(Comment.post_id == post.id, Comment.user_id.is_not(None))))
    recipients.discard(author.id)
    for uid in recipients:
        db.add(Notification(user_id=uid, kind="comment", post_id=post.id, comment_id=comment.id, actor_id=author.id))


def _post(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    return post


def _comment(db: Session, comment_id: int) -> Comment:
    c = db.get(Comment, comment_id)
    if c is None:
        raise HTTPException(status_code=404)
    return c


@router.post("/posts/{post_id}/kommentare")
def add_comment(request: Request, post_id: int, body: str = Form(""), user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    post = _post(db, post_id)
    body = body.strip()[:MAX_COMMENT]
    if not body:
        if request.headers.get("hx-request"):
            return _section(request, db, post, user)
        return redirect(request, f"/posts/{post.id}#kommentare", toast="Bitte etwas schreiben.", kind="error")
    comment = Comment(post_id=post.id, user_id=user.id, body=body)
    db.add(comment)
    db.flush()
    _notify(db, post, comment, user)
    _recount(db, post)
    db.commit()
    if request.headers.get("hx-request"):
        return _section(request, db, post, user, focus=True)
    return redirect(request, f"/posts/{post.id}#kommentar-{comment.id}")


@router.post("/kommentare/{comment_id}")
def edit_comment(request: Request, comment_id: int, body: str = Form(""), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    comment = _comment(db, comment_id)
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Nur wer den Kommentar geschrieben hat, kann ihn bearbeiten.")
    body = body.strip()[:MAX_COMMENT]
    if body and body != comment.body:
        comment.body, comment.edited_at = body, utcnow()
        db.commit()
    if request.headers.get("hx-request"):
        return _section(request, db, comment.post, user)
    return redirect(request, f"/posts/{comment.post_id}#kommentar-{comment.id}")


@router.post("/kommentare/{comment_id}/loeschen")
def delete_comment(request: Request, comment_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    comment = _comment(db, comment_id)
    if not (user.is_admin or comment.user_id == user.id):
        raise HTTPException(status_code=403, detail="Nur wer den Kommentar geschrieben hat (oder ein Admin) kann ihn löschen.")
    post = comment.post
    db.delete(comment)
    db.flush()
    _recount(db, post)
    db.commit()
    if request.headers.get("hx-request"):
        return _section(request, db, post, user, toast="Kommentar gelöscht")
    return redirect(request, f"/posts/{post.id}#kommentare", toast="Kommentar gelöscht")


# --- Benachrichtigungen ------------------------------------------------------------------------

@router.get("/benachrichtigungen")
def notifications(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    items = list(db.scalars(
        select(Notification).where(Notification.user_id == user.id)
        .options(selectinload(Notification.actor), selectinload(Notification.post), selectinload(Notification.comment))
        .order_by(Notification.created_at.desc()).limit(100)))
    return render(request, "notifications.html", nav="notifications", items=items)


@router.get("/benachrichtigungen/{note_id}")
def open_notification(request: Request, note_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Antippen: als gelesen markieren und zum Kommentar springen."""
    note = db.get(Notification, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404)
    if note.read_at is None:
        note.read_at = utcnow()
        db.commit()
    if note.post_id is None:
        return redirect(request, "/benachrichtigungen")
    anchor = f"#kommentar-{note.comment_id}" if note.comment_id else "#kommentare"
    return redirect(request, f"/posts/{note.post_id}{anchor}")


@router.post("/benachrichtigungen/gelesen")
def mark_all_read(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()
    return redirect(request, "/benachrichtigungen", toast="Alles gelesen")


def mark_post_read(db: Session, user: User, post_id: int) -> None:
    """Wer das Posting oeffnet, hat dessen Kommentare gesehen."""
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.post_id == post_id,
                                          Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
