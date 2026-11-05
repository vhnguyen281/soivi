"""Turn an extracted fact into a typed value, and refuse it unless the document backs it.

A fact is kept only if:
1. its quote appears, word for word, in the text of the page it names
   (whitespace differences aside: PDF text wraps lines anywhere), and
2. for numbers, the quote itself contains the value ("miễn phí" counts as 0).
   A real quote next to a made-up number is caught here.
Text fields take the quote itself as their value, so nothing is paraphrased.
"""

import re
from decimal import Decimal, InvalidOperation

from pipeline.cards.document import normalise_space
from pipeline.cards.fields import FieldSpec
from pipeline.extract.vietnamese import fold, parse_vnd

FREE = re.compile(r"\b(mien phi|khong thu phi|khong tinh phi)\b")  # "no fee"
# A number, an optional unit word, an optional currency: "1.499.000 VND", "1 triệu", "5tr".
_AMOUNT = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)*)\s*(ty|trieu|tr|nghin|ngan|k)?\s*(?:dong|vnd|d)?(?![\w])"
)
_PCT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*%")
_INT = re.compile(r"(?<![\d.,])(\d+)(?![\d.,]\d)")
_YEARLY = re.compile(r"\bnam\b|/ ?nam|per year|p\.a\.")
# "Lên đến 10%", "hoàn tiền tới 10%", "up to 10%": a ceiling, not the rate.
_UP_TO = re.compile(r"\b(len den|len toi|toi|den|up to)\s*\d[\d.,]*\s*%")
# "15,5% - 16,5%/năm", "17% đến 18%/năm", "17 tới 18%"
_RANGE = re.compile(r"\d\s*%?\s*(?:[-–—]|đến|tới)\s*\d[\d.,]*\s*%")
_TRAVEL = re.compile(r"\bdu lich\b|\btravel\b")
TRUE = {"true", "co", "yes"}
FALSE = {"false", "khong", "no"}


class Rejected(Exception):
    """The fact can't be used; the message says why (shown to the reviewer)."""


def money(text: str) -> int:
    """'1.499.000 VND/thẻ' -> 1499000; '1 triệu' -> 1000000; 'Miễn phí' -> 0."""
    s = fold(text).replace("đ", "d")
    if FREE.search(s):
        return 0
    m = _AMOUNT.search(s)
    if not m:
        raise Rejected(f"not an amount: {text!r}")
    try:
        return parse_vnd(m.group(0))
    except ValueError as exc:
        raise Rejected(str(exc)) from exc


def amounts_in(text: str) -> set[int]:
    s = fold(text).replace("đ", "d")
    found = {0} if FREE.search(s) else set()
    for m in _AMOUNT.finditer(s):
        try:
            found.add(parse_vnd(m.group(0)))
        except ValueError:
            continue
    return found


def _decimal(number: str) -> Decimal:
    try:
        return Decimal(number.replace(",", "."))
    except InvalidOperation as exc:
        raise Rejected(f"not a number: {number!r}") from exc


def pct(text: str) -> Decimal:
    """'2.59%*số tiền giao dịch' -> 2.59; '1,1%' -> 1.1; 'Miễn phí' -> 0."""
    if FREE.search(fold(text)):
        return Decimal(0)
    m = _PCT.search(text)
    if not m:
        raise Rejected(f"not a percentage: {text!r}")
    value = _decimal(m.group(1))
    if value > 100:
        raise Rejected(f"percentage above 100: {text!r}")
    return value


def pcts_in(text: str) -> set[Decimal]:
    found = {Decimal(0)} if FREE.search(fold(text)) else set()
    return found | {_decimal(m.group(1)) for m in _PCT.finditer(text)}


def integer(text: str) -> int:
    m = _INT.search(text)
    if not m:
        raise Rejected(f"not a whole number: {text!r}")
    return int(m.group(1))


def boolean(text: str) -> bool:
    s = fold(text).strip()
    if s in TRUE:
        return True
    if s in FALSE:
        return False
    raise Rejected(f"not true/false: {text!r}")


def quote_on_page(quote: str, page_text: str) -> bool:
    q = normalise_space(quote)
    return bool(q) and q in normalise_space(page_text)


def check(spec: FieldSpec, value: str, quote: str) -> int | Decimal | bool | str:
    """The typed value, or Rejected. The caller has already found the quote on its page."""
    if spec.kind == "text":
        return normalise_space(quote)
    if spec.kind == "bool":
        flag = boolean(value)
        if spec.name == "travel_insurance" and flag and not _TRAVEL.search(fold(quote)):
            # "Bảo hiểm cho chủ thẻ" may be any cover; only travel cover counts.
            raise Rejected("the quote doesn't say the insurance is travel insurance (du lịch)")
        return flag
    if spec.kind == "money":
        amount = money(value)
        if amount not in amounts_in(quote):
            raise Rejected(f"{amount:,} VND is not in the quote")
        return amount
    if spec.name == "interest_rate_pct" and not _YEARLY.search(fold(quote)):
        # "3.99%" alone may be a monthly rate: never store it as a yearly one.
        raise Rejected("the quote doesn't say the rate is per year (năm)")
    if spec.name == "interest_rate_pct" and _RANGE.search(quote):
        # "15,5% - 16,5%/năm": which one applies depends on the customer.
        raise Rejected("the quote gives a range of rates, not one rate")
    if spec.name == "rate_pct" and _UP_TO.search(fold(quote)):
        raise Rejected("an 'up to' rate (lên đến / tới) is a ceiling, not the reward rate")
    if spec.kind == "pct":
        rate = pct(value)
        if rate not in pcts_in(quote):
            raise Rejected(f"{rate}% is not in the quote")
        return rate
    if spec.kind == "int":
        number = integer(value)
        if str(number) not in re.findall(r"\d+", quote):
            raise Rejected(f"{number} is not in the quote")
        return number
    # "20 điểm", "1 dặm": the number, as long as there's only one
    numbers = re.findall(r"\d+(?:[.,]\d+)?", value)
    if len(numbers) != 1:
        raise Rejected(f"not a number: {value!r}")
    number_d = _decimal(numbers[0])
    if number_d not in {_decimal(n) for n in re.findall(r"\d+(?:[.,]\d+)?", quote)}:
        raise Rejected(f"{number_d} is not in the quote")
    return number_d
