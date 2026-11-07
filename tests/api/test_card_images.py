"""GET /cards/{id}/image: only a reviewer-approved picture is served; cards carry its reference."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.card_images import decide
from core.enums import CardNetwork, CardType, InstitutionType
from core.models import CardImage, CardProduct, Institution


@pytest.mark.db
def test_api_serves_only_the_approved_picture(client: TestClient, db: Session) -> None:
    class Store:
        def get(self, key: str) -> bytes:
            return b"PNG:" + key.encode()

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
    img = CardImage(
        card_product_id=card.id,
        page_url="https://bank.example/card",
        image_url="https://bank.example/1.png",
        sha256="a" * 64,
        storage_key="card-images/a.png",
        content_type="image/png",
        size_bytes=10,
        score=5,
        fetched_at=dt.datetime.now(dt.UTC),
    )
    db.add(img)
    db.flush()
    client.app.state.image_store = Store()  # type: ignore[attr-defined]
    assert client.get(f"/cards/{card.id}/image").status_code == 404
    decide(db, img.id, "approved", "Nguyễn Văn A")
    db.flush()
    r = client.get(f"/cards/{card.id}/image")
    assert r.status_code == 200 and r.content == b"PNG:card-images/a.png"
    assert r.headers["content-type"] == "image/png" and r.headers["etag"]
    again = client.get(f"/cards/{card.id}/image", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
