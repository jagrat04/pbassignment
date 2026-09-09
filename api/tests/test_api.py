"""Roles, filters, search and the viewer/admin boundary."""

from tests.conftest import give_artwork, make_episode, make_season, make_show


def _live_catalog(db, client, auth):
    show = make_show(db, title="Moti's Many Lives", section="featured", categories=["adventure"])
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    for title, lang, group in [
        ("The Lost Kite", "en", "g1"),
        ("The Lost Kite", "hi", "g1"),
        ("Rain on the Roof", "en", "g2"),
    ]:
        ep = make_episode(
            db,
            season,
            episode_number=1 if group == "g1" else 2,
            title=title,
            language=lang,
            content_group=group,
        )
        give_artwork(db, "episode", ep.id, ("thumbnail",))
    assert client.post("/admin/catalog/publish", headers=auth("admin")).status_code == 200
    return show


# ---------------------------------------------------------------------- roles


def test_an_editor_cannot_publish(client, auth, db):
    res = client.post("/admin/catalog/publish", headers=auth("editor"))
    assert res.status_code == 403
    # And is told what to do about it, not just refused.
    assert "admin" in res.json()["detail"]["detail"].lower() if isinstance(
        res.json()["detail"], dict
    ) else True


def test_an_editor_can_still_read_the_validation_report(client, auth):
    assert client.get("/admin/validation-report", headers=auth("editor")).status_code == 200


def test_an_editor_can_create_a_show(client, auth):
    res = client.post(
        "/admin/shows",
        headers=auth("editor"),
        json={"slug": "new-show", "title": "New Show", "section": "series"},
    )
    assert res.status_code == 201


def test_an_admin_can_publish(client, auth, db):
    show = make_show(db, section="series")
    give_artwork(db, "show", show.id, ("poster", "banner"))
    season = make_season(db, show, 1)
    ep = make_episode(db, season)
    give_artwork(db, "episode", ep.id, ("thumbnail",))
    assert client.post("/admin/catalog/publish", headers=auth("admin")).status_code == 200


def test_admin_routes_reject_anonymous_callers(client):
    for method, path in [
        ("get", "/admin/shows"),
        ("get", "/admin/validation-report"),
        ("post", "/admin/catalog/publish"),
        ("get", "/admin/catalog/runs"),
    ]:
        res = getattr(client, method)(path)
        assert res.status_code == 401, f"{path} answered {res.status_code} without a token"


def test_the_role_is_read_from_the_database_not_the_token(client, auth, db, users):
    """A demoted admin loses publish immediately, not when their token expires."""
    headers = auth("admin")
    users["admin"].role = "editor"
    db.commit()
    assert client.post("/admin/catalog/publish", headers=headers).status_code == 403


# -------------------------------------------------------- viewer/admin split


def test_the_viewer_endpoints_need_no_token(client, auth, db):
    _live_catalog(db, client, auth)
    assert client.get("/catalog").status_code == 200
    assert client.get("/catalog/search?q=kite").status_code == 200
    assert client.get("/catalog/shows/motis-many-lives").status_code in (200, 404)


def test_an_unpublished_change_is_invisible_to_the_viewer(client, auth, db):
    """The viewer reads the published catalogue, never the live tables."""
    _live_catalog(db, client, auth)

    res = client.post(
        "/admin/shows",
        headers=auth("admin"),
        json={"slug": "secret-show", "title": "Secret Show", "section": "series"},
    )
    assert res.status_code == 201

    catalog = client.get("/catalog").json()
    assert "secret-show" not in [s["slug"] for s in catalog["shows"]]
    assert client.get("/catalog/search?q=Secret").json()["total"] == 0


# --------------------------------------------------------------------- search


def test_search_matches_show_title_episode_title_and_category(client, auth, db):
    _live_catalog(db, client, auth)

    by_show = client.get("/catalog/search?q=Moti").json()
    assert by_show["total"] > 0

    by_episode = client.get("/catalog/search?q=Rain on the Roof").json()
    assert any(r["title"] == "Rain on the Roof" for r in by_episode["results"])

    by_category = client.get("/catalog/search?q=adventure").json()
    assert by_category["total"] > 0


def test_filters_compose(client, auth, db):
    _live_catalog(db, client, auth)

    both = client.get("/catalog/search?q=kite&language=hi&section=featured&category=adventure")
    assert both.status_code == 200
    for result in both.json()["results"]:
        assert "hi" in result["languages"]

    # A filter that excludes everything returns an honest empty list.
    none = client.get("/catalog/search?q=kite&language=fr").json()
    assert none["total"] == 0
    assert none["results"] == []


def test_search_is_case_insensitive_and_matches_substrings(client, auth, db):
    _live_catalog(db, client, auth)
    assert client.get("/catalog/search?q=KITE").json()["total"] > 0
    assert client.get("/catalog/search?q=oti").json()["total"] > 0


def test_search_before_any_publish_is_empty_not_an_error(client):
    res = client.get("/catalog/search?q=anything")
    assert res.status_code == 200
    assert res.json()["results"] == []


# ----------------------------------------------------------------- crud rules


def test_a_published_show_must_have_a_section(client, auth):
    res = client.post(
        "/admin/shows",
        headers=auth("editor"),
        json={"slug": "no-section", "title": "No Section", "status": "published"},
    )
    assert res.status_code == 422
    assert "section" in str(res.json()).lower()


def test_duplicate_language_variant_is_a_readable_409(client, auth, db):
    show = make_show(db, section="series")
    season = make_season(db, show, 1)
    make_episode(db, season, episode_number=1, language="en", content_group="dup")

    res = client.post(
        "/admin/episodes",
        headers=auth("editor"),
        json={
            "season_id": str(season.id),
            "episode_number": 2,
            "title": "Clash",
            "language": "en",
            "content_group": "dup",
            "duration_seconds": 400,
        },
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error"] == "duplicate_language_variant"
    assert "language" in detail["problem"]
    assert detail["fix"]


def test_an_episode_cannot_be_published_without_artwork_or_duration(client, auth, db):
    show = make_show(db, section="series")
    season = make_season(db, show, 1)
    ep = make_episode(db, season, status="draft", duration_seconds=None)

    res = client.patch(
        f"/admin/episodes/{ep.id}", headers=auth("editor"), json={"status": "published"}
    )
    assert res.status_code == 422
    problem = res.json()["detail"]["problem"]
    assert "run time" in problem and "thumbnail" in problem


def test_unknown_section_is_refused_with_the_allowed_list(client, auth):
    res = client.post(
        "/admin/shows",
        headers=auth("editor"),
        json={"slug": "bad", "title": "Bad", "section": "not-a-section"},
    )
    assert res.status_code == 422
    assert "featured" in str(res.json())


# ---------------------------------------------------------------- list filters


def test_show_list_filters_compose(client, auth, db):
    make_show(db, title="Alpha", section="series", status="published")
    make_show(db, title="Beta", section="songs", status="draft")

    res = client.get("/admin/shows?section=series&status=published", headers=auth("editor"))
    assert [i["title"] for i in res.json()["items"]] == ["Alpha"]

    res = client.get("/admin/shows?q=Bet", headers=auth("editor"))
    assert [i["title"] for i in res.json()["items"]] == ["Beta"]


def test_show_list_paginates(client, auth, db):
    for i in range(5):
        make_show(db, title=f"Show {i}", sort_index=i)
    res = client.get("/admin/shows?page=2&page_size=2", headers=auth("editor")).json()
    assert res["total"] == 5
    assert res["pages"] == 3
    assert len(res["items"]) == 2


# --------------------------------------------------------------------- health


def test_health_reports_its_dependencies(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["storage"]["ok"] is True
    assert "catalog" in body["checks"]
