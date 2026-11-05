"""Techcombank credit cards: fee schedule PDF (card terms) and the card list page
(rewards and perks), both read with the LLM. Notes in docs/adapters/techcombank.md.

Catalogue checked on 2026-10-28 against:
- the fee schedule for standard customers (biểu phí thẻ tín dụng cho khách hàng thường),
- the card list https://techcombank.com/khach-hang-ca-nhan/chi-tieu/the/the-tin-dung,
- each card's own page for its network: Everyday ("Thẻ Techcombank Visa Everyday"),
  Spark (card images named "visa-spark"), Style (the tariff groups it with
  "Thẻ tín dụng Visa khác"); the others carry "Visa" in their name.
"""

from core.enums import CardNetwork, FetchMethod, SourceKind
from pipeline.cards.adapter import LlmCardAdapter
from pipeline.cards.catalogue import Card, Catalogue
from pipeline.registry import register

VISA = CardNetwork.VISA

TECHCOMBANK_CARDS = Catalogue(
    "Techcombank",
    (
        Card(
            "TCB_VISA_SIGNATURE",
            "Techcombank Visa Signature",
            VISA,
            "signature",
            ("Thẻ tín dụng Visa Signature", "Thẻ tín dụng Techcombank Visa Signature"),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "TCB_PRIORITY_VISA_SIGNATURE",
            "Techcombank Priority Visa Signature",
            VISA,
            "signature",
            ("Thẻ tín dụng Techcombank Priority Visa Signature",),
            in_products=True,
            note="Priority members; its fees are in the Priority tariff, not this one",
        ),
        Card(
            "TCB_VISA_INFINITE",
            "Techcombank Visa Infinite",
            VISA,
            "infinite",
            (
                "Thẻ tín dụng Techcombank Visa Infinite",
                "Thẻ tín dụng Techcombank Private Visa Infinite",  # its own page's title
                "Visa Infinite",
            ),
            in_products=True,
            note="its fees are in a separate tariff",
        ),
        Card(
            "TCW_VISA_INFINITE_PRIVATE",
            "Techcom Wealth Visa Infinite Private",
            VISA,
            "infinite",
            ("Thẻ tín dụng Techcom Wealth Visa Infinite Private",),
            in_products=True,
            note="invitation only; its fees are in a separate tariff",
        ),
        Card(
            "TCB_SPARK",
            "Techcombank Spark",
            VISA,
            None,
            ("Thẻ tín dụng Techcombank Spark", "Techcombank Spark"),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "TCB_EVERYDAY",
            "Techcombank Everyday",
            VISA,
            None,
            ("Thẻ tín dụng Techcombank Everyday", "Techcombank Everyday"),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "TCB_STYLE",
            "Techcombank Style",
            VISA,
            None,
            ("Thẻ tín dụng Techcombank Style", "Techcombank Style"),
            in_tariff=True,
            in_products=True,
            note="no longer issued (ngưng phát hành); existing cards keep these terms",
        ),
        Card(
            "TCB_VISA_ECO",
            "Techcombank Visa Eco",
            VISA,
            None,
            ("Thẻ tín dụng Techcombank Eco", "Thẻ tín dụng Techcombank Visa Eco"),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "TCB_VISA_CLASSIC",
            "Techcombank Visa Classic",
            VISA,
            "classic",
            ("Thẻ tín dụng Techcombank Visa Chuẩn", "Visa Chuẩn", "Techcombank Visa Classic"),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "VNA_VISA_PLATINUM",
            "Vietnam Airlines Techcombank Visa Platinum",
            VISA,
            "platinum",
            (
                "Thẻ tín dụng VietnamAirlines Techcombank Visa Platinum",
                "Visa VNA Platinum",
                "VNA Platinum",
            ),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "VNA_VISA_GOLD",
            "Vietnam Airlines Techcombank Visa Gold",
            VISA,
            "gold",
            (
                "Thẻ tín dụng VietnamAirlines Techcombank Visa Vàng",
                "Visa VNA Vàng",
                "VNA Vàng",
                "VNA Gold",
            ),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "VNA_VISA_CLASSIC",
            "Vietnam Airlines Techcombank Visa Classic",
            VISA,
            "classic",
            (
                "Thẻ tín dụng VietnamAirlines Techcombank Visa Chuẩn",
                "VNA Chuẩn",
                "Visa VNA chuẩn",
            ),
            in_tariff=True,
            in_products=True,
        ),
        Card(
            "DREAMCARD",
            "DreamCard",
            None,  # the tariff and the site don't state its network
            None,
            ("Thẻ tín dụng DreamCard", "DreamCard Credit Card"),
            note="in the tariff only; not published until its network is confirmed",
        ),
    ),
)


@register
class TechcombankCardTariff(LlmCardAdapter):
    name = "techcombank_card_tariff"
    institution = "TECHCOMBANK"
    source_kind = SourceKind.CARD_TARIFF_PDF
    fetch_method = FetchMethod.PDF
    mode = "terms"
    catalogue = TECHCOMBANK_CARDS


@register
class TechcombankCardProducts(LlmCardAdapter):
    """The card list page. Not monitored since 2026-10-30: it carries only headlines
    ("Hoàn tiền lên tới 5 triệu/tháng, tới 10%"); the card pages below replace it."""

    name = "techcombank_card_products"
    institution = "TECHCOMBANK"
    source_kind = SourceKind.CARD_PRODUCT_PAGE
    fetch_method = FetchMethod.HTTP
    mode = "products"
    catalogue = TECHCOMBANK_CARDS


# Each card's own page, linked from the card list; checked 2026-10-30.
# source.variant -> cards.
TECHCOMBANK_CARD_PAGES: dict[str, tuple[str, ...]] = {
    "visa-signature": ("TCB_VISA_SIGNATURE",),
    "priority-visa-signature": ("TCB_PRIORITY_VISA_SIGNATURE",),
    "visa-infinite": ("TCB_VISA_INFINITE",),  # page title "... Private Visa Infinite"
    "wealth-visa-infinite-private": ("TCW_VISA_INFINITE_PRIVATE",),
    "spark": ("TCB_SPARK",),
    "everyday": ("TCB_EVERYDAY",),
    "style": ("TCB_STYLE",),
    "visa-eco": ("TCB_VISA_ECO",),
    "visa-classic": ("TCB_VISA_CLASSIC",),
    "vna-visa-platinum": ("VNA_VISA_PLATINUM",),
    "vna-visa-gold": ("VNA_VISA_GOLD",),
    "vna-visa-classic": ("VNA_VISA_CLASSIC",),
}

PAGE_NOTES = """\
- "Hoàn tiền lên đến/tới X triệu/tháng" is a headline over the detailed list below it.
- Cashback at a list of partner merchants ("nhà hàng đối tác (Danh sách ...)") is
  one merchant group, not a category: put it in other_perks_text.
- "điểm hoàn tiền" are cashback points paid out as cash ("rút tiền hoàn"): a cap
  written as "tới 2 triệu điểm hoàn tiền/tháng" is a monthly cashback cap in VND.
- U-Point bonuses that start at a total monthly spend ("từ 50 triệu đồng/tháng")
  are tiered: put them in other_perks_text.
- Promotions with a date or "khi mở thẻ" (welcome offers) are not rewards.
"""


@register
class TechcombankCardPages(LlmCardAdapter):
    """One source per card page (source.variant names the page)."""

    name = "techcombank_card_pages"
    institution = "TECHCOMBANK"
    source_kind = SourceKind.CARD_PRODUCT_PAGE
    fetch_method = FetchMethod.HTTP
    mode = "products"
    catalogue = TECHCOMBANK_CARDS
    card_pages = TECHCOMBANK_CARD_PAGES
    reading_notes = PAGE_NOTES
