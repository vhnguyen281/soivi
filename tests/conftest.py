"""Shared fixtures.

Tests marked `db` run against a throwaway `soivi_test` database on the Postgres
from `make up` (or TEST_DATABASE_URL). It is rebuilt from the Alembic migrations
on every run, so these tests also check that the migrations apply and roll back.
If Postgres is not reachable the tests are skipped, unless SOIVI_REQUIRE_DB=1
(set in CI) turns that into a failure.

Tests never touch the cloud. `.env` may point DATABASE_URL at Neon and S3_* at
AWS; before anything reads settings, this file points them at the local Docker
Postgres and MinIO, and stops the run if the test database is not local.
"""

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from pipeline.fetch.polite import PoliteHttp
    from tests.http_fixture import FakeClock, FixtureServer

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "minio"}


def _pin_local_environment() -> URL:
    """Point every setting the code under test might use at local services."""
    dotenv = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}

    def get(name: str, default: str = "") -> str:
        return os.environ.get(name) or dotenv.get(name) or default

    if get("TEST_DATABASE_URL"):
        url = make_url(get("TEST_DATABASE_URL"))
    else:
        base = make_url(
            get("DATABASE_URL", "postgresql+psycopg://soivi:soivi@localhost:5432/soivi")
        )
        if base.host not in LOCAL_HOSTS:
            # .env points at the cloud: use the local Docker Postgres from POSTGRES_*.
            base = make_url(
                f"postgresql+psycopg://{get('POSTGRES_USER', 'soivi')}@localhost:"
                f"{get('POSTGRES_PORT', '5432')}/soivi"
            ).set(password=get("POSTGRES_PASSWORD") or None)
        url = base.set(database="soivi_test")
    if url.host not in LOCAL_HOSTS:
        pytest.exit(f"refusing to run tests against a non-local database ({url.host})", 2)

    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    if get("S3_ENDPOINT", "localhost:9000").split(":")[0] not in LOCAL_HOSTS:
        os.environ["S3_ENDPOINT"] = f"localhost:{get('MINIO_API_PORT', '9000')}"
        os.environ["S3_ACCESS_KEY"] = get("MINIO_ROOT_USER", "soivi")
        os.environ["S3_SECRET_KEY"] = get("MINIO_ROOT_PASSWORD")
        os.environ["S3_SECURE"] = "false"
    # No paid or outgoing calls from tests: no LLM key, no Telegram bot.
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    return url


TEST_DB_URL = _pin_local_environment()


def _test_db_url() -> URL:
    return TEST_DB_URL


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
