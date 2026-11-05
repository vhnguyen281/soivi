"""Parse the number, term, amount and date formats Vietnamese banks publish.

Every function raises ValueError on input it does not understand, so adapters
can turn that into AdapterBroken instead of guessing.
"""

import datetime as dt
import re
import unicodedata
from decimal import Decimal, InvalidOperation

# --------------------------------------------------------------------------- text


def clean(text: str | None) -> str:
    """NFC-normalise, turn non-breaking spaces into spaces, collapse whitespace."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text).replace("\xa0", " ").replace("​", "")
    return " ".join(text.split())


def fold(text: str | None) -> str:
    """Lowercase ASCII form for matching labels: 'Không kỳ hạn' -> 'khong ky han'."""
    text = unicodedata.normalize("NFD", clean(text).lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- rates

_NO_VALUE = {"", "-", "\u2013", "\u2014", "x", "n/a", "na", "khong ap dung", "kad"}
_RATE = re.compile(r"^(\d{1,3})(?:[.,](\d{1,4}))?$")


def parse_rate(text: str | None) -> Decimal | None:
    """'6,50%' / '6.5' / '6,5 %/năm' -> Decimal('6.50'); '-' or '' -> None (not offered)."""
    s = fold(text)
    for suffix in ("%/nam", "%/ nam", "/nam", "% nam", "%", "nam"):
        s = s.removesuffix(suffix).strip()
    if s in _NO_VALUE:
        return None
    m = _RATE.match(s.replace(" ", ""))
    if not m:
        raise ValueError(f"not a rate: {text!r}")
    value = Decimal(f"{m.group(1)}.{m.group(2) or '0'}")
    if value > 100:
        raise ValueError(f"rate above 100%: {text!r}")
    return value


# --------------------------------------------------------------------------- terms

_DEMAND = ("khong ky han", "kkh", "tien gui thanh toan")
_TERM = re.compile(r"^(?:ky han\s*)?(\d{1,3})\s*(thang|t|tuan|ngay|nam|th|m|w|d|y)\.?$")
_UNIT_DAYS = {"tuan": 7, "w": 7, "ngay": 1, "d": 1}
_UNIT_MONTHS = {"thang": 1, "t": 1, "th": 1, "m": 1, "nam": 12, "y": 12}


def parse_term(text: str | None) -> tuple[int, int]:
    """Return (term_months, term_days).

    'Không kỳ hạn' -> (0, 0); '1 tuần' -> (0, 7); '14 ngày' -> (0, 14);
    '01 tháng' / '1T' -> (1, 0); '1 năm' -> (12, 0).
    """
    s = fold(text)
    if any(s == d or s.startswith(d) for d in _DEMAND):
        return (0, 0)
    m = _TERM.match(s.replace("  ", " "))
    if not m:
        raise ValueError(f"not a term: {text!r}")
    n, unit = int(m.group(1)), m.group(2)
    if n == 0:
        raise ValueError(f"zero-length term: {text!r}")
    if unit in _UNIT_DAYS:
        days = n * _UNIT_DAYS[unit]
        if days % 30 == 0 and unit == "ngay" and days >= 30:
            raise ValueError(f"ambiguous term in days, use months: {text!r}")
        return (0, days)
    return (n * _UNIT_MONTHS[unit], 0)


# --------------------------------------------------------------------------- money

_UNITS = {
    "ty": 1_000_000_000,
    "trieu": 1_000_000,
    "tr": 1_000_000,
    "nghin": 1_000,
    "ngan": 1_000,
    "k": 1_000,
}
_AMOUNT = re.compile(r"^(\d+(?:[.,]\d+)*)\s*(ty|trieu|tr|nghin|ngan|k)?\s*(?:dong|vnd|d)?$")


def parse_vnd(text: str | None) -> int:
    """'500 triệu' -> 500_000_000; '1,5 tỷ' -> 1_500_000_000; '500.000.000 VND' -> 500_000_000."""
    s = fold(text).replace("đ", "d")
    m = _AMOUNT.match(s)
    if not m:
        raise ValueError(f"not an amount: {text!r}")
    number, unit = m.group(1), m.group(2)
    if unit is None:
        # Plain number: dots/commas are thousands separators ("500.000.000").
        digits = re.sub(r"[.,]", "", number)
        if not re.fullmatch(r"\d+", digits) or not re.fullmatch(r"\d{1,3}([.,]\d{3})*|\d+", number):
            raise ValueError(f"not an amount: {text!r}")
        return int(digits)
    # With a unit, a single comma or dot is a decimal mark ("1,5 tỷ").
    try:
        value = Decimal(number.replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    result = value * _UNITS[unit]
    if result != result.to_integral_value():
        raise ValueError(f"amount is not a whole number of đồng: {text!r}")
    return int(result)


# --------------------------------------------------------------------------- dates

_DATE_NUMERIC = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})")
_DATE_WORDS = re.compile(r"(?:ngay\s*)?(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(\d{4})")
_EFFECTIVE = re.compile(
    r"(?:hieu luc|ap dung|ap dung tu|co hieu luc)\s*(?:ke\s*)?(?:tu|ke tu)?\s*(?:ngay)?\s*[:]?\s*"
)


def parse_date(text: str | None) -> dt.date:
    """'01/10/2026', '1-10-2026', 'ngày 01 tháng 10 năm 2026' -> date(2026, 10, 1)."""
    s = fold(text)
    m = _DATE_NUMERIC.search(s) or _DATE_WORDS.search(s)
    if not m:
        raise ValueError(f"no date in {text!r}")
    day, month, year = (int(g) for g in m.groups())
    return dt.date(year, month, day)


def find_effective_date(text: str | None) -> dt.date | None:
    """The date after 'hiệu lực từ ngày' / 'áp dụng từ ngày' in a block of text, if any."""
    s = fold(text)
    for m in _EFFECTIVE.finditer(s):
        tail = s[m.end() : m.end() + 40]
        found = _DATE_NUMERIC.match(tail) or _DATE_WORDS.match(tail)
        if found:
            day, month, year = (int(g) for g in found.groups())
            return dt.date(year, month, day)
    return None


# --------------------------------------------------------------------------- term bands

_N = r"(\d{1,3})\s*thang"
_BANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"^tu\s*{_N}\s*den\s*duoi\s*{_N}$"), "[lo,hi)"),
    (re.compile(rf"^tu\s*{_N}\s*den\s*{_N}$"), "[lo,hi]"),
    (re.compile(rf"^tren\s*{_N}\s*den\s*duoi\s*{_N}$"), "(lo,hi)"),
    (re.compile(rf"^tren\s*{_N}\s*den\s*{_N}$"), "(lo,hi]"),
    (re.compile(rf"^duoi\s*{_N}$"), "(,hi)"),
    (re.compile(rf"^tren\s*{_N}$"), "(lo,)"),
    (re.compile(rf"^tu\s*{_N}\s*tro\s*len$"), "[lo,)"),
]


def parse_term_band(text: str | None) -> tuple[int | None, int | None]:
    """Whole-month range covered by a term band; None for an open end.

    'Từ 1 tháng đến dưới 2 tháng' -> (1, 1); 'Trên 13 tháng đến dưới 18 tháng' -> (14, 17);
    'Trên 12 tháng đến 13 tháng' -> (13, 13); '12 tháng' -> (12, 12);
    'Dưới 1 tháng' -> (None, 0); 'Trên 36 tháng' -> (37, None); 'Không kỳ hạn' -> (0, 0).
    """
    s = fold(text)
    try:
        months, days = parse_term(text)
    except ValueError:
        pass
    else:
        if days:
            raise ValueError(f"band in days not supported: {text!r}")
        return (months, months)
    for pattern, shape in _BANDS:
        m = pattern.match(s)
        if not m:
            continue
        nums = [int(g) for g in m.groups()]
        if shape == "(,hi)":
            return (None, nums[0] - 1)
        if shape == "(lo,)":
            return (nums[0] + 1, None)
        if shape == "[lo,)":
            return (nums[0], None)
        lo, hi = nums
        lo = lo if shape.startswith("[") else lo + 1
        hi = hi if shape.endswith("]") else hi - 1
        if lo > hi:
            raise ValueError(f"empty band: {text!r}")
        return (lo, hi)
    raise ValueError(f"not a term band: {text!r}")
