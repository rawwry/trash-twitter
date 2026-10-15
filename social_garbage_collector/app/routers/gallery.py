"""Galerie: Bilder hochladen, nach selbst angelegten Kategorien ordnen und filtern."""

from __future__ import annotations

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
def gallery(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings)):
    raw = request.query_params.getlist("k")
    uncategorized = "ohne" in raw
    selected = _ids(raw)
    sort = request.query_params.get("sort", "zufall")
    sort = sort if sort in gallery_service.SORTS else "zufall"
    images = gallery_service.query_images(db, selected, uncategorized, sort)
    counts = gallery_service.category_counts(db)
    total = db.scalar(select(func.count()).select_from(GalleryImage)) or 0
    without = db.scalar(select(func.count()).select_from(GalleryImage).where(~GalleryImage.categories.any())) or 0
    ctx = dict(images=images, counts=counts, selected=set(selected), uncategorized=uncategorized,
               total=total, without=without, me=user, sort=sort, sorts=gallery_service.SORTS,
               settings_media_max_mb=settings.media_max_mb)
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "gallery-body":
        return render(request, "partials/gallery_body.html", **ctx)
    return render(request, "gallery.html", **ctx)


@router.post("/galerie/hochladen")
async def upload(request: Request, files: list[UploadFile] = File(default=[]), kategorien: list[str] = Form(default=[]),
                 neue_kategorien: str = Form(""), posters: list[UploadFile] = File(default=[]),
                 video_info: str = Form(""), user: User = Depends(require_user), db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)):
    files = [f for f in files if f and f.filename]
    if len(files) > gallery_service.MAX_FILES:
        return redirect(request, "/galerie", toast=f"Höchstens {gallery_service.MAX_FILES} Dateien auf einmal.", kind="error")
    # Standbilder aus dem Browser: Dateiname = Position des Videos in "files"
    frames: dict[int, bytes] = {}
    for poster in posters[: gallery_service.MAX_FILES]:
        stem = (poster.filename or "").split(".")[0]
        if stem.isdigit():
            frames[int(stem)] = await poster.read(8 * 1024 * 1024)
    durations = _durations(video_info)
    try:
        cats = gallery_service.get_or_create_categories(db, user, _ids(kategorien), neue_kategorien)
        images, videos = [], []
        for i, f in enumerate(files):
            if gallery_service.is_video_upload(f.filename, f.content_type or ""):
                videos.append((i, f))
            else:
                images.append((f.filename, await f.read(gallery_service.MAX_BYTES + 1)))
        if not images and not videos:
            raise gallery_service.GalleryError("Bitte mindestens ein Bild oder Video auswählen.")
        result = gallery_service.add_images(db, settings, user, images, cats) if images else gallery_service.UploadResult()
        for i, f in videos:
            await gallery_service.add_video(db, settings, user, f, frames.get(i), durations.get(i), cats, result)
        db.commit()
    except gallery_service.GalleryError as exc:
        db.rollback()
        return redirect(request, "/galerie", toast=str(exc), kind="error")
    parts = []
    n_vid = sum(1 for img in result.added if img.is_video)
    n_img = len(result.added) - n_vid
    if n_img:
        parts.append(f"{n_img} {'Bild' if n_img == 1 else 'Bilder'}")
    if n_vid:
        parts.append(f"{n_vid} {'Video' if n_vid == 1 else 'Videos'}")
    message = (" und ".join(parts) + " hinzugefügt") if parts else ""
    extra = []
    if result.duplicates:
        extra.append(f"{result.duplicates} schon vorhanden")
    if result.failed:
        extra.append("nicht lesbar: " + ", ".join(result.failed[:3]) + (" …" if len(result.failed) > 3 else ""))
    # Danach die neuesten zuerst - sonst landen die gerade hochgeladenen irgendwo im Zufallsmix
    return redirect(request, "/galerie?sort=neu" if result.added else "/galerie",
                    toast=" · ".join(filter(None, [message, *extra])) or "Nichts hochgeladen",
                    kind="ok" if result.added else "error")


def _durations(raw: str) -> dict[int, float]:
    """video_info aus dem Browser: {"0": 12.4, "3": 61.0} - Laenge je Video in Sekunden."""
    import json

    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    out = {}
    for key, value in (data.items() if isinstance(data, dict) else []):
        try:
            if str(key).isdigit():
                out[int(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


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
    mime = {".webp": "image/webp", **gallery_service.VIDEO_MIME}.get(file.suffix)
    if not file.is_file() or mime is None:
        raise HTTPException(status_code=404)
    # Name zufaellig, Inhalt fest. FileResponse beantwortet Range-Anfragen -> Videos spulen.
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    if download:
        return FileResponse(file, media_type=mime, filename=file.name, headers=headers)
    return FileResponse(file, media_type=mime, headers=headers)
