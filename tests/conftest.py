"""Shared fixtures.

Tests marked `db` run against a throwaway `soivi_test` database on the Postgres
from `make up` (or TEST_DATABASE_URL). It is rebuilt from the Alembic migrations
on every run, so these tests also check that the migrations apply and roll back.
If Postgres is not reachable the tests are skipped, unless SOIVI_REQUIRE_DB=1
(set in CI) turns that into a failure.
"""

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.config import get_settings

if TYPE_CHECKING:
    from pipeline.fetch.polite import PoliteHttp
    from tests.http_fixture import FakeClock, FixtureServer

ROOT = Path(__file__).resolve().parent.parent


def _test_db_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    return make_url(get_settings().database_url).set(database="soivi_test")


def _recreate_database(url: URL) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = _test_db_url()
    try:
        _recreate_database(url)
    except OperationalError as exc:
        if os.environ.get("SOIVI_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not reachable at {url.host}:{url.port} ({exc.orig}); run `make up`")

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # the downgrade path must work too
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after each test."""
    with db_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def t0() -> dt.datetime:
    return dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------------------- fetch fixtures


@pytest.fixture
def http_server() -> Iterator["FixtureServer"]:
    from tests.http_fixture import FixtureServer

    server = FixtureServer().start()
    server.route("/robots.txt", body="User-agent: *\nDisallow: /private\n")
    yield server
    server.stop()


@pytest.fixture
def fake_clock() -> "FakeClock":
    from tests.http_fixture import FakeClock

    return FakeClock()


@pytest.fixture
def polite(fake_clock: "FakeClock") -> Iterator["PoliteHttp"]:
    """PoliteHttp with the real 5 s rule, but a fake clock so tests don't wait."""
    from core.config import Settings
    from pipeline.fetch.polite import PoliteHttp

    settings = Settings(
        crawler_user_agent="SoiviTest/1.0 (+mailto:test@example.com)",
        crawler_min_delay_seconds=5,
    )
    http = PoliteHttp(
        settings=settings, timeout=0.5, clock=fake_clock.clock, sleep=fake_clock.sleep
    )
    yield http
    http.close()
