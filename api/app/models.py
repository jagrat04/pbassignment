import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'editor' = CRUD only. 'admin' = CRUD + publish. Enforced in app/auth.py.
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("role in ('editor','admin')", name="ck_users_role"),)


class Show(Base):
    __tablename__ = "shows"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    synopsis: Mapped[str | None] = mapped_column(Text)
    # Nullable at rest: a draft show may not have a section yet. Publishing requires one.
    section: Mapped[str | None] = mapped_column(String(64))
    # A small fixed vocabulary from reference.json, always read together with the
    # show and only ever queried by containment ("give me the 'music' shows").
    # A native array with a GIN index answers that in one index scan and saves a
    # join table that would never be queried on its own.
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default="{}"
    )
    default_language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # Deterministic ordering inside a section; ties broken by title then id at publish time.
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    seasons: Mapped[list["Season"]] = relationship(
        back_populates="show", cascade="all, delete-orphan", order_by="Season.season_number"
    )

    __table_args__ = (
        CheckConstraint("status in ('draft','published')", name="ck_shows_status"),
        # The publish job scans published shows; the viewer orders inside a section.
        Index("ix_shows_status", "status"),
        Index("ix_shows_section_sort", "section", "sort_index"),
        # Containment filter (`categories @> '{music}'`) for /catalog/search.
        Index("ix_shows_categories_gin", "categories", postgresql_using="gin"),
    )


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    show_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("shows.id", ondelete="CASCADE"), nullable=False
    )
    # Season 0 is reserved for trailers (reference.json convention) and is never
    # rendered as a normal season in the viewer.
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))

    show: Mapped[Show] = relationship(back_populates="seasons")
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="season", cascade="all, delete-orphan", order_by="Episode.episode_number"
    )

    __table_args__ = (
        UniqueConstraint("show_id", "season_number", name="uq_seasons_show_number"),
        CheckConstraint("season_number >= 0", name="ck_seasons_number_nonneg"),
        Index("ix_seasons_show", "show_id"),
    )


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    season_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False
    )
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    synopsis: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    # Episodes sharing a content_group are language variants of one another and
    # collapse into a single catalogue entry carrying a languages list.
    content_group: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    video_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    season: Mapped[Season] = relationship(back_populates="episodes")

    __table_args__ = (
        CheckConstraint("status in ('draft','published')", name="ck_episodes_status"),
        CheckConstraint(
            "duration_seconds is null or duration_seconds > 0",
            name="ck_episodes_duration_positive",
        ),
        # One row per language variant within a season slot.
        UniqueConstraint(
            "season_id", "episode_number", "language", name="uq_episodes_slot_language"
        ),
        Index("ix_episodes_season", "season_id"),
        Index("ix_episodes_status", "status"),
        Index("ix_episodes_language", "language"),
        # Partial unique: NULL content_group means "ungrouped" and must not collide
        # with other ungrouped rows, so the index is restricted to non-NULL groups.
        Index(
            "uq_episodes_group_language",
            "content_group",
            "language",
            unique=True,
            postgresql_where=text("content_group IS NOT NULL"),
        ),
    )


class Artwork(Base):
    __tablename__ = "artworks"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    # Polymorphic by (owner_type, owner_id) rather than two nullable FKs: the
    # rules and the storage path are identical for shows and episodes, and the
    # table is only ever read by owner.
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # poster|banner|thumbnail
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("owner_type in ('show','episode')", name="ck_artworks_owner_type"),
        CheckConstraint("kind in ('poster','banner','thumbnail')", name="ck_artworks_kind"),
        # One current image per slot -- re-uploading replaces the row.
        UniqueConstraint("owner_type", "owner_id", "kind", name="uq_artworks_slot"),
        Index("ix_artworks_owner", "owner_type", "owner_id"),
    )


class PublishRun(Base):
    __tablename__ = "publish_runs"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Denormalised so run history survives the user row being deleted.
    actor_email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    # Immutable versioned object for this run. The live pointer is swapped to it
    # only after the bytes are fully written and fsynced.
    catalog_key: Mapped[str | None] = mapped_column(String(512))
    catalog_checksum: Mapped[str | None] = mapped_column(String(64))
    # True for the run currently served at /catalog. At most one at a time.
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("status in ('running','success','failed')", name="ck_publish_runs_status"),
        Index("ix_publish_runs_started", "started_at"),
        # At most one current run, enforced by the database rather than by hope.
        Index(
            "uq_publish_runs_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class ImportReject(Base):
    """Rows the bulk importer could not accept.

    The seed file is real content-team data and contains conflicts the database
    is right to refuse. Dropping those rows silently would mean an editor
    wondering for a week where an episode went, so every refusal is kept here
    with the payload and a plain-language reason, and surfaced in the
    validation report under "Import conflicts".
    """

    __tablename__ = "import_rejects"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "seed_shows.json"
    source_ref: Mapped[str | None] = mapped_column(String(128))  # e.g. "ep_9001"
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONType)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_import_rejects_resolved", "resolved"),)


class CatalogEntry(Base):
    """The published catalogue, flattened into rows so search is a real query.

    Written by the publish job inside the same transaction that swaps the live
    pointer, and only ever read with `run_id = <current run>`. That is what
    keeps /catalog/search honest: it can only return things that are actually
    in the catalogue a viewer is being served, never a row someone flipped to
    "published" in the CMS five minutes ago but hasn't published yet.

    Rows for older runs are kept so a rollback is a pointer move, not a rebuild.
    """

    __tablename__ = "catalog_entries"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publish_runs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # show|episode
    show_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    show_title: Mapped[str] = mapped_column(String(255), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    episode_title: Mapped[str | None] = mapped_column(String(255))
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Everything the viewer needs to render a result, so a search never joins.
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    # Title + episode title + categories, concatenated once at publish time.
    search_text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("kind in ('show','episode')", name="ck_catalog_entries_kind"),
        # Every query starts by pinning the run, so it leads every index.
        Index("ix_catalog_entries_run", "run_id", "kind"),
        Index("ix_catalog_entries_run_section", "run_id", "section", "sort_index"),
        Index("ix_catalog_entries_run_slug", "run_id", "show_slug"),
        # `categories @> '{music}'` and `languages @> '{hi}'` -- the two filters.
        Index("ix_catalog_entries_categories", "categories", postgresql_using="gin"),
        Index("ix_catalog_entries_languages", "languages", postgresql_using="gin"),
        # Substring search (ILIKE '%kite%') without a sequential scan. Created
        # with pg_trgm in the migration.
        Index(
            "ix_catalog_entries_search_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )
