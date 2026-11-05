"""Find which institutions a headline mentions, by name and alias.

Names come from the institution table (short_name, legal_name_vi) plus
data/seeds/institution_aliases.csv (brands, tickers, older names). Text and
aliases are compared without accents or punctuation, so "Nam Á Bank",
"Nam A Bank" and "NAM A BANK" all match. Short all-caps aliases (tickers such as
VCB, TCB, MB) must match in capitals, so ordinary words don't trigger them.
Longer aliases win over shorter ones that overlap ("VCB Neo" is VCBNEO, not VCB).
"""

import csv
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Institution
from pipeline.extract.vietnamese import clean

ALIASES_FILE = Path(__file__).resolve().parents[2] / "data" / "seeds" / "institution_aliases.csv"
_EDGE = r"(?<![0-9A-Za-z]){}(?![0-9A-Za-z])"


def normalize(text: str | None) -> str:
    """'Ngân hàng TMCP Ngoại thương (VCB)' -> 'Ngan hang TMCP Ngoai thuong VCB'. Keeps case."""
    text = unicodedata.normalize("NFD", clean(text)).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", text).split())


@dataclass(frozen=True)
class Alias:
    short_name: str
    raw: str  # as written, for the LLM prompt
    text: str  # normalised
    case_sensitive: bool
    pattern: re.Pattern[str]


def _alias(short_name: str, raw: str) -> Alias | None:
    text = normalize(raw)
    if len(text.replace(" ", "")) < 2:
        return None
    ticker = len(text) <= 5 and text.isupper() and " " not in text
    flags = 0 if ticker else re.IGNORECASE
    pattern = re.compile(_EDGE.format(re.escape(text)), flags)
    return Alias(short_name, clean(raw), text, ticker, pattern)


def read_alias_file(path: Path = ALIASES_FILE) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [(row["short_name"].strip(), row["alias"].strip()) for row in csv.DictReader(handle)]


class InstitutionMatcher:
    def __init__(self, names: Iterable[tuple[str, str]]) -> None:
        """`names`: (short_name, name or alias) pairs."""
        seen: set[tuple[str, str, bool]] = set()
        aliases: list[Alias] = []
        for short_name, raw in names:
            alias = _alias(short_name, raw)
            if alias is None:
                continue
            key = (alias.short_name, alias.text.lower(), alias.case_sensitive)
            if key not in seen:
                seen.add(key)
                aliases.append(alias)
        # Longest first, so the most specific name claims its words.
        self.aliases = sorted(aliases, key=lambda a: -len(a.text))
        self.short_names = sorted({a.short_name for a in aliases})

    @classmethod
    def from_institutions(
        cls, institutions: Iterable[tuple[str, str]], alias_rows: Iterable[tuple[str, str]]
    ) -> "InstitutionMatcher":
        """`institutions`: (short_name, legal_name_vi). Aliases for unknown short
        names are ignored (tests check the seed file has none)."""
        institutions = list(institutions)
        known = {short_name for short_name, _ in institutions}
        names: list[tuple[str, str]] = []
        for short_name, legal in institutions:
            names.append((short_name, legal))
            # "Ngân hàng TMCP Ngoại thương Việt Nam" is often written without "Việt Nam".
            shorter = re.sub(r"\s*\(?\s*Việt Nam\s*\)?\s*$", "", clean(legal))
            if shorter != clean(legal):
                names.append((short_name, shorter))
        names += [(s, a) for s, a in alias_rows if s in known]
        # Last, so a brand spelling ("Vietcombank") is kept over the code (VIETCOMBANK).
        names += [(s, s) for s, _ in institutions]
        return cls(names)

    @classmethod
    def from_db(cls, session: Session, alias_file: Path = ALIASES_FILE) -> "InstitutionMatcher":
        rows = session.execute(select(Institution.short_name, Institution.legal_name_vi)).all()
        return cls.from_institutions([(r[0], r[1]) for r in rows], read_alias_file(alias_file))

    def names_for(self, short_name: str) -> list[str]:
        """Names of one institution as written, for the LLM prompt (longest first)."""
        return [a.raw for a in self.aliases if a.short_name == short_name]

    def find(self, *texts: str | None) -> list[str]:
        """Short names mentioned in the texts, in order of first mention."""
        found: dict[str, int] = {}
        offset = 0
        for text in texts:
            norm = normalize(text)
            taken = [False] * len(norm)
            for alias in self.aliases:
                for m in alias.pattern.finditer(norm):
                    if any(taken[m.start() : m.end()]):
                        continue
                    taken[m.start() : m.end()] = [True] * (m.end() - m.start())
                    found.setdefault(alias.short_name, offset + m.start())
                    found[alias.short_name] = min(found[alias.short_name], offset + m.start())
            offset += len(norm) + 1
        return sorted(found, key=lambda s: found[s])
