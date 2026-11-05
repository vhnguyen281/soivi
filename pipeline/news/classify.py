"""Decide whether a news item reports a change to a bank's deposit rates or card fees.

Keywords first. An item with none of the topic words is irrelevant. An item whose
headline plainly says "<bank> <raises/cuts> <deposit rates | card fees>" is decided
by keywords, and so is an on-topic item that names no institution we know (there is
nothing to re-check, so an LLM call would buy nothing). Everything else that
mentions the topic is ambiguous and goes to the LLM (pipeline/news/llm.py), if one
is configured; otherwise it stays unclassified and is retried on the next run.

Keywords are matched on the accented text: folding would make "giảm" (cut) equal
"giám" (as in giám đốc) and "tăng" (raise) equal "tặng" (gift).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from core.enums import NewsClassification, NewsDirection
from pipeline.extract.vietnamese import clean
from pipeline.news.institutions import InstitutionMatcher

# The topic words from the brief; any of these makes an item relevant.
RATE_TOPIC = ("lãi suất", "huy động", "tiết kiệm")
CARD_TOPIC = ("phí thẻ", "thẻ tín dụng", "biểu phí")

# Phrases specific enough to decide without the LLM.
RATE_CLEAR = (
    "lãi suất huy động",
    "lãi suất tiết kiệm",
    "lãi suất tiền gửi",
    "lãi suất gửi tiết kiệm",
    "biểu lãi suất",
)
CARD_CLEAR = ("phí thẻ", "biểu phí thẻ", "phí thường niên", "phí chuyển đổi ngoại tệ")

UP = ("tăng", "nâng", "điều chỉnh tăng")
DOWN = ("giảm", "hạ", "cắt giảm", "điều chỉnh giảm")
CHANGE = (*UP, *DOWN, "điều chỉnh", "thay đổi", "áp dụng")
# Removed before looking for change verbs ("tăng trưởng" is growth, not a raise).
NOT_A_CHANGE = ("tăng trưởng", "gia tăng", "tăng cường", "tăng vốn", "hạ tầng", "hạ nhiệt")
# Headlines with these need judgement (lending, policy or foreign rates, opinion).
NEEDS_JUDGEMENT = (
    "cho vay",
    "lãi suất vay",
    "liên ngân hàng",
    "lãi suất điều hành",
    "ngân hàng nhà nước",
    "nhnn",
    "fed",
    "trái phiếu",
    "tín phiếu",
    "dự báo",
)


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text) for p in phrases)


def _lower(text: str | None) -> str:
    return clean(text).lower()


@dataclass
class Classification:
    about_rates: bool
    about_card_fees: bool
    institutions: list[str]  # short names whose rates/fees the item says changed
    direction: NewsDirection
    method: str  # keywords | llm
    relevant: bool = True  # mentions the topic at all
    extra: dict[str, Any] = field(default_factory=dict)  # e.g. the model used

    @property
    def category(self) -> NewsClassification:
        if self.about_rates:
            return NewsClassification.RATE_CHANGE
        if self.about_card_fees:
            return NewsClassification.CARD_CHANGE
        return NewsClassification.OTHER if self.relevant else NewsClassification.IRRELEVANT

    @property
    def triggers_recheck(self) -> bool:
        return (self.about_rates or self.about_card_fees) and bool(self.institutions)

    def as_json(self) -> dict[str, Any]:
        return {
            "about_rates": self.about_rates,
            "about_card_fees": self.about_card_fees,
            "institutions": self.institutions,
            "direction": self.direction.value,
            "method": self.method,
            **self.extra,
        }


def direction_of(text: str) -> NewsDirection:
    for phrase in NOT_A_CHANGE:
        text = text.replace(phrase, " ")
    up, down = _has(text, UP), _has(text, DOWN)
    if up and not down:
        return NewsDirection.UP
    if down and not up:
        return NewsDirection.DOWN
    return NewsDirection.UNKNOWN


def is_relevant(title: str | None, summary: str | None) -> bool:
    text = f"{_lower(title)} {_lower(summary)}"
    return _has(text, RATE_TOPIC + CARD_TOPIC)


def classify_keywords(
    title: str, summary: str | None, matcher: InstitutionMatcher
) -> Classification | None:
    """A decision, or None when the item is on topic but needs the LLM."""
    if not is_relevant(title, summary):
        return Classification(False, False, [], NewsDirection.UNKNOWN, "keywords", relevant=False)

    head = _lower(title)
    without_noise = head
    for phrase in NOT_A_CHANGE:
        without_noise = without_noise.replace(phrase, " ")
    rates, cards = _has(head, RATE_CLEAR), _has(head, CARD_CLEAR)
    says_change = (
        (rates or cards)
        and _has(without_noise, CHANGE)
        and not _has(head, NEEDS_JUDGEMENT)
        and "?" not in head
    )
    if not matcher.find(title, summary):
        # No institution named: nothing to re-check, so the LLM could add nothing.
        return Classification(
            bool(says_change and rates),
            bool(says_change and cards),
            [],
            direction_of(head) if says_change else NewsDirection.UNKNOWN,
            "keywords",
            extra={"note": "no institution named"},
        )
    institutions = matcher.find(title)
    if not (says_change and institutions):
        return None
    return Classification(rates, cards, institutions, direction_of(head), "keywords")
