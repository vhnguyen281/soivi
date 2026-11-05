"""Verified facts -> records, with evidence for each value and notes for the reviewer.

A fact that fails a check is dropped and the reason becomes a note (shown as a
warning on the review task), so the reviewer sees what was left out and why.
Two different verified values for one card field are a conflict: both are
dropped, and the note shows both quotes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from core.enums import CardType, RewardType
from pipeline.cards.catalogue import Card, Catalogue
from pipeline.cards.document import Page
from pipeline.cards.fields import (
    BY_NAME,
    INTEREST,
    PERKS,
    PRODUCT_CARD_FIELDS,
    REWARDS,
    TERMS,
    FieldSpec,
)
from pipeline.cards.llm import Mode, PageAnswer
from pipeline.cards.verify import Rejected, check, quote_on_page
from pipeline.extract.vietnamese import fold
from pipeline.records import (
    CardInterestRecord,
    CardPerkRecord,
    CardRewardRecord,
    CardTermsRecord,
    Record,
)
from pipeline.validate.rules import RuleWarning

Evidence = dict[str, Any]

# A cashback rate with no cap is only taken when the bank says it has none:
# "Hoàn tiền 15% cho mọi chi tiêu" is usually a headline over capped categories.
_UNCAPPED = ("khong gioi han", "unlimited", "no cap")


@dataclass
class Built:
    records: list[Record] = field(default_factory=list)
    notes: list[RuleWarning] = field(default_factory=list)
    unlisted_cards: list[str] = field(default_factory=list)
    missing_cards: list[str] = field(default_factory=list)  # expected but absent
    texts: dict[int, str] = field(default_factory=dict)  # page number -> text quotes are on


@dataclass
class _Accepted:
    value: Any
    evidence: Evidence


class _Builder:
    def __init__(
        self,
        catalogue: Catalogue,
        pages: Sequence[Page],
        mode: Mode,
        only: frozenset[str] | None = None,
    ) -> None:
        self.catalogue = catalogue
        self.only = only  # a card's own page: facts about other cards are ignored
        self.ignored: set[str] = set()
        self.text = {p.number: p.render() for p in pages}
        self.method = {p.number: p.method for p in pages}
        self.mode = mode
        self.out = Built(texts=self.text)
        self.table = "card_terms" if mode == "terms" else "card_perk"

    def note(self, rule: str, table: str, card: str, message: str, fld: str | None = None) -> None:
        self.out.notes.append(RuleWarning(rule, table, {"card": card}, message, fld))

    def card(self, code: str) -> Card | None:
        try:
            card = self.catalogue.get(code)
        except KeyError:
            self.note("unknown_card_code", self.table, code, f"unknown card code {code!r}")
            return None
        if self.only is not None and card.code not in self.only:
            if card.code not in self.ignored:
                self.ignored.add(card.code)
                self.note(
                    "other_card_on_page",
                    self.table,
                    card.name,
                    "named on another card's page (e.g. a 'compare cards' block): ignored here",
                )
            return None
        return card

    def verify(
        self, spec: FieldSpec, fact: dict[str, Any], card: Card, table: str
    ) -> _Accepted | None:
        page, quote, value = fact.get("page"), str(fact.get("quote", "")), str(fact.get("value"))
        where = f"{spec.name} = {value!r} (trang {page})"
        if page not in self.text:
            self.note("dropped_bad_page", table, card.name, f"{where}: no such page", spec.name)
            return None
        if not quote_on_page(quote, self.text[page]):
            self.note(
                "dropped_quote_not_found",
                table,
                card.name,
                f"{where}: quote not found on the page: {quote[:200]!r}",
                spec.name,
            )
            return None
        try:
            typed = check(spec, value, quote)
        except Rejected as exc:
            self.note("dropped_unreadable", table, card.name, f"{where}: {exc}", spec.name)
            return None
        evidence = {"page": page, "quote": quote, "value": value}
        if self.method.get(page) == "ocr":
            evidence["ocr"] = True  # the page text came from OCR: worth a closer look
        return _Accepted(typed, evidence)

    def merge(
        self, card: Card, table: str, found: dict[str, list[_Accepted]]
    ) -> tuple[dict[str, Any], Evidence]:
        values: dict[str, Any] = {}
        evidence: Evidence = {}
        for name, accepted in found.items():
            if BY_NAME[name].kind == "text":
                # Text fields list things (perks, conditions): several quotes add up.
                unique = list({str(a.value): a for a in accepted}.values())
                values[name] = "; ".join(str(a.value) for a in unique)
                evidence[name] = dict(unique[0].evidence)
                if len(unique) > 1:
                    evidence[name]["also"] = [a.evidence for a in unique[1:]]
                continue
            distinct = {repr(a.value) for a in accepted}
            if len(distinct) > 1:
                quotes = "; ".join(
                    f"{a.evidence['value']!r} (trang {a.evidence['page']})" for a in accepted
                )
                self.note(
                    "dropped_conflict",
                    table,
                    card.name,
                    f"{name}: the document gives different values: {quotes}",
                    name,
                )
                continue
            values[name] = accepted[0].value
            evidence[name] = accepted[0].evidence
        return values, evidence

    # ------------------------------------------------------------------ cards

    def card_facts(
        self, answers: Sequence[PageAnswer], fields: tuple[FieldSpec, ...]
    ) -> dict[str, dict[str, list[_Accepted]]]:
        specs = {f.name: f for f in fields}
        found: dict[str, dict[str, list[_Accepted]]] = {}
        for answer in answers:
            self.out.unlisted_cards += [
                n for n in answer.data.get("unlisted_cards", []) if n not in self.out.unlisted_cards
            ]
            for entry in answer.data.get("cards", []):
                card = self.card(entry.get("card", ""))
                if card is None:
                    continue
                for fact in entry.get("facts", []):
                    spec = specs.get(fact.get("field", ""))
                    if spec is None:
                        continue
                    accepted = self.verify(spec, fact, card, self.table)
                    if accepted is not None:
                        found.setdefault(card.code, {}).setdefault(spec.name, []).append(accepted)
        return found

    def terms(self, answers: Sequence[PageAnswer]) -> None:
        found = self.card_facts(answers, TERMS)
        for card in self.catalogue.cards:
            facts = found.get(card.code, {})
            if card.in_tariff and card.publish and "annual_fee_primary_vnd" not in facts:
                self.out.missing_cards.append(card.name)
            if not facts:
                continue
            if not card.publish:
                self.note(
                    "not_published",
                    "card_terms",
                    card.name,
                    "card skipped: the issuer doesn't state its network (catalogue)",
                )
                continue
            values, evidence = self.merge(card, "card_terms", facts)
            if not values:
                continue
            self.out.records.append(
                CardTermsRecord(
                    card_name=card.name,
                    network=card.network,
                    card_type=CardType.CREDIT,
                    tier=card.tier,
                    source_page=min(e["page"] for e in evidence.values()),
                    evidence=evidence,
                    **values,
                )
            )

    def products(self, answers: Sequence[PageAnswer]) -> None:
        found = self.card_facts(answers, PRODUCT_CARD_FIELDS)
        interest_fields = {f.name for f in INTEREST}
        for code, all_facts in found.items():
            card = self.catalogue.get(code)
            if not card.publish:
                continue
            self.interest(card, {k: v for k, v in all_facts.items() if k in interest_fields})
            facts = {k: v for k, v in all_facts.items() if k not in interest_fields}
            if not facts:
                continue
            values, evidence = self.merge(card, "card_perk", facts)
            if values:
                self.out.records.append(
                    CardPerkRecord(
                        card_name=card.name,
                        network=card.network,
                        source_page=min(e["page"] for e in evidence.values()),
                        evidence=evidence,
                        **values,
                    )
                )
        self.rewards(answers)

    def interest(self, card: Card, facts: dict[str, list[_Accepted]]) -> None:
        if not facts:
            return
        values, evidence = self.merge(card, "card_interest", facts)
        if "interest_rate_pct" not in values:
            if values:
                self.note(
                    "dropped_incomplete_interest",
                    "card_interest",
                    card.name,
                    "interest-free days without a yearly interest rate: not stored",
                )
            return
        self.out.records.append(
            CardInterestRecord(
                card_name=card.name,
                network=card.network,
                source_page=min(e["page"] for e in evidence.values()),
                evidence=evidence,
                **values,
            )
        )

    def rewards(self, answers: Sequence[PageAnswer]) -> None:
        specs = {f.name: f for f in REWARDS}
        by_key: dict[tuple[str, str, str], list[CardRewardRecord]] = {}
        for answer in answers:
            for entry in answer.data.get("rewards", []):
                card = self.card(entry.get("card", ""))
                if card is None or not card.publish:
                    continue
                label = f"{entry.get('category')}/{entry.get('reward_type')}"
                page, quote = entry.get("page"), str(entry.get("quote", ""))
                if page not in self.text or not quote_on_page(quote, self.text[page]):
                    self.note(
                        "dropped_quote_not_found",
                        "card_reward",
                        card.name,
                        f"reward {label}: quote not found on the page: {quote[:200]!r}",
                    )
                    continue
                found: dict[str, list[_Accepted]] = {}
                for fact in entry.get("facts", []):
                    spec = specs.get(fact.get("field", ""))
                    if spec is not None and (a := self.verify(spec, fact, card, "card_reward")):
                        found.setdefault(spec.name, []).append(a)
                values, evidence = self.merge(card, "card_reward", found)
                evidence["reward"] = {"page": page, "quote": quote, "value": label}
                try:
                    record = CardRewardRecord(
                        card_name=card.name,
                        network=card.network,
                        category=entry["category"],
                        reward_type=entry["reward_type"],
                        source_page=page,
                        evidence=evidence,
                        **values,
                    )
                except (ValidationError, KeyError) as exc:
                    reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else exc
                    self.note(
                        "dropped_incomplete_reward",
                        "card_reward",
                        card.name,
                        f"reward {label} ({quote[:120]!r}) can't be stored: {reason}",
                    )
                    continue
                if (
                    record.reward_type is RewardType.CASHBACK
                    and record.monthly_cap_vnd is None
                    and not any(
                        w in fold(f"{quote} {record.conditions_text or ''}") for w in _UNCAPPED
                    )
                ):
                    self.note(
                        "dropped_no_cap",
                        "card_reward",
                        card.name,
                        f"reward {label} ({quote[:120]!r}): no cap stated and not stated to "
                        "be unlimited; a headline is not a reward term",
                    )
                    continue
                key = (card.code, record.category.value, record.reward_type.value)
                by_key.setdefault(key, []).append(record)
        for (code, category, kind), records in by_key.items():
            first = records[0]
            rest = [
                r
                for r in records[1:]
                if r.model_dump(exclude={"evidence", "source_page"})
                != first.model_dump(exclude={"evidence", "source_page"})
            ]
            if rest:
                self.note(
                    "dropped_conflict",
                    "card_reward",
                    self.catalogue.get(code).name,
                    f"reward {category}/{kind} is described differently in two places",
                )
                continue
            self.out.records.append(first)


def build(
    catalogue: Catalogue,
    pages: Sequence[Page],
    answers: Sequence[PageAnswer],
    mode: Mode,
    only: frozenset[str] | None = None,
) -> Built:
    builder = _Builder(catalogue, pages, mode, only)
    if mode == "terms":
        builder.terms(answers)
    else:
        builder.products(answers)
    return builder.out


def still_on_page(quotes: list[dict[str, Any]], texts: dict[int, str]) -> bool:
    """Every quote is still, word for word, on its page."""
    return bool(quotes) and all(
        q.get("page") in texts and quote_on_page(str(q.get("quote", "")), texts[q["page"]])
        for q in quotes
    )


TEXT_FIELDS = frozenset(f.name for f in (*TERMS, *PERKS, *REWARDS) if f.kind == "text")


def keep_approved_text(record: Record, current: Any, texts: dict[int, str]) -> Record:
    """Keep the approved wording of text fields that the page still says.

    Text fields (perks, conditions) take the model's chosen quotes, and a fresh
    read may pick other sentences from an unchanged page. When every quote behind
    the approved text is still on the page, that text is still true: keep it (and
    its evidence) so the diff sees no change. A removed sentence fails the check,
    so real changes still go to review.
    """
    if current is None or not current.source_evidence:
        return record
    evidence = dict(record.evidence or {})
    updates: dict[str, Any] = {}
    for name in TEXT_FIELDS & set(type(record).model_fields):
        old, new = getattr(current, name, None), getattr(record, name)
        approved = current.source_evidence.get(name)
        if old is None or old == new or not approved:
            continue
        if still_on_page([approved, *approved.get("also", [])], texts):
            updates[name] = old
            evidence[name] = approved
    if not updates:
        return record
    return record.model_copy(update={**updates, "evidence": evidence})
