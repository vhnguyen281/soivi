"""VPBank credit cards: the current card fee schedule for personal customers, read
with the LLM. Notes in docs/adapters/vpbank.md.

The source is VPBank's document list for personal-customer fee schedules; the
adapter takes the newest "Biểu phí thẻ tín dụng tại VPBank" PDF from it. (The PDF
in the old seed row was an undated file from 2020.)

Cards are table columns, so the document is read with column labels: each value
carries the card names of the columns it covers, and the quote check proves the
mapping (pipeline/cards/document.py).

Networks: only where VPBank writes it, in the card's name (page 1 of the schedule)
or on its card page (https://www.vpbank.com.vn/ca-nhan/the-tin-dung, 2026-10-29).
The other cards stay unpublished until their network is confirmed.
"""

import json
import re

from core.enums import CardNetwork, FetchMethod, SourceKind
from pipeline.adapters.base import AdapterBroken
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.catalogue import Card, Catalogue
from pipeline.registry import register

VISA, MC, JCB, UP = CardNetwork.VISA, CardNetwork.MASTERCARD, CardNetwork.JCB, CardNetwork.UNIONPAY
TITLE = "Biểu phí thẻ tín dụng tại VPBank"
DOC_URL = re.compile(r"^/-/media/vpbank-latest/[\w\-/.%]+\.pdf$", re.IGNORECASE)


def _card(
    code: str, name: str, network: CardNetwork | None, *spellings: str, tier: str | None = None
) -> Card:
    note = "" if network else "network not stated by VPBank yet: not published until confirmed"
    return Card(code, name, network, tier, spellings, in_tariff=network is not None, note=note)


VPBANK_CARDS = Catalogue(
    "VPBank",
    (
        # Network written in the card's name or on its card page.
        _card("VPB_MC2", "VPBank MC2 Mastercard", MC, "MC2", "VPBank MC2 MasterCard"),
        _card("VPB_Z", "VPBank Z JCB", JCB, "VPBank Z", "VPBank JCB Z"),
        _card(
            "VPB_PLATINUM_TRAVEL_MILES",
            "VPBank Visa Platinum Travel Miles",
            VISA,
            "Platinum Travel Miles",
            "Visa Platinum Travel Credit",
            tier="platinum",
        ),
        _card(
            "VPB_SIGNATURE_TRAVEL_MILES",
            "VPBank Visa Signature Travel Miles",
            VISA,
            "Signature Travel Miles",
            "Visa Signature Travel Credit",
            tier="signature",
        ),
        _card(
            "VPB_YOJO",
            "VPBank YoJo Visa Platinum",
            VISA,
            "VPBank YOJO",
            "VPBank YoJo Visa Platinum",
            tier="platinum",
        ),
        _card(
            "VPB_COMMCREDIT",
            "VPBank CommCredit Mastercard",
            MC,
            "CommCredit",
            "CommCredit MC Credit",
        ),
        _card(
            "VPB_UNIONPAY_FREEWAYS",
            "VPBank UnionPay FreeWays",
            UP,
            "UnionPay FreeWays",
            "UnionPay Free Ways",
        ),
        _card("VPB_GAMEON", "VPBank GameON Mastercard", MC, "VPBank GameON"),
        _card("VPB_MWG", "VPBank MWG Mastercard", MC, "VPBank MWG", "VPBank MWG Mastercard Credit"),
        _card("VPB_S_REWARDS", "VPBank S Rewards Mastercard", MC, "VPBank S Rewards"),
        _card(
            "VPB_PRIVATE_INFINITE",
            "VPBank Private Visa Infinite Privilege",
            VISA,
            "Private Visa Infinite Privilege",
            "VPBank Private Visa Infinite Privilege",
            tier="infinite",
        ),
        _card("VPB_FLEX", "VPBank Flex Mastercard", MC, "VPBank Flex", "VPBank Flex Credit"),
        # Network not stated by VPBank in the documents we read.
        _card("VPB_NO1", "VPBank No.1", None, "No.1"),
        _card("VPB_LADY", "VPBank Lady", None, "Lady", "Titanium Lady Credit"),
        _card("VPB_STEPUP", "VPBank StepUp", None, "StepUp", "Titanium StepUp Credit"),
        _card("VPB_GOLD_TRAVEL_MILES", "VPBank Gold Travel Miles", None, "Gold Travel Miles"),
        _card("VPB_TITANIUM_CASHBACK", "VPBank Titanium Cashback", None, "Titanium Cashback"),
        _card(
            "VPB_SHOPEE_PLATINUM",
            "VPBank Shopee Platinum",
            None,
            "Shopee Platinum",
            "Shopee Platinum Credit",
        ),
        _card(
            "VPB_SUPER_SHOPEE",
            "VPBank Super Shopee Platinum",
            None,
            "Super Shopee",
            "Super Shopee Platinum Credit",
        ),
        _card("VPB_PLATINUM_LOYALTY", "VPBank Platinum Loyalty", None, "Platinum Loyalty"),
        _card("VPB_VNA", "Vietnam Airlines VPBank", None, "VNA VPBank", "VNA Credit"),
        _card(
            "VPB_PLATINUM_CASHBACK",
            "VPBank Platinum Cashback",
            None,
            "Platinum Cashback",
            "Platinum Cashback Credit",
        ),
        _card("VPB_PRESTIGE", "VPBank Prestige", None, "Prestige Credit"),
        _card(
            "VPB_MOBIFONE_CLASSIC",
            "Mobifone VPBank Classic",
            None,
            "Mobifone – VPBank Classic",
            "Mobifone VPBank Classic Credit",
        ),
        _card(
            "VPB_MOBIFONE_TITANIUM",
            "Mobifone VPBank Titanium",
            None,
            "Mobifone – VPBank Titanium",
            "Mobifone VPBank Titanium Credit",
        ),
        _card(
            "VPB_MOBIFONE_PLATINUM",
            "Mobifone VPBank Platinum",
            None,
            "Mobifone – VPBank Platinum",
            "Mobifone VPBank Platinum Credit",
        ),
        _card("VPB_CALIFORNIA_PLATINUM", "California Platinum VPBank", None, "California Platinum"),
        _card(
            "VPB_CALIFORNIA_SIGNATURE", "California Signature VPBank", None, "California Signature"
        ),
        _card("VPB_DIAMOND_WORLD", "VPBank Diamond World", None, "Diamond World"),
        _card("VPB_DIAMOND_WORLD_LADY", "VPBank Diamond World Lady", None, "Diamond World Lady"),
        _card("VPB_PRIORITY_PLATINUM", "VPBank Priority Platinum", None, "Priority Platinum"),
        _card(
            "VPB_VNA_PRIORITY_PLATINUM",
            "VNA – VPBank Priority Platinum",
            None,
            "VNA – VPBank Priority Platinum",
        ),
        _card("VPB_TIMO", "TIMO VPBank", None, "TIMO"),
    ),
)

NOTES = """\
- Each table cell starts with the names of the card columns it applies to, in
  brackets: "[Lady, StepUp] 599.000 VND" is 599.000 VND for Lady and for StepUp. A value
  belongs only to the cards in its own brackets. Quote the row label and that cell.
- "TT" means minimum (tối thiểu) and "TĐ" maximum (tối đa).
- Row "2.1. Thẻ chính" is the primary card's annual fee; "2.2. Thẻ phụ" the
  supplementary card's. Row "2.1.2" is the yearly spend that waives the next year's fee.
- For VPBank Flex, use the "Tính năng thẻ tín dụng" (credit) column, not "Tính năng thẻ ghi nợ".
- The interest rates on page 1 ("3.99%") don't say per month or per year: leave them out.
- Fees are before VAT ("chưa bao gồm VAT"): report them as written.
"""


def newest_card_schedule(listing: bytes) -> str:
    """Path of the newest personal-customer credit card fee schedule in the listing."""
    try:
        documents = json.loads(listing)["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AdapterBroken(f"document listing has an unexpected shape: {exc}") from exc
    matching = [d for d in documents if str(d.get("title") or "").startswith(TITLE)]
    if not matching:
        raise AdapterBroken(f"no document titled {TITLE!r} in the listing")
    newest = max(matching, key=lambda d: d.get("publishDate") or "")
    pdfs = [
        i.get("url")
        for i in newest.get("itemList") or []
        if str(i.get("url", "")).lower().endswith(".pdf")
    ]
    if len(pdfs) != 1 or not DOC_URL.match(str(pdfs[0])):
        raise AdapterBroken(f"expected one card schedule PDF, got {pdfs!r}")
    return str(pdfs[0])


@register
class VpbankCardTariff(LlmCardAdapter):
    name = "vpbank_card_tariff"
    institution = "VPBANK"
    source_kind = SourceKind.CARD_TARIFF_PDF
    fetch_method = FetchMethod.PDF
    mode = "terms"
    catalogue = VPBANK_CARDS
    label_columns = True
    reading_notes = NOTES

    def resolve_url(self) -> str:
        listing = self.ctx.fetchers.for_method(FetchMethod.HTTP).fetch(super().resolve_url())
        return "https://www.vpbank.com.vn" + newest_card_schedule(listing.content)


# Card pages from https://www.vpbank.com.vn/sitemap.xml, checked 2026-10-29.
# source.variant -> cards. YoJo has no page of its own.
VPBANK_CARD_PAGES: dict[str, tuple[str, ...]] = {
    "mc2": ("VPB_MC2",),
    "z": ("VPB_Z",),
    "platinum-travel-miles": ("VPB_PLATINUM_TRAVEL_MILES",),
    "signature-travel-miles": ("VPB_SIGNATURE_TRAVEL_MILES",),
    "commcredit": ("VPB_COMMCREDIT",),
    "unionpay": ("VPB_UNIONPAY_FREEWAYS",),
    "gameon": ("VPB_GAMEON",),
    "mwg": ("VPB_MWG",),
    "s-rewards": ("VPB_S_REWARDS",),
    "private-visa-infinite": ("VPB_PRIVATE_INFINITE",),
    "flex": ("VPB_FLEX",),
}

PRODUCT_NOTES = """\
- The card's terms are in the detail blocks after the page header ("Tính năng nổi
  bật", "Lợi ích", FAQ); the header repeats them as headlines.
- "/kỳ sao kê" (per statement period) is monthly.
- The interest rate in the FAQ is per month ("%/tháng"): it is not a yearly
  interest_rate_pct, so leave it out. "miễn lãi tối đa N ngày" is interest_free_days.
"""


@register
class VpbankCardProducts(LlmCardAdapter):
    """One source per card page (source.variant names the page). The details are
    shipped as page data, not markup; the reader decodes them (document.py)."""

    name = "vpbank_card_products"
    institution = "VPBANK"
    source_kind = SourceKind.CARD_PRODUCT_PAGE
    fetch_method = FetchMethod.HTTP
    mode = "products"
    catalogue = VPBANK_CARDS
    card_pages = VPBANK_CARD_PAGES
    reading_notes = PRODUCT_NOTES
