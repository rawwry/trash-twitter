"""Plattform-Register. Neue Plattformen hier eintragen."""

from __future__ import annotations

from .base import ParsedPost, PlatformService
from .bluesky import BlueskyService
from .x import XService

SERVICES: dict[str, PlatformService] = {
    s.name: s for s in (XService(), BlueskyService())
}

LABELS = {name: s.label for name, s in SERVICES.items()}


def get_service(platform: str) -> PlatformService:
    return SERVICES[platform]


def detect(url: str) -> tuple[PlatformService, ParsedPost] | None:
    """Erkennt die Plattform am Link. None, wenn keine zustaendig ist."""
    for service in SERVICES.values():
        parsed = service.parse_url(url)
        if parsed:
            return service, parsed
    return None
