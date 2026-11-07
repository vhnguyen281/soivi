"""Which card picture is shown: the latest approved candidate whose latest decision is approval."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import CardImage, CardImageDecision

DECISIONS = ("approved", "rejected")


class CardImageError(Exception):
    pass


def latest_decisions(session: Session) -> dict[int, CardImageDecision]:
    """card_image id -> its latest decision."""
    last = (
        select(CardImageDecision.card_image_id, func.max(CardImageDecision.id).label("id"))
        .group_by(CardImageDecision.card_image_id)
        .subquery()
    )
    rows = session.scalars(select(CardImageDecision).join(last, CardImageDecision.id == last.c.id))
    return {d.card_image_id: d for d in rows}


def approved_images(session: Session) -> dict[int, CardImage]:
    """card id -> the picture to show (most recently approved)."""
    decided = latest_decisions(session)
    out: dict[int, tuple[CardImage, int]] = {}
    for image in session.scalars(select(CardImage)):
        d = decided.get(image.id)
        if d is None or d.decision != "approved":
            continue
        if image.card_product_id not in out or d.id > out[image.card_product_id][1]:
            out[image.card_product_id] = (image, d.id)
    return {k: v[0] for k, v in out.items()}


def decide(session: Session, image_id: int, decision: str, reviewer: str) -> CardImageDecision:
    if decision not in DECISIONS:
        raise CardImageError(f"unknown decision {decision!r}")
    if not reviewer.strip():
        raise CardImageError("the reviewer's name is required")
    image = session.get(CardImage, image_id)
    if image is None:
        raise CardImageError(f"no card image {image_id}")
    row = CardImageDecision(card_image_id=image.id, decision=decision, reviewer=reviewer.strip())
    session.add(row)
    session.flush()
    return row
