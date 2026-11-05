"""The card pipeline end to end: local HTTP server -> PDF snapshot -> mocked API ->
pending versions with evidence -> review task -> review page. No real network."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.enums import (
    ExtractionMethod,
    FetchMethod,
    InstitutionType,
    SourceKind,
    VersionStatus,
)
from core.models import CardProduct, CardTerms, Institution, ReviewTask, Source
from pipeline.adapters.base import AdapterContext
from pipeline.adapters.techcombank_cards import TechcombankCardTariff
from pipeline.cards.llm import CardExtractor, ExtractionError
from pipeline.fetch.fetchers import Fetchers
from pipeline.fetch.polite import PoliteHttp
from pipeline.fetch.storage import MemoryStore
from pipeline.runner import run_source
from review_app.app import create_app
from tests.cards.conftest import TARIFF_PDF, FakeClient, saved_answers
from tests.http_fixture import FixtureServer, Reply

pytestmark = pytest.mark.db
PDF = {"Content-Type": "application/pdf"}


@pytest.fixture
def client_answers(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient(saved_answers("card_tariff_llm_answers.json"))
    extractor = CardExtractor(TechcombankCardTariff.catalogue, "terms", client=client)
    monkeypatch.setattr(TechcombankCardTariff, "extractor", classmethod(lambda cls: extractor))
    return client


@pytest.fixture
def source(db: Session, http_server: FixtureServer) -> Source:
    bank = Institution(
        legal_name_vi="Ngân hàng TMCP Kỹ Thương Việt Nam",
        short_name="TECHCOMBANK",
        type=InstitutionType.JOINT_STOCK_BANK,
    )
    db.add(bank)
    db.flush()
    http_server.route("/bieu-phi-the.pdf", Reply(200, TARIFF_PDF.read_bytes(), PDF))
    src = Source(
        institution_id=bank.id,
        kind=SourceKind.CARD_TARIFF_PDF,
        url=http_server.url("/bieu-phi-the.pdf"),
        fetch_method=FetchMethod.PDF,
        cadence_hours=168,
        adapter_name=TechcombankCardTariff.name,
    )
    db.add(src)
    db.flush()
    return src


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def ctx(db: Session, polite: PoliteHttp, store: MemoryStore) -> AdapterContext:
    return AdapterContext(session=db, fetchers=Fetchers(polite), store=store)


def test_tariff_to_review_task(
    db: Session, ctx: AdapterContext, source: Source, client_answers: FakeClient
) -> None:
    result = run_source(ctx, source)

    assert result.status == "parsed", result.error
    assert result.diff is not None and result.diff.new == 9
    assert db.scalar(select(func.count()).select_from(CardProduct)) == 9

    sig = db.scalars(
        select(CardTerms)
        .join(CardProduct, CardProduct.id == CardTerms.card_product_id)
        .where(CardProduct.name == "Techcombank Visa Signature")
    ).one()
    assert sig.status is VersionStatus.PENDING  # a human approves it first
    assert sig.extraction_method is ExtractionMethod.LLM
    assert sig.annual_fee_primary_vnd == 1_499_000 and sig.fx_fee_pct == Decimal("1.100")
    assert sig.source_evidence is not None
    assert sig.source_evidence["fx_fee_pct"] == {
        "page": 2,
        "quote": "Thẻ tín dụng Visa Signature | 1.1%*số tiền giao dịch",
        "value": "1.1%*số tiền giao dịch",
    }

    task = db.get(ReviewTask, result.diff.review_task_id)
    assert task is not None
    item = next(i for i in task.payload_json["items"] if i["version_id"] == sig.id)
    assert item["label"] == "Techcombank Visa Signature · phí & điều khoản"
    assert item["evidence"]["annual_fee_primary_vnd"]["page"] == 1
    rules = sorted({w["rule"] for w in task.payload_json["warnings"]})
    # the adapter's notes sit next to the rule checks
    assert {"dropped_conflict", "dropped_quote_not_found", "dropped_unreadable"} <= set(rules)
    assert "new_card_product" in rules


def test_unchanged_pdf_is_not_sent_again(
    ctx: AdapterContext, source: Source, client_answers: FakeClient
) -> None:
    run_source(ctx, source)
    calls = len(client_answers.requests)
    again = run_source(ctx, source)

    assert again.status == "unchanged"
    assert len(client_answers.requests) == calls == 8


def test_api_failure_is_retried_on_the_same_pdf(
    monkeypatch: pytest.MonkeyPatch, ctx: AdapterContext, source: Source
) -> None:
    failing = FakeClient({3: ExtractionError("Anthropic API error 529: overloaded")})

    def broken(cls: Any) -> CardExtractor:
        return CardExtractor(cls.catalogue, "terms", client=failing)

    monkeypatch.setattr(TechcombankCardTariff, "extractor", classmethod(broken))
    first = run_source(ctx, source)
    assert first.status == "parse_failed" and "529" in (first.error or "")

    working = FakeClient(saved_answers("card_tariff_llm_answers.json"))
    monkeypatch.setattr(
        TechcombankCardTariff,
        "extractor",
        classmethod(lambda cls: CardExtractor(cls.catalogue, "terms", client=working)),
    )
    second = run_source(ctx, source)  # same bytes, but last time failed: parse again
    assert second.status == "parsed" and second.diff is not None and second.diff.new == 9


@pytest.fixture
def app(db: Session, store: MemoryStore) -> Iterator[TestClient]:
    conn = db.connection()
    assert isinstance(conn, Connection)
    settings = Settings(review_username="reviewer", review_password="pw")
    application = create_app(
        settings,
        session_factory=lambda: Session(bind=conn, join_transaction_mode="create_savepoint"),
        store=store,
    )
    with TestClient(application) as c:
        c.auth = ("reviewer", "pw")
        yield c


def test_review_page_shows_each_value_with_its_quote(
    db: Session,
    ctx: AdapterContext,
    source: Source,
    client_answers: FakeClient,
    app: TestClient,
) -> None:
    result = run_source(ctx, source)
    assert result.diff is not None
    db.flush()
    html = app.get(f"/tasks/{result.diff.review_task_id}").text

    assert "Techcombank Visa Signature · phí &amp; điều khoản" in html
    assert "“Thẻ tín dụng Visa Signature | 1.499.000 VND/thẻ”" in html
    assert "ghi là “1.499.000 VND/thẻ”" in html
    assert '?page=8" target="_blank">trang 8</a>' in html  # waiver spend, page 8
    assert "dropped_quote_not_found" in html and "Miễn lãi tới 55 ngày" in html


# --------------------------------------------------------------------------- card pages


def test_card_page_reread_keeps_what_the_page_still_says(
    db: Session, ctx: AdapterContext, http_server: FixtureServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh read that leaves out an approved reward, or rewords a perk, while the
    page still says them, proposes nothing: no false 'removed' or 'changed'."""
    from pipeline.adapters.vpbank_cards import VpbankCardProducts
    from review_app import service
    from tests.adapters.test_card_pages import VPB_Z, Z_DINING, reward

    bank = Institution(
        legal_name_vi="Ngân hàng TMCP Việt Nam Thịnh Vượng",
        short_name="VPBANK",
        type=InstitutionType.JOINT_STOCK_BANK,
    )
    db.add(bank)
    db.flush()
    http_server.route("/the-z", Reply(200, VPB_Z.read_bytes(), {"Content-Type": "text/html"}))
    src = Source(
        institution_id=bank.id,
        kind=SourceKind.CARD_PRODUCT_PAGE,
        variant="z",
        url=http_server.url("/the-z"),
        fetch_method=FetchMethod.HTTP,
        cadence_hours=168,
        adapter_name=VpbankCardProducts.name,
    )
    db.add(src)
    db.flush()
    gift = "Hoàn tiền 300.000 VND cho Khách hàng mở thẻ"
    fitness = "Hoàn 15% cho giao dịch Giải trí, Fitness (*), tối đa 500,000"
    first = {
        "cards": [
            {
                "card": "VPB_Z",
                "facts": [
                    {"field": "other_perks_text", "value": q, "page": 1, "quote": q}
                    for q in (fitness, gift)
                ],
            }
        ],
        "rewards": [
            reward("VPB_Z", "dining", Z_DINING, ("rate_pct", "15%"), ("monthly_cap_vnd", "500,000"))
        ],
    }
    # the second read finds one perk sentence and misses the reward
    second = {
        "cards": [
            {
                "card": "VPB_Z",
                "facts": [{"field": "other_perks_text", "value": gift, "page": 1, "quote": gift}],
            }
        ],
        "rewards": [],
    }
    answers = iter([first, second])

    def extractor(cls: type, focus: str = "") -> CardExtractor:
        client = FakeClient({1: next(answers)})
        return CardExtractor(VpbankCardProducts.catalogue, "products", client=client)

    monkeypatch.setattr(VpbankCardProducts, "extractor", classmethod(extractor))
    one = run_source(ctx, src)
    assert one.status == "parsed", one.error
    assert one.diff is not None and one.diff.new == 2 and one.diff.review_task_id
    service.approve_all(db, one.diff.review_task_id, "reviewer")

    two = run_source(ctx, src, reparse=True)
    assert two.status == "parsed", two.error
    assert two.diff is not None
    assert (two.diff.new, two.diff.changed, two.diff.removed) == (0, 0, 0)
    assert two.diff.unchanged == 2 and two.diff.review_task_id is None
