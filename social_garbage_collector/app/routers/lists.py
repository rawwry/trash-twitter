"""Listen: fuer alle sichtbar und von allen bearbeitbar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Account, ListPost, Post, PostList, User
from ..security import get_db, require_user
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])


def _get_list(db: Session, list_id: int) -> PostList:
    pl = db.get(PostList, list_id)
    if pl is None:
        raise HTTPException(status_code=404)
    return pl


def _clean_title(title: str) -> str:
    return " ".join(title.split())[:120]


def _overview_rows(db: Session) -> list[tuple[PostList, int, object, object, int]]:
    """Je Liste: Anzahl Aussagen, Zeitraum der Aussagen, Anzahl Personen."""
    said = func.coalesce(Post.posted_at, Post.created_at)
    rows = db.execute(
        select(PostList, func.count(Post.id), func.min(said), func.max(said),
               func.count(func.distinct(Account.person_id)))
        .join(ListPost, ListPost.list_id == PostList.id, isouter=True)
        .join(Post, Post.id == ListPost.post_id, isouter=True)
        .join(Account, Account.id == Post.account_id, isouter=True)
        .group_by(PostList.id)
        .order_by(PostList.title)
    ).all()
    return [tuple(r) for r in rows]


def _faces(db: Session, list_ids: list[int]) -> dict[int, list]:
    """Bis zu 5 Personen je Liste (fuer die Gesichter auf der Kachel)."""
    from ..models import Person

    out: dict[int, list] = {}
    for lid in list_ids:
        out[lid] = list(db.scalars(
            select(Person).join(Account, Account.person_id == Person.id).join(Post, Post.account_id == Account.id)
            .join(ListPost, ListPost.post_id == Post.id).where(ListPost.list_id == lid)
            .group_by(Person.id).order_by(func.count().desc()).limit(5)))
    return out


@router.get("/lists")
def overview(request: Request, db: Session = Depends(get_db)):
    rows = _overview_rows(db)
    return render(request, "lists.html", lists=rows, faces=_faces(db, [r[0].id for r in rows]))


@router.post("/lists")
def create(request: Request, title: str = Form(""), user: User = Depends(require_user),
           db: Session = Depends(get_db)):
    title = _clean_title(title)
    if not title:
        rows = _overview_rows(db)
        return render(request, "lists.html", status_code=400, error="Bitte einen Titel angeben.",
                      lists=rows, faces=_faces(db, [r[0].id for r in rows]))
    pl = PostList(title=title, created_by_id=user.id)
    db.add(pl)
    db.commit()
    return redirect(request, f"/lists/{pl.id}", toast=f"Liste „{pl.title}“ angelegt")


# --------------------------------------------------------------------------
# Listen-Auswahl (Fenster): antippen statt Dropdown
# --------------------------------------------------------------------------

def _picker_ctx(db: Session, post: Post | None, mode: str) -> dict:
    rows = db.execute(
        select(PostList, func.count(ListPost.post_id))
        .join(ListPost, ListPost.list_id == PostList.id, isouter=True)
        .group_by(PostList.id).order_by(func.lower(PostList.title))
    ).all()
    member = {link.list_id for link in post.list_links} if post else set()
    return dict(rows=rows, member=member, picker_post=post, mode=mode)


def _post_or_404(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    return post


@router.get("/lists/picker")
def picker(request: Request, post: int = 0, mode: str = "post", db: Session = Depends(get_db)):
    target = _post_or_404(db, post) if post else None
    return render(request, "partials/list_picker.html", **_picker_ctx(db, target, "post" if target else "bulk"))


@router.post("/posts/{post_id}/lists/{list_id}/toggle")
def toggle(request: Request, post_id: int, list_id: int, user: User = Depends(require_user),
           db: Session = Depends(get_db)):
    """Aussage in eine Liste legen bzw. herausnehmen (ein Tipp in der Auswahl)."""
    post = _post_or_404(db, post_id)
    pl = _get_list(db, list_id)
    link = db.get(ListPost, (pl.id, post.id))
    if link:
        db.delete(link)
    else:
        db.add(ListPost(list_id=pl.id, post_id=post.id, added_by_id=user.id))
    db.commit()
    db.refresh(post)
    count = db.scalar(select(func.count()).select_from(ListPost).where(ListPost.list_id == pl.id)) or 0
    return render(request, "partials/list_picker_row.html", pl=pl, count=count, member=link is None,
                  picker_post=post, mode="post", oob_chips=True, post=post)


@router.post("/lists/picker/new")
def picker_new(request: Request, title: str = Form(""), post: int = Form(0), user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    """Neue Liste aus dem Suchfeld anlegen (gibt es den Namen schon: die vorhandene nehmen)."""
    target = _post_or_404(db, post) if post else None
    title = _clean_title(title)
    if title:
        pl = db.scalar(select(PostList).where(func.lower(PostList.title) == title.lower()))
        if pl is None:
            pl = PostList(title=title, created_by_id=user.id)
            db.add(pl)
            db.flush()
        if target is not None and not db.get(ListPost, (pl.id, target.id)):
            db.add(ListPost(list_id=pl.id, post_id=target.id, added_by_id=user.id))
        db.commit()
        if target is not None:
            db.refresh(target)
    return render(request, "partials/list_picker.html", **_picker_ctx(db, target, "post" if target else "bulk"),
                  oob_chips=target is not None, post=target)


@router.post("/lists/{list_id}/describe")
def describe(request: Request, list_id: int, description: str = Form(""), db: Session = Depends(get_db)):
    pl = _get_list(db, list_id)
    pl.description = description.strip()[:2000]
    db.commit()
    return redirect(request, f"/lists/{pl.id}", toast="Beschreibung gespeichert")


@router.get("/lists/{list_id}")
def detail(request: Request, list_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    pl = _get_list(db, list_id)
    posts = list(db.scalars(
        select(Post).join(ListPost, ListPost.post_id == Post.id)
        .where(ListPost.list_id == pl.id)
        .options(selectinload(Post.tags), selectinload(Post.added_by),
                 selectinload(Post.account).selectinload(Account.person))
        .order_by(func.coalesce(Post.posted_at, Post.created_at).asc(), Post.id.asc())
    ))
    return render(request, "list.html", plist=pl, posts=posts)


@router.post("/lists/{list_id}/rename")
def rename(request: Request, list_id: int, title: str = Form(""), db: Session = Depends(get_db)):
    pl = _get_list(db, list_id)
    title = _clean_title(title)
    if title:
        pl.title = title
        db.commit()
    return redirect(request, f"/lists/{pl.id}", toast="Titel gespeichert")


@router.get("/lists/{list_id}/delete")
def delete_confirm(request: Request, list_id: int, db: Session = Depends(get_db)):
    return render(request, "confirm_delete.html", plist=_get_list(db, list_id))


@router.post("/lists/{list_id}/delete")
def delete(request: Request, list_id: int, confirm: str = Form(""), db: Session = Depends(get_db)):
    pl = _get_list(db, list_id)
    # Loeschen nur mit ausdruecklicher Bestaetigung aus dem Bestaetigungsformular.
    if confirm != "ja":
        return redirect(request, f"/lists/{pl.id}/delete")
    title = pl.title
    db.delete(pl)  # Beitraege bleiben erhalten, nur die Zuordnung verschwindet.
    db.commit()
    return redirect(request, "/lists", toast=f"Liste „{title}“ gelöscht")
