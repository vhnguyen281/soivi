"""An issuer's credit cards: the identity data a human curates once.

The LLM extracts values; it does not decide which cards exist. Each card has a
stable code (the only card identifiers the model may answer with), the name we
store in card_product, its network, and how each document spells it. That keeps
the tariff PDF and the product page pointing at the same card_product row, and a
card the catalogue doesn't know makes the adapter raise instead of guessing.
"""

from dataclasses import dataclass, field

from core.enums import CardNetwork


@dataclass(frozen=True)
class Card:
    code: str
    name: str  # card_product.name
    network: CardNetwork | None  # None: not stated by the issuer -> never published
    tier: str | None = None
    spellings: tuple[str, ...] = ()  # how the documents write it
    in_tariff: bool = False  # expected to appear in the tariff PDF
    in_products: bool = False  # expected on the product page
    note: str = ""

    @property
    def publish(self) -> bool:
        return self.network is not None


@dataclass(frozen=True)
class Catalogue:
    issuer: str
    cards: tuple[Card, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        codes = [c.code for c in self.cards]
        if len(codes) != len(set(codes)):
            raise ValueError(f"{self.issuer}: card codes must be unique")

    @property
    def codes(self) -> list[str]:
        return [c.code for c in self.cards]

    def get(self, code: str) -> Card:
        for card in self.cards:
            if card.code == code:
                return card
        raise KeyError(code)

    def prompt_lines(self) -> str:
        lines = []
        for c in self.cards:
            names = "; ".join(dict.fromkeys((c.name, *c.spellings)))
            network = c.network.value if c.network else "network not stated"
            lines.append(f"{c.code}: {names} [{network}]")
        return "\n".join(lines)
