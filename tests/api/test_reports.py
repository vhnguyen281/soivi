"""POST /reports: stored for triage, screenshot checks, rate limit, captcha."""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.common import HEADER
from api.reports import SiteVerifyCaptcha
from core.models import CommunityReport
from core.scoring import METHODOLOGY_VERSION
from pipeline.fetch.storage import MemoryStore
from tests.api.conftest import Clock, World, make_client

pytestmark = pytest.mark.db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MESSAGE = "Lãi suất 12 tháng trên web đã đổi thành 6,3%"


def report(db: Session, report_id: int) -> CommunityReport:
    db.expire_all()
    found = db.get(CommunityReport, report_id)
    assert found is not None
    return found


def test_report_is_stored(client: TestClient, world: World, db: Session) -> None:
    r = client.post(
        "/reports",
        data={
            "message": MESSAGE,
            "institution": "vidu",
            "product_ref": "Tiết kiệm thường 12 tháng",
            "contact": "nguoidung@example.com",
        },
    )
    assert r.status_code == 201 and r.headers[HEADER] == METHODOLOGY_VERSION
    body = r.json()
    assert body["methodology_version"] == METHODOLOGY_VERSION and body["status"] == "new"
    assert "nguoidung@example.com" not in r.text  # contact is never echoed back
    saved = report(db, body["id"])
    assert saved.institution_id == world.vidu.id and saved.message == MESSAGE
    assert saved.contact == "nguoidung@example.com" and saved.evidence_storage_key is None


def test_screenshot_is_stored(
    client: TestClient, world: World, db: Session, store: MemoryStore
) -> None:
    r = client.post(
        "/reports", data={"message": MESSAGE}, files={"screenshot": ("anh.png", PNG, "image/png")}
    )
    assert r.status_code == 201
    key = report(db, r.json()["id"]).evidence_storage_key
    assert key is not None and key.startswith("reports/") and key.endswith(".png")
    assert store.get(key) == PNG


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"MZ not an image", 400),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 6_000_000, 413),
    ],
)
def test_bad_screenshots(client: TestClient, world: World, data: bytes, status: int) -> None:
    r = client.post(
        "/reports", data={"message": MESSAGE}, files={"screenshot": ("anh.png", data, "image/png")}
    )
    assert r.status_code == status and r.json()["methodology_version"] == METHODOLOGY_VERSION


@pytest.mark.parametrize(
    ("data", "status"),
    [
        ({"message": "ngắn"}, 422),
        ({"message": MESSAGE, "institution": "NOPE"}, 400),
        ({}, 422),
    ],
)
def test_bad_reports(client: TestClient, world: World, data: dict[str, str], status: int) -> None:
    assert client.post("/reports", data=data).status_code == status


def test_rate_limit_per_ip(client: TestClient, world: World, clock: Clock) -> None:
    for _ in range(3):
        assert client.post("/reports", data={"message": MESSAGE}).status_code == 201
    blocked = client.post("/reports", data={"message": MESSAGE})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["methodology_version"] == METHODOLOGY_VERSION
    clock.now += 3601
    assert client.post("/reports", data={"message": MESSAGE}).status_code == 201


def _captcha(success: bool) -> tuple[SiteVerifyCaptcha, list[dict[str, str]]]:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"success": success})

    return SiteVerifyCaptcha("turnstile", "s3cret", httpx.MockTransport(handler)), seen


def test_captcha_when_configured(
    db: Session, store: MemoryStore, clock: Clock, world: World
) -> None:
    good, seen = _captcha(True)
    with make_client(db, store, clock, captcha=good) as c:
        assert c.post("/reports", data={"message": MESSAGE}).status_code == 400  # no token
        ok = c.post("/reports", data={"message": MESSAGE, "captcha_token": "tok"})
        assert ok.status_code == 201
    assert seen[-1]["secret"] == "s3cret" and seen[-1]["response"] == "tok"
    bad, _ = _captcha(False)
    with make_client(db, store, clock, captcha=bad) as c:
        r = c.post("/reports", data={"message": MESSAGE, "captcha_token": "forged"})
        assert r.status_code == 400 and r.json()["error"] == "captcha check failed"
    stored = db.scalars(select(CommunityReport)).all()
    assert len(stored) == 1
