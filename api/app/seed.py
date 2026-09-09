"""Import seed_shows.json into the database, defects and all.

This deliberately behaves like a bulk import an editor might run, not like a
fixture loader: it goes through the same constraints as the API, and anything
the database refuses is recorded in `import_rejects` with a plain-language
reason instead of being quietly dropped. Losing an episode silently is the
failure that costs a content team a week.

Run: python -m app.seed
"""

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import Artwork, Episode, ImportReject, Season, Show, User
from app.reference import TRAILER_SEASON, get_reference
from app.services.artwork import validate_image
from app.storage import get_storage

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("seed")

SEED_USERS = [
    ("admin@peblo.test", "Priya (admin)", "admin", "peblo-admin"),
    ("editor@peblo.test", "Arjun (editor)", "editor", "peblo-editor"),
]

# The sample images stand in for real artwork. Each seed row lists which slots
# it "has"; we materialise those slots from the matching good asset.
ASSET_FOR_KIND = {
    "poster": "poster_good.jpg",
    "banner": "banner_good.jpg",
    "thumbnail": "thumb_good.jpg",
}


def _load_assets() -> dict[str, tuple[bytes, str]]:
    """Upload the three good sample images once and keep their keys.

    They go through the real validator, so a bad sample would fail the seed
    rather than sneak a non-conforming image into the catalogue.
    """
    storage = get_storage()
    out: dict[str, tuple[bytes, str]] = {}
    for kind, filename in ASSET_FOR_KIND.items():
        path = settings.seed_assets_dir / filename
        if not path.is_file():
            log.warning("sample asset %s missing; %s slots will be left empty", path, kind)
            continue
        image = validate_image(path.read_bytes(), filename, kind)
        key = f"artwork/{kind}/{image.checksum[:2]}/{image.checksum}.{image.extension}"
        if not storage.exists(key):
            storage.put(key, image.data, image.content_type)
        out[kind] = (key, storage.url_for(key))
        log.info("asset %-9s -> %dx%d %s", kind, image.width, image.height, key)
    return out


def _artwork_row(owner_type: str, owner_id, kind: str, assets: dict) -> Artwork | None:
    if kind not in assets:
        return None
    key, url = assets[kind]
    path = settings.seed_assets_dir / ASSET_FOR_KIND[kind]
    spec = get_reference().spec(kind)
    return Artwork(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        storage_key=key,
        url=url,
        width=spec.target_w,
        height=spec.target_h,
        bytes=path.stat().st_size,
        content_type="image/jpeg",
        original_filename=ASSET_FOR_KIND[kind],
    )


def _reject(db: Session, row: dict, code: str, reason: str) -> None:
    db.add(
        ImportReject(
            source="seed_shows.json",
            source_ref=row.get("episode_id"),
            reason_code=code,
            reason=reason,
            payload=row,
        )
    )
    log.warning("rejected %s: %s", row.get("episode_id"), reason)


def seed(reset: bool = False) -> int:
    rows: list[dict] = json.loads(Path(settings.seed_path).read_text(encoding="utf-8"))
    ref = get_reference()
    assets = _load_assets()

    with SessionLocal() as db:
        if db.query(Show).count() and not reset:
            log.info("database already has shows; nothing to do (use --reset to reload)")
            return 0
        if reset:
            for model in (Artwork, Episode, Season, Show, ImportReject):
                db.query(model).delete()
            db.commit()

        for email, name, role, password in SEED_USERS:
            if db.query(User).filter(User.email == email).count() == 0:
                db.add(
                    User(
                        email=email,
                        name=name,
                        role=role,
                        hashed_password=hash_password(password),
                    )
                )
        db.commit()

        # ---------------------------------------------------------------- shows
        by_slug: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_slug[row["slug"]].append(row)

        shows: dict[str, Show] = {}
        for sort_index, (slug, group) in enumerate(sorted(by_slug.items())):
            first = group[0]
            # A show is published if any of its episodes is. Nothing in the seed
            # file carries a show-level status, and inventing one that made every
            # show published would have manufactured section errors that the
            # content team never actually has.
            any_published = any(r["status"] == "published" for r in group)
            show = Show(
                slug=slug,
                title=first["show_title"],
                synopsis=first.get("synopsis"),
                section=first.get("section"),
                categories=[c for c in (first.get("categories") or []) if c in ref.categories],
                default_language="en" if any(r["language"] == "en" for r in group) else None,
                status="published" if any_published and first.get("section") else "draft",
                sort_index=sort_index,
            )
            db.add(show)
            shows[slug] = show
        db.commit()

        for show in shows.values():
            for kind in ("poster", "banner"):
                art = _artwork_row("show", show.id, kind, assets)
                if art is not None:
                    db.add(art)
        db.commit()

        # -------------------------------------------------------------- seasons
        seasons: dict[tuple[str, int], Season] = {}
        for slug, group in by_slug.items():
            for number in sorted({r["season_number"] for r in group}):
                season = Season(
                    show_id=shows[slug].id,
                    season_number=number,
                    title="Trailers" if number == TRAILER_SEASON else f"Season {number}",
                )
                db.add(season)
                seasons[(slug, number)] = season
        db.commit()

        # ------------------------------------------------------------- episodes
        imported = 0
        rejected = 0
        for row in rows:
            season = seasons[(row["slug"], row["season_number"])]
            episode = Episode(
                season_id=season.id,
                episode_number=row["episode_number"],
                title=row["episode_title"],
                synopsis=row.get("synopsis"),
                duration_seconds=row.get("duration_seconds"),
                language=row["language"],
                content_group=row.get("content_group"),
                status=row["status"],
                video_url=f"https://video.peblo.test/{row['episode_id']}.m3u8",
            )
            # A nested transaction so one bad row rolls back alone rather than
            # poisoning the whole import.
            savepoint = db.begin_nested()
            try:
                db.add(episode)
                savepoint.commit()
            except IntegrityError as exc:
                savepoint.rollback()
                rejected += 1
                detail = str(getattr(exc, "orig", exc))
                if "uq_episodes_group_language" in detail:
                    reason = (
                        f"“{row['episode_title']}” could not be imported: another episode "
                        f"already covers {row['language']} for content group "
                        f"“{row['content_group']}”. Two rows in the file claim to be the same "
                        "episode in the same language, with different titles, so we kept the "
                        "first one and held this one back."
                    )
                    code = "duplicate_language_variant"
                elif "uq_episodes_slot_language" in detail:
                    reason = (
                        f"“{row['episode_title']}” could not be imported: season "
                        f"{row['season_number']} already has an episode "
                        f"{row['episode_number']} in {row['language']}."
                    )
                    code = "duplicate_episode_slot"
                else:
                    reason = f"“{row['episode_title']}” could not be imported: {detail[:300]}"
                    code = "constraint_violation"
                _reject(db, row, code, reason)
                continue

            imported += 1
            for kind in row.get("artwork_available") or []:
                art = _artwork_row("episode", episode.id, kind, assets)
                if art is not None:
                    db.add(art)
        db.commit()

        log.info(
            "imported %d episodes across %d shows (%d rejected)",
            imported,
            len(shows),
            rejected,
        )
        _log_findings(db)
        return rejected


def _log_findings(db: Session) -> None:
    """Print what the seed data turned out to contain, so it is on the record."""
    from app.services.validation import build_validation_report

    report = build_validation_report(db)
    log.info("-" * 70)
    log.info(
        "validation: %d blocking, %d warnings, can_publish=%s",
        report.blocking_count,
        report.warning_count,
        report.can_publish,
    )
    for group in report.groups:
        for issue in group.issues:
            log.info("  [%-8s] %s — %s", issue.severity, group.title, issue.message)
    log.info("-" * 70)


def bootstrap_publish() -> None:
    """Publish once at the end of seeding so a fresh checkout has a viewer.

    Uses force, because the seed data really does contain one episode that is
    marked published with no artwork, and the honest thing is to publish
    everything else and record the exclusion rather than to quietly fix the row
    or to hand a reviewer an empty viewer app. The forced run and its reason are
    visible in the CMS run history.
    """
    from app.services.publish import PublishBlocked, current_run, publish

    with SessionLocal() as db:
        # Only ever bootstraps an empty install. The container entrypoint runs
        # this on every start, and restarting the API is not a reason to
        # publish -- doing so would add a meaningless run to the history and,
        # worse, quietly re-force a publish an operator had deliberately
        # rolled back.
        existing = current_run(db)
        if existing is not None:
            log.info("catalogue already published (run %s); nothing to bootstrap", existing.id)
            return
        admin = db.query(User).filter(User.role == "admin").first()
        if admin is None:
            log.error("no admin user; skipping bootstrap publish")
            return
        try:
            outcome = publish(db, admin)
            log.info("bootstrap publish clean: %s", outcome.counts)
        except PublishBlocked as exc:
            log.warning(
                "seed data has %d blocking issue(s); publishing the rest and recording them",
                exc.report["blocking_count"],
            )
            outcome = publish(
                db,
                admin,
                force=True,
                force_reason=(
                    "Initial import of seed_shows.json. Published everything that validates; "
                    "the blocked items are listed on the Publish page and in this run."
                ),
            )
            log.info("bootstrap publish forced: %s", outcome.counts)
            for ex in outcome.exclusions:
                log.warning("  excluded %s: %s", ex.get("title"), ex.get("reason"))


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    seed(reset=reset)
    if "--no-publish" not in sys.argv:
        bootstrap_publish()
