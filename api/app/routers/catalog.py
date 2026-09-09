"""The public, viewer-facing API.

Nothing here requires a token and nothing here reads a draft. The viewer app
talks to exactly these three routes and never to an /admin one -- which is
enforced by there being no admin route that answers without a bearer token.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import String, and_, func, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CatalogEntry
from app.services.publish import current_run
from app.storage import ObjectNotFound, Storage, get_storage

router = APIRouter(prefix="/catalog", tags=["catalog"])

# The published catalogue is immutable per run, so it is safe to hold in memory
# keyed by run id. One small dict, replaced wholesale when a publish lands.
_cache: dict[str, bytes] = {}


def _current_bytes(db: Session, storage: Storage) -> tuple[str, bytes]:
    run = current_run(db)
    if run is None or not run.catalog_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "no_catalog",
                "message": "Nothing has been published yet.",
            },
        )
    key = str(run.id)
    if key not in _cache:
        try:
            _cache.clear()  # only ever one live version worth keeping
            _cache[key] = storage.get(run.catalog_key)
        except ObjectNotFound:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "catalog_missing",
                    "message": "The published catalogue file is missing from storage.",
                },
            ) from None
    return run.catalog_checksum or key, _cache[key]


@router.get("")
def get_catalog(
    request: Request,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Serve the published catalogue document.

    Served straight from storage bytes with the publish checksum as the ETag, so
    a returning viewer gets a 304 and no JSON is parsed on either side.
    """
    checksum, body = _current_bytes(db, storage)
    etag = f'W/"{checksum}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "ETag": etag,
            # Short max-age with revalidation: a publish should be visible in a
            # minute, and the ETag makes the revalidation nearly free.
            "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
        },
    )


@router.get("/search")
def search_catalog(
    q: str | None = Query(None, description="Matches show title, episode title and category"),
    category: str | None = None,
    language: str | None = None,
    section: str | None = None,
    kind: str | None = Query(None, pattern="^(show|episode)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Search the *published* catalogue.

    Runs against catalog_entries, which the publish job writes in the same
    transaction that moves the live pointer. That is deliberate: searching the
    shows table directly would happily return an episode somebody flipped to
    "published" in the CMS but hasn't published yet, and the viewer would get a
    result that 404s.
    """
    run = current_run(db)
    if run is None:
        return {"results": [], "total": 0, "limit": limit, "offset": offset, "query": q}

    conditions = [CatalogEntry.run_id == run.id]
    if section:
        conditions.append(CatalogEntry.section == section)
    if kind:
        conditions.append(CatalogEntry.kind == kind)
    if category:
        # Array containment, answered by the GIN index.
        conditions.append(CatalogEntry.categories.contains(array([category], type_=String)))
    if language:
        conditions.append(CatalogEntry.languages.contains(array([language], type_=String)))
    if q and q.strip():
        term = q.strip()
        # ILIKE '%term%' over the denormalised search_text, index-backed by
        # pg_trgm. Substring rather than word matching, because editors and
        # children both search for "kite", not "kites AND lost".
        conditions.append(CatalogEntry.search_text.ilike(f"%{term}%"))

    where = and_(*conditions)
    total = db.execute(select(func.count()).select_from(CatalogEntry).where(where)).scalar_one()

    # Shows before episodes for the same relevance, then a title-prefix boost,
    # then the editor's ordering. Stable across identical queries.
    prefix_boost = (
        func.coalesce(CatalogEntry.episode_title, CatalogEntry.show_title).ilike(f"{q.strip()}%")
        if q and q.strip()
        else None
    )
    order = [
        CatalogEntry.kind.desc(),  # 'show' > 'episode' alphabetically reversed
    ]
    if prefix_boost is not None:
        order.insert(0, prefix_boost.desc())
    order += [CatalogEntry.sort_index, CatalogEntry.show_title, CatalogEntry.episode_number]

    rows = db.execute(
        select(CatalogEntry).where(where).order_by(*order).limit(limit).offset(offset)
    ).scalars().all()

    return {
        "query": q,
        "filters": {
            "category": category,
            "language": language,
            "section": section,
            "kind": kind,
        },
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [r.payload for r in rows],
    }


@router.get("/shows/{slug}")
def get_show(slug: str, db: Session = Depends(get_db), storage: Storage = Depends(get_storage)):
    """One show's detail page, read out of the same published document."""
    _, body = _current_bytes(db, storage)
    catalog = json.loads(body)
    for show in catalog.get("shows", []):
        if show["slug"] == slug:
            return show
    raise HTTPException(
        status_code=404,
        detail={"error": "not_found", "message": f"No published show with the slug “{slug}”."},
    )
