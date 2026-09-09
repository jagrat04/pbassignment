"""The publish job.

The whole design in one paragraph: the catalogue is written to an *immutable,
run-scoped key* that nothing is serving yet; only once those bytes are safely
written (and read back and checksummed) does a single database transaction move
the "current run" pointer. Readers resolve the pointer, so the cutover is a
committed row update -- the smallest atomic thing available. Nothing ever
overwrites the live object, which is why rollback is a pointer move and why a
process dying mid-publish leaves an orphaned file, not a broken catalogue.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CatalogEntry, PublishRun, User
from app.services.catalog_builder import BuildResult, build_catalog, canonical_json, checksum_of
from app.services.validation import build_validation_report
from app.storage import ObjectNotFound, Storage

log = logging.getLogger(__name__)

# One publisher at a time, cluster-wide. Two admins pressing the button at the
# same moment would otherwise race to set is_current and the loser's catalogue
# object would linger unreferenced.
PUBLISH_LOCK_ID = 0x9EB10


class PublishBlocked(Exception):
    def __init__(self, report: dict):
        self.report = report
        super().__init__("publish blocked by validation errors")


class PublishBusy(Exception):
    pass


@dataclass
class PublishOutcome:
    run_id: str
    status: str
    unchanged: bool
    counts: dict
    checksum: str
    catalog_key: str
    exclusions: list[dict]


@contextmanager
def publish_lock(db: Session):
    """Hold the advisory lock on a connection of its own.

    Deliberately not the ORM session's connection: publish commits several times
    and a pooled connection handed back between those commits would take the
    session-level lock with it to whichever request checked it out next.
    """
    conn = db.get_bind().connect()
    try:
        acquired = bool(
            conn.exec_driver_sql(f"SELECT pg_try_advisory_lock({PUBLISH_LOCK_ID})").scalar()
        )
        if not acquired:
            raise PublishBusy(
                "Another publish is running right now. Wait for it to finish and try again."
            )
        try:
            yield
        finally:
            conn.exec_driver_sql(f"SELECT pg_advisory_unlock({PUBLISH_LOCK_ID})")
    finally:
        conn.close()


def current_run(db: Session) -> PublishRun | None:
    return db.query(PublishRun).filter(PublishRun.is_current.is_(True)).one_or_none()


def reap_interrupted_runs(db: Session, older_than_minutes: int = 15) -> int:
    """Mark runs that were still 'running' when the process died.

    Called at startup. Their catalogue objects, if any were written, are
    unreferenced and harmless -- no pointer ever moved to them.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    stale = (
        db.query(PublishRun)
        .filter(PublishRun.status == "running", PublishRun.started_at < cutoff)
        .all()
    )
    for run in stale:
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = (
            "The publish process stopped before it finished. The live catalogue was not "
            "changed — nothing was published from this run. Safe to publish again."
        )
    if stale:
        db.commit()
        log.warning("reaped %d interrupted publish run(s)", len(stale))
    return len(stale)


def dry_run(db: Session) -> dict:
    """Build the catalogue and diff it against what is live, changing nothing."""
    report = build_validation_report(db)
    result = build_catalog(
        db,
        generated_at=datetime.now(UTC),
        run_id="dry-run",
        excluded_show_ids=report.blocking_show_ids(),
        excluded_episode_ids=report.blocking_episode_ids(),
    )
    live = load_current_catalog(db, _storage()) or {}
    return {
        "can_publish": report.can_publish,
        "blocking_count": report.blocking_count,
        "counts": result.counts,
        "exclusions": result.exclusions,
        "diff": diff_catalogs(live, result.catalog),
    }


def _storage() -> Storage:
    from app.storage import get_storage

    return get_storage()


def publish(
    db: Session,
    actor: User,
    *,
    force: bool = False,
    force_reason: str | None = None,
) -> PublishOutcome:
    with publish_lock(db):
        return _run_publish(db, actor, force=force, force_reason=force_reason)


def _run_publish(
    db: Session, actor: User, *, force: bool, force_reason: str | None
) -> PublishOutcome:
    """The publish itself. Always called with the advisory lock held."""
    storage = _storage()
    run: PublishRun | None = None
    try:
        report = build_validation_report(db)
        if not report.can_publish and not force:
            raise PublishBlocked(report.to_dict())

        excluded_shows = report.blocking_show_ids() if force else set()
        excluded_episodes = report.blocking_episode_ids() if force else set()

        # Step 1: record the attempt and commit it, so a crash from here on
        # leaves evidence in the run history rather than silence.
        run = PublishRun(
            actor_user_id=actor.id,
            actor_email=actor.email,
            status="running",
            error=(
                f"Published with unresolved validation errors. Reason: {force_reason}"
                if force and not report.can_publish
                else None
            ),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = str(run.id)

        # Step 2: build from one consistent read of the database.
        generated_at = datetime.now(UTC)
        result: BuildResult = build_catalog(
            db,
            generated_at=generated_at,
            run_id=run_id,
            excluded_show_ids=excluded_shows,
            excluded_episode_ids=excluded_episodes,
        )

        # `generated_at` and `run_id` change every run, so they are excluded from
        # the identity of the content. Without this, no publish is ever a no-op.
        identity = dict(result.catalog)
        identity.pop("generated_at", None)
        identity.pop("run_id", None)
        content_checksum = checksum_of(identity)

        live = current_run(db)
        if live is not None and live.catalog_checksum == content_checksum and not force:
            # Idempotent: nothing changed, so nothing is written and the live
            # pointer is left exactly where it is.
            run.status = "success"
            run.finished_at = datetime.now(UTC)
            run.counts = {**result.counts, "unchanged": True}
            run.catalog_key = live.catalog_key
            run.catalog_checksum = content_checksum
            db.commit()
            return PublishOutcome(
                run_id=run_id,
                status="success",
                unchanged=True,
                counts=run.counts,
                checksum=content_checksum,
                catalog_key=live.catalog_key or "",
                exclusions=result.exclusions,
            )

        # Step 3: write the immutable, run-scoped object. Nothing serves this
        # key yet, so a failure here is invisible to viewers.
        key = f"{settings.catalog_versions_prefix}/{run_id}.json"
        body = canonical_json(result.catalog)
        storage.put_atomic(key, body, "application/json")

        # Step 4: read it back before trusting it. A truncated write on a full
        # disk is exactly the failure this catches, and it costs milliseconds.
        written = storage.get(key)
        if written != body:
            raise RuntimeError(
                f"catalogue written to {key} does not match what was built "
                f"({len(written)} bytes back, {len(body)} expected)"
            )

        # Step 5: the cutover. One transaction: insert this run's search rows,
        # clear the old pointer, set the new one. Postgres gives us all-or-
        # nothing, and the partial unique index on is_current makes "two current
        # runs" unrepresentable rather than merely unlikely.
        db.add_all([CatalogEntry(run_id=run.id, **row) for row in result.search_rows])
        db.query(PublishRun).filter(PublishRun.is_current.is_(True)).update(
            {"is_current": False}, synchronize_session=False
        )
        run.is_current = True
        run.status = "success"
        run.finished_at = datetime.now(UTC)
        run.counts = {**result.counts, "unchanged": False, "forced": bool(force)}
        run.catalog_key = key
        run.catalog_checksum = content_checksum
        db.commit()

        # Step 6: convenience copy at a stable key, for a CDN or a static host
        # that wants one URL. Deliberately after the commit and deliberately
        # not fatal: the database pointer is what /catalog resolves, so a
        # failure here degrades the CDN path, not the product.
        try:
            storage.put_atomic(settings.catalog_key, body, "application/json")
        except Exception:  # noqa: BLE001 - best-effort mirror
            log.exception("could not update the stable catalogue key; pointer is still correct")

        return PublishOutcome(
            run_id=run_id,
            status="success",
            unchanged=False,
            counts=run.counts,
            checksum=content_checksum,
            catalog_key=key,
            exclusions=result.exclusions,
        )

    except PublishBlocked:
        raise
    except Exception as exc:
        if run is not None:
            db.rollback()
            fresh = db.get(PublishRun, run.id)
            if fresh is not None:
                fresh.status = "failed"
                fresh.finished_at = datetime.now(UTC)
                fresh.error = f"{type(exc).__name__}: {exc}"
                db.commit()
        raise


def rollback(db: Session, actor: User, target_run_id: str) -> PublishOutcome:
    """Point the catalogue back at a previous successful run.

    Cheap and safe precisely because publish never overwrites: every past run's
    bytes are still sitting at their own key, and its search rows are still in
    catalog_entries.
    """
    storage = _storage()
    with publish_lock(db):
        target = db.get(PublishRun, target_run_id)
        if target is None or target.status != "success" or not target.catalog_key:
            raise ValueError(
                "That run never produced a catalogue, so there is nothing to roll back to."
            )
        try:
            body = storage.get(target.catalog_key)
        except ObjectNotFound as exc:
            raise ValueError(
                "The catalogue file for that run is no longer in storage."
            ) from exc

        db.query(PublishRun).filter(PublishRun.is_current.is_(True)).update(
            {"is_current": False}, synchronize_session=False
        )
        target.is_current = True
        marker = PublishRun(
            actor_user_id=actor.id,
            actor_email=actor.email,
            status="success",
            finished_at=datetime.now(UTC),
            counts={**(target.counts or {}), "rollback_to": str(target.id)},
            catalog_key=target.catalog_key,
            catalog_checksum=target.catalog_checksum,
            error=f"Rolled the catalogue back to run {target.id}.",
            is_current=False,
        )
        db.add(marker)
        db.commit()

        try:
            storage.put_atomic(settings.catalog_key, body, "application/json")
        except Exception:  # noqa: BLE001
            log.exception("could not update the stable catalogue key after rollback")

        return PublishOutcome(
            run_id=str(target.id),
            status="success",
            unchanged=False,
            counts=target.counts or {},
            checksum=target.catalog_checksum or "",
            catalog_key=target.catalog_key,
            exclusions=[],
        )


def load_current_catalog(db: Session, storage: Storage) -> dict | None:
    run = current_run(db)
    if run is None or not run.catalog_key:
        return None
    try:
        import json

        return json.loads(storage.get(run.catalog_key))
    except ObjectNotFound:
        log.error("current run %s points at missing object %s", run.id, run.catalog_key)
        return None


def diff_catalogs(old: dict, new: dict) -> dict:
    """What this publish would change, in terms an editor recognises."""

    def index(cat: dict) -> tuple[dict, dict]:
        shows = {s["slug"]: s for s in cat.get("shows", [])}
        eps = {}
        for s in cat.get("shows", []):
            for season in s.get("seasons", []) + [{"episodes": s.get("trailers", [])}]:
                for e in season["episodes"]:
                    eps[f"{s['slug']}/{e['id']}"] = e
        return shows, eps

    old_shows, old_eps = index(old)
    new_shows, new_eps = index(new)

    changed_shows = [
        slug
        for slug in old_shows.keys() & new_shows.keys()
        if canonical_json(old_shows[slug]) != canonical_json(new_shows[slug])
    ]
    changed_eps = [
        k
        for k in old_eps.keys() & new_eps.keys()
        if canonical_json(old_eps[k]) != canonical_json(new_eps[k])
    ]
    return {
        "shows_added": sorted(new_shows.keys() - old_shows.keys()),
        "shows_removed": sorted(old_shows.keys() - new_shows.keys()),
        "shows_changed": sorted(changed_shows),
        "episodes_added": len(new_eps.keys() - old_eps.keys()),
        "episodes_removed": len(old_eps.keys() - new_eps.keys()),
        "episodes_changed": len(changed_eps),
        "is_first_publish": not old,
    }
