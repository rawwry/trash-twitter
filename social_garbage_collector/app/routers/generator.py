"""Suchbefehl-Generator: Formular, Live-Vorschau, Vorlagen, gespeicherte Suchen.

Die eigentliche Logik steckt in services/search/ - hier nur Oberflaeche.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SavedSearch, User
from ..security import get_db, require_user
from ..services.search import builder
from ..services.search.fields import LANGUAGES
from ..services.search.presets import presets
from ..templating import redirect, render

router = APIRouter(dependencies=[Depends(require_user)])

FIELD_KEYS = builder.all_field_keys()


def _values_from(params) -> dict[str, str]:
    return {k: str(params.get(k, "") or "")[:500] for k in FIELD_KEYS}


def _platform(value: str | None) -> str:
    return value if value in builder.PLATFORMS else "x"


def _context(db: Session, platform: str, values: dict[str, str], sort: str = "latest", **extra) -> dict:
    result = builder.build_query(platform, values)
    # Feld -> Plattformen, auf denen es existiert (fuer das Ein-/Ausblenden im Formular)
    field_platforms: dict[str, list[str]] = {}
    fields = []
    for name, mod in builder.PLATFORMS.items():
        for f in mod.FIELDS:
            field_platforms.setdefault(f.key, []).append(name)
            if f.key not in [x.key for x in fields]:
                fields.append(f)
    return dict(
        platform=platform, values=values, sort=sort, result=result,
        mod=builder.PLATFORMS[platform], platforms=builder.PLATFORMS,
        fields=fields, field_platforms=field_platforms, languages=LANGUAGES,
        presets={p: presets(p) for p in builder.PLATFORMS},
        saved=list(db.scalars(select(SavedSearch).order_by(SavedSearch.created_at.desc()))),
        **extra,
    )


@router.get("/generator")
def page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from ..prefs import get_prefs

    params = request.query_params
    prefs = get_prefs(user)
    platform = _platform(params.get("platform") or prefs["gen_platform"])
    values = _values_from(params)
    focus = ""
    if params.get("saved"):
        try:
            saved = db.get(SavedSearch, int(params["saved"]))
        except ValueError:
            saved = None
        if saved is None:
            raise HTTPException(status_code=404)
        platform = _platform(saved.platform)
        values = _values_from(json.loads(saved.params or "{}"))
    elif params.get("preset"):
        preset = next((p for p in presets(platform) if p["key"] == params["preset"]), None)
        if preset:
            values = _values_from(preset["values"])
            focus = preset["focus"]
    return render(request, "generator.html", focus=focus,
                  **_context(db, platform, values, params.get("sort") or prefs["gen_sort"]))


@router.get("/generator/preview")
def preview(request: Request, db: Session = Depends(get_db)):
    """Live-Vorschau: wird bei jeder Eingabe per htmx neu geholt."""
    params = request.query_params
    platform = _platform(params.get("platform"))
    sort = params.get("sort", "latest")
    result = builder.build_query(platform, _values_from(params))
    return render(request, "partials/generator_preview.html", platform=platform, result=result, sort=sort,
                  mod=builder.PLATFORMS[platform])


@router.post("/generator/save")
async def save(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    form = await request.form()
    platform = _platform(form.get("platform"))
    name = " ".join(str(form.get("search_name", "")).split())[:120]
    values = _values_from(form)
    result = builder.build_query(platform, values)
    if not name or result.empty:
        return render(request, "generator.html", status_code=400,
                      save_error="Bitte einen Namen angeben und mindestens ein Feld ausfüllen.",
                      focus="", **_context(db, platform, values))
    stored = {k: v for k, v in values.items() if v}
    db.add(SavedSearch(name=name, platform=platform, params=json.dumps(stored, ensure_ascii=False),
                       query=result.query, created_by_id=user.id))
    db.commit()
    return redirect(request, f"/generator?platform={platform}", toast=f"Suche „{name}“ gespeichert")


@router.post("/generator/saved/{search_id}/delete")
def delete_saved(request: Request, search_id: int, db: Session = Depends(get_db)):
    saved = db.get(SavedSearch, search_id)
    if saved is None:
        raise HTTPException(status_code=404)
    platform = saved.platform
    db.delete(saved)
    db.commit()
    return redirect(request, f"/generator?platform={platform}", toast="Gespeicherte Suche gelöscht")
