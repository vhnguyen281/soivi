# Card pipeline

Card terms, rewards and perks are read from the bank's own documents by the Anthropic API. Every value must be backed by an exact quote from the document, and nothing goes live until a reviewer approves it.

```
PDF / page ──► text per page ──► one API call per page ──► check each quote ──► records ──► diff ──► review task
              (pdfplumber,        (strict JSON schema:      (on the page? value   (+ evidence)
               Camelot, OCR)       value, page, quote)        in the quote?)
```

Code is in `pipeline/cards/`. Per-issuer adapters (e.g. `pipeline/adapters/techcombank_cards.py`) only declare the source and the card catalogue.

## Steps

1. **Fetch.** This is the usual adapter fetch: the bytes are stored in MinIO with their SHA-256. If the hash matches the last snapshot, the document isn't parsed again and no API call is made. The exception is when the previous parse failed (for example an API outage); then the same bytes are parsed again.
2. **Text, page by page** (`document.py`). Page numbers are 1-based, as in a PDF viewer. A product page counts as page 1.
   - pdfplumber reads the text layer and tables.
   - If pdfplumber finds text but no table on a page, Camelot is tried (lattice, then stream).
   - If a page has fewer than 40 characters of text, it is treated as a scan and read with Tesseract (`vie`, 300 dpi). Values from OCR pages are flagged on the review page.
3. **Extraction** (`llm.py`). One request per page, with the previous page as context.
   - Model: `ANTHROPIC_MODEL` (default `claude-opus-5-5`). Effort: `CARD_EXTRACTION_EFFORT` (default `high`).
   - The request uses structured output (`output_config.format`, `json_schema`), is streamed, and sets `fallbacks: "default"`.
   - The system prompt (rules, fields, card catalogue) is the same for every page, so it is cached.
   - Each fact is `{field, value, page, quote}`. A field the page doesn't state is simply not returned, which means null. The prompt forbids guessing.
   - Cards are named only by catalogue codes (an enum). Cards the model sees that aren't in the catalogue go in `unlisted_cards`, and the adapter raises.
4. **Checks** (`verify.py`, `build.py`). A fact is dropped, with a note shown as a warning on the review task, when:
   - its quote isn't on the page it names (whitespace aside);
   - its value can't be read: amounts like "1.000.000 VNĐ", "1 triệu" or "1.499.000 VND/thẻ"; percentages like "2.59%*số tiền giao dịch"; "Miễn phí" = 0;
   - the value isn't in its own quote;
   - two different values are found for the same card and field (both dropped).

   Text fields take the quote itself as their value, so nothing is paraphrased.
5. **Diff and review.** These are the usual steps: pending versions, one review task per snapshot, and range rules from `rules.yaml`.
   - Each version keeps its evidence in `source_evidence` (`{field: {page, quote, value}}`). The column is frozen like the rest of the version.
   - The review page shows each value with its quote and a link to that page of the stored PDF.

## What the checks can't catch

A quote check proves the value is in the bank's document. It can't prove the value comes from the right row. For example, Spark's cash-advance row (4%) quoted as its FX fee would pass. The reviewer is still the safeguard: compare each value with its quote and page.

## Adding an issuer

1. Save the tariff and product page as fixtures: `make pipeline ARGS="save URL tests/fixtures/<bank>/..."`.
2. Write the card catalogue. For each card: its code, the name to store, its network as the issuer states it (`None` if unknown, which keeps it unpublished), and the spellings each document uses.
3. Add two adapters (`mode = "terms"` for the tariff, `"products"` for the product page), and set `adapter_name` in `data/seeds/sources.csv`.
4. Write tests with mocked API answers that quote the fixtures. Include a few wrong facts to show they are dropped.

## Requirements

- `ANTHROPIC_API_KEY` in `.env`. Without it, card sources fail with "ANTHROPIC_API_KEY is not set" and are retried on the next run.
- For scanned PDFs, Tesseract with Vietnamese data. The Docker image has it; a local Mac install may only have English.
