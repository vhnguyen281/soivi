"""Public, versioned ranking formulas (CLAUDE.md principle 5: no paid placement).

    savings.py  rank approved deposit rates by VND earned at maturity
    cards.py    annual net value of a credit card for a spending profile
    data.py     load approved current values from the database into the formulas

Every formula is explained in docs/methodology.md. Change METHODOLOGY_VERSION
whenever a formula, an assumption or a preset changes, and add a line to the
changelog there; the version is returned with every API response, so a ranking
can always be traced to the method that produced it.
"""

METHODOLOGY_VERSION = "1.2.0"
