"""Suchbefehl-Generator fuer X und Bluesky (Logik ohne Oberflaeche)."""

from .builder import PLATFORMS, BuildResult, build_query

__all__ = ["PLATFORMS", "BuildResult", "build_query"]
