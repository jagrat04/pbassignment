import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_editor
from app.db import get_db
from app.models import Artwork, Episode, Show
from app.reference import get_reference
from app.services.artwork import ArtworkRejected, store_artwork
from app.storage import Storage, get_storage

router = APIRouter(
    prefix="/admin/artwork", tags=["admin:artwork"], dependencies=[Depends(require_editor)]
)

# Read at most this much before deciding the file is too big. The spec ceiling
# is 200 KB; anything past 5 MB is refused without buffering the whole upload.
HARD_READ_LIMIT = 5 * 1024 * 1024


def _owner_exists(db: Session, owner_type: str, owner_id: uuid.UUID) -> None:
    model = {"show": Show, "episode": Episode}[owner_type]
    if db.get(model, owner_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "problem": f"That {owner_type} no longer exists.",
                "fix": "Reload the page — someone may have deleted it.",
            },
        )


@router.post("/{owner_type}/{owner_id}/{kind}", status_code=201)
async def upload_artwork(
    owner_type: str = Path(..., pattern="^(show|episode)$"),
    owner_id: uuid.UUID = Path(...),
    kind: str = Path(..., pattern="^(poster|banner|thumbnail)$"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> dict:
    """Upload one artwork slot.

    Validation lives in app/services/artwork.py and runs on the server, on the
    bytes we actually received. The CMS shows the same rules next to the field,
    but nothing the browser says is trusted.
    """
    _owner_exists(db, owner_type, owner_id)

    data = await file.read(HARD_READ_LIMIT + 1)
    if len(data) > HARD_READ_LIMIT:
        spec = get_reference().spec(kind)
        raise HTTPException(
            status_code=413,
            detail={
                "error": "artwork_rejected",
                "problem": "That file is far too large to upload.",
                "fix": f"A {kind} has to be under {spec.max_kb} KB. Export it as a JPEG at "
                f"{spec.target_w}x{spec.target_h} first.",
                "field": "file",
            },
        )

    try:
        artwork = store_artwork(
            db,
            storage,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            data=data,
            filename=file.filename or "upload",
        )
        db.commit()
    except ArtworkRejected as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=exc.as_response()) from exc

    db.refresh(artwork)
    return {
        "kind": artwork.kind,
        "url": artwork.url,
        "width": artwork.width,
        "height": artwork.height,
        "bytes": artwork.bytes,
        "original_filename": artwork.original_filename,
    }


@router.delete("/{owner_type}/{owner_id}/{kind}", status_code=204)
def delete_artwork(
    owner_type: str = Path(..., pattern="^(show|episode)$"),
    owner_id: uuid.UUID = Path(...),
    kind: str = Path(..., pattern="^(poster|banner|thumbnail)$"),
    db: Session = Depends(get_db),
) -> None:
    row = (
        db.query(Artwork)
        .filter(
            Artwork.owner_type == owner_type,
            Artwork.owner_id == owner_id,
            Artwork.kind == kind,
        )
        .one_or_none()
    )
    if row is not None:
        # The stored object is left alone: keys are content-addressed, so another
        # show or episode may be pointing at exactly these bytes.
        db.delete(row)
        db.commit()
