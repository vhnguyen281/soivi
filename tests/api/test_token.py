"""API_TOKEN: when set, only callers sending X-Soivi-Token get through (the public site)."""

import pytest
from sqlalchemy.orm import Session

from tests.api.conftest import Clock, MemoryStore, make_client

pytestmark = pytest.mark.db


def test_without_a_token_the_api_is_open(db: Session, store: MemoryStore, clock: Clock) -> None:
    with make_client(db, store, clock) as c:
        assert c.get("/methodology").status_code == 200
        assert c.get("/health").json() == {"status": "ok"}


def test_with_a_token_every_route_but_health_needs_it(
    db: Session, store: MemoryStore, clock: Clock
) -> None:
    with make_client(db, store, clock, api_token="s3cret-token") as c:
        assert c.get("/health").status_code == 200
        missing = c.get("/methodology")
        assert missing.status_code == 401 and missing.json()["error"] == "unauthorised"
        assert c.get("/methodology", headers={"X-Soivi-Token": "wrong"}).status_code == 401
        assert c.get("/docs").status_code == 401
        ok = c.get("/methodology", headers={"X-Soivi-Token": "s3cret-token"})
        assert ok.status_code == 200 and ok.headers["X-Methodology-Version"]
