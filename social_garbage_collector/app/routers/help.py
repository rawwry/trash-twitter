"""Hilfe & FAQ: Anleitungen zum Teilen vom Handy und haeufige Fragen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import VERSION
from ..models import User
from ..security import get_db, require_user
from ..templating import redirect, render, root_path

router = APIRouter(dependencies=[Depends(require_user)])


def direct_url(request: Request) -> str:
    """Adresse, unter der Kurzbefehle die App erreichen.

    Ueber die HA-Seitenleiste (Ingress) laeuft alles hinter dem HA-Login - das
    kann ein Kurzbefehl nicht. Dann gilt die direkte Adresse mit Port 8780."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "homeassistant.local:8780"
    if root_path(request):
        return f"http://{host.split(':')[0]}:8780"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


@router.get("/hilfe")
def help_page(request: Request, user: User = Depends(require_user)):
    base = direct_url(request)
    return render(request, "help.html", nav="help", base=base, api_url=f"{base}/api/teilen",
                  via_ingress=bool(root_path(request)), is_https=base.startswith("https://"))


@router.post("/neuigkeiten/gesehen")
def release_seen(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Das "Neu in x.x"-Fenster nicht noch einmal zeigen (gilt bis zur naechsten x.x-Version)."""
    user.release_seen = ".".join(VERSION.split(".")[:2])
    db.commit()
    if request.headers.get("hx-request") or request.headers.get("x-requested-with"):
        return Response(status_code=204)
    return redirect(request, "/")


@router.get("/netzwerk")
def old_network(request: Request):
    """Netzwerk (0.18) entfernt in 0.23 - alte Lesezeichen landen im Idiotarium."""
    return redirect(request, "/")
