"""BIDV: personal savings rates, counter and online. Notes in docs/adapters/bidv.md."""

import json
import re
from collections.abc import Sequence
from typing import Any, ClassVar

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.vietnamese import find_effective_date, parse_rate, parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

REGIONS = ("hanoi", "hcm")


def js_unescape(text: str) -> str:
    """Undo JavaScript escape(): '%u1EA5' and '%E3' -> characters."""
    return re.sub(
        r"%u([0-9A-Fa-f]{4})|%([0-9A-Fa-f]{2})",
        lambda m: chr(int(m.group(1) or m.group(2), 16)),
        text,
    )


class _BidvSavings(BaseAdapter):
    """Both BIDV endpoints answer an empty form POST with the same JSON shape."""

    institution = "BIDV"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    http_method = "POST"
    http_data: ClassVar[dict[str, str] | None] = {}

    product_name: ClassVar[str]
    channel: ClassVar[Channel]
    core_terms: ClassVar[tuple[int, ...]]

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise AdapterBroken(f"response is not JSON: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("status") != 1:
            raise AdapterBroken(f"status is not 1: {str(payload)[:200]}")

        regions = {}
        for region in REGIONS:
            block = payload.get(region)
            if not isinstance(block, dict) or not isinstance(block.get("data"), list):
                raise AdapterBroken(f"missing region block {region!r}")
            regions[region] = block

        # The page lets you pick Hà Nội or Hồ Chí Minh. Identical tables are stored
        # once as nationwide (region ''); if they differ, each is stored by region.
        if regions["hanoi"]["data"] == regions["hcm"]["data"]:
            blocks = {"": regions["hanoi"]}
        else:
            blocks = {"hanoi": regions["hanoi"], "hcm": regions["hcm"]}

        # Only a date the page states counts. `day_vi` is in the JSON but not shown,
        # and may be an edit date, so it is not used as effective_from.
        effective = find_effective_date(js_unescape(str(payload.get("note_vi", ""))))

        records: list[Record] = []
        for region, block in blocks.items():
            _check_vnd_visible(block)
            region_records = [
                r for row in block["data"] if (r := cls._record(row, effective, region)) is not None
            ]
            cls._check_complete(region_records)
            records.extend(region_records)
        return records

    @classmethod
    def _record(cls, row: Any, effective: Any, region: str) -> SavingsRateRecord | None:
        if not isinstance(row, dict) or "title_vi" not in row or "VND" not in row:
            raise AdapterBroken(f"row without title_vi/VND: {row!r}")
        # Online rows carry a "+/- ưu đãi" column. It is empty today; if it fills in,
        # we can't tell whether VND already includes it, so stop and ask.
        if str(row.get("TGVND") or "").strip():
            raise AdapterBroken(f"preferential column TGVND is set for {row['title_vi']!r}")
        try:
            term_months, term_days = parse_term(row["title_vi"])
            rate = parse_rate(str(row["VND"]))
        except ValueError as exc:
            raise AdapterBroken(str(exc)) from exc
        if rate is None:
            return None  # term not offered in VND
        return SavingsRateRecord(
            region=region,
            product_name=cls.product_name,
            channel=cls.channel,
            term_months=term_months,
            term_days=term_days,
            min_amount_vnd=0,
            # Online page note: "áp dụng cho tiền gửi trả lãi cuối kỳ". Counter: see docs.
            interest_payment=InterestPayment.END,
            rate_pct=rate,
            effective_from=effective,
        )

    @classmethod
    def _check_complete(cls, records: Sequence[Record]) -> None:
        months = {r.term_months for r in records}  # type: ignore[attr-defined]
        missing = [m for m in cls.core_terms if m not in months]
        if missing:
            raise AdapterBroken(f"{cls.product_name}: no VND rate for {missing} months")


def _check_vnd_visible(block: dict[str, Any]) -> None:
    """`visible` lists currencies; enable '0' means the column is shown."""
    visible = block.get("visible")
    if not isinstance(visible, list):
        raise AdapterBroken("missing 'visible' list")
    vnd = [v for v in visible if isinstance(v, dict) and v.get("currency") == "VND"]
    if not vnd or vnd[0].get("enable") != "0":
        raise AdapterBroken("VND column is hidden on the page")


@register
class BidvSavingsCounter(_BidvSavings):
    name = "bidv_savings_counter"
    product_name = "Tiền gửi tại quầy"
    channel = Channel.COUNTER
    core_terms = (0, 1, 3, 6, 12, 24)
    # Source URL: https://bidv.com.vn/ServicesBIDV/InterestDetailServlet (POST)


@register
class BidvSavingsOnline(_BidvSavings):
    name = "bidv_savings_online"
    product_name = "Tiền gửi Online"
    channel = Channel.ONLINE
    core_terms = (1, 3, 6, 12, 24)
    # Source URL: https://bidv.com.vn/ServicesLaiSuatOnline/InterestDetailOnlineServlet (POST)
