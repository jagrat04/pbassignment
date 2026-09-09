"""Turn the database into the catalogue document the viewer reads.

Pure-ish: it takes a session and returns a dict plus the flattened search rows.
No storage, no transactions, no clock beyond the timestamp it is handed -- which
is what makes it testable and what makes `publish` able to run it twice (once
for a dry-run diff, once for real) without side effects.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from app.models import Artwork, Episode, Season, Show
from app.reference import TRAILER_SEASON, get_reference

SCHEMA_VERSION = 1


@dataclass
class BuildResult:
    catalog: dict
    search_rows: list[dict]
    counts: dict
    # Episodes/shows deliberately left out, with the reason. Recorded on the run
    # so "where did my episode go?" has an answer in the run history.
    exclusions: list[dict] = field(default_factory=list)


def canonical_json(payload: dict) -> bytes:
    """Byte-identical output for identical content.

    sort_keys makes the checksum stable across Python versions and dict
    insertion order, which is what lets us detect a no-op publish.
    """
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def checksum_of(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _artwork_map(db: Session) -> dict[tuple[str, str], dict[str, dict]]:
    out: dict[tuple[str, str], dict[str, dict]] = {}
    for a in db.query(Artwork).all():
        out.setdefault((a.owner_type, str(a.owner_id)), {})[a.kind] = {
            "url": a.url,
            "width": a.width,
            "height": a.height,
        }
    return out


def build_catalog(
    db: Session,
    *,
    generated_at: datetime,
    run_id: str,
    excluded_show_ids: set[str] | None = None,
    excluded_episode_ids: set[str] | None = None,
) -> BuildResult:
    ref = get_reference()
    art = _artwork_map(db)
    excluded_show_ids = excluded_show_ids or set()
    excluded_episode_ids = excluded_episode_ids or set()
    exclusions: list[dict] = []

    # Language precedence comes from reference.json order, so "which variant is
    # the primary one" is a content decision, not an accident of row ordering.
    lang_rank = {code: i for i, code in enumerate(ref.languages)}

    shows = (
        db.query(Show)
        .filter(Show.status == "published")
        .options(selectinload(Show.seasons).selectinload(Season.episodes))
        .all()
    )

    built_shows: list[dict] = []
    search_rows: list[dict] = []
    collapsed_variants = 0

    for show in shows:
        sid = str(show.id)
        if sid in excluded_show_ids:
            exclusions.append(
                {"type": "show", "id": sid, "title": show.title, "reason": "failed validation"}
            )
            continue
        if not show.section or show.section not in ref.sections:
            exclusions.append(
                {
                    "type": "show",
                    "id": sid,
                    "title": show.title,
                    "reason": f"section {show.section!r} is not a known section",
                }
            )
            continue

        seasons_out: list[dict] = []
        trailers_out: list[dict] = []
        show_languages: set[str] = set()
        episode_count = 0

        for season in sorted(show.seasons, key=lambda s: s.season_number):
            entries, collapsed, skipped = _collapse_season(
                season, show, art, lang_rank, excluded_episode_ids
            )
            collapsed_variants += collapsed
            exclusions.extend(skipped)
            if not entries:
                continue
            for e in entries:
                show_languages.update(e["languages"])
            episode_count += len(entries)

            if season.season_number == TRAILER_SEASON:
                # Season 0 is trailers. It is carried on the show as `trailers`
                # and never appears in `seasons`, so no viewer surface can
                # accidentally render it as "Season 0".
                trailers_out.extend(entries)
            else:
                seasons_out.append(
                    {
                        "season_number": season.season_number,
                        "title": season.title or f"Season {season.season_number}",
                        "episodes": entries,
                    }
                )

        if episode_count == 0:
            exclusions.append(
                {
                    "type": "show",
                    "id": sid,
                    "title": show.title,
                    "reason": "no publishable episodes",
                }
            )
            continue

        show_art = art.get(("show", sid), {})
        show_doc = {
            "id": sid,
            "slug": show.slug,
            "title": show.title,
            "synopsis": show.synopsis,
            "section": show.section,
            "categories": sorted(show.categories or []),
            "languages": sorted(show_languages, key=lambda c: (lang_rank.get(c, 99), c)),
            "artwork": {
                "poster": show_art.get("poster"),
                "banner": show_art.get("banner"),
            },
            "episode_count": episode_count,
            "seasons": seasons_out,
            "trailers": trailers_out,
            "sort_index": show.sort_index,
        }
        built_shows.append(show_doc)

        search_rows.append(
            {
                "kind": "show",
                "show_slug": show.slug,
                "show_title": show.title,
                "section": show.section,
                "categories": sorted(show.categories or []),
                "languages": show_doc["languages"],
                "episode_title": None,
                "season_number": None,
                "episode_number": None,
                "sort_index": show.sort_index,
                "payload": _show_card(show_doc),
                "search_text": " ".join(
                    filter(None, [show.title, show.synopsis or "", *sorted(show.categories or [])])
                ),
            }
        )
        for season in show_doc["seasons"] + [
            {"season_number": TRAILER_SEASON, "episodes": show_doc["trailers"]}
        ]:
            for ep in season["episodes"]:
                search_rows.append(
                    {
                        "kind": "episode",
                        "show_slug": show.slug,
                        "show_title": show.title,
                        "section": show.section,
                        "categories": sorted(show.categories or []),
                        "languages": ep["languages"],
                        "episode_title": ep["title"],
                        "season_number": season["season_number"],
                        "episode_number": ep["episode_number"],
                        "sort_index": show.sort_index,
                        "payload": _episode_card(show_doc, season["season_number"], ep),
                        "search_text": " ".join(
                            filter(
                                None,
                                [
                                    ep["title"],
                                    show.title,
                                    ep.get("synopsis") or "",
                                    *sorted(show.categories or []),
                                ],
                            )
                        ),
                    }
                )

    # Deterministic ordering: explicit sort_index first (an editor's choice),
    # then title, then slug as an absolute tie-break so two shows with the same
    # name never swap places between runs.
    built_shows.sort(key=lambda s: (s["sort_index"], s["title"].lower(), s["slug"]))

    sections_out = []
    for section in ref.sections:  # reference.json order is the row order on screen
        slugs = [s["slug"] for s in built_shows if s["section"] == section]
        if slugs:
            sections_out.append(
                {"key": section, "title": section.replace("-", " ").title(), "show_slugs": slugs}
            )

    hero = _pick_hero(built_shows, ref.sections)

    catalog = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at.isoformat(),
        "reference": {
            "sections": list(ref.sections),
            "categories": list(ref.categories),
            "languages": list(ref.languages),
        },
        "hero": hero,
        "sections": sections_out,
        "shows": built_shows,
    }

    counts = {
        "shows": len(built_shows),
        "sections": len(sections_out),
        "episodes": sum(s["episode_count"] for s in built_shows),
        "trailers": sum(len(s["trailers"]) for s in built_shows),
        "language_variants_collapsed": collapsed_variants,
        "excluded": len(exclusions),
        "search_rows": len(search_rows),
    }
    return BuildResult(
        catalog=catalog, search_rows=search_rows, counts=counts, exclusions=exclusions
    )


def _collapse_season(
    season: Season,
    show: Show,
    art: dict,
    lang_rank: dict[str, int],
    excluded_episode_ids: set[str],
) -> tuple[list[dict], int, list[dict]]:
    """Collapse language variants within one season into single entries."""
    groups: dict[str, list[Episode]] = {}
    skipped: list[dict] = []

    for ep in season.episodes:
        if ep.status != "published":
            continue
        if str(ep.id) in excluded_episode_ids:
            skipped.append(
                {
                    "type": "episode",
                    "id": str(ep.id),
                    "title": f"{show.title} S{season.season_number}E{ep.episode_number} "
                    f"{ep.title} ({ep.language})",
                    "reason": "failed validation",
                }
            )
            continue
        # An episode with no content_group is its own group of one. Using the
        # episode id as the key keeps ungrouped episodes from colliding.
        key = ep.content_group or f"__ungrouped__{ep.id}"
        groups.setdefault(key, []).append(ep)

    entries: list[dict] = []
    collapsed = 0
    for variants in groups.values():
        variants.sort(key=lambda e: (lang_rank.get(e.language, 99), e.language, str(e.id)))
        primary = variants[0]
        collapsed += len(variants) - 1

        ep_art = art.get(("episode", str(primary.id)), {})
        if "thumbnail" not in ep_art:
            # Fall back to any variant that does have one before giving up --
            # the same episode in Hindi carries the same picture.
            for v in variants[1:]:
                other = art.get(("episode", str(v.id)), {})
                if "thumbnail" in other:
                    ep_art = other
                    break

        entries.append(
            {
                "id": str(primary.id),
                "content_group": primary.content_group,
                "episode_number": primary.episode_number,
                "title": primary.title,
                "synopsis": primary.synopsis,
                "duration_seconds": primary.duration_seconds,
                "is_trailer": season.season_number == TRAILER_SEASON,
                "artwork": {"thumbnail": ep_art.get("thumbnail")},
                "languages": [v.language for v in variants],
                # Per-language detail, so the viewer can offer "Watch in Hindi"
                # without a second request.
                "variants": [
                    {
                        "episode_id": str(v.id),
                        "language": v.language,
                        "title": v.title,
                        "duration_seconds": v.duration_seconds,
                        "video_url": v.video_url,
                    }
                    for v in variants
                ],
            }
        )

    entries.sort(key=lambda e: (e["episode_number"], e["id"]))
    return entries, collapsed, skipped


def _pick_hero(shows: list[dict], sections: tuple[str, ...]) -> dict | None:
    """The banner at the top of the home screen.

    First show of the first section that has one, preferring a show that
    actually has a banner image. Deterministic, and it degrades to "no hero"
    rather than to a broken image.
    """
    for section in sections:
        for s in shows:
            if s["section"] == section and s["artwork"].get("banner"):
                return {
                    "slug": s["slug"],
                    "title": s["title"],
                    "synopsis": s["synopsis"],
                    "banner": s["artwork"]["banner"],
                    "categories": s["categories"],
                    "languages": s["languages"],
                }
    return None


def _show_card(show_doc: dict) -> dict:
    """Trimmed show shape for search results and browse rows."""
    return {
        "kind": "show",
        "slug": show_doc["slug"],
        "title": show_doc["title"],
        "synopsis": show_doc["synopsis"],
        "section": show_doc["section"],
        "categories": show_doc["categories"],
        "languages": show_doc["languages"],
        "poster": show_doc["artwork"].get("poster"),
        "banner": show_doc["artwork"].get("banner"),
        "episode_count": show_doc["episode_count"],
    }


def _episode_card(show_doc: dict, season_number: int, ep: dict) -> dict:
    return {
        "kind": "episode",
        "slug": show_doc["slug"],
        "show_title": show_doc["title"],
        "season_number": season_number,
        "episode_number": ep["episode_number"],
        "title": ep["title"],
        "synopsis": ep["synopsis"],
        "duration_seconds": ep["duration_seconds"],
        "languages": ep["languages"],
        "thumbnail": ep["artwork"].get("thumbnail"),
        "is_trailer": ep["is_trailer"],
        "categories": show_doc["categories"],
    }
