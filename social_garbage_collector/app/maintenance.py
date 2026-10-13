"""Medienbestand nur lesen: python -m app.maintenance --base-path /share/SocialGarbageCollector"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .config import Settings, UnsafePathError, safe_path


def inspect_media(settings: Settings) -> dict[str, list[str]]:
    refs: set[str] = set()
    invalid: list[str] = []
    with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in (
            ("posts", ("screenshot_path", "author_avatar_path")), ("accounts", ("avatar_path",)),
            ("persons", ("photo_path",)), ("users", ("avatar_path",)),
            ("gallery_images", ("path", "thumb_path")),
        ):
            if table not in tables:
                continue
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column in existing:
                    refs.update(row[0] for row in db.execute(f"SELECT {column} FROM {table}") if row[0])
        if "post_revisions" in tables:
            for revision_id, raw in db.execute("SELECT id, snapshot FROM post_revisions"):
                try:
                    path = json.loads(raw).get("screenshot_path")
                    if path:
                        refs.add(path)
                except (ValueError, AttributeError, TypeError):
                    invalid.append(f"post_revisions:{revision_id}")
        if "account_changes" in tables:
            for old, new in db.execute("SELECT old_value, new_value FROM account_changes WHERE field='avatar_path'"):
                refs.update(path for path in (old, new) if path)
    missing = []
    for ref in refs:
        try:
            path = safe_path(settings.base_path, ref)
            if not path.is_file():
                missing.append(ref)
        except (UnsafePathError, TypeError):
            invalid.append(str(ref))
    present = set()
    for folder in (settings.screenshot_dir, settings.author_dir, settings.avatar_dir, settings.gallery_dir):
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg"):
                present.add(path.relative_to(settings.base_path).as_posix())
    return {"missing": sorted(missing), "unreferenced": sorted(present - refs), "invalid": sorted(invalid)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Medienverweise prüfen; verändert und löscht keine Dateien.")
    parser.add_argument("--base-path", type=Path, default=Settings.from_env().base_path)
    args = parser.parse_args()
    report = inspect_media(Settings(base_path=args.base_path))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["missing"] or report["invalid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
