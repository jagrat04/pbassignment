"""Request/response models.

Field validators here are the *first* line of defence and the one that produces
a readable message; the database constraints in models.py are the line that
actually holds. Client-side validation in the CMS is a third, purely cosmetic
layer -- it never decides anything.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reference import TRAILER_SEASON, get_reference

Status = Literal["draft", "published"]


def _check_section(v: str | None) -> str | None:
    if v is None:
        return v
    allowed = get_reference().sections
    if v not in allowed:
        raise ValueError(f"“{v}” isn't a section. Choose one of: {', '.join(allowed)}.")
    return v


def _check_categories(v: list[str]) -> list[str]:
    allowed = set(get_reference().categories)
    unknown = [c for c in v if c not in allowed]
    if unknown:
        raise ValueError(
            f"{', '.join(unknown)} " + ("aren't" if len(unknown) > 1 else "isn't")
            + " on the approved category list. Approved: "
            + ", ".join(sorted(allowed))
            + "."
        )
    # De-duplicate but keep the editor's order.
    return list(dict.fromkeys(v))


def _check_language(v: str) -> str:
    allowed = get_reference().languages
    if v not in allowed:
        raise ValueError(f"“{v}” isn't a supported language. Supported: {', '.join(allowed)}.")
    return v


# --------------------------------------------------------------------------- auth


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    name: str
    role: str


# --------------------------------------------------------------------------- shows


class ShowCreate(BaseModel):
    slug: Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
    title: Annotated[str, Field(min_length=1, max_length=255)]
    synopsis: str | None = None
    section: str | None = None
    categories: list[str] = Field(default_factory=list)
    default_language: str | None = None
    status: Status = "draft"
    sort_index: int = 0

    _v_section = field_validator("section")(_check_section)
    _v_categories = field_validator("categories")(_check_categories)

    @field_validator("default_language")
    @classmethod
    def _v_lang(cls, v: str | None) -> str | None:
        return None if v is None else _check_language(v)

    @model_validator(mode="after")
    def _published_needs_section(self):
        # The rule from the brief, enforced on the way in rather than only at
        # publish time -- an editor finds out now, not on Friday afternoon.
        if self.status == "published" and not self.section:
            raise ValueError(
                "A published show needs a section — that's what decides which row it "
                "appears in on the home screen. Pick one, or save this as a draft."
            )
        return self


class ShowUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    synopsis: str | None = None
    section: str | None = None
    categories: list[str] | None = None
    default_language: str | None = None
    status: Status | None = None
    sort_index: int | None = None

    _v_section = field_validator("section")(_check_section)

    @field_validator("categories")
    @classmethod
    def _v_categories(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_categories(v)

    @field_validator("default_language")
    @classmethod
    def _v_lang(cls, v: str | None) -> str | None:
        return None if v is None else _check_language(v)


class ArtworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: str
    url: str
    width: int
    height: int
    bytes: int
    original_filename: str | None = None


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    season_id: uuid.UUID
    episode_number: int
    title: str
    synopsis: str | None
    duration_seconds: int | None
    language: str
    content_group: str | None
    status: str
    video_url: str | None
    artwork: list[ArtworkOut] = Field(default_factory=list)
    # Filled in by the router: what is stopping this episode from going out.
    blocking_issues: list[str] = Field(default_factory=list)


class SeasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    season_number: int
    title: str | None
    is_trailer_season: bool = False
    episodes: list[EpisodeOut] = Field(default_factory=list)


class ShowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    title: str
    synopsis: str | None
    section: str | None
    categories: list[str]
    default_language: str | None
    status: str
    sort_index: int
    updated_at: datetime
    artwork: list[ArtworkOut] = Field(default_factory=list)
    episode_count: int = 0
    languages: list[str] = Field(default_factory=list)


class ShowDetailOut(ShowOut):
    seasons: list[SeasonOut] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int


# --------------------------------------------------------------------------- seasons


class SeasonCreate(BaseModel):
    season_number: Annotated[int, Field(ge=0)]
    title: str | None = None

    @model_validator(mode="after")
    def _label_trailers(self):
        if self.season_number == TRAILER_SEASON and not self.title:
            self.title = "Trailers"
        return self


# --------------------------------------------------------------------------- episodes


class EpisodeCreate(BaseModel):
    season_id: uuid.UUID
    episode_number: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=255)]
    synopsis: str | None = None
    duration_seconds: Annotated[int, Field(gt=0)] | None = None
    language: str
    content_group: str | None = None
    status: Status = "draft"
    video_url: str | None = None

    _v_lang = field_validator("language")(_check_language)

    @model_validator(mode="after")
    def _published_needs_duration(self):
        if self.status == "published" and not self.duration_seconds:
            raise ValueError(
                "A published episode needs a run time. Add the duration, or save it as a draft."
            )
        return self


class EpisodeUpdate(BaseModel):
    episode_number: Annotated[int, Field(ge=1)] | None = None
    title: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    synopsis: str | None = None
    duration_seconds: Annotated[int, Field(gt=0)] | None = None
    language: str | None = None
    content_group: str | None = None
    status: Status | None = None
    video_url: str | None = None

    @field_validator("language")
    @classmethod
    def _v_lang(cls, v: str | None) -> str | None:
        return None if v is None else _check_language(v)


# --------------------------------------------------------------------------- publish


class PublishRequest(BaseModel):
    # Publishing with known-blocking issues is allowed but never accidental: it
    # takes an explicit flag and a reason, and both land in the run history.
    force: bool = False
    force_reason: str | None = None

    @model_validator(mode="after")
    def _force_needs_reason(self):
        if self.force and not (self.force_reason or "").strip():
            raise ValueError(
                "Publishing past the blocking issues needs a short reason — it goes in "
                "the run history so the next person knows why."
            )
        return self


class PublishRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_email: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict | None
    error: str | None
    catalog_key: str | None
    catalog_checksum: str | None
    is_current: bool
