"""The validation report is the screen an editor reads when they are stuck.

These tests check the two things that matter about it: that it catches the
right problems, and that what it says is usable by someone who does not know
what a foreign key is.
"""

from app.services.validation import build_validation_report
from tests.conftest import give_artwork, make_episode, make_season, make_show


def test_a_clean_catalogue_reports_nothing(db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    ep = make_episode(db, season)
    give_artwork(db, "episode", ep.id, ("thumbnail",))

    report = build_validation_report(db)
    assert report.can_publish is True
    assert report.blocking_count == 0


def test_a_published_show_without_a_section_blocks(db):
    show = make_show(db, section=None, status="published")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    report = build_validation_report(db)

    assert report.can_publish is False
    codes = [i.code for g in report.groups for i in g.issues]
    assert "show_missing_section" in codes


def test_a_draft_show_without_a_section_only_warns(db):
    """This is the rhyme-rangers case in the seed file: incomplete, not broken."""
    make_show(db, section=None, status="draft")
    report = build_validation_report(db)

    assert report.can_publish is True
    assert report.warning_count >= 1


def test_a_published_episode_without_a_thumbnail_blocks(db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    make_episode(db, season, title="The Midnight Market")

    report = build_validation_report(db)
    assert report.can_publish is False
    group = next(g for g in report.groups if g.kind == "episode")
    assert "The Midnight Market" in group.title
    assert "thumbnail" in group.issues[0].message


def test_a_published_episode_without_a_duration_blocks(db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    ep = make_episode(db, season, duration_seconds=None)
    give_artwork(db, "episode", ep.id, ("thumbnail",))

    report = build_validation_report(db)
    codes = [i.code for g in report.groups for i in g.issues]
    assert "episode_missing_duration" in codes


def test_a_draft_episode_is_allowed_to_be_incomplete(db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    make_episode(db, season, status="draft", duration_seconds=None)
    ok = make_episode(db, season, episode_number=2)
    give_artwork(db, "episode", ok.id, ("thumbnail",))

    report = build_validation_report(db)
    assert report.can_publish is True


def test_a_published_show_with_nothing_publishable_blocks(db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    make_episode(db, season, status="draft")

    report = build_validation_report(db)
    codes = [i.code for g in report.groups for i in g.issues]
    assert "show_no_publishable_episodes" in codes


def test_issues_are_grouped_by_the_thing_you_go_and_fix(db):
    show = make_show(db, section=None, status="published")
    season = make_season(db, show, 1)
    make_episode(db, season, title="Broken One")
    make_episode(db, season, episode_number=2, title="Broken Two")

    report = build_validation_report(db)
    kinds = [g.kind for g in report.groups]
    assert kinds.count("episode") == 2
    assert kinds.count("show") == 1
    # Blocking work comes first, so the editor's first screen is the work.
    assert report.groups[0].blocking is True


def test_every_issue_carries_a_fix_and_a_place_to_go(db):
    show = make_show(db, section=None, status="published")
    season = make_season(db, show, 1)
    make_episode(db, season, duration_seconds=None)

    report = build_validation_report(db)
    for group in report.groups:
        for issue in group.issues:
            assert issue.fix.strip(), f"{issue.code} has no suggested fix"
            assert issue.location.get("id"), f"{issue.code} has nowhere to click through to"
            # No identifiers or jargon in the editor-facing sentence.
            assert "uuid" not in issue.message.lower()
            assert "null" not in issue.message.lower()
