# Seed data

Reference data loaded by `make seed` (`core/seed.py`). Loading is idempotent: rows are matched on a natural key, inserted or updated, and never deleted.

| File | One row per | Matched on |
|---|---|---|
| `institutions.csv` | bank or finance company | `short_name` |
| `sources.csv` | page we fetch for one institution | `institution` + `kind` |

`institution_aliases.csv` (`short_name,alias`) is not loaded into the database. The news pipeline reads it to recognise institutions in headlines: brands, tickers and former names (see [docs/news.md](../../docs/news.md)). Write tickers in capitals; they then only match in capitals. A test checks that every `short_name` exists in `institutions.csv`.

`note` columns are for humans and are not loaded.

**`needs_check=true`** means a person must confirm the row before it is trusted. Reasons are in `note`. A source with an empty `url` always has `needs_check=true`; it is a to-do item, and the scheduler must skip it.

Re-check every URL politely (robots.txt, at most 1 request per 5 s per host):

```bash
make check-seeds
```

---

## institutions.csv

### Scope

Included:

- **State-owned commercial banks and banks where the State holds a majority:** Agribank, Vietcombank, VietinBank, BIDV. SBV lists Vietcombank, VietinBank and BIDV with the joint-stock banks; we tag them `state_bank` because they are commonly treated as the state-owned group.
- **Joint-stock commercial banks:** every bank in SBV's list dated 30/06/2026. This includes the four one-member LLC banks created by the 2024–2025 compulsory transfers (GPBank, MBV, VCBNeo, Vikki Bank), which SBV lists in the same table. Our `type` enum has no "one-member LLC" value, so they are tagged `joint_stock_bank` and flagged `needs_check` with a note.
- **100% foreign-owned banks** that serve retail customers.
- **Consumer-finance companies that issue credit cards.** Their `deposit_insurance` is false because finance companies may not take deposits from individuals.

Excluded on purpose:

- **ANZ Bank (Vietnam):** still on SBV's foreign-owned list (30/09/2024), but it sold its retail business to Shinhan Bank Vietnam in 2017 and takes no retail deposits.
- **Joint-venture banks** (Indovina Bank, Vietnam–Russia Bank) and **foreign bank branches:** outside the categories requested. Add them later if wanted.
- **Policy banks** (Vietnam Bank for Social Policies, Vietnam Development Bank) and **the Co-operative Bank:** not open retail deposit-takers.
- **Finance companies with no credit card found:** Mcredit (MB Shinsei), Mirae Asset (MAFC), JACCS, TNEX, PTF, EVN Finance, Handico, Vietcredit, SHB Finance, Toyota Financial Services, Vietnam Shipbuilding Finance.

### Sources

Lists of institutions, from the State Bank of Vietnam (SBV):

- [Joint-stock commercial banks (by 30/06/2026)](https://sbv.gov.vn/en/joint-stock-commercial-banks)
- [State-owned commercial banks (by 30/06/2026)](https://sbv.gov.vn/en/state-owned-commercial-banks)
- [100% foreign-owned banks (by 30/09/2024)](https://sbv.gov.vn/en/w/danh-s%C3%A1ch-ng%C3%A2n-h%C3%A0ng-100-v%E1%BB%91n-n%C6%B0%E1%BB%9Bc-ngo%C3%A0i)
- [Finance companies (by 30/06/2025)](https://www.sbv.gov.vn/en/web/sbv_portal/w/danh-s%C3%A1ch-c%C3%A1c-c%C3%B4ng-ty-t%C3%A0i-ch%C3%ADnh-%C4%91%E1%BA%BFn-30/6/2025-): websites for finance companies come from this table.

Names that changed recently, confirmed in the press (SBV decision numbers quoted there):

- Sacombank → Ngân hàng TMCP Sài Gòn Tài Lộc (36/QĐ-QLGS4, 01/06/2026): [VnExpress](https://vnexpress.net/sacombank-doi-ten-thanh-ngan-hang-sai-gon-tai-loc-5080730.html), [Thời báo Tài chính](https://thoibaotaichinhvietnam.vn/sacombank-chinh-thuc-doi-ten-thanh-ngan-hang-tmcp-sai-gon-tai-loc-198379.html)
- LPBank → Ngân hàng TMCP Lộc Phát Việt Nam (423/QĐ-TTGSNH2, 15/07/2024): [Vietstock](https://finance.vietstock.vn/LPB-ngan-hang-tmcp-loc-phat-viet-nam.htm)
- DongA Bank → Ngân hàng TNHH MTV Số Vikki (42/QĐ-TTGSNH2, 14/02/2025): [Thị trường Tài chính Tiền tệ](https://thitruongtaichinhtiente.vn/donga-bank-doi-ten-thanh-ngan-hang-so-vikki-65735.html)
- CBBank → Ngân hàng Thương mại TNHH MTV Ngoại thương Công nghệ số, VCBNeo (30/QĐ-TTGSNH1): [VietnamFinance](https://vietnamfinance.vn/cb-doi-ten-thanh-ngan-hang-ngoai-thuong-cong-nghe-so--vcbneo-d121700.html)
- OceanBank → MBV, and GPBank's new name: [The Investor](https://theinvestor.vn/two-remaining-weak-vietnamese-banks-transferred-to-vpbank-hdbank-d14212.html), [Wikipedia: List of banks in Vietnam](https://en.wikipedia.org/wiki/List_of_banks_in_Vietnam). Sources disagree on the exact Vietnamese wording, so both are flagged.

Which finance companies issue credit cards: [VietnamFinance (market overview)](https://vietnamfinance.vn/tai-chinh-tieu-dung-phac-hoa-can-can-quyen-luc-d16169.html), [Thị trường Tài chính Tiền tệ on FE Credit's JCB cards](https://thitruongtaichinhtiente.vn/fe-credit-la-cong-ty-tai-chinh-duy-nhat-duoc-jcb-vinh-danh-tai-viet-nam-68154.html), [Vietnambiz on Shinhan Finance](https://vietnambiz.vn/profile-cong-ty-tai-chinh-tung-lai-hang-tram-ty-moi-nam-shinhan-finance-quay-dau-lo-tu-2023-toi-nay-2024916145310981.htm). Lotte Finance and Shinhan Finance stay flagged until an official page confirms they issue cards.

Bank websites and Vietnamese legal names that SBV's English tables don't give were checked against each bank's own homepage (see below).

---

## sources.csv

98 rows:
- one savings-rate page and one card-fee page per bank
- a card product page and a card-fee page per finance company
- VIB's card list, because VIB publishes fees per card
- BIDV's online savings rates, a second savings source with `variant=online`

31 rows are flagged `needs_check`, and 15 of those have no URL yet.

**Savings sources that have an adapter (10 banks, 11 sources)** may point at the data behind the human page rather than the page itself: a JSON endpoint (Vietcombank, BIDV), an HTML fragment (Agribank), a document listing (Techcombank, VPBank) or a PDF with a stable name (Sacombank). Each `note` points to `docs/adapters/<bank>.md`, which explains the choice.

### How URLs were found and checked (26/10/2026)

1. **From the bank's own homepage.** A script followed the homepage's links whose text or address mentions *lãi suất* or *biểu phí*, staying on the bank's domain.
2. **Web search limited to the bank's domain,** for sites whose homepage is built with JavaScript (no links in the HTML) or that block crawlers.
3. **Every URL fetched once with `pipeline/fetch/url_check.py`.** The checker reads robots.txt first, waits at least 5 s between requests to a host, and sends `SoiviBot/0.1` with a contact email. A URL passed when:
   - robots.txt allowed it,
   - it returned HTTP 200,
   - the page text contained the expected words (*lãi suất* for rates, *biểu phí*/*phí thường niên* for fees).

   Redirects were checked by hand. Two guesses that redirected to an error page or a homepage were thrown out, even though the keyword test passed.

### When a row is flagged `needs_check=true`

| Situation | Banks |
|---|---|
| No URL found | BacABank, MB, PGBank, SeABank, VIB, Vietbank, VPBank, GPBank, VCBNeo, HSBC, Shinhan Bank, Public Bank, CIMB, Woori, FE Credit, Home Credit, Shinhan Finance (one kind each, see `note`) |
| Site returns 403 to the crawler, so the URL came from search and was not fetched | MB, NCB, PGBank, SHB |
| TLS certificate chain the client could not verify | Shinhan Bank, Woori |
| URL is a dated PDF, which goes stale when the bank publishes a new version: an adapter should start from the index page instead | BIDV, BVBank, Eximbank, HDBank, MBV, PGBank, SHB, Woori |
| URL found but did not pass the check | GPBank (404), Standard Chartered card PDF (text did not match; may be scanned) |

### Notes for adapter authors

- **`card_tariff_pdf` URLs are often HTML index pages** that link the current PDF(s), because index pages change address less often than the files. `fetch_method` says what the URL itself returns: `http` for a page, `pdf` for a file.
- **One page can carry rates for several channels or tiers,** e.g. the VietinBank page notes rates vary by branch.
- **Index pages are not the data.** Most `false` rows are verified to be the right *page*, not that the page holds a machine-readable table. Each adapter still needs its own fixture-based tests.

### Search sources

Pages found by web search came from the banks' own domains only, e.g. [VietinBank](https://www.vietinbank.vn/ca-nhan/cong-cu-tien-ich/lai-suat-khcn), [BIDV](https://bidv.com.vn/vn/tra-cuu-lai-suat), [Techcombank](https://techcombank.com/content/dam/techcombank/public-site/documents/techcombank-bieu-phi-dich-vu-the-tin-dung-cho-khach-hang-thuong.pdf), [VPBank](https://www.vpbank.com.vn/-/media/vpbank-latest/1retail/picture/0-dich-vu-the/cards/bieu-phi-the-tin-dung.pdf), [MB](https://pilotwebcdn.mbbank.com.vn/public/media/3d31081e-352b-481e-b5af-cb8f18d64dc6.pdf) (its PDF names `mbbank.com.vn/fee` as the fee page), [MSB](https://www.msb.com.vn/khach-hang-ca-nhan/lai-suat-tien-gui/), [UOB](https://www.uob.com.vn/web-resources/personal/pdf/personal/vi/save/index/personal-banking-deposit-interest-rates.pdf), [Lotte Finance](https://lottefinance.vn/web/card/cardList). The exact URL for every row is in `sources.csv`.
