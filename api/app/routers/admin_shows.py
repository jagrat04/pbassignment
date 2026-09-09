"""CMS CRUD. Requires a signed-in editor or admin on every route."""

import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import require_editor
from app.db import get_db
from app.models import Artwork, Episode, Season, Show, User
from app.reference import TRAILER_SEASON, get_reference
from app.schemas import (
    EpisodeCreate,
    EpisodeUpdate,
    SeasonCreate,
    ShowCreate,
    ShowUpdate,
)
from app.services.validation import (
    REQUIRED_EPISODE_ARTWORK,
    REQUIRED_SHOW_ARTWORK,
)

router = APIRouter(prefix="/admin", tags=["admin:content"], dependencies=[Depends(require_editor)])


# --------------------------------------------------------------------- helpers


def _conflict(detail: dict) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _translate_integrity_error(exc: IntegrityError) -> HTTPException:
    """Turn a Postgres constraint name into something an editor can act on.

    The constraints are the real enforcement; this only decides how the failure
    reads. Anything unrecognised falls through as a generic 409 rather than a
    500, because a constraint firing is the user's data being wrong, not ours.
    """
    text = str(getattr(exc, "orig", exc))
    if "uq_episodes_group_language" in text:
        return _conflict(
            {
                "error": "duplicate_language_variant",
                "problem": "Another episode already covers this language for this content group.",
                "fix": (
                    "Each content group can hold one episode per language. Either change the "
                    "language, or open the existing episode in this group and edit that one."
                ),
                "field": "content_group",
            }
        )
    if "uq_episodes_slot_language" in text:
        return _conflict(
            {
                "error": "duplicate_episode_slot",
                "problem": "This season already has an episode with that number in that language.",
                "fix": "Give it the next free episode number, or edit the existing episode.",
                "field": "episode_number",
            }
        )
    if "uq_seasons_show_number" in text:
        return _conflict(
            {
                "error": "duplicate_season",
                "problem": "That season already exists for this show.",
                "fix": "Add episodes to the existing season instead.",
                "field": "season_number",
            }
        )
    if "shows_slug_key" in text or "uq_shows_slug" in text:
        return _conflict(
            {
                "error": "duplicate_slug",
                "problem": "Another show already uses that URL slug.",
                "fix": "Pick a different slug — it has to be unique across all shows.",
                "field": "slug",
            }
        )
    if "ck_episodes_duration_positive" in text:
        return _conflict(
            {
                "error": "invalid_duration",
                "problem": "The run time has to be greater than zero.",
                "fix": "Enter the episode's length in minutes and seconds.",
                "field": "duration_seconds",
            }
        )
    return _conflict(
        {
            "error": "constraint_violation",
            "problem": "That change conflicts with something already saved.",
            "fix": "Reload the page to see the current state, then try again.",
        }
    )


def _artwork_for(db: Session, owner_type: str, ids: list[uuid.UUID]) -> dict[str, list[Artwork]]:
    if not ids:
        return {}
    rows = (
        db.query(Artwork)
        .filter(Artwork.owner_type == owner_type, Artwork.owner_id.in_(ids))
        .all()
    )
    out: dict[str, list[Artwork]] = {}
    for a in rows:
        out.setdefault(str(a.owner_id), []).append(a)
    return out


def _show_blockers(show: Show, art_kinds: set[str]) -> list[str]:
    out = []
    if not show.section:
        out.append("No section chosen")
    for kind in REQUIRED_SHOW_ARTWORK:
        if kind not in art_kinds:
            out.append(f"No {kind} image")
    return out


def _episode_blockers(ep: Episode, art_kinds: set[str]) -> list[str]:
    out = []
    if not ep.duration_seconds:
        out.append("No run time")
    for kind in REQUIRED_EPISODE_ARTWORK:
        if kind not in art_kinds:
            out.append(f"No {kind} image")
    return out


def _get_show(db: Session, show_id: uuid.UUID) -> Show:
    show = db.get(Show, show_id)
    if show is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "problem": "That show no longer exists.",
                    "fix": "It may have been deleted. Go back to the show list."},
        )
    return show


# ----------------------------------------------------------------------- shows


@router.get("/shows")
def list_shows(
    q: str | None = Query(None, description="Matches show title, slug and episode title"),
    section: str | None = None,
    status: str | None = Query(None, pattern="^(draft|published)$"),
    language: str | None = None,
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Show)
    conditions = []
    if section:
        conditions.append(Show.section == section)
    if status:
        conditions.append(Show.status == status)
    if category:
        from sqlalchemy.dialects.postgresql import array

        conditions.append(Show.categories.contains(array([category], type_=String)))
    if language:
        # "Shows that have at least one episode in this language."
        conditions.append(
            Show.id.in_(
                select(Season.show_id)
                .join(Episode, Episode.season_id == Season.id)
                .where(Episode.language == language)
            )
        )
    if q and q.strip():
        term = f"%{q.strip()}%"
        conditions.append(
            or_(
                Show.title.ilike(term),
                Show.slug.ilike(term),
                Show.id.in_(
                    select(Season.show_id)
                    .join(Episode, Episode.season_id == Season.id)
                    .where(Episode.title.ilike(term))
                ),
            )
        )
    if conditions:
        stmt = stmt.where(*conditions)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    rows = (
        db.execute(
            stmt.order_by(Show.sort_index, Show.title)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .scalars()
        .all()
    )

    art = _artwork_for(db, "show", [s.id for s in rows])
    counts = dict(
        db.execute(
            select(Season.show_id, func.count(Episode.id))
            .join(Episode, Episode.season_id == Season.id)
            .where(Season.show_id.in_([s.id for s in rows] or [uuid.uuid4()]))
            .group_by(Season.show_id)
        ).all()
    )
    langs: dict[uuid.UUID, list[str]] = {}
    for show_id, lang in db.execute(
        select(Season.show_id, Episode.language)
        .join(Episode, Episode.season_id == Season.id)
        .where(Season.show_id.in_([s.id for s in rows] or [uuid.uuid4()]))
        .distinct()
    ).all():
        langs.setdefault(show_id, []).append(lang)

    items = []
    for s in rows:
        arts = art.get(str(s.id), [])
        items.append(
            {
                "id": str(s.id),
                "slug": s.slug,
                "title": s.title,
                "synopsis": s.synopsis,
                "section": s.section,
                "categories": s.categories or [],
                "default_language": s.default_language,
                "status": s.status,
                "sort_index": s.sort_index,
                "updated_at": s.updated_at,
                "episode_count": counts.get(s.id, 0),
                "languages": sorted(langs.get(s.id, [])),
                "artwork": [
                    {"kind": a.kind, "url": a.url, "width": a.width, "height": a.height,
                     "bytes": a.bytes, "original_filename": a.original_filename}
                    for a in arts
                ],
                "blocking_issues": _show_blockers(s, {a.kind for a in arts})
                if s.status == "published"
                else [],
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


@router.get("/shows/{show_id}", response_model=None)
def get_show_detail(show_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    show = db.get(
        Show,
        show_id,
        options=[selectinload(Show.seasons).selectinload(Season.episodes)],
    )
    if show is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "problem": "That show no longer exists.",
                    "fix": "Go back to the show list."},
        )

    show_art = _artwork_for(db, "show", [show.id]).get(str(show.id), [])
    ep_ids = [e.id for s in show.seasons for e in s.episodes]
    ep_art = _artwork_for(db, "episode", ep_ids)

    seasons = []
    for season in sorted(show.seasons, key=lambda s: s.season_number):
        episodes = []
        for ep in sorted(season.episodes, key=lambda e: (e.episode_number, e.language)):
            arts = ep_art.get(str(ep.id), [])
            episodes.append(
                {
                    "id": str(ep.id),
                    "season_id": str(ep.season_id),
                    "episode_number": ep.episode_number,
                    "title": ep.title,
                    "synopsis": ep.synopsis,
                    "duration_seconds": ep.duration_seconds,
                    "language": ep.language,
                    "content_group": ep.content_group,
                    "status": ep.status,
                    "video_url": ep.video_url,
                    "artwork": [
                        {"kind": a.kind, "url": a.url, "width": a.width, "height": a.height,
                         "bytes": a.bytes, "original_filename": a.original_filename}
                        for a in arts
                    ],
                    "blocking_issues": _episode_blockers(ep, {a.kind for a in arts})
                    if ep.status == "published"
                    else [],
                }
            )
        seasons.append(
            {
                "id": str(season.id),
                "season_number": season.season_number,
                "title": season.title,
                "is_trailer_season": season.season_number == TRAILER_SEASON,
                "episodes": episodes,
            }
        )

    return {
        "id": str(show.id),
        "slug": show.slug,
        "title": show.title,
        "synopsis": show.synopsis,
        "section": show.section,
        "categories": show.categories or [],
        "default_language": show.default_language,
        "status": show.status,
        "sort_index": show.sort_index,
        "updated_at": show.updated_at,
        "artwork": [
            {"kind": a.kind, "url": a.url, "width": a.width, "height": a.height,
             "bytes": a.bytes, "original_filename": a.original_filename}
            for a in show_art
        ],
        "episode_count": len(ep_ids),
        "languages": sorted({e.language for s in show.seasons for e in s.episodes}),
        "seasons": seasons,
        "blocking_issues": _show_blockers(show, {a.kind for a in show_art})
        if show.status == "published"
        else [],
    }


@router.post("/shows", status_code=201)
def create_show(payload: ShowCreate, db: Session = Depends(get_db)) -> dict:
    show = Show(**payload.model_dump())
    db.add(show)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _translate_integrity_error(exc) from exc
    db.refresh(show)
    return {"id": str(show.id), "slug": show.slug}


@router.patch("/shows/{show_id}")
def update_show(show_id: uuid.UUID, payload: ShowUpdate, db: Session = Depends(get_db)) -> dict:
    show = _get_show(db, show_id)
    data = payload.model_dump(exclude_unset=True)

    # Re-check the cross-field rule against the *resulting* row, not the patch.
    section = data.get("section", show.section)
    status = data.get("status", show.status)
    if status == "published" and not section:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "section_required",
                "problem": "A published show needs a section.",
                "fix": "Choose a section (" + ", ".join(get_reference().sections)
                + ") before publishing this show.",
                "field": "section",
            },
        )

    for k, v in data.items():
        setattr(show, k, v)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _translate_integrity_error(exc) from exc
    return {"id": str(show.id), "status": show.status}


@router.delete("/shows/{show_id}", status_code=204)
def delete_show(show_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    show = _get_show(db, show_id)
    db.delete(show)
    db.commit()


# --------------------------------------------------------------------- seasons


@router.post("/shows/{show_id}/seasons", status_code=201)
def create_season(
    show_id: uuid.UUID, payload: SeasonCreate, db: Session = Depends(get_db)
) -> dict:
    _get_show(db, show_id)
    season = Season(show_id=show_id, **payload.model_dump())
    db.add(season)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _translate_integrity_error(exc) from exc
    db.refresh(season)
    return {
        "id": str(season.id),
        "season_number": season.season_number,
        "is_trailer_season": season.season_number == TRAILER_SEASON,
    }


# -------------------------------------------------------------------- episodes


@router.post("/episodes", status_code=201)
def create_episode(payload: EpisodeCreate, db: Session = Depends(get_db)) -> dict:
    season = db.get(Season, payload.season_id)
    if season is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "problem": "That season no longer exists.",
                    "fix": "Reload the show and pick a season again."},
        )
    episode = Episode(**payload.model_dump())
    db.add(episode)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _translate_integrity_error(exc) from exc
    db.refresh(episode)
    return {"id": str(episode.id)}


@router.patch("/episodes/{episode_id}")
def update_episode(
    episode_id: uuid.UUID, payload: EpisodeUpdate, db: Session = Depends(get_db)
) -> dict:
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "problem": "That episode no longer exists.",
                    "fix": "Go back to the show and reload."},
        )
    data = payload.model_dump(exclude_unset=True)

    status = data.get("status", ep.status)
    duration = data.get("duration_seconds", ep.duration_seconds)
    if status == "published":
        problems = []
        if not duration:
            problems.append("it has no run time")
        have = {
            a.kind
            for a in db.query(Artwork).filter(
                Artwork.owner_type == "episode", Artwork.owner_id == ep.id
            )
        }
        missing = [k for k in REQUIRED_EPISODE_ARTWORK if k not in have]
        if missing:
            problems.append("it has no " + " or ".join(missing) + " image")
        if problems:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "episode_not_publishable",
                    "problem": "This episode can't be published because "
                    + " and ".join(problems)
                    + ".",
                    "fix": "Fill those in first, then set it to published.",
                },
            )

    for k, v in data.items():
        setattr(ep, k, v)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _translate_integrity_error(exc) from exc
    return {"id": str(ep.id), "status": ep.status}


@router.delete("/episodes/{episode_id}", status_code=204)
def delete_episode(episode_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    ep = db.get(Episode, episode_id)
    if ep is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    db.delete(ep)
    db.commit()


@router.get("/episodes/{episode_id}/group")
def episode_group(episode_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """The other language variants of this episode.

    The CMS shows this next to the content_group field so an editor can see, at
    the moment they type it, that they are about to join an existing group.
    """
    ep = db.get(Episode, episode_id)
    if ep is None or not ep.content_group:
        return {"content_group": None, "variants": []}
    siblings = (
        db.query(Episode).filter(Episode.content_group == ep.content_group).all()
    )
    return {
        "content_group": ep.content_group,
        "variants": [
            {
                "id": str(s.id),
                "language": s.language,
                "title": s.title,
                "status": s.status,
                "is_self": s.id == ep.id,
            }
            for s in sorted(siblings, key=lambda s: s.language)
        ],
    }


_ = User  # re-exported for type checkers reading the dependency chain
