"""Galerie: Bilder hochladen, nach selbst angelegten Kategorien ordnen und filtern."""

from __future__ import annotations
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, UnsafePathError, safe_path
from ..models import GalleryCategory, GalleryImage, User
from ..security import get_db, get_settings, require_user
from ..services import gallery as gallery_service
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])


def _image(db: Session, image_id: int) -> GalleryImage:
    image = db.get(GalleryImage, image_id)
    if image is None:
        raise HTTPException(status_code=404)
    return image


def _category(db: Session, category_id: int) -> GalleryCategory:
    cat = db.get(GalleryCategory, category_id)
    if cat is None:
        raise HTTPException(status_code=404)
    return cat


def _may_change(user: User, image: GalleryImage) -> bool:
    return user.is_admin or image.uploaded_by_id == user.id


def _ids(values: list[str]) -> list[int]:
    return [int(v) for v in values if v.isdigit()][:50]


@router.get("/galerie")
def gallery(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    raw = request.query_params.getlist("k")
    uncategorized = "ohne" in raw
    selected = _ids(raw)
    try:
        page = max(1, min(100_000, int(request.query_params.get("page", "1"))))
    except ValueError:
        page = 1
    images = gallery_service.query_images(db, selected, uncategorized, page)
    has_next = len(images) > gallery_service.PAGE_SIZE
    images = images[:gallery_service.PAGE_SIZE]
    def page_url(n):
        return "/galerie?" + urlencode([("k", k) for k in raw] + [("page", n)])
    counts = gallery_service.category_counts(db)
    total = db.scalar(select(func.count()).select_from(GalleryImage)) or 0
    without = db.scalar(select(func.count()).select_from(GalleryImage).where(~GalleryImage.categories.any())) or 0
    ctx = dict(images=images, counts=counts, selected=set(selected), uncategorized=uncategorized,
               total=total, without=without, me=user, page=page,
               previous=page_url(page - 1) if page > 1 else None,
               next_page=page_url(page + 1) if has_next else None)
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "gallery-body":
        return render(request, "partials/gallery_body.html", **ctx)
    return render(request, "gallery.html", **ctx)


@router.post("/galerie/hochladen")
def upload(request: Request, files: list[UploadFile] = File(default=[]), kategorien: list[str] = Form(default=[]),
                 neue_kategorien: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)):
    try:
        selected_files = [f for f in files if f and f.filename]
        if len(selected_files) > gallery_service.MAX_FILES:
            raise gallery_service.GalleryError(f"Höchstens {gallery_service.MAX_FILES} Bilder auf einmal.")
        if sum(f.size or 0 for f in selected_files) > gallery_service.MAX_TOTAL_BYTES:
            raise gallery_service.GalleryError("Zusammen höchstens 100 MB pro Upload.")
        # Sync-Route: Lesen und Pillow laufen im Threadpool; nur eine Datei im RAM.
        blobs = ((f.filename, f.file.read(gallery_service.MAX_BYTES + 1)) for f in selected_files)
        result = gallery_service.add_images(db, settings, user, blobs, _ids(kategorien), neue_kategorien)
    except gallery_service.GalleryError as exc:
        db.rollback()
        return redirect(request, "/galerie", toast=str(exc), kind="error")
    parts = []
    n = len(result.added)
    if n:
        parts.append(f"{n} {'Bild' if n == 1 else 'Bilder'} hinzugefügt")
    if result.duplicates:
        parts.append(f"{result.duplicates} schon vorhanden")
    if result.failed:
        parts.append(f"{len(result.failed)} nicht lesbar")
    return redirect(request, "/galerie", toast=" · ".join(parts) or "Nichts hochgeladen",
                    kind="ok" if n else "error")


@router.post("/galerie/bild/{image_id}")
def update_image(request: Request, image_id: int, title: str = Form(""), note: str = Form(""),
                 kategorien: list[str] = Form(default=[]), neue_kategorien: str = Form(""),
                 back: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db)):
    image = _image(db, image_id)
    image.title = " ".join(title.split())[:200]
    image.note = note.strip()[:2000]
    image.categories = gallery_service.get_or_create_categories(db, user, _ids(kategorien), neue_kategorien)
    db.commit()
    return redirect(request, _back(back), toast="Gespeichert")


@router.post("/galerie/bild/{image_id}/loeschen")
def delete_image(request: Request, image_id: int, back: str = Form(""), user: User = Depends(require_user),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    image = _image(db, image_id)
    if not _may_change(user, image):
        raise HTTPException(status_code=403, detail="Nur wer das Bild hochgeladen hat (oder ein Admin) kann es löschen.")
    gallery_service.delete_image(db, settings, image)
    return redirect(request, _back(back), toast="Bild gelöscht")


def _back(back: str) -> str:
    """Zurueck in die Galerie mit dem gleichen Filter - nur interne Ziele."""
    return back if back.startswith("/galerie") and "//" not in back else "/galerie"


@router.get("/galerie/bild/{image_id}/bearbeiten")
def edit_form(request: Request, image_id: int, back: str = "", user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    image = _image(db, image_id)
    return render(request, "partials/gallery_edit.html", image=image, counts=gallery_service.category_counts(db),
                  back=_back(back), may_delete=_may_change(user, image))


# --- Kategorien ------------------------------------------------------------------

@router.get("/galerie/kategorien")
def categories(request: Request, db: Session = Depends(get_db)):
    return render(request, "partials/gallery_categories.html", counts=gallery_service.category_counts(db))


@router.post("/galerie/kategorien")
def create_category(request: Request, name: str = Form(""), user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    gallery_service.get_or_create_categories(db, user, [], name)
    db.commit()
    return render(request, "partials/gallery_categories.html", counts=gallery_service.category_counts(db), changed=True)


@router.post("/galerie/kategorien/{category_id}/umbenennen")
def rename_category(request: Request, category_id: int, name: str = Form(""), db: Session = Depends(get_db)):
    cat = _category(db, category_id)
    name = gallery_service.normalize_category(name)
    clash = db.scalar(select(GalleryCategory).where(func.lower(GalleryCategory.name) == name.lower(),
                                                    GalleryCategory.id != cat.id)) if name else None
    if clash is not None:  # gleicher Name -> zusammenfuehren
        for image in list(cat.images):
            if clash not in image.categories:
                image.categories.append(clash)
        db.delete(cat)
    elif name:
        cat.name = name
    db.commit()
    return render(request, "partials/gallery_categories.html", counts=gallery_service.category_counts(db), changed=True)


@router.post("/galerie/kategorien/{category_id}/loeschen")
def delete_category(request: Request, category_id: int, db: Session = Depends(get_db)):
    db.delete(_category(db, category_id))  # Bilder bleiben, nur die Zuordnung verschwindet
    db.commit()
    return render(request, "partials/gallery_categories.html", counts=gallery_service.category_counts(db), changed=True)


# --- Dateien -----------------------------------------------------------------------

@router.get("/galerie/datei/{path:path}")
def gallery_file(path: str, download: int = 0, settings: Settings = Depends(get_settings)):
    try:
        file = safe_path(settings.base_path, path)
        file.relative_to(settings.gallery_dir.resolve())
    except (UnsafePathError, ValueError):
        raise HTTPException(status_code=404)
    if not file.is_file() or file.suffix != ".webp":
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}  # Name zufaellig, Inhalt fest
    if download:
        return FileResponse(file, media_type="image/webp", filename=file.name, headers=headers)
    return FileResponse(file, media_type="image/webp", headers=headers)
