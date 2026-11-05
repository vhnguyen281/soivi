"""Card pipeline: read a card tariff PDF or product page, extract card terms,
rewards and perks with the Anthropic API, and check every value against the
document before it goes to human review.

    document.py   PDF / HTML -> text per page (pdfplumber, then Camelot, then Tesseract)
    catalogue.py  the issuer's cards: names, network, how each document spells them
    fields.py     the fields we extract and how each is parsed
    llm.py        one API call per page, strict JSON schema, value + page + exact quote
    verify.py     quote must be in the page text and must contain the value
    build.py      verified facts -> records (+ evidence, + notes for the reviewer)
    adapter.py    BaseAdapter subclass that ties it together

Nothing extracted here goes live without a human approving it (CLAUDE.md).
"""
