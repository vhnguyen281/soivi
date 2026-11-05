# News feeds

News never publishes a value. When an item says a bank changed its deposit rates or card fees, we re-run that bank's own sources right away. Any change goes to human review as usual, with the article linked on the review task.

## Run it

```
make pipeline ARGS="news"                          # every feed in pipeline/news/feeds.yaml
make pipeline ARGS="news --feed vietstock-ngan-hang"
make pipeline ARGS="news --no-recheck"             # store and classify only
```

The scheduler (`make scheduler`) does this every hour from 06:00 to 22:00 Vietnam time.

## Feeds (checked 2026-10-28)

| Feed | URL |
|---|---|
| CafeF, Tài chính – Ngân hàng | https://cafef.vn/tai-chinh-ngan-hang.rss |
| VnExpress, Kinh doanh | https://vnexpress.net/rss/kinh-doanh.rss |
| Vietstock, Ngân hàng | https://vietstock.vn/757/tai-chinh/ngan-hang.rss |
| Thời báo Ngân hàng | https://thoibaonganhang.vn/rss_feed/ (dates are local time labelled GMT) |

Thị trường Tài chính Tiền tệ is not used. Its firewall answers 403 to every page. To add a feed:

1. Check it with `make pipeline ARGS="save URL tests/fixtures/news/<name>.rss"`.
2. Add it to `feeds.yaml`.
3. Add a parse test in `tests/news/test_feeds.py`.

For a site without RSS, use `kind: html` with a `link_pattern` regex for article URLs.

## How an item is handled

1. **Store.** New URLs only. The same title within 7 days counts as the same story.
2. **Match institutions** in the title and summary, using `legal_name_vi`, `short_name` and `data/seeds/institution_aliases.csv`. Add aliases there: one row per alias, and tickers in capitals.
3. **Classify:**
   - **irrelevant:** no topic word.
   - **keywords:** a clear "<bank> tăng/giảm … lãi suất huy động / phí thẻ" headline, or on topic but naming no known bank.
   - **LLM:** everything else that names a bank. It needs `ANTHROPIC_API_KEY` in `.env`; without it these items stay unclassified (`classification IS NULL`) and are retried each run while they are under 48 h old.
4. **Re-check** when the decision says rates or card fees changed and names a bank:
   - the bank's runnable sources of the right kind run now (`trigger = news`);
   - the article is added to the resulting review task, or to the source's newest open one;
   - the outcome is in `news_item.recheck_json`.

## Where to look

- `news_item`: each article, its classification, the decision JSON and the re-check outcome.
- `news_fetch`: each read of each feed (ok, items seen and new, error).
- The review task page has a "Tin tức liên quan" box when news is attached.
- The daily Telegram summary includes a news line and lists failing feeds.
