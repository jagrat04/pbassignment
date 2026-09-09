"""Artwork ingest: validate, content-address, store.

Every rejection message here is written for a content editor, not an engineer.
The rule is: say what was wrong with *their* file, in their units, and say what
to do about it. "422 aspect_ratio_mismatch" is not an error message.
"""

import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.models import Artwork
from app.reference import ArtworkSpec, get_reference
from app.storage import Storage

# Pillow will happily open a 40000x40000 PNG and allocate 6 GB doing it.
Image.MAX_IMAGE_PIXELS = 8000 * 8000

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ArtworkRejected(Exception):
    """A validation failure with a message an editor can act on."""

    def __init__(self, problem: str, fix: str, *, field: str = "file", detail: dict | None = None):
        self.problem = problem
        self.fix = fix
        self.field = field
        self.detail = detail or {}
        super().__init__(f"{problem} {fix}")

    def as_response(self) -> dict:
        return {
            "error": "artwork_rejected",
            # The CMS shows `problem` in red and `fix` underneath in grey.
            "problem": self.problem,
            "fix": self.fix,
            "field": self.field,
            **self.detail,
        }


@dataclass
class ValidatedImage:
    data: bytes
    width: int
    height: int
    content_type: str
    extension: str
    checksum: str


def _human_kb(n: int) -> str:
    return f"{n / 1024:.0f} KB"


def validate_image(data: bytes, filename: str, kind: str) -> ValidatedImage:
    """Check one uploaded file against the spec for `kind` from reference.json."""
    spec: ArtworkSpec = get_reference().spec(kind)

    if not data:
        raise ArtworkRejected(
            "That file is empty.",
            "Pick the image again — the upload may have been interrupted.",
        )

    # --- size ceiling -------------------------------------------------------
    # Checked before decoding: no reason to spend memory on a file we will
    # refuse anyway.
    if len(data) > spec.max_bytes:
        raise ArtworkRejected(
            f"This image is {_human_kb(len(data))}. The limit for a {kind} is {spec.max_kb} KB.",
            (
                f"Export it again as a JPEG at {spec.target_w}x{spec.target_h} with quality "
                "around 80 — that almost always lands under the limit. PNG photographs are "
                "usually the culprit."
            ),
            detail={"bytes": len(data), "max_bytes": spec.max_bytes},
        )

    # --- decodable image ----------------------------------------------------
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # cheap structural check; consumes the file object
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            pil_format = (img.format or "").upper()
    except (UnidentifiedImageError, OSError):
        raise ArtworkRejected(
            "That file isn't an image we can read.",
            "Upload a JPG, PNG or WebP. If you exported from a design tool, "
            "use File > Export rather than renaming the file.",
        ) from None

    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(pil_format)
    if content_type is None:
        raise ArtworkRejected(
            f"{pil_format or 'That format'} images aren't supported.",
            "Save the artwork as a JPG, PNG or WebP and upload it again.",
        )

    if width <= 0 or height <= 0:
        raise ArtworkRejected(
            "That image has no dimensions.", "Re-export it and try again."
        )

    # --- aspect ratio -------------------------------------------------------
    actual = width / height
    if abs(actual - spec.aspect) / spec.aspect > spec.aspect_tolerance:
        raise ArtworkRejected(
            (
                f"A {kind} has to be {spec.aspect_label} (like {spec.target_w}x{spec.target_h}). "
                f"This image is {width}x{height}, which is closer to "
                f"{_closest_ratio_label(actual)}."
            ),
            (
                f"Crop it to {spec.aspect_label} before uploading. The safest route is to "
                f"resize the canvas to exactly {spec.target_w}x{spec.target_h}."
            ),
            detail={
                "width": width,
                "height": height,
                "expected_aspect": spec.aspect_label,
                "target_px": [spec.target_w, spec.target_h],
            },
        )

    # --- dimensions ---------------------------------------------------------
    # Too small is fatal: nothing downstream can invent pixels. Too large is
    # fatal too, but for a different reason -- a 4000px poster inside the size
    # ceiling means it was crushed to mush by JPEG quality.
    min_w = int(spec.target_w * (1 - spec.aspect_tolerance))
    min_h = int(spec.target_h * (1 - spec.aspect_tolerance))
    if width < min_w or height < min_h:
        raise ArtworkRejected(
            (
                f"This {kind} is {width}x{height} — too small. It needs to be at least "
                f"{spec.target_w}x{spec.target_h}, or it will look blurry on a TV."
            ),
            (
                "Export it again from the original artwork at "
                f"{spec.target_w}x{spec.target_h}. Enlarging the small file won't help."
            ),
            detail={"width": width, "height": height, "target_px": [spec.target_w, spec.target_h]},
        )

    max_w = int(spec.target_w * spec.max_scale)
    max_h = int(spec.target_h * spec.max_scale)
    if width > max_w or height > max_h:
        raise ArtworkRejected(
            (
                f"This {kind} is {width}x{height} — much larger than the "
                f"{spec.target_w}x{spec.target_h} we use."
            ),
            (
                f"Resize it to {spec.target_w}x{spec.target_h} and export again. Squeezing a "
                f"very large image under {spec.max_kb} KB loses more detail than resizing it."
            ),
            detail={"width": width, "height": height, "target_px": [spec.target_w, spec.target_h]},
        )

    return ValidatedImage(
        data=data,
        width=width,
        height=height,
        content_type=content_type,
        extension=ALLOWED_CONTENT_TYPES[content_type],
        checksum=hashlib.sha256(data).hexdigest(),
    )


def _closest_ratio_label(actual: float) -> str:
    """Name the ratio the editor actually uploaded, so the error is recognisable."""
    known = {
        "1:1": 1.0,
        "2:3": 2 / 3,
        "3:2": 1.5,
        "3:4": 0.75,
        "4:3": 4 / 3,
        "9:16": 9 / 16,
        "16:9": 16 / 9,
    }
    label, _ = min(known.items(), key=lambda kv: abs(kv[1] - actual))
    return label


def store_artwork(
    db: Session,
    storage: Storage,
    *,
    owner_type: str,
    owner_id: uuid.UUID,
    kind: str,
    data: bytes,
    filename: str,
) -> Artwork:
    """Validate then persist. Replaces whatever was in the slot."""
    image = validate_image(data, filename, kind)

    # Content-addressed: the same file uploaded to fifty episodes is stored
    # once, and the key never needs invalidating because the bytes never change.
    key = f"artwork/{kind}/{image.checksum[:2]}/{image.checksum}.{image.extension}"
    if not storage.exists(key):
        storage.put(key, image.data, image.content_type)
    url = storage.url_for(key)

    existing = (
        db.query(Artwork)
        .filter(
            Artwork.owner_type == owner_type,
            Artwork.owner_id == owner_id,
            Artwork.kind == kind,
        )
        .one_or_none()
    )
    if existing is None:
        existing = Artwork(owner_type=owner_type, owner_id=owner_id, kind=kind)
        db.add(existing)

    existing.storage_key = key
    existing.url = url
    existing.width = image.width
    existing.height = image.height
    existing.bytes = len(image.data)
    existing.content_type = image.content_type
    existing.original_filename = filename[:255]
    # Old objects are deliberately not deleted: another owner may reference the
    # same checksum. A separate sweep reclaims unreferenced keys (see README).
    return existing
