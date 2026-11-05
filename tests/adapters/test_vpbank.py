"""VPBank savings adapter (OCR), against the PDF and listing saved on 2026-10-26.

Fast tests run the strict rules on recorded OCR output (savings_2026-10-26.ocr.json).
test_live_ocr_matches_recording re-runs Tesseract on the PDF (slow, ~90 s).
"""

import copy
import datetime as dt
import json
import shutil
from decimal import Decimal
from typing import Any

import pytest

from core.enums import Channel, InterestPayment
from pipeline.adapters.base import AdapterBroken
from pipeline.adapters.vpbank import extract_grids, newest_document_path, records_from_grids
from pipeline.records import SavingsRateRecord
from tests.adapters.conftest import FIXTURES, fixture_bytes

OCR = json.loads((FIXTURES / "vpbank" / "savings_2026-10-26.ocr.json").read_text())
LISTING = fixture_bytes("vpbank", "document_list_2026-10-26.json")
END, UPFRONT = InterestPayment.END, InterestPayment.UPFRONT
STANDARD = "Tiết kiệm thường/Tiền gửi có kỳ hạn lĩnh lãi cuối kỳ"
PREPAID = "Tiết kiệm/Tiền gửi có kỳ hạn trả lãi trước"
B = 1_000_000_000

Key = tuple[str, Channel, int, int, int]


@pytest.fixture(scope="module")
def records() -> dict[Key, SavingsRateRecord]:
    parsed: list[SavingsRateRecord] = records_from_grids(OCR)  # type: ignore[assignment]
    out = {
        (r.product_name, r.channel, r.term_months, r.term_days, r.min_amount_vnd): r for r in parsed
    }
    assert len(out) == len(parsed) == 206
    return out


@pytest.mark.parametrize(
    ("product", "channel", "months", "days", "amount", "rate"),
    [
        # Values checked by eye against the rendered PDF page.
        (STANDARD, Channel.COUNTER, 0, 7, 0, "0.40"),  # 1-3 tuần, merged cell
        (STANDARD, Channel.COUNTER, 1, 0, 0, "4.45"),
        (STANDARD, Channel.COUNTER, 6, 0, 0, "6.30"),
        (STANDARD, Channel.COUNTER, 6, 0, 10 * B, "6.80"),
        (STANDARD, Channel.COUNTER, 12, 0, 50 * B, "6.90"),
        (STANDARD, Channel.COUNTER, 15, 0, 0, "6.90"),
        (STANDARD, Channel.COUNTER, 36, 0, 0, "5.80"),
        (STANDARD, Channel.ONLINE, 1, 0, 0, "4.75"),
        (STANDARD, Channel.ONLINE, 12, 0, 0, "6.70"),
        (STANDARD, Channel.ONLINE, 15, 0, 3 * B, "7.40"),
        (STANDARD, Channel.ONLINE, 24, 0, 0, "7.10"),
        (PREPAID, Channel.COUNTER, 1, 0, 0, "4.43"),
        (PREPAID, Channel.COUNTER, 13, 0, 0, "5.99"),  # once misread as 5.95 when cropped by cell
        (PREPAID, Channel.COUNTER, 36, 0, 5 * B, "4.94"),
    ],
)
def test_exact_rates(
    records: dict[Key, SavingsRateRecord],
    product: str,
    channel: Channel,
    months: int,
    days: int,
    amount: int,
    rate: str,
) -> None:
    assert records[(product, channel, months, days, amount)].rate_pct == Decimal(rate)


def test_fields(records: dict[Key, SavingsRateRecord]) -> None:
    for (product, *_), r in records.items():
        assert r.effective_from == dt.date(2026, 10, 24)
        assert r.interest_payment == (UPFRONT if product == PREPAID else END)


def test_listing_gives_newest_pdf() -> None:
    assert newest_document_path(LISTING) == (
        "/-/media/vpbank-latest/tai-lieu-bieu-mau/lai-suat-huy-dong/khcn/2026/"
        "2.-20261024-Phu-luc-BLS-niem-yet.pdf"
    )


# --------------------------------------------------------------------------- strict checks


def _blank_headers(n: int) -> Any:
    def apply(d: dict[str, Any]) -> None:
        for i in range(n):
            d["tables"][0]["headers"][i] = None

    return apply


def mutated(change: Any) -> dict[str, Any]:
    data = copy.deepcopy(OCR)
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(effective=None), "effective date"),
        (lambda d: d["tables"].pop(), "expected 3 tables"),
        (lambda d: d["tables"][0]["values"][2].__setitem__(4, None), "unreadable or malformed"),
        (lambda d: d["tables"][0]["values"][2].__setitem__(4, "465"), "unreadable or malformed"),
        (lambda d: d["tables"][0]["values"][2].__setitem__(4, "9.65"), "fall as the amount rises"),
        (lambda d: d["tables"][1]["values"][0].__setitem__(0, "0.00"), "implausible rate"),
        (lambda d: d["tables"][0]["labels"].__setitem__(4, "≥100"), "amount tiers changed"),
        (lambda d: d["tables"][0]["headers"].__setitem__(5, "7T"), "column for 6T reads '7T'"),
        (_blank_headers(3), "only 12 of 17"),
        (lambda d: d["tables"][2]["images_per_cell"][0].__setitem__(3, 2), "exactly one number"),
        (lambda d: d["tables"][0]["values"][0].pop(), "grid shape changed"),
        (lambda d: d["tables"][1].update(weeks="0,40%"), "'1-3 tuần' rate unreadable"),
    ],
    ids=[
        "date",
        "table count",
        "unreadable cell",
        "missing dot",
        "tier order",
        "implausible",
        "tier labels",
        "wrong header",
        "too few headers",
        "two numbers",
        "shape",
        "weeks",
    ],
)
def test_strict_checks_raise(change: Any, message: str) -> None:
    with pytest.raises(AdapterBroken, match=message):
        records_from_grids(mutated(change))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(data=[]), "unexpected shape"),
        (lambda d: d["data"][0].update(title="Biểu phí dịch vụ"), "not a KHCN rate sheet"),
        (lambda d: d["data"][0]["itemList"].clear(), "expected one rate-sheet PDF"),
        (
            lambda d: d["data"][0]["itemList"][0].update(url="https://evil.example/x.pdf"),
            "expected one rate-sheet PDF",
        ),
    ],
)
def test_listing_changes_raise(change: Any, message: str) -> None:
    data = json.loads(LISTING)
    change(data)
    with pytest.raises(AdapterBroken, match=message):
        newest_document_path(json.dumps(data).encode())


def test_not_a_pdf_raises() -> None:
    with pytest.raises(AdapterBroken, match="not a PDF"):
        extract_grids(b"<html/>")


@pytest.mark.ocr
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_live_ocr_matches_recording() -> None:
    """Real OCR must reproduce the recorded rates exactly (headers may vary by version)."""
    live = extract_grids(fixture_bytes("vpbank", "savings_2026-10-26.pdf"))
    assert live["effective"] == OCR["effective"]
    for got, want in zip(live["tables"], OCR["tables"], strict=True):
        assert got["values"] == want["values"]
        assert got["labels"] == want["labels"]
        assert got["weeks"] == want["weeks"]
    assert records_from_grids(live) == records_from_grids(OCR)
