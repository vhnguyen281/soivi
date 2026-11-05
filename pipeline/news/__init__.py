"""News: read finance news feeds and re-check a bank's sources when an item says the
bank changed its deposit rates or card fees.

News never writes product values (CLAUDE.md principle 1). The only effects are:
news_item rows, an immediate (polite) run of the bank's own sources, and the news
URL attached to any resulting review task as context for the reviewer.
"""
