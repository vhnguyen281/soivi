"""POST /cards/rank, errors (all versioned), caching, and the OpenAPI docs."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.common import HEADER
from core.scoring import METHODOLOGY_VERSION
from tests.api.conftest import Clock, World

pytestmark = pytest.mark.db


def test_rank_with_persona(client: TestClient, world: World) -> None:
    r = client.post("/cards/rank", json={"persona": "everyday"})
    assert r.status_code == 200 and r.headers[HEADER] == METHODOLOGY_VERSION
    body = r.json()
    assert body["methodology_version"] == METHODOLOGY_VERSION
    [item] = body["results"]
    # dining 2M x 5% = 100.000 (= cap) x 12; fee waived (144M >= 100M)
    assert item["annual_value_vnd"] == 1_200_000 and item["breakdown"]["fee_waived"] is True
    assert item["card"]["id"] == world.card.id
    assert len(item["provenance"]) == 3  # terms, perks, reward
    for p in item["provenance"]:
        assert p["source_url"] and p["checked_at"] and "effective_from" in p
        assert p["methodology_version"] == METHODOLOGY_VERSION


def test_rank_with_profile(client: TestClient, world: World) -> None:
    body = client.post(
        "/cards/rank",
        json={
            "profile": {"monthly_spend_vnd": {"dining": 1_000_000}, "monthly_income_vnd": 5_000_000}
        },
    ).json()
    assert body["results"] == []
    assert body["not_ranked"][0]["reasons"] == ["income_below_minimum"]
    revolver = client.post("/cards/rank", json={"persona": "revolver"}).json()
    assert revolver["not_ranked"][0]["reasons"] == ["interest_rate_unknown"]


@pytest.mark.parametrize(
    ("method", "path", "kw", "status"),
    [
        ("get", "/savings/rank", {"params": {"amount": 0, "term": 12}}, 422),
        ("get", "/savings/rank", {"params": {"amount": 1, "term": 12, "channel": "atm"}}, 422),
        ("get", "/savings/rates", {"params": {"channel": "atm"}}, 422),
        ("get", "/savings/history", {"params": {"institution": "NOPE"}}, 404),
        ("get", "/savings/history", {}, 422),
        ("get", "/cards/999999", {}, 404),
        ("post", "/cards/rank", {"json": {}}, 422),
        ("post", "/cards/rank", {"json": {"persona": "everyday", "profile": {}}}, 422),
        ("post", "/cards/rank", {"json": {"persona": "student"}}, 404),
        ("post", "/cards/rank", {"json": {"profile": {"monthly_spend_vnd": {"casino": 1}}}}, 422),
        ("get", "/changes", {"params": {"since": "yesterday"}}, 422),
        ("get", "/nowhere", {}, 404),
    ],
)
def test_errors_carry_the_version(
    client: TestClient, world: World, method: str, path: str, kw: dict[str, Any], status: int
) -> None:
    r = getattr(client, method)(path, **kw)
    assert r.status_code == status
    assert r.headers[HEADER] == METHODOLOGY_VERSION
    body = r.json()
    assert body["methodology_version"] == METHODOLOGY_VERSION and body["error"]


def test_get_responses_are_cached_with_etag(client: TestClient, world: World, clock: Clock) -> None:
    first = client.get("/savings/rates")
    assert first.headers["X-Cache"] == "MISS"
    assert first.headers["Cache-Control"] == "public, max-age=60"
    second = client.get("/savings/rates")
    assert second.headers["X-Cache"] == "HIT" and second.content == first.content
    etag = first.headers["ETag"]
    not_modified = client.get("/savings/rates", headers={"If-None-Match": etag})
    assert not_modified.status_code == 304 and not not_modified.content
    assert not_modified.headers[HEADER] == METHODOLOGY_VERSION
    other_query = client.get("/savings/rates", params={"term": 6})
    assert other_query.headers["X-Cache"] == "MISS"
    clock.now += 61
    assert client.get("/savings/rates").headers["X-Cache"] == "MISS"  # expired


def test_rank_post_is_cached_by_body(client: TestClient, world: World) -> None:
    a = client.post("/cards/rank", json={"persona": "everyday"})
    b = client.post("/cards/rank", json={"persona": "everyday"})
    c = client.post("/cards/rank", json={"persona": "traveller"})
    assert (a.headers["X-Cache"], b.headers["X-Cache"], c.headers["X-Cache"]) == (
        "MISS",
        "HIT",
        "MISS",
    )
    assert "Cache-Control" not in a.headers


def test_openapi_docs(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == METHODOLOGY_VERSION
    assert set(spec["paths"]) >= {
        "/institutions",
        "/savings/rates",
        "/savings/rank",
        "/savings/history",
        "/cards",
        "/cards/{card_id}",
        "/cards/rank",
        "/changes",
        "/reports",
        "/methodology",
    }
    rates = spec["paths"]["/savings/rates"]["get"]["responses"]["200"]["content"]
    assert rates["application/json"]["schema"]["$ref"].endswith("SavingsRatesOut")
    assert "Provenance" in spec["components"]["schemas"]
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_no_cache_request_skips_the_cache(client: TestClient, world: World) -> None:
    client.get("/savings/rates")
    assert client.get("/savings/rates").headers["X-Cache"] == "HIT"
    fresh = client.get("/savings/rates", headers={"Cache-Control": "no-cache"})
    assert fresh.headers["X-Cache"] == "MISS"
    assert client.get("/savings/rates").headers["X-Cache"] == "HIT"  # refreshed copy
