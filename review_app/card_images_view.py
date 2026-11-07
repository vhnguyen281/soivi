"""Review page for card pictures: every card with its candidates, best first."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.card_images import approved_images, latest_decisions
from core.models import CardImage, CardProduct, Institution


def cards(session: Session) -> list[dict[str, Any]]:
    decided = latest_decisions(session)
    shown = approved_images(session)
    images: dict[int, list[CardImage]] = {}
    for img in session.scalars(select(CardImage).order_by(CardImage.score.desc(), CardImage.id)):
        images.setdefault(img.card_product_id, []).append(img)
    rows = session.execute(
        select(CardProduct, Institution.short_name)
        .join(Institution, Institution.id == CardProduct.institution_id)
        .where(CardProduct.active.is_(True))
        .order_by(Institution.short_name, CardProduct.name)
    ).all()
    out: list[dict[str, Any]] = []
    keys: list[tuple[bool, bool, str, str]] = []
    for card, bank in rows:
        cands = [
            {"image": i, "decision": decided[i.id].decision if i.id in decided else None}
            for i in images.get(card.id, [])
        ]
        out.append(
            {
                "card": card,
                "bank": bank,
                "candidates": cands,
                "shown": shown.get(card.id),
            }
        )
        keys.append((card.id in shown, not cands, bank, card.name))
    # Cards still waiting for a choice first.
    return [row for _, row in sorted(zip(keys, out, strict=True), key=lambda kv: kv[0])]
