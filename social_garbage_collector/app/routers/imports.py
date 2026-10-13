"""Massenimport: viele Links einfuegen, Fortschritt verfolgen."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ImportBatch, Post, PostList, User
from ..security import get_db, get_settings, require_user
from ..services import bulk
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

PROGRESS_LIST = 300


def _get_batch(db: Session, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id[:16])
    if batch is None:
        raise HTTPException(status_code=404)
    return batch


def _progress(db: Session, batch: ImportBatch) -> dict:
    counts = dict(db.execute(select(Post.status, func.count()).where(Post.import_batch == batch.id)
                             .group_by(Post.status)).all())
    posts = list(db.scalars(select(Post).where(Post.import_batch == batch.id).order_by(Post.id).limit(PROGRESS_LIST)))
    total = sum(counts.values())
    open_ = counts.get("pending", 0) + counts.get("running", 0)
    return dict(batch=batch, posts=posts, counts=counts, total=total, open=open_,
                percent=round(100 * (total - open_) / total) if total else 100)


@router.post("/import")
async def start_import(request: Request, links: str = Form(""), tags: str = Form(""), list_id: int = Form(0),
                       new_list: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings)):
    target = None
    title = " ".join(new_list.split())[:120]
    if title:
        target = PostList(title=title, created_by_id=user.id)
        db.add(target)
        db.flush()
    elif list_id:
        target = db.get(PostList, list_id)
    try:
        result = await bulk.import_links(db, user, links, tags_raw=tags, target_list=target,
                                         network=settings.network_enabled)
    except bulk.BulkError as exc:
        db.rollback()
        return render(request, "add.html", status_code=400, mode="bulk", add_error=str(exc),
                      form_links=links, form_tags=tags, check=None)
    worker = getattr(request.app.state, "worker", None)
    if worker:
        for post in result.created:
            worker.enqueue(post.id)
    n = len(result.created)
    return redirect(request, f"/import/{result.batch.id}",
                    toast=f"{n} {'Aussage' if n == 1 else 'Aussagen'} in der Warteschlange" if n else "Nichts Neues dabei")


@router.get("/import")
def import_list(request: Request, db: Session = Depends(get_db)):
    batches = list(db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(30)))
    return render(request, "imports.html", batches=batches)


@router.get("/import/{batch_id}")
def import_detail(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = _get_batch(db, batch_id)
    existing = json.loads(batch.existing or "[]")
    return render(request, "import.html", existing=existing, repeated=json.loads(batch.repeated or "[]"),
                  invalid=json.loads(batch.invalid or "[]"), **_progress(db, batch))


@router.get("/import/{batch_id}/progress")
def import_progress(request: Request, batch_id: str, db: Session = Depends(get_db)):
    return render(request, "partials/import_progress.html", **_progress(db, _get_batch(db, batch_id)))
