"""Alte Konto-Adresse. Das Konto selbst lebt in den Einstellungen (/settings/konto)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..models import User
from ..security import require_user_allow_pw_change
from ..templating import redirect

router = APIRouter()


@router.get("/account")
def account(request: Request, _user: User = Depends(require_user_allow_pw_change)):
    query = f"?{request.url.query}" if request.url.query else ""
    return redirect(request, f"/settings/konto{query}")
