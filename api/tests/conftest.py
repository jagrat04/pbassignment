"""Test fixtures.

Tests run against a real Postgres, not SQLite. The parts most worth testing --
the partial unique index on (content_group, language), array containment,
pg_trgm search, the advisory lock -- do not exist on SQLite, so testing against
it would mean testing something other than what ships.
"""

import os
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Set before any app module is imported: Settings is read at import time.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://peblo:peblo@127.0.0.1:5433/peblo_test"
)
os.environ.setdefault("REFERENCE_PATH", str(REPO_ROOT / "data" / "reference.json"))
os.environ.setdefault("SEED_PATH", str(REPO_ROOT / "data" / "seed_shows.json"))
os.environ.setdefault("SEED_ASSETS_DIR", str(REPO_ROOT / "data" / "assets"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("STORAGE_BACKEND", "local")


@pytest.fixture(scope="session")
def storage_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("storage")
    os.environ["STORAGE_LOCAL_ROOT"] = str(root)
    return root


@pytest.fixture(scope="session")
def engine(storage_root):
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db import Base

    get_settings.cache_clear()
    settings = get_settings()
    eng = create_engine(settings.database_url, future=True)

    # The schema comes from the migration, not from create_all, so the tests
    # exercise the same DDL production gets -- extensions and partial indexes
    # included.
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "api" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    yield eng
    Base.metadata.clear()
    eng.dispose()


@pytest.fixture
def clean(engine):
    """Truncate between tests. Faster than re-running migrations, and it keeps
    the indexes and extensions the tests actually care about.

    Requested by `db` and `client` rather than autouse, so the pure-unit tests
    (artwork validation, catalogue building) run without a database at all.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE catalog_entries, publish_runs, artworks, episodes, seasons, "
                "shows, import_rejects, users RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def db(clean):
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(clean):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def users(db):
    from app.auth import hash_password
    from app.models import User

    admin = User(
        email="admin@test", name="Admin", role="admin", hashed_password=hash_password("pw")
    )
    editor = User(
        email="editor@test", name="Editor", role="editor", hashed_password=hash_password("pw")
    )
    db.add_all([admin, editor])
    db.commit()
    db.refresh(admin)
    db.refresh(editor)
    return {"admin": admin, "editor": editor}


@pytest.fixture
def auth(client, users):
    def _token(role: str) -> dict[str, str]:
        res = client.post(
            "/auth/login", json={"email": f"{role}@test", "password": "pw"}
        )
        assert res.status_code == 200, res.text
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    return _token


@pytest.fixture
def sample_images():
    """The images the challenge shipped, good and bad."""
    d = REPO_ROOT / "data" / "assets"
    return {p.stem: p.read_bytes() for p in d.glob("*.*")}


def make_show(db, **kwargs):
    from app.models import Show

    defaults = {
        "slug": f"show-{uuid.uuid4().hex[:8]}",
        "title": "A Show",
        "section": "series",
        "categories": ["stories"],
        "status": "published",
    }
    show = Show(**{**defaults, **kwargs})
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


def make_season(db, show, number=1):
    from app.models import Season

    season = Season(show_id=show.id, season_number=number, title=f"Season {number}")
    db.add(season)
    db.commit()
    db.refresh(season)
    return season


def make_episode(db, season, **kwargs):
    from app.models import Episode

    defaults = {
        "episode_number": 1,
        "title": "An Episode",
        "duration_seconds": 480,
        "language": "en",
        "status": "published",
    }
    ep = Episode(season_id=season.id, **{**defaults, **kwargs})
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep


def give_artwork(db, owner_type, owner_id, kinds=("poster", "banner", "thumbnail")):
    from app.models import Artwork
    from app.reference import get_reference

    for kind in kinds:
        spec = get_reference().spec(kind)
        db.add(
            Artwork(
                owner_type=owner_type,
                owner_id=owner_id,
                kind=kind,
                storage_key=f"artwork/{kind}/test.jpg",
                url=f"http://test/{kind}.jpg",
                width=spec.target_w,
                height=spec.target_h,
                bytes=1234,
                content_type="image/jpeg",
            )
        )
    db.commit()
