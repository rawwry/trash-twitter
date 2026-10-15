"""Datenmodell (SQLAlchemy 2.0, deklarativ).

Zeitstempel werden als naive UTC-Werte gespeichert und erst in der
Oberflaeche in die lokale Zeitzone umgerechnet (siehe templating.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)

PLATFORM_X = "x"
PLATFORM_BLUESKY = "bluesky"
PLATFORMS = (PLATFORM_X, PLATFORM_BLUESKY)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

TEXT_OCR = "ocr"
TEXT_API = "api"
TEXT_MANUAL = "manual"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Eindeutig ohne Ruecksicht auf Gross-/Kleinschreibung (siehe db.py, Index).
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    # Seit 0.6 ungenutzt (Discomodus entfernt), bleibt fuer alte Datenbanken stehen.
    disco: Mapped[bool] = mapped_column(Boolean, default=False)
    # Profil: Anzeigename (leer = Benutzername) und Profilbild (relativ zum Basispfad).
    display_name: Mapped[str] = mapped_column(String(40), default="")
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Persoenlicher Schluessel fuer Kurzbefehle/Teilen (0.11.0). Gespeichert nur der
    # SHA-256-Hash; hint = letzte 4 Zeichen zum Wiedererkennen.
    api_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    api_token_hint: Mapped[str] = mapped_column(String(8), default="")
    api_token_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Persoenliche Einstellungen als JSON (siehe app/prefs.py).
    prefs: Mapped[str] = mapped_column(Text, default="{}")
    # Seit 0.6 ungenutzt ("Neu fuer dich" entfernt), bleiben fuer alte Datenbanken stehen.
    seen_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN and self.is_active

    @property
    def name(self) -> str:
        """Was die Oberflaeche anzeigt: Anzeigename, sonst Benutzername."""
        return self.display_name or self.username


class UserSession(Base):
    """Server-seitige Sitzung. Im Cookie steht nur ein Zufallstoken,
    in der Datenbank nur dessen SHA-256-Hash."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped[User] = relationship(lazy="joined")


class AdminLog(Base):
    __tablename__ = "admin_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Name als Kopie, damit das Protokoll auch nach dem Loeschen lesbar bleibt.
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), default="")
    details: Mapped[str] = mapped_column(Text, default="")


post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    url: Mapped[str] = mapped_column(String(512))
    # Plattform-spezifischer Schluessel zur Duplikaterkennung,
    # z. B. "x:1234" oder "bluesky:did:plc:abc:3kxyz".
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    post_id: Mapped[str] = mapped_column(String(64))
    author_handle: Mapped[str] = mapped_column(String(255), index=True, default="")
    author_did: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_display_name: Mapped[str] = mapped_column(String(255), default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Woher das Datum stammt: api | id | ocr | manual (siehe services/dates.py),
    # "none" = im Screenshot gesucht, nichts gefunden. Ohne Uhrzeit: date_has_time False.
    date_source: Mapped[str | None] = mapped_column(String(8), nullable=True)
    date_has_time: Mapped[bool] = mapped_column(Boolean, default=True)
    # Langer X-Beitrag (> 280 Zeichen): das Embed - und damit der Beleg-Screenshot -
    # zeigt nur den Anfang mit "Mehr anzeigen", der Wortlaut ist trotzdem vollstaendig.
    long_post: Mapped[bool] = mapped_column(Boolean, default=False)
    # Beleg-Screenshot mit von der App eingesetztem Volltext (0.7.1) - kein reines Abbild.
    shot_reconstructed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Medien (0.10.0): schon nach Bildern/GIFs/Videos geschaut? (fuer das Nachholen alter Postings)
    media_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    # 0.12: Screenshot ohne Link - Plattform selbst erkennen; Kopf/Fuss schon ausgewertet
    platform_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    shot_parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Massenimport (0.8.0): Kennung des Imports, aus dem das Posting stammt.
    import_batch: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    text_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Alt-Texte der Bilder (Bluesky), zeilenweise.
    alt_texts: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # Relativ zum Basispfad, damit der Ordner verschiebbar bleibt.
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Format und Randfarbe des Screenshots - fuer gleich grosse Raster-Kacheln
    # (breite Bilder werden eingepasst, die Luecke bekommt diese Farbe).
    shot_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shot_bg: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Herkunft des Screenshots: "auto" = von der App aufgenommen, "upload" = selbst
    # hochgeladen. Hochgeladene Bilder ueberschreibt der Worker nie.
    shot_source: Mapped[str] = mapped_column(String(8), default="auto")
    # Threads: bis 0.6.0 "auto" = automatisch erkennen. Seit 0.6.1 ist die
    # Erkennung aus, es zaehlen nur die von Hand ergaenzten Teile (thread_extra).
    thread_mode: Mapped[str] = mapped_column(String(8), default="off")
    # Von Hand ergaenzte Teile (JSON-Liste kanonischer URLs, in Reihenfolge).
    thread_extra: Mapped[str] = mapped_column(Text, default="")
    # Tatsaechlich zusammengeklebte Teile (JSON: [{"url", "post_id"}]), 0 = kein Thread.
    thread_parts: Mapped[str] = mapped_column(Text, default="")
    thread_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    status_message: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Wer hat das gesagt? author_handle/author_display_name oben sind der Stand
    # beim Archivieren (so wird zitiert), das Konto dahinter ist der heutige Stand.
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"),
                                                   nullable=True, index=True)
    # Profilbild des Verfassers zum Zeitpunkt der Archivierung (relativ zum Basispfad).
    author_avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    added_by: Mapped[User | None] = relationship()
    account: Mapped["Account | None"] = relationship(back_populates="posts")
    tags: Mapped[list["Tag"]] = relationship(secondary=post_tags, back_populates="posts", order_by="Tag.name")
    list_links: Mapped[list["ListPost"]] = relationship(back_populates="post", cascade="all, delete-orphan")
    media: Mapped[list["PostMedia"]] = relationship(back_populates="post", cascade="all, delete-orphan",
                                                    order_by="PostMedia.position")

    @property
    def thread_list(self) -> list[dict]:
        import json

        try:
            return json.loads(self.thread_parts) if self.thread_parts else []
        except ValueError:
            return []

    @property
    def shot_is_wide(self) -> bool:
        return bool(self.shot_w and self.shot_h and self.shot_w / self.shot_h > 1.25)

    @property
    def lists(self) -> list["PostList"]:
        return [link.list for link in self.list_links]

    @property
    def author_name(self) -> str:
        """Anzeigename, sonst @handle - so wie die Aussage zitiert wird."""
        if self.author_display_name:
            return self.author_display_name
        return f"@{self.author_handle}" if self.author_handle else "Unbekannt"

    @property
    def said_at(self) -> datetime:
        """Wann die Aussage gemacht wurde (Rueckfall: wann sie archiviert wurde)."""
        return self.posted_at or self.created_at

    @property
    def date_only(self) -> bool:
        """Datum ohne Uhrzeit (von Hand nur der Tag, oder im Screenshot stand keine)."""
        return not self.date_has_time


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Immer klein geschrieben gespeichert, siehe services/posts.normalize_tag.
    name: Mapped[str] = mapped_column(String(64), unique=True)

    posts: Mapped[list[Post]] = relationship(secondary=post_tags, back_populates="tags")


class PostList(Base):
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_by: Mapped[User | None] = relationship()
    post_links: Mapped[list["ListPost"]] = relationship(
        back_populates="list", cascade="all, delete-orphan", order_by="ListPost.added_at.desc()"
    )


class ListPost(Base):
    __tablename__ = "list_posts"
    __table_args__ = (UniqueConstraint("list_id", "post_id"),)

    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    list: Mapped[PostList] = relationship(back_populates="post_links")
    post: Mapped[Post] = relationship(back_populates="list_links")


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(16))
    # Formularwerte als JSON, damit die Suche wieder geladen werden kann.
    params: Mapped[str] = mapped_column(Text, default="{}")
    query: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_by: Mapped[User | None] = relationship()


class Person(Base):
    """Mensch oder Organisation hinter einem oder mehreren Accounts.

    Wird beim ersten Account automatisch angelegt. Gehoeren mehrere Accounts
    derselben Person, werden sie hier von Hand zusammengefuehrt."""

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # False: Name folgt automatisch dem Anzeigenamen des Accounts.
    # True: von Hand gesetzt, wird nie mehr ueberschrieben.
    name_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    # Nur Darstellung (0.7.0): Kurzbeschreibung unter dem Namen und eigenes Foto.
    # Die archivierten Aussagen behalten ihr Original-Profilbild.
    subtitle: Mapped[str] = mapped_column(String(120), default="")
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    accounts: Mapped[list["Account"]] = relationship(back_populates="person", order_by="Account.id")

    @property
    def avatar_path(self) -> str | None:
        """Eigenes Foto, sonst das Profilbild des ersten Accounts, der eins hat."""
        if self.photo_path:
            return self.photo_path
        for acc in self.accounts:
            if acc.avatar_path:
                return acc.avatar_path
        return None


class Account(Base):
    """Ein Konto auf einer Plattform.

    stable_id bleibt bei Umbenennungen gleich (Bluesky: DID, X: User-ID). Aendert
    sich Handle, Name oder Profilbild, entsteht kein neuer Account, sondern ein
    Eintrag in account_changes. Ohne stable_id (z. B. Upload ohne Link) wird
    ueber den Handle zugeordnet, bis die ID bekannt ist."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "stable_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    stable_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handle: Mapped[str] = mapped_column(String(255), default="", index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Zuletzt bei der Plattform nachgeschlagen (Profilbild, Name).
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    person: Mapped[Person] = relationship(back_populates="accounts")
    posts: Mapped[list[Post]] = relationship(back_populates="account")
    changes: Mapped[list["AccountChange"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", order_by="AccountChange.seen_at.desc()")

    @property
    def label(self) -> str:
        return f"@{self.handle}" if self.handle else (self.display_name or "unbekannt")

    @property
    def profile_url(self) -> str:
        if self.platform == PLATFORM_BLUESKY:
            ident = self.stable_id or self.handle
            return f"https://bsky.app/profile/{ident}" if ident else ""
        if self.handle:
            return f"https://x.com/{self.handle}"
        return f"https://x.com/i/user/{self.stable_id}" if self.stable_id else ""


class AccountChange(Base):
    """Verlauf eines Accounts: alter und neuer Handle, Name oder Profilbild."""

    __tablename__ = "account_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(16))  # handle | display_name | avatar_path
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="changes")


class ImportBatch(Base):
    """Ein Massenimport: was neu angelegt, was uebersprungen wurde (und warum).
    Die neu angelegten Aussagen tragen die Kennung in posts.import_batch."""

    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    total_links: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    # JSON-Listen: [{"url", "post_id"}] schon im Archiv, ["url"] doppelt eingefuegt, ["zeile"] nicht erkannt
    existing: Mapped[str] = mapped_column(Text, default="[]")
    repeated: Mapped[str] = mapped_column(Text, default="[]")
    invalid: Mapped[str] = mapped_column(Text, default="[]")

    created_by: Mapped[User | None] = relationship()


# --------------------------------------------------------------------------
# Galerie (0.9.0): eigene Bilder, frei waehlbare Kategorien
# --------------------------------------------------------------------------

gallery_image_categories = Table(
    "gallery_image_categories",
    Base.metadata,
    Column("image_id", ForeignKey("gallery_images.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("gallery_categories.id", ondelete="CASCADE"), primary_key=True),
)


class GalleryCategory(Base):
    __tablename__ = "gallery_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    images: Mapped[list["GalleryImage"]] = relationship(secondary=gallery_image_categories, back_populates="categories")

    @property
    def tone(self) -> int:
        """Farbton (0-7) fuer den Punkt vor dem Namen - fest je Kategorie."""
        return self.id % 8


class GalleryImage(Base):
    __tablename__ = "gallery_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Relativ zum Basispfad: gallery/<jahr>/<name>.webp und .thumb.webp
    path: Mapped[str] = mapped_column(String(255))
    thumb_path: Mapped[str] = mapped_column(String(255))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Durchschnittsfarbe als Platzhalter, solange das Bild laedt
    color: Mapped[str] = mapped_column(String(7), default="#888888")
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # 0.12: Aufnahmedatum aus den Kameradaten (vor dem Entfernen gelesen), sonst leer
    taken_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    uploaded_by: Mapped[User | None] = relationship()
    categories: Mapped[list[GalleryCategory]] = relationship(
        secondary=gallery_image_categories, back_populates="images", order_by="GalleryCategory.name")

    @property
    def ratio(self) -> float:
        return round(self.width / self.height, 4) if self.height else 1.0


class PostMedia(Base):
    """Ein Bild, GIF oder Video aus einem Posting - als Datei gesichert (0.10.0).
    X liefert GIFs als stumme MP4-Schleife (kind "gif"), Bluesky-Videos kommen
    als Originaldatei vom Server des Accounts."""

    __tablename__ = "post_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(8))          # photo | gif | video
    path: Mapped[str] = mapped_column(String(255))        # relativ: media/<plattform>/<jahr>/<name>
    # Kleines Vorschaubild (WebP, max. 720 px) fuer die Archivuebersicht (0.11.0)
    thumb_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime: Mapped[str] = mapped_column(String(64), default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    alt: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    post: Mapped[Post] = relationship(back_populates="media")

    @property
    def is_video(self) -> bool:
        return self.mime.startswith("video/")


# --------------------------------------------------------------------------
# Ideen fuer neue Funktionen (0.11.0)
# --------------------------------------------------------------------------

IDEA_STATUSES = {"neu": "Neu", "geplant": "Geplant", "umgesetzt": "Umgesetzt", "abgelehnt": "Nicht geplant"}


class FeatureIdea(Base):
    __tablename__ = "feature_ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(140))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="neu", index=True)
    answer: Mapped[str] = mapped_column(Text, default="")   # Antwort/Notiz vom Admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_by: Mapped[User | None] = relationship()
    votes: Mapped[list["IdeaVote"]] = relationship(back_populates="idea", cascade="all, delete-orphan")


class IdeaVote(Base):
    """"Will ich auch" - eine Stimme pro Person und Idee, zum Priorisieren."""

    __tablename__ = "idea_votes"

    idea_id: Mapped[int] = mapped_column(ForeignKey("feature_ideas.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    idea: Mapped[FeatureIdea] = relationship(back_populates="votes")
