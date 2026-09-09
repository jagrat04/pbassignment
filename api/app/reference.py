"""reference.json is the content team's rulebook and the single source of truth
for sections, categories, languages and artwork specs.

It is read once at startup and used by validation, the API, and both UIs (the
CMS fetches it from /reference so the dropdowns can never drift from the rules
the server enforces). Nothing in this codebase hard-codes a section name.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings

# reference.json states the convention; the number lives here so the rest of the
# code reads `TRAILER_SEASON` instead of a bare 0.
TRAILER_SEASON = 0


@dataclass(frozen=True)
class ArtworkSpec:
    kind: str
    aspect_w: int
    aspect_h: int
    target_w: int
    target_h: int
    max_bytes: int
    # How far from the exact aspect ratio we accept. 2% absorbs a 1279x720
    # export without letting a square image through as a banner.
    aspect_tolerance: float = 0.02
    # Dimensions may differ from target, but never be smaller: upscaling a small
    # image is the one thing we cannot fix after the fact. Above 1.5x we refuse
    # too -- a 2560px banner squeezed under 200 KB has visibly worse JPEG
    # artefacts than the same picture exported at 1280px.
    max_scale: float = 1.5

    @property
    def aspect(self) -> float:
        return self.aspect_w / self.aspect_h

    @property
    def aspect_label(self) -> str:
        return f"{self.aspect_w}:{self.aspect_h}"

    @property
    def max_kb(self) -> int:
        return self.max_bytes // 1024


@dataclass(frozen=True)
class Reference:
    sections: tuple[str, ...]
    categories: tuple[str, ...]
    languages: tuple[str, ...]
    artwork: dict[str, ArtworkSpec]
    conventions: dict[str, str]

    def spec(self, kind: str) -> ArtworkSpec:
        try:
            return self.artwork[kind]
        except KeyError:
            raise ValueError(
                f"unknown artwork kind {kind!r} (want one of {', '.join(sorted(self.artwork))})"
            ) from None

    def as_dict(self) -> dict:
        """Shape handed to the CMS so its form controls match the server rules."""
        return {
            "sections": list(self.sections),
            "categories": list(self.categories),
            "languages": list(self.languages),
            "trailer_season": TRAILER_SEASON,
            "artwork_specs": {
                k: {
                    "aspect": s.aspect_label,
                    "target_px": [s.target_w, s.target_h],
                    "max_kb": s.max_kb,
                    "min_px": [
                        int(s.target_w * (1 - s.aspect_tolerance)),
                        int(s.target_h * (1 - s.aspect_tolerance)),
                    ],
                }
                for k, s in self.artwork.items()
            },
            "conventions": self.conventions,
        }


def _parse_aspect(value: str) -> tuple[int, int]:
    w, _, h = value.partition(":")
    return int(w), int(h)


@lru_cache
def get_reference() -> Reference:
    path = settings.reference_path
    if not path.is_file():
        raise RuntimeError(
            f"reference.json not found at {path}. It defines the allowed sections, "
            "categories, languages and artwork specs and the API refuses to start without it."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))

    artwork: dict[str, ArtworkSpec] = {}
    for kind, spec in raw["artwork_specs"].items():
        aw, ah = _parse_aspect(spec["aspect"])
        tw, th = spec["target_px"]
        artwork[kind] = ArtworkSpec(
            kind=kind,
            aspect_w=aw,
            aspect_h=ah,
            target_w=int(tw),
            target_h=int(th),
            max_bytes=int(spec["max_kb"]) * 1024,
        )

    return Reference(
        sections=tuple(raw["sections"]),
        categories=tuple(raw["categories"]),
        languages=tuple(raw["languages"]),
        artwork=artwork,
        conventions=dict(raw.get("conventions", {})),
    )
