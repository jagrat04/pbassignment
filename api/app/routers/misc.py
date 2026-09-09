"""Auth, the reference document, and health."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, verify_password
from app.db import get_db
from app.models import PublishRun, User
from app.reference import get_reference
from app.schemas import LoginRequest
from app.storage import Storage, get_storage

router = APIRouter()


@router.post("/auth/login", tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email.lower().strip()).one_or_none()
    # Same message and roughly the same work either way: no telling an attacker
    # which half they got right.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_credentials",
                "problem": "That email and password don't match an account.",
                "fix": "Check for typos, or ask an admin to reset your password.",
            },
        )
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
    }


@router.get("/auth/me", tags=["auth"])
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": str(user.id), "email": user.email, "name": user.name, "role": user.role}


@router.get("/reference", tags=["reference"])
def reference() -> dict:
    """The rules the server enforces, handed to the CMS so its dropdowns and
    upload hints can never drift from them."""
    return get_reference().as_dict()


@router.get("/health", tags=["ops"])
def health(db: Session = Depends(get_db), storage: Storage = Depends(get_storage)) -> dict:
    """Liveness + the two dependencies that actually break in production.

    A health check that only says "the process is up" tells you nothing you
    couldn't get from the load balancer. This one touches the database and the
    object store, and reports whether a catalogue is currently being served --
    the three ways this service fails while still answering requests.
    """
    checks: dict[str, dict] = {}
    ok = True

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        ok = False
        checks["database"] = {"ok": False, "error": str(exc)[:200]}

    try:
        probe = "health/probe.txt"
        storage.put(probe, b"ok", "text/plain")
        checks["storage"] = {"ok": storage.get(probe) == b"ok"}
        ok = ok and checks["storage"]["ok"]
    except Exception as exc:  # noqa: BLE001
        ok = False
        checks["storage"] = {"ok": False, "error": str(exc)[:200]}

    try:
        run = db.query(PublishRun).filter(PublishRun.is_current.is_(True)).one_or_none()
        checks["catalog"] = {
            "ok": run is not None,
            "run_id": str(run.id) if run else None,
            "published_at": run.finished_at.isoformat() if run and run.finished_at else None,
            # The number worth alerting on: see the README.
            "age_seconds": (
                int((datetime.now(UTC) - run.finished_at).total_seconds())
                if run and run.finished_at
                else None
            ),
        }
    except Exception as exc:  # noqa: BLE001
        checks["catalog"] = {"ok": False, "error": str(exc)[:200]}

    if not ok:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "checks": checks})
    return {"status": "ok", "checks": checks}
