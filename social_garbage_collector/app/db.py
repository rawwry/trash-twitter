"""Datenbank: Engine, Sitzungen, Schema-Init, Volltextindex, Backups.

Kein Alembic: das Schema wird beim Start mit create_all angelegt
(CREATE TABLE IF NOT EXISTS). Spaetere Aenderungen kommen als kleine,
idempotente Migrationen in _migrate().
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

log = logging.getLogger("sgc.db")


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        # WAL: Lesen und Schreiben blockieren sich kaum (Worker + Web parallel).
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


# Volltextsuche: FTS5 als "external content"-Tabelle ueber posts.
# Die Trigger halten den Index bei jedem INSERT/UPDATE/DELETE synchron.
_FTS_SQL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
        text, note, author_handle, author_display_name, alt_texts,
        content='posts', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_fts_ai AFTER INSERT ON posts BEGIN
        INSERT INTO posts_fts(rowid, text, note, author_handle, author_display_name, alt_texts)
        VALUES (new.id, new.text, new.note, new.author_handle, new.author_display_name, new.alt_texts);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_fts_ad AFTER DELETE ON posts BEGIN
        INSERT INTO posts_fts(posts_fts, rowid, text, note, author_handle, author_display_name, alt_texts)
        VALUES ('delete', old.id, old.text, old.note, old.author_handle, old.author_display_name, old.alt_texts);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_fts_au AFTER UPDATE ON posts BEGIN
        INSERT INTO posts_fts(posts_fts, rowid, text, note, author_handle, author_display_name, alt_texts)
        VALUES ('delete', old.id, old.text, old.note, old.author_handle, old.author_display_name, old.alt_texts);
        INSERT INTO posts_fts(rowid, text, note, author_handle, author_display_name, alt_texts)
        VALUES (new.id, new.text, new.note, new.author_handle, new.author_display_name, new.alt_texts);
    END
    """,
    # Benutzernamen eindeutig ohne Gross-/Kleinschreibung.
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_nocase ON users(lower(username))",
]


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _FTS_SQL:
            conn.execute(text(stmt))
        _migrate(conn)


# Spalten, die nach 0.1.0 dazugekommen sind. create_all legt nur neue
# TABELLEN an, keine neuen Spalten in bestehenden - das passiert hier.
_ADDED_COLUMNS = {
    "users": [
        ("prefs", "TEXT NOT NULL DEFAULT '{}'"),
        ("seen_until", "DATETIME"),
        ("last_visit_at", "DATETIME"),
        ("display_name", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("avatar_path", "VARCHAR(255)"),
        ("api_token_hash", "VARCHAR(64)"),
        ("api_token_hint", "VARCHAR(8) NOT NULL DEFAULT ''"),
        ("api_token_created_at", "DATETIME"),
        ("release_seen", "VARCHAR(16) NOT NULL DEFAULT ''"),
    ],
    "posts": [
        ("shot_w", "INTEGER"),
        ("shot_h", "INTEGER"),
        ("shot_bg", "VARCHAR(7)"),
        ("thread_mode", "VARCHAR(8) NOT NULL DEFAULT 'auto'"),
        ("thread_extra", "TEXT NOT NULL DEFAULT ''"),
        ("thread_parts", "TEXT NOT NULL DEFAULT ''"),
        ("thread_count", "INTEGER NOT NULL DEFAULT 0"),
        ("shot_source", "VARCHAR(8) NOT NULL DEFAULT 'auto'"),
        ("account_id", "INTEGER REFERENCES accounts(id) ON DELETE SET NULL"),
        ("author_avatar_path", "VARCHAR(255)"),
        ("date_source", "VARCHAR(8)"),
        ("date_has_time", "BOOLEAN NOT NULL DEFAULT 1"),
        ("long_post", "BOOLEAN NOT NULL DEFAULT 0"),
        ("shot_reconstructed", "BOOLEAN NOT NULL DEFAULT 0"),
        ("import_batch", "VARCHAR(16)"),
        ("media_checked", "BOOLEAN NOT NULL DEFAULT 0"),
        ("platform_auto", "BOOLEAN NOT NULL DEFAULT 0"),
        ("shot_parsed", "BOOLEAN NOT NULL DEFAULT 0"),
    ],
    "post_media": [
        ("thumb_path", "VARCHAR(255)"),
    ],
    "lists": [
        ("description", "TEXT NOT NULL DEFAULT ''"),
    ],
    "tags": [
        ("parent_id", "INTEGER REFERENCES tags(id) ON DELETE SET NULL"),
        ("is_group", "BOOLEAN NOT NULL DEFAULT 0"),
    ],
    "gallery_images": [
        ("taken_at", "DATETIME"),
        ("kind", "VARCHAR(8) NOT NULL DEFAULT 'image'"),
        ("poster_path", "VARCHAR(255)"),
        ("mime", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("bytes", "INTEGER NOT NULL DEFAULT 0"),
        ("duration", "FLOAT"),
    ],
    "persons": [
        ("subtitle", "VARCHAR(120) NOT NULL DEFAULT ''"),
        ("photo_path", "VARCHAR(255)"),
    ],
}

# Tabellen, die es nicht mehr gibt (0.6: Reaktionen entfernt - das Archiv
# kennt keine Likes).
_DROPPED_TABLES = ("reactions",)


def _migrate(conn) -> None:
    """Idempotente Schema-Migrationen (laufen bei jedem Start)."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("Migration: Spalte %s.%s ergaenzt", table, name)
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_account_id ON posts(account_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_import_batch ON posts(import_batch)"))
    for table in _DROPPED_TABLES:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    # 0.9: Passwort-Anzeige entfernt - verschluesselte Kopien weg (SQLite >= 3.35).
    if "password_enc" in {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}:
        conn.execute(text("UPDATE users SET password_enc = NULL"))
        try:
            conn.execute(text("ALTER TABLE users DROP COLUMN password_enc"))
        except Exception:  # pragma: no cover - sehr altes SQLite: Spalte bleibt leer stehen
            log.info("Spalte users.password_enc geleert (DROP COLUMN nicht verfuegbar).")
    # 0.6.3: Herkunft vorhandener Daten nachtragen (nur wo noch leer).
    conn.execute(text("UPDATE posts SET date_source = 'manual', date_has_time = 0 WHERE date_source IS NULL "
                      "AND posted_at IS NOT NULL AND shot_source = 'upload' AND url = ''"))
    conn.execute(text("UPDATE posts SET date_source = 'api' WHERE date_source IS NULL AND posted_at IS NOT NULL"))
    conn.execute(text("PRAGMA user_version = 7"))


def backup_database(db_path: Path, backup_dir: Path, keep: int) -> Path | None:
    """Sichert die DB per sqlite3.backup() - nicht per Dateikopie (WAL!).

    Behaelt die neuesten `keep` Sicherungen, aeltere werden geloescht.
    keep=0 schaltet die automatische Sicherung ab.
    """
    if keep <= 0 or not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"archiv-{datetime.now():%Y-%m-%d_%H%M%S}.sqlite"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(backup_dir.glob("archiv-*.sqlite"))
    for path in old[:-keep]:
        path.unlink(missing_ok=True)
    log.info("Datenbank gesichert: %s", target.name)
    return target
