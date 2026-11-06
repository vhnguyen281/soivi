"""Draft documents and release approval in the review app (VNCMA Prompt 8)."""

import io
import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.cma.config import parse_config
from core.cma.release import ReleaseError, approve, next_version
from core.cma.report import changes, markdown_vi, payload
from core.cma.run import create_run
from core.config import Settings
from core.models import CmaRelease, CmaReleaseValue, CmaRun
from pipeline.fetch.storage import MemoryStore
from review_app.app import create_app
from tests.cma.test_blocks import DOC
from tests.cma.test_run import market_data, store

pytestmark = pytest.mark.db
AUTH = ("reviewer", "s3cret-review")
HX = {"HX-Request": "true"}


@pytest.fixture
def run(db: Session) -> CmaRun:
    store(db, market_data())
    return create_run(db, parse_config(DOC), "QA")


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    conn = db.connection()
    assert isinstance(conn, Connection)
    app = create_app(
        Settings(review_username=AUTH[0], review_password=AUTH[1], site_revalidate_url=""),
        session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        store=MemoryStore(),
    )
    with TestClient(app) as c:
        c.auth = AUTH
        yield c


def test_payload_and_markdown_have_the_disclaimer_and_no_raw_series(run: CmaRun) -> None:
    doc = payload(run, "2027.1-draft")
    assert doc["methodology_version"] == "1.0.0" and doc["status"] == "draft"
    ids = [c["id"] for c in doc["classes"]]
    assert ids[0] == "cash_vnd" and "real_estate" in ids
    assert all(isinstance(c["expected_return"], str) for c in doc["classes"])
    assert "không phải lời khuyên đầu tư" in doc["disclaimer"]["vi"]
    assert "observations" not in json.dumps(doc)  # derived statistics only
    md = markdown_vi(doc)
    assert "Bản đầu tiên" in md and "Hạng dữ liệu" in md and doc["disclaimer"]["vi"] in md


def test_review_app_shows_the_draft_and_approves_a_named_release(
    client: TestClient, db: Session, run: CmaRun
) -> None:
    assert next_version(db, run) == "2027.1"
    page = client.get(f"/vncma/runs/{run.id}")
    assert page.status_code == 200 and "VNCMA 2027.1-draft" in page.text
    assert "Duyệt phát hành" in page.text
    assert f"/vncma/runs/{run.id}" in client.get("/vncma").text

    xlsx = client.get(f"/vncma/runs/{run.id}/download/xlsx")
    sheets = load_workbook(io.BytesIO(xlsx.content)).sheetnames
    assert sheets == [
        "Summary", "Macro", "Building blocks", "Correlation", "Scenarios", "Inputs", "Changes"
    ]  # fmt: skip
    assert client.get(f"/vncma/runs/{run.id}/download/json").json()["version"] == "2027.1-draft"

    form = {"version": "2027.1", "reviewer_name": "", "note": ""}
    assert client.post(f"/vncma/runs/{run.id}/release", data=form).status_code == 403  # no HX
    refused = client.post(f"/vncma/runs/{run.id}/release", data=form, headers=HX)
    assert refused.status_code == 409 and "named reviewer" in refused.text
    form["reviewer_name"] = "Nguyễn Văn A"
    ok = client.post(f"/vncma/runs/{run.id}/release", data=form, headers=HX)
    assert ok.status_code == 204 and ok.headers["HX-Redirect"] == f"/vncma/runs/{run.id}"

    release = db.scalar(select(CmaRelease).where(CmaRelease.run_id == run.id))
    assert release is not None and release.approved_by == "Nguyễn Văn A"
    assert release.payload["status"] == "released" and release.payload["version"] == "2027.1"
    values = list(
        db.scalars(select(CmaReleaseValue).where(CmaReleaseValue.release_id == release.id))
    )
    assert len(values) == 9
    cash = next(v for v in values if v.asset_class == "cash_vnd")
    assert cash.expected_return == Decimal(release.payload["classes"][0]["expected_return"])
    assert "Đã phát hành 2027.1" in client.get(f"/vncma/runs/{run.id}").text

    again = client.post(f"/vncma/runs/{run.id}/release", data=form, headers=HX)
    assert again.status_code == 409 and "already released" in again.text
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("DELETE FROM cma_release WHERE id = :id"), {"id": release.id})


def test_version_rules_and_changes(db: Session, run: CmaRun) -> None:
    with pytest.raises(ReleaseError, match="look like"):
        approve(db, run.id, "2027.1-draft", "A")
    first = approve(db, run.id, "2027.1", "A")
    second_run = create_run(db, parse_config(DOC), "QA")
    assert next_version(db, second_run) == "2027.2"
    with pytest.raises(ReleaseError, match="already exists"):
        approve(db, second_run.id, "2027.1", "A")
    doc = payload(second_run, "2027.2")
    rows = changes(doc, first.payload)
    assert rows and all(r["change_pp"] == "+0.00" for r in rows)  # same inputs, same values
