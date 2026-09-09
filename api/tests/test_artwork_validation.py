"""Artwork validation, against the exact files the challenge shipped.

This is the first place a real editor meets the system, and the first place a
sloppy implementation shows: accepting anything at any size is explicitly on
the list of things that count against us.
"""

import io

import pytest
from PIL import Image

from app.services.artwork import ArtworkRejected, validate_image


def _jpeg(width: int, height: int, quality: int = 80) -> bytes:
    """A noisy image, so JPEG cannot compress it into nothing."""
    import random

    img = Image.new("RGB", (width, height))
    rnd = random.Random(1)
    img.putdata(
        [
            (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            for _ in range(width * height)
        ]
    )
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# --------------------------------------------------------------- the good ones


@pytest.mark.parametrize(
    "name,kind,size",
    [
        ("poster_good", "poster", (600, 900)),
        ("banner_good", "banner", (1280, 720)),
        ("thumb_good", "thumbnail", (640, 360)),
    ],
)
def test_supplied_good_assets_are_accepted(sample_images, name, kind, size):
    result = validate_image(sample_images[name], f"{name}.jpg", kind)
    assert (result.width, result.height) == size
    assert result.content_type == "image/jpeg"


# ---------------------------------------------------------------- the bad ones


def test_wrong_aspect_ratio_is_rejected_with_the_ratio_named(sample_images):
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(sample_images["poster_wrong_ratio"], "poster_wrong_ratio.jpg", "poster")
    # The editor is told what they uploaded, not just that it was wrong.
    assert "2:3" in exc.value.problem
    assert "900x600" in exc.value.problem
    assert "3:2" in exc.value.problem
    assert "600x900" in exc.value.fix


def test_undersized_thumbnail_is_rejected(sample_images):
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(sample_images["thumb_tiny"], "thumb_tiny.jpg", "thumbnail")
    assert "160x90" in exc.value.problem
    assert "too small" in exc.value.problem
    assert "won't help" in exc.value.fix


def test_oversized_banner_is_rejected(sample_images):
    # 2560x1440 has the right ratio and is under the byte ceiling, so only a
    # dimension check catches it.
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(sample_images["banner_too_big"], "banner_too_big.png", "banner")
    assert "2560x1440" in exc.value.problem


def test_size_ceiling_is_enforced():
    big = _jpeg(1280, 720, quality=100)
    assert len(big) > 200 * 1024, "test fixture is not actually over the limit"
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(big, "huge.jpg", "banner")
    assert "200 KB" in exc.value.problem
    assert "quality" in exc.value.fix


def test_a_banner_is_not_accepted_as_a_poster(sample_images):
    """The three slots are genuinely distinct, not three names for one check."""
    with pytest.raises(ArtworkRejected):
        validate_image(sample_images["banner_good"], "banner_good.jpg", "poster")


def test_a_thumbnail_sized_image_is_not_accepted_as_a_banner(sample_images):
    # Same 16:9 ratio, but half the pixels a banner needs.
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(sample_images["thumb_good"], "thumb_good.jpg", "banner")
    assert "too small" in exc.value.problem


def test_non_image_is_rejected_kindly():
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(b"PK\x03\x04 this is a zip", "artwork.jpg", "poster")
    assert "isn't an image" in exc.value.problem
    assert "renaming" in exc.value.fix


def test_empty_file_is_rejected():
    with pytest.raises(ArtworkRejected) as exc:
        validate_image(b"", "empty.jpg", "poster")
    assert "empty" in exc.value.problem


def _smooth_jpeg(width: int, height: int) -> bytes:
    """A gradient: right dimensions, comfortably under the byte ceiling."""
    img = Image.linear_gradient("L").resize((width, height)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def test_slightly_off_dimensions_are_tolerated():
    """1278x719 is a real export artefact, not an editor mistake."""
    result = validate_image(_smooth_jpeg(1278, 719), "close.jpg", "banner")
    assert result.width == 1278


def test_every_rejection_says_what_to_do(sample_images):
    for name, kind in [
        ("poster_wrong_ratio", "poster"),
        ("thumb_tiny", "thumbnail"),
        ("banner_too_big", "banner"),
    ]:
        with pytest.raises(ArtworkRejected) as exc:
            validate_image(sample_images[name], name, kind)
        assert exc.value.fix.strip(), f"{name} rejected without telling the editor what to do"
        # No jargon leaking into the editor-facing text.
        for word in ("aspect_ratio", "422", "ValidationError", "None"):
            assert word not in exc.value.problem
