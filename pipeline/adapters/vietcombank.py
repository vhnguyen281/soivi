"""Vietcombank: personal savings rates. Notes in docs/adapters/vietcombank.md."""

import json
from decimal import Decimal
from typing import Any

from core.enums import Channel, FetchMethod, InterestPayment, SourceKind
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.extract.vietnamese import parse_term
from pipeline.records import Record, SavingsRateRecord
from pipeline.registry import register

# tenorType in the API -> (product name as shown on the page, channel)
PRODUCTS = {
    "Savings": ("Tiết kiệm tại quầy", Channel.COUNTER),
    "FixedDeposit": ("Tiền gửi có kỳ hạn tại quầy", Channel.COUNTER),
    "Online": ("Tiền gửi trực tuyến", Channel.ONLINE),
}
REQUIRED_KEYS = {"tenorType", "tenor", "currencyCode", "tenorDisplay", "rates"}


@register
class VietcombankSavings(BaseAdapter):
    name = "vietcombank_savings"
    institution = "VIETCOMBANK"
    source_kind = SourceKind.SAVINGS_RATE_PAGE
    fetch_method = FetchMethod.HTTP
    # Source URL: https://www.vietcombank.com.vn/vi-VN/api/interestrates?accountType=Personal

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        try:
            # parse_float=Decimal: rates arrive as JSON floats (0.054) and must stay exact.
            payload = json.loads(content, parse_float=Decimal)
        except (ValueError, UnicodeDecodeError) as exc:
            raise AdapterBroken(f"response is not JSON: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("Data"), list):
            raise AdapterBroken("expected an object with a 'Data' list")
        if payload.get("AccountType") != "Personal":
            raise AdapterBroken(f"AccountType is {payload.get('AccountType')!r}, not 'Personal'")
        data: list[Any] = payload["Data"]
        if payload.get("Count") != len(data):
            raise AdapterBroken(f"Count {payload.get('Count')} != {len(data)} rows")

        records: list[Record] = []
        seen_types: set[str] = set()
        for i, row in enumerate(data):
            if not isinstance(row, dict) or not row.keys() >= REQUIRED_KEYS:
                raise AdapterBroken(f"row {i} is missing keys: {row!r}")
            tenor_type = row["tenorType"]
            if tenor_type not in PRODUCTS:
                raise AdapterBroken(f"unknown tenorType {tenor_type!r} (new product?)")
            seen_types.add(tenor_type)
            if row["currencyCode"] != "VND":
                continue
            records.append(cls._record(row))

        missing = set(PRODUCTS) - seen_types
        if missing:
            raise AdapterBroken(f"products missing from response: {sorted(missing)}")
        cls._check_complete(records)
        return records

    @classmethod
    def _record(cls, row: dict[str, Any]) -> SavingsRateRecord:
        product, channel = PRODUCTS[row["tenorType"]]
        try:
            term_months, term_days = parse_term(row["tenorDisplay"])
        except ValueError as exc:
            raise AdapterBroken(str(exc)) from exc
        if _tenor_key(row["tenor"]) != (term_months, term_days):
            raise AdapterBroken(
                f"tenor {row['tenor']!r} does not match label {row['tenorDisplay']!r}"
            )
        rate = row["rates"]
        if not isinstance(rate, Decimal | int) or not 0 <= rate < Decimal("0.2"):
            raise AdapterBroken(f"rate {rate!r} for {row['tenorDisplay']} is not a fraction < 20%")
        rate_pct = (Decimal(rate) * 100).normalize()
        if rate_pct.as_tuple().exponent < -3:  # type: ignore[operator]
            raise AdapterBroken(f"rate {rate!r} has more precision than we store")
        return SavingsRateRecord(
            product_name=product,
            channel=channel,
            term_months=term_months,
            term_days=term_days,
            min_amount_vnd=0,
            # Not stated on the page; listed rates are end-of-term (see adapter notes).
            interest_payment=InterestPayment.END,
            rate_pct=rate_pct,
            is_cd=False,
        )

    @classmethod
    def _check_complete(cls, records: list[Record]) -> None:
        """The core terms must be there, or the response was cut short."""
        have = {(r.product_name, r.term_months, r.term_days) for r in records}  # type: ignore[attr-defined]
        for product, _ in PRODUCTS.values():
            for months in (1, 3, 6, 12):
                if (product, months, 0) not in have:
                    raise AdapterBroken(f"{product}: {months}-month VND rate missing")


def _tenor_key(tenor: object) -> tuple[int, int]:
    """'Demand' -> (0, 0); '7-days' -> (0, 7); '12-months' -> (12, 0)."""
    if tenor == "Demand":
        return (0, 0)
    if isinstance(tenor, str) and "-" in tenor:
        number, unit = tenor.split("-", 1)
        if number.isdigit() and unit == "days":
            return (0, int(number))
        if number.isdigit() and unit == "months":
            return (int(number), 0)
    raise AdapterBroken(f"unknown tenor key {tenor!r}")
