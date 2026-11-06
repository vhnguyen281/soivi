"""Fetch market series from their providers (docs/vncma/design-market-data.md §4).

One fetcher per provider. A fetch returns the raw payload (stored in S3 with its
SHA-256) and the dated points for each requested value field. A fetcher raises
MarketDataError, naming the call, when anything is missing: it never returns
partial data.

- vnstock: through MarketClient (pipeline/market/client.py, the only module that
  imports vnstock). Transient errors are retried; empty tables raise. Rows of the
  current (open) month are dropped before hashing, so two runs in one month
  produce the same payload.
- HNX: the government bond yield curve, one read-only POST per date.
- World Bank: the Pink Sheet monthly workbook, found on the Commodity Markets page.
"""

import calendar
import datetime as dt
import hashlib
import html
import importlib
import io
import json
import re
import ssl
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar, Protocol
from urllib.parse import urljoin

from pipeline.fetch.polite import FetchError
from pipeline.market import members
from pipeline.market.client import TRANSIENT, MarketClient, MarketDataError, Step, describe
from pipeline.market.monthend import Point, month_ends

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CERTS = Path(__file__).resolve().parent / "certs"
# Provenance attributes (df.attrs) kept in the payload. Only stable ones: others such as
# latency_ms, end (today's date), length (includes today's row) and requested_at change
# on every call and would make equal data hash differently.
STABLE_ATTRS = frozenset(
    {
        "source",
        "source_name",
        "route",
        "organisation",
        "organization",
        "terms_url",
        "robots_txt",
        "access_domain",
        "access_method",
        "access_protocol",
        "symbol",
        "interval",
        "start",
        "tool",
        "disclaimer",
        "is_tool_only",
        "algorithm_role",
        "algorithm_participation",
    }
)


@dataclass
class Fetched:
    url: str  # what was called; becomes snapshot.url
    content_type: str
    payload: bytes | None  # None: nothing new to fetch (e.g. every HNX month is stored)
    points: dict[str, list[Point]] = field(default_factory=dict)  # value_field -> points
    http_status: int | None = 200
    more: bool = False  # the fetcher works in chunks and has more to fetch

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload or b"").hexdigest()


class Fetcher(Protocol):
    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        """`have`: period ends already stored for every series of this request."""
        ...


class Http(Protocol):
    def get(self, url: str, method: str = "GET", data: dict[str, str] | None = None) -> Any: ...


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def first_of_month(day: dt.date) -> dt.date:
    return day.replace(day=1)


def to_decimal(value: Any) -> Decimal | None:
    """A finite number, or None for blanks, NaN and text such as '…'."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("\u00a0", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _pandas() -> Any:
    return importlib.import_module("pandas")


# --------------------------------------------------------------------------- vnstock


def chain_from(request: dict[str, Any]) -> list[Step]:
    steps: list[Step] = []
    for name, args, kwargs in request["call"]:
        steps.append((str(name), None if args is None else tuple(args), dict(kwargs or {})))
    return steps


@dataclass
class VnstockFetcher:
    client: MarketClient
    pause: float = 1.0
    attempts: int = 3
    backoff: float = 5.0
    sleep: Callable[[float], None] = time.sleep
    _calls: int = 0

    def _call(self, chain: Sequence[Step]) -> Any:
        return self._retry(lambda: self.client.call(chain))

    def _retry(self, fn: Callable[[], Any]) -> Any:
        for attempt in range(1, self.attempts + 1):
            if self._calls:
                self.sleep(self.pause)
            self._calls += 1
            try:
                return fn()
            except MarketDataError as exc:
                cause = type(exc.__cause__).__name__ if exc.__cause__ else ""
                if cause not in TRANSIENT or attempt == self.attempts:
                    raise
                self.sleep(self.backoff * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        if "members" in request:
            return self._members(request, value_fields, have, today)
        chain = chain_from(request)
        call = describe(chain)
        df = self._call(chain)
        if df is None or not hasattr(df, "columns") or len(df) == 0:
            raise MarketDataError(f"{call} returned an empty table")
        if request.get("reduce") == "median":
            return self._median_today(df, call, value_fields, today)
        date_field = str(request["date_field"])
        missing = [c for c in (date_field, *value_fields) if c not in df.columns]
        if missing:
            raise MarketDataError(f"{call} has no column(s) {missing}; got {list(df.columns)}")
        pd = _pandas()
        dates = pd.to_datetime(df[date_field], errors="coerce")
        if dates.isna().all():
            raise MarketDataError(f"{call}: column {date_field!r} has no dates")
        days = dates.dt.date
        closed = df[(days < first_of_month(today)) & dates.notna()].copy()
        if len(closed) == 0:
            raise MarketDataError(f"{call} has no rows before {first_of_month(today)}")
        closed_days = days[closed.index]
        closed = closed.sort_values(date_field)
        attrs = {
            str(k): str(v) for k, v in dict(getattr(df, "attrs", {})).items() if k in STABLE_ATTRS
        }
        table = json.loads(closed.to_json(orient="split", date_format="iso", index=False))
        payload = canonical_json({"call": call, "attrs": attrs, "table": table})
        points: dict[str, list[Point]] = {}
        for column in value_fields:
            values: list[Point] = []
            for idx, raw in closed[column].items():
                number = to_decimal(raw)
                if number is not None:
                    values.append(Point(closed_days[idx], number))
            if not values:
                raise MarketDataError(f"{call}: column {column!r} has no numbers")
            points[column] = values
        return Fetched(f"vnstock:{call}", "application/json", payload, points)

    def _members(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        """An aggregate over an index's current members (pipeline/market/members.py)."""
        index, report = str(request["members"]), str(request["report"])
        url = f"vnstock:members({index!r}).{report}"
        if report == "ratio" and members.last_closed_quarter(today) in have:
            return Fetched(url, "application/json", None)  # quarterly: nothing new yet
        if report == "summary":
            payload, points = members.summary(self._call, index, today)
        else:
            quant = getattr(self.client, "quant_ratios", None)
            use_quant = request.get("source", "quant") == "quant" and quant is not None

            def ratios(symbols: Sequence[str]) -> Any:
                assert quant is not None
                return self._retry(lambda: quant(symbols, list(members.RATIO_IDS)))

            payload, points = members.ratio(self._call, index, today, ratios if use_quant else None)
        missing = [f for f in value_fields if f not in points]
        if missing:
            raise MarketDataError(f"{url} has no field(s) {missing}; got {sorted(points)}")
        return Fetched(url, "application/json", canonical_json(payload), points)

    def _median_today(
        self, df: Any, call: str, value_fields: Sequence[str], today: dt.date
    ) -> Fetched:
        """A current snapshot across rows (deposit rates by bank): the whole table is the
        payload; each field's median across rows is today's value."""
        missing = [c for c in value_fields if c not in df.columns]
        if missing:
            raise MarketDataError(f"{call} has no column(s) {missing}; got {list(df.columns)}")
        attrs = {
            str(k): str(v) for k, v in dict(getattr(df, "attrs", {})).items() if k in STABLE_ATTRS
        }
        table = json.loads(df.to_json(orient="split", date_format="iso", index=False))
        payload = canonical_json({"call": call, "attrs": attrs, "table": table})
        points: dict[str, list[Point]] = {}
        for column in value_fields:
            numbers = sorted(v for v in (to_decimal(x) for x in df[column]) if v is not None)
            if not numbers:
                raise MarketDataError(f"{call}: column {column!r} has no numbers")
            mid = len(numbers) // 2
            median = numbers[mid] if len(numbers) % 2 else (numbers[mid - 1] + numbers[mid]) / 2
            points[column] = [Point(today, median)]
        return Fetched(f"vnstock:{call}", "application/json", payload, points)


# --------------------------------------------------------------------------- HNX

HNX_PAGE = "https://www.hnx.vn/vi-vn/trai-phieu/duong-cong-loi-suat.html"
HNX_ENDPOINT = (
    "https://www.hnx.vn/ModuleReportBonds/Bond_YieldCurve/SearchAndNextPageYieldCurveData"
)
HNX_HEADER = ("Kỳ hạn còn lại", "Spot rate liên tục (%)", "Par yield (%)", "Spot rate theo năm (%)")
HNX_MONTHS_PER_FETCH = 24  # stored after each chunk, so a late failure loses little
HNX_MAX_BACK_DAYS = 10  # Tết can close the market for 9-10 days


def hnx_ssl_context() -> ssl.SSLContext:
    """certifi plus GlobalSign's intermediate, which hnx.vn does not send. Full verification."""
    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(str(CERTS / "globalsign_gcc_r3_ev_tls_ca_2025.pem"))
    return ctx


def _tenor_key(label: str) -> str:
    m = re.fullmatch(r"(\d+)\s*(năm|tháng)", label.strip())
    if not m:
        raise MarketDataError(f"HNX yield curve: unknown tenor label {label!r}")
    return f"{m.group(1)}{'y' if m.group(2) == 'năm' else 'm'}"


def parse_hnx(page: str) -> dict[str, Decimal] | None:
    """{"par_10y": Decimal(...), ...} from one HNX yield-curve response; None if the day
    has no curve (holiday). Raises if the table layout is not the one we know."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)
        rows.append([html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in cells])
    if not rows or tuple(rows[0]) != HNX_HEADER:
        raise MarketDataError(f"HNX yield curve: unexpected table header {rows[:1]}")
    out: dict[str, Decimal] = {}
    for row in rows[1:]:
        if len(row) != len(HNX_HEADER):
            raise MarketDataError(f"HNX yield curve: unexpected row {row}")
        par = to_decimal(row[2].replace(",", "."))
        if par is not None:
            out[f"par_{_tenor_key(row[0])}"] = par
    return out or None


@dataclass
class PerDateFetcher:
    """A provider asked one date at a time for month-end values (HNX, SJC).

    For each closed month not yet stored, ask the month end, then step back a day at a
    time (up to `max_back_days`) until the provider has data. Works in chunks of
    `months_per_fetch` months (Fetched.more), and never asks a month twice in one run.
    """

    http: Http
    months_per_fetch: int = HNX_MONTHS_PER_FETCH
    _tried: set[dt.date] = field(default_factory=set)

    endpoint: ClassVar[str]
    name: ClassVar[str]
    skip_weekends: ClassVar[bool]
    max_back_days: ClassVar[int] = HNX_MAX_BACK_DAYS

    def lookup(
        self, request: dict[str, Any], day: dt.date
    ) -> tuple[str, dict[str, Decimal] | None]:
        """(raw response text, values by field) for one date; None when the date has no data."""
        raise NotImplementedError

    def lookup_month(
        self, request: dict[str, Any], end: dt.date
    ) -> tuple[dt.date, str, dict[str, Decimal]] | None:
        """(date used, raw text, values) for the month ending `end`: the month end, or the
        last earlier day with data within `max_back_days`. None if there is none."""
        for back in range(self.max_back_days + 1):
            day = end - dt.timedelta(days=back)
            if self.skip_weekends and day.weekday() >= 5:
                continue
            try:
                raw, values = self.lookup(request, day)
            except FetchError as exc:
                raise MarketDataError(f"{self.name} {day}: {exc}") from exc
            if values is not None:
                return day, raw, values
        return None

    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        start = dt.date.fromisoformat(f"{request['start']}-01")
        last_closed = first_of_month(today) - dt.timedelta(days=1)
        todo = [m for m in month_ends(start, last_closed) if m not in have and m not in self._tried]
        wanted, rest = todo[: self.months_per_fetch], todo[self.months_per_fetch :]
        self._tried.update(wanted)
        pages: dict[str, str] = {}
        points: dict[str, list[Point]] = {f: [] for f in value_fields}
        for end in wanted:
            try:
                found = self.lookup_month(request, end)
            except FetchError as exc:
                raise MarketDataError(f"{self.name} {end:%Y-%m}: {exc}") from exc
            if found is None:
                continue
            day, raw, values = found
            missing = [f for f in value_fields if f not in values]
            if missing:
                raise MarketDataError(f"{self.name} {day}: no {missing}")
            pages[day.isoformat()] = raw
            for f in value_fields:
                points[f].append(Point(day, values[f]))
        more = bool(rest)
        if not pages:
            return Fetched(self.endpoint, "application/json", None, {}, more=more)
        payload = canonical_json({"endpoint": self.endpoint, "pages": pages})
        return Fetched(self.endpoint, "application/json", payload, points, more=more)


@dataclass
class HnxFetcher(PerDateFetcher):
    endpoint: ClassVar[str] = HNX_ENDPOINT
    name: ClassVar[str] = "HNX yield curve"
    skip_weekends: ClassVar[bool] = True  # no curve on weekends

    def lookup(
        self, request: dict[str, Any], day: dt.date
    ) -> tuple[str, dict[str, Decimal] | None]:
        response = self.http.get(HNX_ENDPOINT, "POST", {"pDate": day.strftime("%d/%m/%Y")})
        return response.text, parse_hnx(response.text)


# --------------------------------------------------------------------------- SJC

SJC_ENDPOINT = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"
VN_TZ = dt.timezone(dt.timedelta(hours=7))
# SJC's by-date method (GetSJCGoldPriceByDate) returns only the first 10 rows, so a branch
# can be missing; the history method for one branch has every update with its time.


def _sjc_time(value: Any) -> dt.datetime:
    m = re.fullmatch(r"/Date\((-?\d+)\)/", str(value))
    if not m:
        raise MarketDataError(f"SJC: unexpected GroupDate {value!r}")
    return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, dt.UTC).astimezone(VN_TZ)


def parse_sjc_history(
    text: str, end: dt.date, gold_type: str
) -> tuple[dt.date, dict[str, Decimal]] | None:
    """The last price update on or before `end` (Vietnam time): (its date, {"buy", "sell"})
    in VND per lượng. None when the window has no update."""
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise MarketDataError(f"SJC {end:%Y-%m}: response is not JSON") from exc
    if not isinstance(doc, dict) or doc.get("success") is not True or "data" not in doc:
        raise MarketDataError(f"SJC {end:%Y-%m}: unexpected response {str(doc)[:200]}")
    rows = [
        (_sjc_time(r.get("GroupDate")), r)
        for r in doc["data"] or []
        if r.get("TypeName") == gold_type
    ]
    rows = [(t, r) for t, r in rows if t.date() <= end]
    if not rows:
        return None
    when, row = max(rows, key=lambda x: x[0])
    buy, sell = to_decimal(row.get("BuyValue")), to_decimal(row.get("SellValue"))
    if buy is None or sell is None or buy <= 0 or sell <= 0:
        raise MarketDataError(f"SJC {when:%Y-%m-%d}: no buy/sell price in {row}")
    return when.date(), {"buy": buy, "sell": sell}


@dataclass
class SjcFetcher(PerDateFetcher):
    """SJC gold bar prices (VND per lượng), one request per month: the price history of one
    branch (`gold_price_id`, 1 = Hồ Chí Minh) over the last days of the month; the last
    update on or before the month end is the month's value. robots.txt allows /GoldPrice/
    but sets ai-input=no: this content is parsed by code and must never be sent to an LLM."""

    endpoint: ClassVar[str] = SJC_ENDPOINT
    name: ClassVar[str] = "SJC gold price"
    skip_weekends: ClassVar[bool] = False  # SJC trades on weekends
    max_back_days: ClassVar[int] = 10  # the window asked for

    def lookup_month(
        self, request: dict[str, Any], end: dt.date
    ) -> tuple[dt.date, str, dict[str, Decimal]] | None:
        data = {
            "method": "GetGoldPriceHistory",
            "goldPriceId": str(request["gold_price_id"]),
            "fromDate": (end - dt.timedelta(days=self.max_back_days)).strftime("%d/%m/%Y"),
            "toDate": end.strftime("%d/%m/%Y"),
        }
        response = self.http.get(SJC_ENDPOINT, "POST", data)
        found = parse_sjc_history(response.text, end, str(request["gold_type"]))
        if found is None:
            return None
        day, values = found
        return day, response.text, values


# --------------------------------------------------------------------------- SBV

SBV_RATE_PAGE = "https://sbv.gov.vn/t%E1%BB%B7-gi%C3%A1"
SBV_RATE = re.compile(
    r"(Ngân hàng Nhà nước Việt Nam công bố tỷ giá trung tâm.*?áp dụng cho ngày "
    r"(\d{2}/\d{2}/\d{4}) như sau:.*?1 Đô la Mỹ\s*=\s*([\d.]+)\s*VND"
    r".*?Số văn bản\s*(\S+))",
    re.S,
)


@dataclass(frozen=True)
class SbvRate:
    day: dt.date
    rate: Decimal  # VND per USD
    document_no: str  # e.g. 463/TB-NHNN
    statement: str  # the announcement as written on the page


def parse_sbv_central_rate(page: str) -> SbvRate:
    """Today's central rate from the SBV exchange-rate page (it shows today's only)."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    m = SBV_RATE.search(text)
    if not m:
        raise MarketDataError("SBV rate page: no 'áp dụng cho ngày … 1 Đô la Mỹ = … VND'")
    d, mth, y = (int(x) for x in m.group(2).split("/"))
    return SbvRate(dt.date(y, mth, d), Decimal(m.group(3).replace(".", "")), m.group(4), m.group(1))


@dataclass
class SbvFetcher:
    """The payload is the announcement itself (date, rate, document number, statement as
    written), not the whole page: the page's markup changes on every load."""

    http: Http

    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        if list(value_fields) != ["central_rate"]:
            raise MarketDataError(f"SBV rate page has only central_rate, not {list(value_fields)}")
        try:
            page = self.http.get(SBV_RATE_PAGE)
        except FetchError as exc:
            raise MarketDataError(f"SBV rate page: {exc}") from exc
        found = parse_sbv_central_rate(page.text)
        payload = canonical_json(
            {
                "url": SBV_RATE_PAGE,
                "date": found.day.isoformat(),
                "central_rate_vnd_per_usd": str(found.rate),
                "document_no": found.document_no,
                "statement": found.statement,
            }
        )
        points = {"central_rate": [Point(found.day, found.rate)]}
        return Fetched(SBV_RATE_PAGE, "application/json", payload, points)


# --------------------------------------------------------------------------- World Bank


def find_link(page: str, contains: str, base: str = "") -> str:
    """The one link on `page` containing `contains`, made absolute against `base`."""
    links = sorted(
        {
            urljoin(base, html.unescape(h))
            for h in re.findall(r'href="([^"]+)"', page)
            if contains in h
        }
    )
    if len(links) != 1:
        raise MarketDataError(f"expected one link containing {contains!r}, found {links}")
    return links[0]


def parse_pink_sheet(data: bytes, sheet: str, columns: Iterable[str]) -> dict[str, list[Point]]:
    """Monthly prices from the Pink Sheet: a header row of commodity names, then rows
    labelled like 1960M01. Each value is dated at its month end."""
    pd = _pandas()
    try:
        frame = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None)
    except Exception as exc:
        raise MarketDataError(f"World Bank workbook: cannot read sheet {sheet!r}: {exc}") from exc
    labels = frame.iloc[:, 0].astype(str)
    data_rows = labels[labels.str.fullmatch(r"\d{4}M\d{2}")].index
    if len(data_rows) == 0:
        raise MarketDataError("World Bank workbook: no rows like 1960M01")
    wanted = list(columns)
    header_row = next(
        (
            i
            for i in range(int(data_rows[0]))
            if all(c in frame.iloc[i].astype(str).tolist() for c in wanted)
        ),
        None,
    )
    if header_row is None:
        raise MarketDataError("World Bank workbook: no header row with commodity names")
    header = frame.iloc[header_row].astype(str).tolist()
    out: dict[str, list[Point]] = {}
    for name in wanted:
        if header.count(name) != 1:
            raise MarketDataError(f"World Bank workbook: column {name!r} not found exactly once")
        col = header.index(name)
        values = []
        for r in data_rows:
            year, month = int(labels[r][:4]), int(labels[r][5:])
            number = to_decimal(frame.iat[r, col])
            if number is not None:
                end = dt.date(year, month, calendar.monthrange(year, month)[1])
                values.append(Point(end, number))
        if not values:
            raise MarketDataError(f"World Bank workbook: column {name!r} has no numbers")
        out[name] = values
    return out


def parse_shiller(data: bytes, sheet: str, columns: Iterable[str]) -> dict[str, list[Point]]:
    """Monthly S&P Composite data (Shiller): a header row starting with "Date", then rows
    dated like 1871.01 (2026.1 is October). Each value is dated at its month end."""
    pd = _pandas()
    try:
        frame = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None)
    except Exception as exc:
        raise MarketDataError(f"Shiller workbook: cannot read sheet {sheet!r}: {exc}") from exc
    wanted = list(columns)
    header_row = next(
        (
            i
            for i in range(min(len(frame), 50))
            if str(frame.iat[i, 0]).strip() == "Date"
            and all(c in frame.iloc[i].astype(str).str.strip().tolist() for c in wanted)
        ),
        None,
    )
    if header_row is None:
        raise MarketDataError(f"Shiller workbook: no header row with Date and {wanted}")
    header = frame.iloc[header_row].astype(str).str.strip().tolist()
    out: dict[str, list[Point]] = {}
    for name in wanted:
        col = header.index(name)
        values = []
        for r in range(header_row + 1, len(frame)):
            stamp = to_decimal(frame.iat[r, 0])
            number = to_decimal(frame.iat[r, col])
            if stamp is None or number is None:
                continue
            year = int(stamp)
            month = int(((stamp - year) * 100).to_integral_value())
            if not 1 <= month <= 12:
                raise MarketDataError(f"Shiller workbook: bad date {frame.iat[r, 0]!r}")
            values.append(Point(dt.date(year, month, calendar.monthrange(year, month)[1]), number))
        if not values:
            raise MarketDataError(f"Shiller workbook: column {name!r} has no numbers")
        out[name] = values
    return out


Parser = Callable[[bytes, str, Iterable[str]], dict[str, list[Point]]]


@dataclass
class LinkedWorkbookFetcher:
    """A workbook whose link is found on a page each time (World Bank, Shiller)."""

    http: Http
    parse: Parser
    name: str

    def fetch(
        self,
        request: dict[str, Any],
        value_fields: Sequence[str],
        have: set[dt.date],
        today: dt.date,
    ) -> Fetched:
        try:
            page = self.http.get(str(request["page"]))
            url = find_link(page.text, str(request["link_contains"]), str(request["page"]))
            workbook = self.http.get(url)
        except FetchError as exc:
            raise MarketDataError(f"{self.name}: {exc}") from exc
        content_type = str(getattr(workbook, "headers", {}).get("content-type", XLSX)).split(";")[0]
        points = self.parse(workbook.content, str(request["sheet"]), value_fields)
        return Fetched(url, content_type, workbook.content, points)


def WorldBankFetcher(http: Http) -> LinkedWorkbookFetcher:
    return LinkedWorkbookFetcher(http, parse_pink_sheet, "World Bank Pink Sheet")


def ShillerFetcher(http: Http) -> LinkedWorkbookFetcher:
    return LinkedWorkbookFetcher(http, parse_shiller, "Shiller data")
