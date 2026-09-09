"""What is stopping the catalogue from going out, phrased for a content editor.

The report is grouped by *the thing you have to go fix* (a show, an episode, an
import conflict), not by rule, because an editor works through it one screen at
a time. Each issue carries a `location` the CMS turns into a deep link.

Severity:
    blocking  -- content is marked published but cannot be represented in the
                 catalogue. Publish refuses to run. Silently dropping these is
                 the failure mode that turns into "why isn't my episode live?"
                 three weeks later.
    warning   -- worth an editor's attention but the catalogue is still correct
                 without it (a draft show with no section, an empty season).
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session, selectinload

from app.models import Artwork, Episode, ImportReject, Season, Show
from app.reference import TRAILER_SEASON, get_reference

# Which artwork each surface actually needs. The viewer uses a show poster in
# the browse rows, a show banner in the hero, and an episode thumbnail in the
# episode list -- so those are the three we require, and only those. Demanding a
# poster on every episode would block the trailers for artwork nothing renders.
REQUIRED_SHOW_ARTWORK = ("poster", "banner")
REQUIRED_EPISODE_ARTWORK = ("thumbnail",)


@dataclass
class Issue:
    severity: str  # "blocking" | "warning"
    code: str
    message: str  # what is wrong, in an editor's words
    fix: str  # what to do about it
    location: dict = field(default_factory=dict)  # {type, id, label} for deep links


@dataclass
class IssueGroup:
    key: str
    title: str  # e.g. "Discover India with Moti - S1E4 The Midnight Market"
    kind: str  # "show" | "episode" | "import"
    id: str | None
    issues: list[Issue]

    @property
    def blocking(self) -> bool:
        return any(i.severity == "blocking" for i in self.issues)


@dataclass
class ValidationReport:
    blocking_count: int
    warning_count: int
    can_publish: bool
    groups: list[IssueGroup]

    def to_dict(self) -> dict:
        return {
            "can_publish": self.can_publish,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "groups": [
                {
                    "key": g.key,
                    "title": g.title,
                    "kind": g.kind,
                    "id": g.id,
                    "blocking": g.blocking,
                    "issues": [asdict(i) for i in g.issues],
                }
                for g in self.groups
            ],
        }

    def blocking_episode_ids(self) -> set[str]:
        return {
            g.id
            for g in self.groups
            if g.kind == "episode" and g.blocking and g.id is not None
        }

    def blocking_show_ids(self) -> set[str]:
        return {
            g.id for g in self.groups if g.kind == "show" and g.blocking and g.id is not None
        }


def _artwork_index(db: Session) -> dict[tuple[str, str], set[str]]:
    rows = db.query(Artwork.owner_type, Artwork.owner_id, Artwork.kind).all()
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for owner_type, owner_id, kind in rows:
        index[(owner_type, str(owner_id))].add(kind)
    return index


def build_validation_report(db: Session) -> ValidationReport:
    ref = get_reference()
    art = _artwork_index(db)
    groups: list[IssueGroup] = []

    shows = (
        db.query(Show)
        .options(selectinload(Show.seasons).selectinload(Season.episodes))
        .order_by(Show.title)
        .all()
    )

    for show in shows:
        show_issues: list[Issue] = []
        published_show = show.status == "published"
        loc = {"type": "show", "id": str(show.id), "label": show.title}

        # --- section --------------------------------------------------------
        if not show.section:
            show_issues.append(
                Issue(
                    severity="blocking" if published_show else "warning",
                    code="show_missing_section",
                    message=f"“{show.title}” has no section.",
                    fix=(
                        "Open the show and pick a section ("
                        + ", ".join(ref.sections)
                        + "). The section decides which row it appears in on the home screen."
                    ),
                    location=loc,
                )
            )
        elif show.section not in ref.sections:
            show_issues.append(
                Issue(
                    severity="blocking" if published_show else "warning",
                    code="show_unknown_section",
                    message=(
                        f"“{show.title}” is in section “{show.section}”, "
                        "which no longer exists."
                    ),
                    fix="Move it to one of: " + ", ".join(ref.sections) + ".",
                    location=loc,
                )
            )

        unknown_cats = [c for c in (show.categories or []) if c not in ref.categories]
        if unknown_cats:
            show_issues.append(
                Issue(
                    severity="warning",
                    code="show_unknown_category",
                    message=(
                        f"“{show.title}” uses categor"
                        + ("ies " if len(unknown_cats) > 1 else "y ")
                        + ", ".join(f"“{c}”" for c in unknown_cats)
                        + ", which aren't on the approved list."
                    ),
                    fix="Remove them or replace them with approved categories. "
                    "Viewers can't filter by an unapproved category.",
                    location=loc,
                )
            )

        # --- show artwork ---------------------------------------------------
        have = art.get(("show", str(show.id)), set())
        for kind in REQUIRED_SHOW_ARTWORK:
            if kind not in have:
                spec = ref.spec(kind)
                where = "the home-screen rows" if kind == "poster" else "the featured banner"
                show_issues.append(
                    Issue(
                        severity="blocking" if published_show else "warning",
                        code=f"show_missing_{kind}",
                        message=f"“{show.title}” has no {kind} image.",
                        fix=(
                            f"Upload a {spec.aspect_label} {kind} "
                            f"({spec.target_w}x{spec.target_h}, under {spec.max_kb} KB). "
                            f"It's what viewers see in {where}."
                        ),
                        location=loc,
                    )
                )

        # --- episodes -------------------------------------------------------
        publishable_episodes = 0
        for season in show.seasons:
            for ep in season.episodes:
                ep_issues = _episode_issues(ep, season, show, art, ref)
                if ep.status == "published" and not any(
                    i.severity == "blocking" for i in ep_issues
                ):
                    publishable_episodes += 1
                if ep_issues:
                    label = _episode_label(show, season, ep)
                    groups.append(
                        IssueGroup(
                            key=f"episode:{ep.id}",
                            title=label,
                            kind="episode",
                            id=str(ep.id),
                            issues=ep_issues,
                        )
                    )

        if published_show and publishable_episodes == 0:
            show_issues.append(
                Issue(
                    severity="blocking",
                    code="show_no_publishable_episodes",
                    message=f"“{show.title}” is published but has no episode ready to go out.",
                    fix=(
                        "Publish at least one episode, or set the show back to draft. "
                        "A show with no episodes would appear as an empty row."
                    ),
                    location=loc,
                )
            )

        if show_issues:
            groups.append(
                IssueGroup(
                    key=f"show:{show.id}",
                    title=show.title,
                    kind="show",
                    id=str(show.id),
                    issues=show_issues,
                )
            )

    groups.extend(_import_reject_groups(db))

    # Blocking first, then by title, so the editor's first screen is the work.
    groups.sort(key=lambda g: (not g.blocking, g.kind, g.title))

    blocking = sum(1 for g in groups for i in g.issues if i.severity == "blocking")
    warnings = sum(1 for g in groups for i in g.issues if i.severity == "warning")
    return ValidationReport(
        blocking_count=blocking,
        warning_count=warnings,
        can_publish=blocking == 0,
        groups=groups,
    )


def _episode_label(show: Show, season: Season, ep: Episode) -> str:
    if season.season_number == TRAILER_SEASON:
        return f"{show.title} — Trailer: {ep.title} ({ep.language})"
    return (
        f"{show.title} — S{season.season_number}E{ep.episode_number} "
        f"{ep.title} ({ep.language})"
    )


def _episode_issues(
    ep: Episode, season: Season, show: Show, art: dict, ref
) -> list[Issue]:
    issues: list[Issue] = []
    if ep.status != "published":
        # A draft episode is allowed to be incomplete -- that is what draft means.
        return issues

    loc = {
        "type": "episode",
        "id": str(ep.id),
        "show_id": str(show.id),
        "label": _episode_label(show, season, ep),
    }

    if not ep.duration_seconds:
        issues.append(
            Issue(
                severity="blocking",
                code="episode_missing_duration",
                message=f"“{ep.title}” is published but has no run time.",
                fix="Add the run time in minutes and seconds. The viewer app shows it "
                "on the episode list and uses it for the progress bar.",
                location=loc,
            )
        )

    have = art.get(("episode", str(ep.id)), set())
    for kind in REQUIRED_EPISODE_ARTWORK:
        if kind not in have:
            spec = ref.spec(kind)
            issues.append(
                Issue(
                    severity="blocking",
                    code=f"episode_missing_{kind}",
                    message=f"“{ep.title}” is published but has no {kind} image.",
                    fix=(
                        f"Upload a {spec.aspect_label} {kind} "
                        f"({spec.target_w}x{spec.target_h}, under {spec.max_kb} KB). "
                        "Without it the episode would be a grey box in the episode list."
                    ),
                    location=loc,
                )
            )

    if ep.language not in ref.languages:
        issues.append(
            Issue(
                severity="blocking",
                code="episode_unknown_language",
                message=f"“{ep.title}” is in language “{ep.language}”, which isn't supported.",
                fix="Change it to one of: " + ", ".join(ref.languages) + ".",
                location=loc,
            )
        )

    return issues


def _import_reject_groups(db: Session) -> list[IssueGroup]:
    rejects = (
        db.query(ImportReject)
        .filter(ImportReject.resolved.is_(False))
        .order_by(ImportReject.created_at)
        .all()
    )
    if not rejects:
        return []
    return [
        IssueGroup(
            key=f"import:{r.id}",
            title=f"Import conflict — {r.source_ref or r.source}",
            kind="import",
            id=str(r.id),
            issues=[
                Issue(
                    # A rejected import is not blocking: the row never made it
                    # into the database, so the catalogue is consistent without
                    # it. It is loud, though -- somebody is missing an episode.
                    severity="warning",
                    code=r.reason_code,
                    message=r.reason,
                    fix=(
                        "Check with whoever supplied the file which version is correct, "
                        "then create the episode by hand or re-import a corrected row. "
                        "Mark this resolved once it's sorted."
                    ),
                    location={"type": "import_reject", "id": str(r.id), "payload": r.payload},
                )
            ],
        )
        for r in rejects
    ]
