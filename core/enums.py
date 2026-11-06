"""Fixed value sets used by the models.

Stored in Postgres as VARCHAR + CHECK constraint (not native enums), so adding a
value is a simple migration that swaps the CHECK.
"""

from enum import StrEnum


class InstitutionType(StrEnum):
    STATE_BANK = "state_bank"
    JOINT_STOCK_BANK = "joint_stock_bank"
    FOREIGN_BANK = "foreign_bank"
    CONSUMER_FINANCE = "consumer_finance"


class SourceKind(StrEnum):
    SAVINGS_RATE_PAGE = "savings_rate_page"
    CARD_TARIFF_PDF = "card_tariff_pdf"
    CARD_PRODUCT_PAGE = "card_product_page"
    NEWS_FEED = "news_feed"
    OFFICIAL = "official"
    MARKET_DATA = "market_data"  # VNCMA: one source per data provider (vnstock, HNX, ...)


class FetchMethod(StrEnum):
    HTTP = "http"
    BROWSER = "browser"
    PDF = "pdf"
    OCR = "ocr"
    API = "api"  # a library or JSON API (vnstock), not a page


class ExtractionMethod(StrEnum):
    """How a value was read from its snapshot."""

    MANUAL = "manual"
    HTML = "html"
    PDF_TABLE = "pdf_table"
    OCR = "ocr"
    LLM = "llm"


class VersionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    # A pending version replaced by a newer proposal before anyone reviewed it.
    SUPERSEDED = "superseded"


class Channel(StrEnum):
    COUNTER = "counter"
    ONLINE = "online"
    APP = "app"


class InterestPayment(StrEnum):
    END = "end"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    UPFRONT = "upfront"


class CardNetwork(StrEnum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    JCB = "jcb"
    NAPAS = "napas"
    AMEX = "amex"
    UNIONPAY = "unionpay"


class CardType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class RewardCategory(StrEnum):
    ALL = "all"
    DINING = "dining"
    ONLINE = "online"
    TRAVEL = "travel"
    FUEL = "fuel"
    GROCERY = "grocery"
    OVERSEAS = "overseas"
    OTHER = "other"


class RewardType(StrEnum):
    CASHBACK = "cashback"
    POINTS = "points"
    MILES = "miles"


class ReviewTaskKind(StrEnum):
    VERSION_REVIEW = "version_review"
    PARSE_FAILURE = "parse_failure"
    COMMUNITY_REPORT = "community_report"
    NEWS_RECHECK = "news_recheck"


class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_FIX = "needs_fix"


class ReviewActionKind(StrEnum):
    APPROVE = "approve"  # one version
    REJECT = "reject"  # one version
    APPROVE_ALL = "approve_all"  # every pending version in a task
    REJECT_ALL = "reject_all"
    NEEDS_FIX = "needs_fix"  # task flagged for a developer; its pending versions rejected
    RETIRE = "retire"  # a live version taken down without a successor (needs a note)


class CommunityReportStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    RECHECK_QUEUED = "recheck_queued"
    CLOSED = "closed"


class NewsClassification(StrEnum):
    RATE_CHANGE = "rate_change"
    CARD_CHANGE = "card_change"
    OTHER = "other"
    IRRELEVANT = "irrelevant"


class NewsDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class MonthEndRule(StrEnum):
    """How one value per period is taken from a market series.

    See docs/vncma/design-market-data.md §3.
    """

    # The last value on or before the period end, at most `max_gap_days` earlier.
    LAST_ON_OR_BEFORE = "last_on_or_before"
    # The provider already gives one value per period (CPI per month, GDP per year).
    PERIOD_VALUE = "period_value"


class DataGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
