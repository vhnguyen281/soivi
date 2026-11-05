"""BIDV credit cards: the card section of BIDV's fee schedule, read with the LLM.
Notes in docs/adapters/bidv.md.

The schedule (PDF, 24 pages, applies from 20/08/2026) covers credit, debit, prepaid
and other banks' cards; only section 1 (credit cards, pages 1-6) is read. Cards are
rows; the columns are customer segments, and we publish the standard customer
column ("KHCN thông thường").

Every network below is written in the card's own name in the schedule.
"""

from core.enums import CardNetwork, FetchMethod, SourceKind
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.catalogue import Card, Catalogue
from pipeline.registry import register

VISA, MC, JCB = CardNetwork.VISA, CardNetwork.MASTERCARD, CardNetwork.JCB
DISCONTINUED = (
    "no longer issued: annual fees from the discontinued-cards annex, "
    "late fee from the 'Thẻ khác' (other cards) row"
)


def _card(
    code: str,
    name: str,
    network: CardNetwork | None,
    *spellings: str,
    tariff: bool = True,
    tier: str | None = None,
    note: str = "",
) -> Card:
    return Card(
        code, name, network, tier, spellings, in_tariff=tariff and network is not None, note=note
    )


BIDV_CARDS = Catalogue(
    "BIDV",
    (
        _card(
            "BIDV_VISA_INFINITE_30",
            "BIDV Visa Infinite (gói đặc quyền 30 triệu)",
            VISA,
            "Thẻ chính/phụ Visa Infinite (gói đặc quyền 30 triệu đồng)",
            tier="infinite",
        ),
        _card(
            "BIDV_VISA_INFINITE_15",
            "BIDV Visa Infinite (gói đặc quyền 15 triệu)",
            VISA,
            "Thẻ chính/phụ Visa Infinite (gói đặc quyền 15 triệu đồng)",
            tier="infinite",
        ),
        _card(
            "BIDV_VISA_INFINITE_05",
            "BIDV Visa Infinite (gói đặc quyền 5 triệu)",
            VISA,
            "Thẻ chính/phụ Visa Infinite (gói đặc quyền 05 triệu đồng)",
            tier="infinite",
        ),
        _card("BIDV_JCB_ULTIMATE", "BIDV JCB Ultimate", JCB, "JCB Ultimate"),
        _card(
            "BIDV_MC_WORLD_TRAVEL",
            "BIDV Mastercard World Travel",
            MC,
            "Mastercard World Travel",
            tier="world",
        ),
        _card("BIDV_JCB_WELLBEING", "BIDV JCB Well-being", JCB, "JCB Well-being"),
        _card(
            "BIDV_VISA_CASHBACK_ONLINE", "BIDV Visa Cashback Online", VISA, "Visa Cashback Online"
        ),
        _card(
            "BIDV_VISA_CASHBACK_360",
            "BIDV Visa Cashback 360",
            VISA,
            "Visa Cashback 360",
            "Visa Platinum Cashback 360",
        ),
        _card(
            "BIDV_MC_STANDARD_TPV",
            "BIDV Mastercard Standard TPV",
            MC,
            "Mastercard standard TPV",
            "Master Card Standard TPV",
        ),
        _card("BIDV_VISA_FLEXI", "BIDV Visa Flexi", VISA, "Visa Flexi"),
        _card("BIDV_VISA_EASY", "BIDV Visa Easy", VISA, "Visa Easy"),
        _card(
            "BIDV_VISA_PREMIER",
            "BIDV Visa Premier",
            VISA,
            "Visa Premier (Platinum)",
            "Visa Premier",
            tier="platinum",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_MC_INSPIRE",
            "BIDV Mastercard Inspire",
            MC,
            "MasterCard Inspire",
            "MasterCard Insipre",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_VISA_PRECIOUS",
            "BIDV Visa Precious",
            VISA,
            "Visa Precious",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_MC_VIETRAVEL_PLATINUM",
            "BIDV Mastercard Vietravel Platinum",
            MC,
            "MasterCard Vietravel Platinum",
            tier="platinum",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_MC_VIETRAVEL_STANDARD",
            "BIDV Mastercard Vietravel Standard",
            MC,
            "Mastercard Vietravel Standard",
            "Master card Vietravel Standard",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_VISA_CREDIT_TPV",
            "BIDV Visa Credit TPV",
            VISA,
            "Visa Credit TPV",
            "Visa Classic TPV",
            note=DISCONTINUED,
        ),
        _card(
            "BIDV_VISA_PLATINUM",
            "BIDV Visa Platinum",
            VISA,
            "Visa Platinum",
            tariff=False,
            tier="platinum",
            note="named in group fee rows, but has no annual fee row",
        ),
        _card(
            "BIDV_PRIVATE_BANKING",
            "BIDV Private Banking",
            None,
            "Private Banking",
            "Premier (hạng Signature)",
            note="network not written in the schedule: not published until confirmed",
        ),
    ),
)

NOTES = """\
- Use only the "KHCN thông thường" column (standard personal customers). Ignore the
  "KH Premier/Premier Elite" and "KH Private" columns, even when they hold the same value.
- "Thẻ chính X" rows give annual_fee_primary_vnd; "Thẻ phụ X" rows give annual_fee_supp_vnd;
  "Thẻ chính/phụ X" rows give both. A combo row ("Combo thẻ ...") is not a card: skip it.
- Fees are before VAT ("chưa bao gồm VAT"): report them as written.
- A fee row in this credit card section that names no card (e.g. "Phí chuyển đổi ngoại
  tệ") applies to every card listed above: report it for each card, quoting that row.
- Cash advance: use the general row "Các trường hợp còn lại". The Visa Easy row "tại
  POS/MGDTD BIDV" is a special rate at BIDV's own machines only: don't use it.
- "Thẻ khác" (other cards) rows apply to every card not named in the rows above them.
"""


@register
class BidvCardTariff(LlmCardAdapter):
    name = "bidv_card_tariff"
    institution = "BIDV"
    source_kind = SourceKind.CARD_TARIFF_PDF
    fetch_method = FetchMethod.PDF
    mode = "terms"
    catalogue = BIDV_CARDS
    section = ("1. BIỂU PHÍ DỊCH VỤ THẺ TÍN DỤNG", "2. BIỂU PHÍ DỊCH VỤ THẺ GHI NỢ")
    reading_notes = NOTES


# Card pages under the credit card list (https://bidv.com.vn/vn/ca-nhan/san-pham-dich-vu/
# dich-vu-the/the-tin-dung-quoc-te), checked 2026-10-29. source.variant -> cards.
# The Visa Infinite page covers all three privilege packages.
BIDV_CARD_PAGES: dict[str, tuple[str, ...]] = {
    "visa-infinite": ("BIDV_VISA_INFINITE_30", "BIDV_VISA_INFINITE_15", "BIDV_VISA_INFINITE_05"),
    "jcb-ultimate": ("BIDV_JCB_ULTIMATE",),
    "mc-world-travel": ("BIDV_MC_WORLD_TRAVEL",),
    "jcb-well-being": ("BIDV_JCB_WELLBEING",),
    "visa-cashback-online": ("BIDV_VISA_CASHBACK_ONLINE",),
    "visa-cashback-360": ("BIDV_VISA_CASHBACK_360",),
    "visa-flexi": ("BIDV_VISA_FLEXI",),
    "visa-easy": ("BIDV_VISA_EASY",),
    "mc-inspire": ("BIDV_MC_INSPIRE",),
    "mc-vietravel-standard": ("BIDV_MC_VIETRAVEL_STANDARD",),
    "mc-vietravel-platinum": ("BIDV_MC_VIETRAVEL_PLATINUM",),
    "visa-precious": ("BIDV_VISA_PRECIOUS",),
    "visa-platinum": ("BIDV_VISA_PLATINUM",),
}

PRODUCT_NOTES = """\
- "Chương trình tích lũy điểm thưởng" is a points programme: rates written as
  "Tích điểm ... % giá trị giao dịch" are points, not cashback.
- The "Biểu phí" lines on these pages are not rewards or perks. "Lãi suất: X%/năm"
  is interest_rate_pct; "miễn lãi tối đa N ngày" is interest_free_days.
"""


@register
class BidvCardProducts(LlmCardAdapter):
    """One source per card page (source.variant names the page)."""

    name = "bidv_card_products"
    institution = "BIDV"
    source_kind = SourceKind.CARD_PRODUCT_PAGE
    fetch_method = FetchMethod.HTTP
    mode = "products"
    catalogue = BIDV_CARDS
    card_pages = BIDV_CARD_PAGES
    # Under the card details every page lists the bank's card promotions.
    html_until = "Dịch vụ hỗ trợ 1900"
    reading_notes = PRODUCT_NOTES
