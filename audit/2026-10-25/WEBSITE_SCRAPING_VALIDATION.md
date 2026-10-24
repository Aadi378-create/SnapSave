# Website scraping validation — 25 October 2026

## Result

**Browser-assisted BigBasket extraction works on actual retailer HTML. Unattended retailer fetching remains blocked.** This report supersedes the earlier report's no-results conclusion for browser-assisted extraction only; the earlier HTTP failures remain accurate.

In normal Edge, the public [milk category](https://www.bigbasket.com/pc/bakery-cakes-dairy/dairy/milk/) and [Amul product page](https://www.bigbasket.com/pd/306926/amul-homogenised-toned-milk-1-l-carton/) loaded without login or CAPTCHA. Only public product markup and public robots text were captured. Beautiful Soup extracted 33 category products and one independently parsed product-page result. Example observations:

| Product | Selected pack | Selling price |
| --- | --- | --- |
| Amul Gold Full Cream Milk | 500 ml pouch | ₹32 |
| Amul Taaza Milk | 500 ml | ₹27 |
| Amul Taaza Homogenised Toned Milk | 1 L Tetra Pak | ₹73 |

The ₹73 result matched both catalogue and product page. The parser excluded ₹77 MRP, ₹7.30/100 ml unit comparison, ratings and other pack variants. `browser-capture-evidence.json` records the exact query, SKU 306926, source, capture timestamp, extraction method and review-only result. `browser-catalogue-products.json` records all extracted rows. Capture time was 2026-10-24 22:10:50 UTC (25 October in India). These are point-in-time observations, not current price guarantees. Raw retailer markup remains outside Git.

## Changes

- Added observed BigBasket rendered product/card parsers, supporting dropdown and single-variant pack labels. Missing/ambiguous selling-price selectors produce no price.
- Fixed robots handling: longest matching rules, Allow ties, wildcards, end anchors, merged agent groups and unreserved percent escapes. BigBasket `/ps/`, `/_next/data/` and `/avengers-svc/` remain excluded. Default BigBasket source now uses its permitted milk category.
- Added `BrowserCaptureClient` and CLI `--browser-capture`. Captures must be recent (15 minutes), size-bounded, from an allowed HTTPS retailer origin, and include permitting robots evidence. Supplied snapshots are explicitly labelled `browser_capture`, with original observation timestamps. Duplicate results from a category and product page are combined.
- Added a reusable public-DOM export script and an optional server-owned `RESEARCH_BROWSER_CAPTURE_FILE` input to the existing AI provider. No credentials/profile export, order submission or checkout automation.
- Existing human review remains mandatory: no payable quote, location-specific stock, delivery fees or promotions are inferred. Existing production research settings and the global AI switch were not changed.

## Access limitations

| Route | Observed outcome |
| --- | --- |
| Plain HTTP defaults | Earlier actual 403/202/robots failures; no usable prices |
| Isolated Playwright Chromium, default headless | BigBasket robots and product each returned HTTP 403 Access Denied |
| Normal Edge | BigBasket public category, product and robots pages loaded |
| Browser DOM → Beautiful Soup → query matching | Actual retailer captures produced the correct ₹73 / 1 L result |
| Reusable exporter | Download/import round trip verified with an isolated browser fixture; not claimed as independently live-tested |

Beautiful Soup parses returned HTML; it cannot supply credentials, render JavaScript or remove retailer access restrictions ([official documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)). No documented consumer price API usable by this project was established. Private endpoint permutations, logged-in session replay and challenge evasion were not used. A fully unattended multi-retailer comparison still needs an accessible supported feed/API or a separately validated permitted browser integration. The legacy `/deal` and `/optimize-cart` routes are not enabled by this change.

The captured category covers milk, not all groceries. The retailer location was not set to postcode 110001; that postcode only labels the requested context. Public stock/price is therefore unverified for delivery. CSS changes may require parser maintenance; failure to identify a unique scoped price stops extraction instead of falling back to the first rupee amount.

## Validation

- Real public DOM captures parsed through the command-line provider; 33 catalogue rows and one product-page row.
- Focused scraper suite: 40 tests passed, including price/pack isolation, exporter download/import, capture expiry, denied URLs, robots matching, duplicate sources and AI review-only behavior.
- Full regression suite: **143 passed**; results in `browser-research-tests.xml`. One existing Starlette/httpx deprecation warning remains.
- Python/frontend source checks: `browser-research-source/source-verification.json`; exporter separately checked with `node --check`.
- Raw capture files, browser screenshot and policies were retained locally outside the repository. No real application database was used for tests.
