"""Publishing, the validation report, and run history.

Every route here that changes the live catalogue depends on `require_admin`.
The read-only ones (the report, the history) only need an editor, because an
editor needs to see what they have to fix even though they cannot publish it.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin, require_editor
from app.db import get_db
from app.models import ImportReject, PublishRun, User
from app.schemas import PublishRequest
from app.services import publish as publish_service
from app.services.validation import build_validation_report

router = APIRouter(prefix="/admin", tags=["admin:publish"])


@router.get("/validation-report", dependencies=[Depends(require_editor)])
def validation_report(db: Session = Depends(get_db)) -> dict:
    """Everything standing between the current content and a publish."""
    return build_validation_report(db).to_dict()


@router.get("/catalog/runs", dependencies=[Depends(require_editor)])
def list_runs(
    limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)
) -> dict:
    runs = (
        db.query(PublishRun)
        .order_by(PublishRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "runs": [
            {
                "id": str(r.id),
                "actor_email": r.actor_email,
                "status": r.status,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "duration_ms": (
                    int((r.finished_at - r.started_at).total_seconds() * 1000)
                    if r.finished_at
                    else None
                ),
                "counts": r.counts,
                "error": r.error,
                "catalog_key": r.catalog_key,
                "catalog_checksum": r.catalog_checksum,
                "is_current": r.is_current,
            }
            for r in runs
        ]
    }


@router.post("/catalog/publish/dry-run", dependencies=[Depends(require_editor)])
def publish_dry_run(db: Session = Depends(get_db)) -> dict:
    """What a publish would do right now. Writes nothing."""
    return publish_service.dry_run(db)


@router.post("/catalog/publish")
def run_publish(
    payload: PublishRequest | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
) -> dict:
    payload = payload or PublishRequest()
    try:
        outcome = publish_service.publish(
            db, actor, force=payload.force, force_reason=payload.force_reason
        )
    except publish_service.PublishBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "publish_blocked",
                "problem": (
                    f"{exc.report['blocking_count']} thing"
                    + ("s" if exc.report["blocking_count"] != 1 else "")
                    + " must be fixed before this can go out."
                ),
                "fix": "Work through the list below, then publish again.",
                "report": exc.report,
            },
        ) from exc
    except publish_service.PublishBusy as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "publish_busy", "problem": str(exc), "fix": "Try again in a moment."},
        ) from exc

    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "unchanged": outcome.unchanged,
        "counts": outcome.counts,
        "checksum": outcome.checksum,
        "catalog_key": outcome.catalog_key,
        "exclusions": outcome.exclusions,
    }


@router.post("/catalog/rollback/{run_id}")
def run_rollback(
    run_id: uuid.UUID, db: Session = Depends(get_db), actor: User = Depends(require_admin)
) -> dict:
    try:
        outcome = publish_service.rollback(db, actor, str(run_id))
    except publish_service.PublishBusy as exc:
        raise HTTPException(
            status_code=409, detail={"error": "publish_busy", "problem": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "rollback_unavailable",
                "problem": str(exc),
                "fix": "Pick a different run from the history.",
            },
        ) from exc
    return {"run_id": outcome.run_id, "status": "rolled_back", "counts": outcome.counts}


@router.post("/import-rejects/{reject_id}/resolve", dependencies=[Depends(require_editor)])
def resolve_reject(reject_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    row = db.get(ImportReject, reject_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    row.resolved = True
    db.commit()
    return {"id": str(row.id), "resolved": True}
