"""GET /vncma/*: approved releases only, with the VNCMA methodology version (Prompt 10)."""

import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from core.cma.config import parse_config
from core.cma.release import approve
from core.cma.run import create_run
from tests.cma.test_blocks import DOC
from tests.cma.test_run import market_data, store

pytestmark = pytest.mark.db


def test_no_release_is_a_404_and_drafts_never_show(client: TestClient, db: Session) -> None:
    store(db, market_data())
    create_run(db, parse_config(DOC), "QA")  # a draft only
    r = client.get("/vncma/latest")
    assert r.status_code == 404 and "methodology_version" in r.json()
    assert client.get("/vncma/releases").json()["releases"] == []


def test_latest_and_by_version(client: TestClient, db: Session) -> None:
    store(db, market_data())
    first = approve(db, create_run(db, parse_config(DOC), "QA").id, "2027.1", "Nguyễn Văn A")
    approve(db, create_run(db, parse_config(DOC), "QA").id, "2027.2", "Nguyễn Văn A")
    db.flush()

    latest = client.get("/vncma/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["version"] == "2027.2" and body["status"] == "released"
    assert body["methodology_version"] == "1.0.0"
    assert latest.headers["X-VNCMA-Methodology-Version"] == "1.0.0"
    assert "X-Methodology-Version" in latest.headers
    cash = next(c for c in body["classes"] if c["id"] == "cash_vnd")
    assert isinstance(cash["expected_return"], str) and cash["grade"] == "B"
    assert body["provenance"]["payload_sha256"] and body["disclaimer"]["vi"]
    assert len(body["correlation"]["matrix"]) == len(body["correlation"]["classes"]) == 8

    old = client.get("/vncma/2027.1").json()
    assert old["version"] == "2027.1" and old["approved_by"] == "Nguyễn Văn A"
    assert old["provenance"]["payload_sha256"] == first.payload_sha256
    assert client.get("/vncma/2026.9").status_code == 404
    assert [r["version"] for r in client.get("/vncma/releases").json()["releases"]] == [
        "2027.2",
        "2027.1",
    ]

    xlsx = client.get(body["downloads"]["xlsx"])
    assert (
        xlsx.status_code == 200 and "Changes" in load_workbook(io.BytesIO(xlsx.content)).sheetnames
    )
    md = client.get("/vncma/2027.2/download/md").text
    assert "VNCMA 2027.2" in md and "người duyệt: Nguyễn Văn A" in md
    assert client.get("/vncma/2027.2/download/pdf").status_code == 422
