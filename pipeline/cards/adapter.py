"""Base adapter for card sources read with the LLM.

    @register
    class TechcombankCardTariff(LlmCardAdapter):
        name = "techcombank_card_tariff"
        institution = "TECHCOMBANK"
        source_kind = SourceKind.CARD_TARIFF_PDF
        fetch_method = FetchMethod.PDF
        mode = "terms"
        catalogue = TECHCOMBANK_CARDS

Fetching is BaseAdapter's (hash-unchanged documents are not parsed again, so the
API is only called when the bank's document changes). parse():
document text per page -> one API call per page -> verified facts -> records.

It raises AdapterBroken, never returns partial data, when:
- the document names a credit card the catalogue doesn't know, or
- (tariff) a card the catalogue expects in it has no verified annual fee, or
- nothing at all could be verified.
"""

from typing import Any, ClassVar

from sqlalchemy import select

from core.config import get_settings
from core.enums import ExtractionMethod
from core.models import CardInterest, CardPerk, CardProduct, CardReward, Snapshot
from core.versioning import get_current, key_columns, value_columns
from pipeline.adapters.base import AdapterBroken, BaseAdapter
from pipeline.cards.build import Built, build, keep_approved_text, still_on_page
from pipeline.cards.catalogue import Catalogue
from pipeline.cards.document import DocumentError, read
from pipeline.cards.llm import CardExtractor, Mode, make_extractor
from pipeline.records import (
    CardInterestRecord,
    CardPerkRecord,
    CardRecord,
    CardRewardRecord,
    Record,
)
from pipeline.validate.rules import RuleWarning

_RECORD_TYPES: dict[type, type[CardRecord]] = {
    CardReward: CardRewardRecord,
    CardPerk: CardPerkRecord,
    CardInterest: CardInterestRecord,
}


class LlmCardAdapter(BaseAdapter):
    mode: ClassVar[Mode]
    catalogue: ClassVar[Catalogue]
    extraction_method = ExtractionMethod.LLM
    # Tables with one card per column: label each cell with its card (document.py).
    label_columns: ClassVar[bool] = False
    # Only the pages from the one containing section[0] up to the one containing
    # section[1] (e.g. the credit card part of a tariff that also covers debit cards).
    section: ClassVar[tuple[str, str | None] | None] = None
    # Issuer-specific reading notes for the model (which column applies, etc.).
    reading_notes: ClassVar[str] = ""
    # One source per card page: source.variant -> the catalogue codes that page is
    # about. Facts about any other card named on the page are ignored.
    card_pages: ClassVar[dict[str, tuple[str, ...]]] = {}
    # HTML: drop the page text from this marker on (e.g. a news list).
    html_until: ClassVar[str | None] = None

    @classmethod
    def extractor(cls, focus: str = "") -> CardExtractor:
        """The API client; tests replace this with a mocked one."""
        notes = "\n".join(n for n in (cls.reading_notes, focus) if n)
        return make_extractor(get_settings(), cls.catalogue, cls.mode, notes=notes)

    def allows_empty(self) -> bool:
        # A card's own page may state no reward or perk we store; a tariff can't be empty.
        return bool(self.card_pages)

    @classmethod
    def page_cards(cls, variant: str) -> frozenset[str] | None:
        if not cls.card_pages:
            return None
        if variant not in cls.card_pages:
            raise AdapterBroken(f"no card is mapped to page {variant!r} in {cls.__name__}")
        return frozenset(cls.card_pages[variant])

    @classmethod
    def build_from(cls, content: bytes, content_type: str = "", variant: str = "") -> Built:
        only = cls.page_cards(variant)
        try:
            pages = read(
                content,
                content_type,
                label_columns=cls.label_columns,
                section=cls.section,
                until=cls.html_until,
            )
        except DocumentError as exc:
            raise AdapterBroken(str(exc)) from exc
        focus = ""
        if only is not None:
            names = ", ".join(cls.catalogue.get(c).name for c in sorted(only))
            focus = (
                f"- This is the product page of {names}. Report facts for "
                f"{'that card' if len(only) == 1 else 'those cards'} only."
            )
        answers = (cls.extractor(focus) if focus else cls.extractor()).extract(pages)
        built = build(cls.catalogue, pages, answers, cls.mode, only)
        if only is not None:
            built.unlisted_cards = []  # other cards named on a card's page don't matter
        if built.unlisted_cards:
            raise AdapterBroken(
                "the document names cards the catalogue doesn't know: "
                + ", ".join(built.unlisted_cards)
                + f" (add them to the {cls.catalogue.issuer} card catalogue)"
            )
        if built.missing_cards:
            raise AdapterBroken("no verified annual fee for: " + ", ".join(built.missing_cards))
        if not built.records:
            if only is None:
                raise AdapterBroken("no value could be verified against the document")
            # A card's own page may simply state no reward or perk we store.
            built.notes.append(
                RuleWarning(
                    "nothing_stored",
                    "card_perk",
                    {"card": ", ".join(cls.catalogue.get(c).name for c in sorted(only))},
                    "no reward or perk on this page could be stored",
                )
            )
        return built

    @classmethod
    def parse_content(cls, content: bytes) -> list[Record]:
        return cls.build_from(content).records

    def parse(self, snapshot: Snapshot) -> list[Record]:
        built = self.build_from(
            self.read(snapshot), snapshot.content_type or "", self.source.variant
        )
        self.notes = built.notes
        records = [self._settled(r, built.texts) for r in built.records]
        return records + self._still_stated(records, built.texts)

    def _still_stated(self, records: list[Record], texts: dict[int, str]) -> list[Record]:
        """Approved rows from this source that this read left out, while every quote
        behind them is still on the page: the bank still says it, so keep proposing
        it (it comes out unchanged). A row whose quotes are gone is left out and shows
        as removed, for a reviewer."""
        if not self.card_pages:
            return []
        from pipeline.diff.diff import _approved_from_source

        session = self.ctx.session
        seen = {
            (
                r.table,
                tuple(getattr(r, c) for c in key_columns(r.table) if c != "card_product_id"),
                r.card_name,
            )
            for r in records
            if isinstance(r, CardRecord)
        }
        kept: list[Record] = []
        for model, record_type in _RECORD_TYPES.items():
            for row in _approved_from_source(session, model, self.source):
                product = session.get(CardProduct, row.card_product_id)  # type: ignore[attr-defined]
                if product is None:
                    continue
                rest = tuple(getattr(row, c) for c in key_columns(model) if c != "card_product_id")
                if (model, rest, product.name) in seen or not row.source_evidence:
                    continue
                quotes = [
                    q
                    for e in row.source_evidence.values()
                    if isinstance(e, dict)
                    for q in (e, *e.get("also", []))
                ]
                if not still_on_page(quotes, texts):
                    continue
                values = {
                    c: getattr(row, c)
                    for c in (*key_columns(model), *value_columns(model))
                    if c != "card_product_id"
                }
                kept.append(
                    record_type(
                        card_name=product.name,
                        network=product.network,
                        source_page=min(q["page"] for q in quotes),
                        evidence=row.source_evidence,
                        **values,
                    )
                )
        return kept

    def _settled(self, record: Record, texts: dict[int, str]) -> Record:
        """The record, with approved text kept where the page still says it."""
        if not isinstance(record, CardRecord):
            return record
        session = self.ctx.session
        product = session.scalars(
            select(CardProduct).where(
                CardProduct.institution_id == self.source.institution_id,
                CardProduct.name == record.card_name,
                CardProduct.network == record.network,
            )
        ).first()
        if product is None:
            return record
        key: dict[str, Any] = {
            c: product.id if c == "card_product_id" else getattr(record, c)
            for c in key_columns(record.table)
        }
        return keep_approved_text(record, get_current(session, record.table, **key), texts)
