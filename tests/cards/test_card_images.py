"""Card pictures: candidate scoring (offline) and the reviewer's decision (database)."""

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.card_images import CardImageError, approved_images, decide
from core.enums import CardNetwork, CardType, InstitutionType
from core.models import CardImage, CardProduct, Institution
from pipeline.cards.images import candidates, image_urls, name_tokens

BIDV = """
<img src="/wps/wcm/connect/aa/banner_canhan_chitietthe.png?MOD=AJPERES&amp;CACHEID=1">
<img src="/wps/wcm/connect/bb/img_visaEasy_0deg.png?MOD=AJPERES&amp;CACHEID=2">
<img src="/wps/wcm/connect/cc/icon_canhan_chitietthe_3.svg">
<img src="/wps/wcm/connect/dd/img_visaFlexi_0deg.png?MOD=AJPERES">
<img src="/wps/wcm/connect/ee/Mo-the-nhan-qua-lien-tay-792x484.jpg">
"""
TCB = """
<meta property="og:image" content="/content/dam/seo/techcombank-default-thumbnail.jpg">
<img src="/content/dam/imported-assets/card-Search-Popup-28e9.png.rendition/cq5dam.web.webp">
<img src="/content/dam/public-site/com_img/Spark-Credit-Card-img-masthead.png">
<script>{"img":"\\/content\\/dam\\/x\\/bg-hero.jpg"}</script>
"""


def test_name_tokens_drop_bank_and_generic_words() -> None:
    assert name_tokens("BIDV Visa Easy") == ["visa", "easy"]
    assert name_tokens("Techcombank Spark") == ["spark"]
    assert name_tokens("BIDV Visa Infinite (gói đặc quyền 5 triệu)") == ["visa", "infinite"]


def test_the_cards_own_picture_ranks_first() -> None:
    page = "https://bidv.com.vn/bidv/the/the-bidv-visa-easy"
    best = candidates(BIDV, page, "BIDV Visa Easy")
    assert best[0][0].startswith("https://bidv.com.vn/wps/wcm/connect/bb/img_visaEasy_0deg.png")
    assert all("banner" not in u and not u.endswith(".svg") for u, _ in best)
    tcb = candidates(TCB, "https://techcombank.com/the/techcombank-spark", "Techcombank Spark")
    assert tcb[0][0].endswith("Spark-Credit-Card-img-masthead.png")
    assert all("Popup" not in u and "thumbnail" not in u for u, _ in tcb)


def test_image_urls_reads_escaped_json_and_skips_svg() -> None:
    urls = image_urls(TCB, "https://techcombank.com/x")
    assert "https://techcombank.com/content/dam/x/bg-hero.jpg" in urls
    assert not any(u.endswith(".svg") for u in image_urls(BIDV, "https://bidv.com.vn/x"))


@pytest.mark.db
def test_only_approved_pictures_show_and_decisions_are_append_only(db: Session) -> None:
    bank = Institution(
        legal_name_vi="Ngân hàng Thử", short_name="TESTBANK", type=InstitutionType.JOINT_STOCK_BANK
    )
    db.add(bank)
    db.flush()
    card = CardProduct(
        institution_id=bank.id,
        name="Test Card",
        network=CardNetwork.VISA,
        card_type=CardType.CREDIT,
    )
    db.add(card)
    db.flush()

    def image(n: int) -> CardImage:
        row = CardImage(
            card_product_id=card.id,
            page_url="https://bank.example/card",
            image_url=f"https://bank.example/{n}.png",
            sha256=f"{n:064x}",
            storage_key=f"card-images/{n}.png",
            content_type="image/png",
            size_bytes=10,
            score=5,
            fetched_at=dt.datetime.now(dt.UTC),
        )
        db.add(row)
        db.flush()
        return row

    a, b = image(1), image(2)
    assert card.id not in approved_images(db)
    with pytest.raises(CardImageError):
        decide(db, a.id, "approved", " ")
    decide(db, a.id, "approved", "Nguyễn Văn A")
    assert approved_images(db)[card.id].id == a.id
    decide(db, b.id, "approved", "Nguyễn Văn A")
    assert approved_images(db)[card.id].id == b.id
    decide(db, b.id, "rejected", "Nguyễn Văn A")
    assert approved_images(db)[card.id].id == a.id
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE card_image_decision SET reviewer = 'x'"))
