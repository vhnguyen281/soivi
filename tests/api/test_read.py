"""GET endpoints: values, filters, provenance, unverified flag, history, changes."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.common import HEADER
from core.scoring import METHODOLOGY_VERSION
from tests.api.conftest import CARDS_URL, RATES_URL, World

pytestmark = pytest.mark.db


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    assert response.headers[HEADER] == METHODOLOGY_VERSION
    body: dict[str, Any] = response.json()
    assert body["methodology_version"] == METHODOLOGY_VERSION
    return body


def provenance_ok(p: dict[str, Any]) -> None:
    assert set(p) >= {"source_url", "checked_at", "effective_from", "methodology_version"}
    assert p["methodology_version"] == METHODOLOGY_VERSION


# --------------------------------------------------------------------------- institutions


def test_institutions(client: TestClient, world: World) -> None:
    body = ok(client.get("/institutions"))
    by_name = {i["short_name"]: i for i in body["institutions"]}
    assert set(by_name) == {"CU", "VIDU"}
    vidu, cu = by_name["VIDU"], by_name["CU"]
    assert (vidu["verification"], vidu["unverified"]) == ("verified", False)
    assert (cu["verification"], cu["unverified"]) == ("unverified", True)
    provenance_ok(vidu["provenance"])
    assert vidu["provenance"]["source_url"] == "https://vidu.example"
    assert vidu["provenance"]["checked_at"] is not None


# --------------------------------------------------------------------------- savings


def test_rates_are_current_approved_with_provenance(client: TestClient, world: World) -> None:
    body = ok(client.get("/savings/rates", params={"term": 12}))
    ids = [r["id"] for r in body["rates"]]
    assert sorted(ids) == sorted([world.live_12m, world.monthly_12m, world.cu_12m])
    assert world.old_12m not in ids and world.pending_12m not in ids
    live = next(r for r in body["rates"] if r["id"] == world.live_12m)
    assert live["rate_pct"] == "6.200"  # a string, never a float
    assert live["institution"] == {"short_name": "VIDU", "legal_name_vi": "Ngân hàng TMCP Ví Dụ"}
    p = live["provenance"]
    provenance_ok(p)
    assert p["source_url"] == RATES_URL
    assert p["checked_at"] == "2026-10-20T03:00:00Z"
    assert p["effective_from"] == "2026-10-18"
    assert p["approved_at"] == "2026-10-20T03:00:00Z"
    assert p["extraction_method"] == "html" and len(p["snapshot_sha256"]) == 64
    # re-seen unchanged on 27/10: checked_at is the later read
    monthly = next(r for r in body["rates"] if r["id"] == world.monthly_12m)
    assert monthly["provenance"]["checked_at"] == "2026-10-27T03:00:00Z"
    stale = next(r for r in body["rates"] if r["id"] == world.cu_12m)
    assert stale["unverified"] is True and live["unverified"] is False


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"term": 6}, ["live_6m"]),
        ({"term": 12, "channel": "online"}, ["monthly_12m"]),
        ({"term": 12, "institution": "cu"}, ["cu_12m"]),
        ({"amount": 1}, ["cu_12m", "live_6m", "live_12m", "monthly_12m"]),
        ({}, ["cu_12m", "live_6m", "live_12m", "monthly_12m"]),
    ],
)
def test_rate_filters(
    client: TestClient, world: World, params: dict[str, Any], expected: list[str]
) -> None:
    ids = {r["id"] for r in ok(client.get("/savings/rates", params=params))["rates"]}
    assert ids == {getattr(world, name) for name in expected}


def test_rank(client: TestClient, world: World) -> None:
    body = ok(client.get("/savings/rank", params={"amount": 100_000_000, "term": 12}))
    got = [(r["rank"], r["rate"]["id"], r["equivalent_interest_vnd"]) for r in body["results"]]
    assert got == [
        (1, world.live_12m, 6_200_000),
        (2, world.cu_12m, 6_100_000),
        (3, world.monthly_12m, 5_956_695),
    ]
    first = body["results"][0]
    provenance_ok(first["rate"]["provenance"])
    assert first["maturity_value_vnd"] == 106_200_000
    assert body["results"][1]["flags"]["unverified"] is True
    assert body["results"][2]["flags"]["rate_is_maximum"] is True
    digital = ok(
        client.get("/savings/rank", params={"amount": 1, "term": 12, "channel": "digital"})
    )
    assert [r["rate"]["id"] for r in digital["results"]] == [world.monthly_12m]


def test_history(client: TestClient, world: World) -> None:
    body = ok(client.get("/savings/history", params={"institution": "vidu", "term": 12}))
    assert body["institution"]["short_name"] == "VIDU"
    counter = next(s for s in body["series"] if s["channel"] == "counter")
    points = [
        (p["version_id"], p["rate_pct"], p["valid_from"], p["valid_to"]) for p in counter["points"]
    ]
    assert points == [
        (world.old_12m, "6.000", "2026-09-01T03:00:00Z", "2026-10-20T03:00:00Z"),
        (world.live_12m, "6.200", "2026-10-20T03:00:00Z", None),
    ]
    provenance_ok(counter["points"][0]["provenance"])
    assert counter["points"][0]["provenance"]["effective_from"] == "2026-09-01"
    every = ok(client.get("/savings/history", params={"institution": "VIDU"}))
    shown = {p["version_id"] for s in every["series"] for p in s["points"]}
    assert world.pending_12m not in shown and world.live_6m in shown


# --------------------------------------------------------------------------- cards


def test_cards(client: TestClient, world: World) -> None:
    [card] = ok(client.get("/cards"))["cards"]
    assert (card["id"], card["name"], card["network"], card["tier"]) == (
        world.card.id,
        "Ví Dụ Visa",
        "visa",
        "gold",
    )
    terms = card["terms"]
    assert terms["version_id"] == world.terms
    assert terms["values"]["annual_fee_primary_vnd"] == 500_000
    assert terms["values"]["fx_fee_pct"] == "2.500"
    provenance_ok(terms["provenance"])
    assert terms["provenance"]["source_url"] == CARDS_URL
    assert terms["provenance"]["extraction_method"] == "llm"
    assert card["rewards_count"] == 1


def test_card_detail(client: TestClient, world: World) -> None:
    card = ok(client.get(f"/cards/{world.card.id}"))["card"]
    assert card["terms"]["provenance"]["evidence"]["annual_fee_primary_vnd"]["quote"] == (
        "Ví Dụ Visa | 500.000 VND"
    )
    [reward] = card["rewards"]
    assert reward["values"]["category"] == "dining" and reward["values"]["rate_pct"] == "5.000"
    provenance_ok(reward["provenance"])
    assert card["perks"]["values"]["other_perks_text"] == "Golf"
    provenance_ok(card["perks"]["provenance"])


def test_personas(client: TestClient) -> None:
    keys = [p["key"] for p in ok(client.get("/cards/personas"))["personas"]]
    assert keys == ["everyday", "traveller", "first_card", "revolver"]


# --------------------------------------------------------------------------- changes


def test_changes(client: TestClient, world: World) -> None:
    body = ok(client.get("/changes", params={"since": "2026-10-01"}))
    by_id = {(c["table"], c["version_id"]): c for c in body["changes"]}
    assert ("savings_rate", world.old_12m) not in by_id  # approved before `since`
    moved = by_id[("savings_rate", world.live_12m)]
    assert moved["kind"] == "changed"
    assert moved["changes"] == [{"field": "rate_pct", "old": "6.000", "new": "6.200"}]
    assert moved["label"] == "Tiết kiệm thường · counter · 12 tháng"
    provenance_ok(moved["provenance"])
    assert by_id[("savings_rate", world.live_6m)]["kind"] == "new"
    terms = by_id[("card_terms", world.terms)]
    assert terms["label"] == "Ví Dụ Visa" and terms["kind"] == "new"
    # newest first
    stamps = [c["approved_at"] for c in body["changes"]]
    assert stamps == sorted(stamps, reverse=True)
    assert world.pending_12m not in {c["version_id"] for c in body["changes"]}
    everything = ok(client.get("/changes", params={"since": "2026-08-01", "limit": 500}))
    assert ("savings_rate", world.old_12m) in {
        (c["table"], c["version_id"]) for c in everything["changes"]
    }
