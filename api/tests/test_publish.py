"""The publish job: grouping, determinism, atomicity, idempotence, recording."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Episode, PublishRun
from app.services.catalog_builder import build_catalog, canonical_json
from app.services.publish import PublishBlocked, current_run, publish, reap_interrupted_runs
from app.storage import get_storage
from tests.conftest import give_artwork, make_episode, make_season, make_show


def _complete_show(db, **kwargs):
    """A show that passes validation, so tests can isolate one failure at a time."""
    show = make_show(db, **kwargs)
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    return show, season


def _publishable_episode(db, season, **kwargs):
    ep = make_episode(db, season, **kwargs)
    give_artwork(db, "episode", ep.id, ("thumbnail",))
    return ep


# ------------------------------------------------------------------ grouping


def test_language_variants_collapse_into_one_entry(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season, language="en", content_group="g1", title="The Lost Kite")
    _publishable_episode(db, season, language="hi", content_group="g1", title="पतंग")

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))

    episodes = catalog["shows"][0]["seasons"][0]["episodes"]
    assert len(episodes) == 1, "two language variants should be one catalogue entry"
    assert episodes[0]["languages"] == ["en", "hi"]
    # The primary variant decides the entry's title; both are reachable.
    assert episodes[0]["title"] == "The Lost Kite"
    assert {v["language"] for v in episodes[0]["variants"]} == {"en", "hi"}
    assert outcome.counts["language_variants_collapsed"] == 1


def test_ungrouped_episodes_do_not_collapse_together(db, users):
    """Two episodes with NULL content_group are two episodes, not one."""
    show, season = _complete_show(db)
    _publishable_episode(db, season, episode_number=1, content_group=None, title="One")
    _publishable_episode(db, season, episode_number=2, content_group=None, title="Two")

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    assert len(catalog["shows"][0]["seasons"][0]["episodes"]) == 2


def test_content_group_language_pair_is_unique_in_the_database(db):
    show, season = _complete_show(db)
    make_episode(db, season, episode_number=1, language="en", content_group="g1")
    with pytest.raises(IntegrityError):
        # Same group, same language, different slot -- still a conflict.
        make_episode(db, season, episode_number=2, language="en", content_group="g1")
    db.rollback()


def test_trailers_are_kept_out_of_the_seasons_list(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season, episode_number=1)
    trailer_season = make_season(db, show, 0)
    _publishable_episode(db, trailer_season, episode_number=1, title="Trailer", duration_seconds=75)

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    doc = catalog["shows"][0]

    assert [s["season_number"] for s in doc["seasons"]] == [1]
    assert len(doc["trailers"]) == 1
    assert doc["trailers"][0]["is_trailer"] is True


# ------------------------------------------------------- published-only rule


def test_drafts_never_reach_the_catalogue(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season, episode_number=1, title="Live one")
    draft = make_episode(db, season, episode_number=2, title="Not ready", status="draft")
    give_artwork(db, "episode", draft.id, ("thumbnail",))

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    titles = [e["title"] for e in catalog["shows"][0]["seasons"][0]["episodes"]]
    assert titles == ["Live one"]


def test_a_draft_show_is_absent_even_with_published_episodes(db, users):
    show, season = _complete_show(db, status="draft")
    _publishable_episode(db, season)
    live, live_season = _complete_show(db)
    _publishable_episode(db, live_season)

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    assert [s["slug"] for s in catalog["shows"]] == [live.slug]


# --------------------------------------------------------------- determinism


def test_two_builds_of_the_same_data_are_byte_identical(db):
    show, season = _complete_show(db)
    for n in range(1, 6):
        _publishable_episode(db, season, episode_number=n, content_group=f"g{n}")

    now = datetime.now(UTC)
    first = build_catalog(db, generated_at=now, run_id="fixed")
    second = build_catalog(db, generated_at=now, run_id="fixed")
    assert canonical_json(first.catalog) == canonical_json(second.catalog)


def test_shows_are_ordered_by_sort_index_then_title(db, users):
    for title, idx in [("Zebra", 0), ("Apple", 0), ("Mango", -1)]:
        show, season = _complete_show(db, title=title, sort_index=idx, section="series")
        _publishable_episode(db, season)

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    assert [s["title"] for s in catalog["shows"]] == ["Mango", "Apple", "Zebra"]


def test_sections_follow_reference_order(db, users):
    # reference.json order is featured, series, minisodes, songs.
    for section in ("songs", "featured", "series"):
        show, season = _complete_show(db, section=section)
        _publishable_episode(db, season)

    outcome = publish(db, users["admin"])
    catalog = json.loads(get_storage().get(outcome.catalog_key))
    assert [s["key"] for s in catalog["sections"]] == ["featured", "series", "songs"]


# ----------------------------------------------------------------- recording


def test_the_run_records_who_when_and_what(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season)

    outcome = publish(db, users["admin"])
    run = db.get(PublishRun, outcome.run_id)

    assert run.status == "success"
    assert run.actor_email == "admin@test"
    assert run.finished_at is not None
    assert run.counts["shows"] == 1
    assert run.counts["episodes"] == 1
    assert run.is_current is True
    assert run.catalog_checksum


def test_only_one_run_is_ever_current(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season)
    publish(db, users["admin"])

    _publishable_episode(db, season, episode_number=2, content_group="second")
    publish(db, users["admin"])

    current = db.query(PublishRun).filter(PublishRun.is_current.is_(True)).all()
    assert len(current) == 1


# ---------------------------------------------------------------- idempotence


def test_publishing_twice_with_no_changes_is_a_no_op(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season)

    first = publish(db, users["admin"])
    second = publish(db, users["admin"])

    assert second.unchanged is True
    assert second.checksum == first.checksum
    # The live pointer did not move, so the viewer's ETag still matches.
    assert current_run(db).catalog_key == first.catalog_key


def test_a_real_change_produces_a_new_version(db, users):
    show, season = _complete_show(db)
    ep = _publishable_episode(db, season)
    first = publish(db, users["admin"])

    ep.title = "Renamed"
    db.commit()
    second = publish(db, users["admin"])

    assert second.unchanged is False
    assert second.checksum != first.checksum
    assert second.catalog_key != first.catalog_key
    # The previous version is still there -- which is what makes rollback cheap.
    assert get_storage().exists(first.catalog_key)


# ------------------------------------------------------------------ blocking


def test_publish_refuses_while_something_is_blocking(db, users):
    show, season = _complete_show(db)
    # Published, but with no thumbnail: it could not be rendered.
    make_episode(db, season, title="No artwork")

    with pytest.raises(PublishBlocked) as exc:
        publish(db, users["admin"])
    assert exc.value.report["blocking_count"] >= 1
    assert current_run(db) is None, "a blocked publish must not change what is live"


def test_forcing_publishes_the_rest_and_records_the_exclusion(db, users):
    show, season = _complete_show(db)
    _publishable_episode(db, season, episode_number=1, title="Fine")
    make_episode(db, season, episode_number=2, title="Broken")

    outcome = publish(db, users["admin"], force=True, force_reason="launch tonight")

    catalog = json.loads(get_storage().get(outcome.catalog_key))
    titles = [e["title"] for e in catalog["shows"][0]["seasons"][0]["episodes"]]
    assert titles == ["Fine"]
    assert any("Broken" in ex["title"] for ex in outcome.exclusions)
    assert "launch tonight" in db.get(PublishRun, outcome.run_id).error


# ------------------------------------------------------------------ atomicity


def test_a_failed_publish_leaves_the_live_catalogue_alone(db, users, monkeypatch):
    show, season = _complete_show(db)
    _publishable_episode(db, season, title="Original")
    good = publish(db, users["admin"])

    # Break the write half-way through the next run.
    ep = db.query(Episode).first()
    ep.title = "Changed"
    db.commit()

    from app.storage.local import LocalStorage

    def explode(self, key, data, content_type):
        raise OSError("No space left on device")

    monkeypatch.setattr(LocalStorage, "put_atomic", explode)

    with pytest.raises(OSError):
        publish(db, users["admin"])

    # The pointer never moved, so viewers are still on the last good version.
    assert str(current_run(db).id) == good.run_id
    catalog = json.loads(get_storage().get(current_run(db).catalog_key))
    assert catalog["shows"][0]["seasons"][0]["episodes"][0]["title"] == "Original"

    failed = (
        db.query(PublishRun)
        .filter(PublishRun.status == "failed")
        .order_by(PublishRun.started_at.desc())
        .first()
    )
    assert failed is not None and "No space left" in failed.error


def test_a_corrupted_write_is_caught_before_the_pointer_moves(db, users, monkeypatch):
    show, season = _complete_show(db)
    _publishable_episode(db, season)

    from app.storage.local import LocalStorage

    # Write succeeds but stores the wrong bytes -- a silent truncation.
    original = LocalStorage.put_atomic

    def truncating(self, key, data, content_type):
        return original(self, key, data[: len(data) // 2], content_type)

    monkeypatch.setattr(LocalStorage, "put_atomic", truncating)

    with pytest.raises(RuntimeError, match="does not match"):
        publish(db, users["admin"])
    assert current_run(db) is None


def test_an_interrupted_run_is_reaped_and_never_becomes_live(db, users):
    """What happens if the process dies mid-publish."""
    from datetime import timedelta

    stuck = PublishRun(
        actor_user_id=users["admin"].id,
        actor_email="admin@test",
        status="running",
        started_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db.add(stuck)
    db.commit()

    assert reap_interrupted_runs(db) == 1
    db.refresh(stuck)
    assert stuck.status == "failed"
    assert stuck.is_current is False
    assert "was not changed" in stuck.error
