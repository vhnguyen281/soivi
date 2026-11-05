"""Savings ranking: VND earned at maturity for a given amount and term.

Rates are percent per year, simple interest over the term (the way Vietnamese
banks quote them). Time is term_months / 12 years; banks count actual days / 365,
so a bank's own figure can differ by a few đồng to a few thousand đồng.

Interest paid before maturity is worth more than the same interest at the end,
so banks pay lower rates for it. To compare fairly, every payment is assumed to
be reinvested at the offer's own rate until maturity (docs/methodology.md §1.2):

    end        I = P·r·t
    monthly    I = P·[(1 + r/12)^n - 1]                  n = term in months
    quarterly  I = P·[((1 + r/4)^k - 1)·(1 + r·m/12) + r·m/12]
               k = full quarters, m = leftover months (paid at maturity)
    upfront    I = P·r·t·(1 + r·t)                        paid at the start

The ranking uses this "equivalent at maturity" amount. The cash interest the
bank actually pays (P·r·t, whatever the schedule) is shown next to it.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from core.enums import Channel, InterestPayment

HUNDRED = Decimal(100)
TWELVE = Decimal(12)

# Channel preference -> channels it accepts.
CHANNEL_PREFERENCES: dict[str, frozenset[Channel]] = {
    "any": frozenset(Channel),
    "counter": frozenset({Channel.COUNTER}),
    "online": frozenset({Channel.ONLINE}),
    "app": frozenset({Channel.APP}),
    "digital": frozenset({Channel.ONLINE, Channel.APP}),
}

# Words in the bank's own conditions text that set a flag (accents removed).
_NEW_CUSTOMER = re.compile(r"\b(khach hang moi|kh moi|lan dau|mo moi)\b")
_APP_ONLY = re.compile(r"\b(ung dung|mobile app|app|ngan hang so)\b")
_EARLY = re.compile(r"\b(rut truoc han|tat toan truoc han)\b")
_MAXIMUM = re.compile(r"\btoi da\b")


def fold(text: str | None) -> str:
    """Lowercase, no accents: 'Khách hàng mới' -> 'khach hang moi'."""
    s = unicodedata.normalize("NFD", (text or "").lower()).replace("đ", "d")
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


class ScoringError(ValueError):
    """The query can't be scored (e.g. a non-positive amount or term)."""


@dataclass(frozen=True)
class SavingsOffer:
    """One approved, current rate (a savings_rate row plus its institution)."""

    version_id: int
    institution: str  # short_name
    institution_name: str
    product_name: str
    channel: Channel
    term_months: int
    min_amount_vnd: int
    interest_payment: InterestPayment
    rate_pct: Decimal
    region: str = ""
    conditions_text: str | None = None
    is_cd: bool = False
    deposit_insurance: bool | None = None
    verified: bool = True  # False when the institution's sources are stale


@dataclass(frozen=True)
class SavingsQuery:
    amount_vnd: int
    term_months: int
    channel: str = "any"
    region: str | None = None  # None: every region; else '' (nationwide) + this one

    def __post_init__(self) -> None:
        if self.amount_vnd <= 0:
            raise ScoringError("amount_vnd must be positive")
        if self.term_months <= 0:
            raise ScoringError("term_months must be at least 1")
        if self.channel not in CHANNEL_PREFERENCES:
            raise ScoringError(f"channel must be one of {sorted(CHANNEL_PREFERENCES)}")


@dataclass(frozen=True)
class SavingsResult:
    rank: int
    offer: SavingsOffer
    equivalent_interest_vnd: int  # ranking basis: value at maturity, reinvested
    cash_interest_vnd: int  # what the bank pays in total, on its own schedule
    equivalent_rate_pct: Decimal  # equivalent_interest as a simple yearly rate
    flags: dict[str, bool | None] = field(default_factory=dict)


def vnd(amount: Decimal) -> int:
    """Round to whole đồng (half up)."""
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cash_interest(principal: int, rate_pct: Decimal, term_months: int) -> Decimal:
    """Total interest the bank pays over the term: P·r·t."""
    return Decimal(principal) * rate_pct / HUNDRED * Decimal(term_months) / TWELVE


def equivalent_interest(
    principal: int, rate_pct: Decimal, term_months: int, payment: InterestPayment
) -> Decimal:
    """Interest valued at maturity, each payment reinvested at the offer's rate."""
    p = Decimal(principal)
    r = rate_pct / HUNDRED
    t = Decimal(term_months) / TWELVE
    if payment is InterestPayment.END:
        return p * r * t
    if payment is InterestPayment.MONTHLY:
        return p * ((1 + r / TWELVE) ** term_months - 1)
    if payment is InterestPayment.QUARTERLY:
        quarters, leftover = divmod(term_months, 3)
        tail = r * Decimal(leftover) / TWELVE
        return p * (((1 + r / 4) ** quarters - 1) * (1 + tail) + tail)
    if payment is InterestPayment.UPFRONT:
        return p * r * t * (1 + r * t)
    raise ScoringError(f"unknown interest payment {payment!r}")


def flags(offer: SavingsOffer) -> dict[str, bool | None]:
    text = fold(offer.conditions_text)
    return {
        "new_customer_only": bool(_NEW_CUSTOMER.search(text)),
        "app_only": offer.channel is Channel.APP or bool(_APP_ONLY.search(text)),
        # Term deposits withdrawn early lose most of their interest (docs §1.4).
        "early_withdrawal_penalty": True,
        "early_withdrawal_terms_stated": bool(_EARLY.search(text)),
        "rate_is_maximum": bool(_MAXIMUM.search(text)),
        "certificate_of_deposit": offer.is_cd,
        "deposit_insurance": offer.deposit_insurance,
        "regional": bool(offer.region),
        "unverified": not offer.verified,
    }


def _eligible(offers: Iterable[SavingsOffer], q: SavingsQuery) -> list[SavingsOffer]:
    channels = CHANNEL_PREFERENCES[q.channel]
    out = [
        o
        for o in offers
        if o.term_months == q.term_months
        and o.min_amount_vnd <= q.amount_vnd
        and o.channel in channels
        and (q.region is None or o.region in ("", q.region))
    ]
    # Amount tiers of one product: keep only the tier this amount falls in
    # (the highest floor not above it), so a product is listed once.
    best: dict[tuple[object, ...], SavingsOffer] = {}
    for o in out:
        key = (o.institution, o.region, o.product_name, o.channel, o.interest_payment)
        if key not in best or o.min_amount_vnd > best[key].min_amount_vnd:
            best[key] = o
    return list(best.values())


def rank_savings(offers: Sequence[SavingsOffer], q: SavingsQuery) -> list[SavingsResult]:
    scored = []
    for o in _eligible(offers, q):
        equivalent = equivalent_interest(
            q.amount_vnd, o.rate_pct, q.term_months, o.interest_payment
        )
        scored.append((o, equivalent))
    scored.sort(key=lambda s: (-s[1], -s[0].rate_pct, s[0].institution, s[0].product_name))
    t = Decimal(q.term_months) / TWELVE
    results = []
    for i, (o, equivalent) in enumerate(scored, 1):
        rate = equivalent / (Decimal(q.amount_vnd) * t) * HUNDRED
        results.append(
            SavingsResult(
                rank=i,
                offer=o,
                equivalent_interest_vnd=vnd(equivalent),
                cash_interest_vnd=vnd(cash_interest(q.amount_vnd, o.rate_pct, q.term_months)),
                equivalent_rate_pct=rate.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
                flags=flags(o),
            )
        )
    return results


def excluded_by_amount(offers: Sequence[SavingsOffer], q: SavingsQuery) -> int:
    """Offers for this term left out only because their minimum is above the amount."""
    return sum(
        1 for o in offers if o.term_months == q.term_months and o.min_amount_vnd > q.amount_vnd
    )
