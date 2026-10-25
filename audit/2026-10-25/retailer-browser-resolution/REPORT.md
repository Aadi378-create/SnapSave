# Working browser capture for Zepto, Instamart and Blinkit

25 October 2026, Asia/Kolkata. This follow-up establishes a usable browser-assisted route, comparable to the earlier BigBasket result. It does **not** establish unattended server-side retailer access.

## Result from the installed helper

The user approved and installed the prepared Edge extension. Its toolbar action ran the existing exporter on actual retailer pages, fetched permitting public robots text, and downloaded real JSON files into Downloads. The files were read from disk and validated through `BrowserCaptureClient` and `extract_products`, rather than treating a console message as proof of a completed download.

| Retailer | Capture time, IST | Parsed products | Observed examples |
| --- | --- | ---: | --- |
| [Zepto milk category](https://www.zepto.com/category/dairy-bread-eggs/milk) | 14:32:36 | 30 | Amul Taaza Homogenised Toned Milk, 1 L: ₹77 |
| [Instamart storefront](https://www.swiggy.com/instamart/) | 14:38:30 | 30 | Epigamia High Protein Paneer, 200 g: ₹150; Indian Tomato, 500 g: ₹24 |
| [Blinkit milk category](https://blinkit.com/cn/milk/cid/14/922) | 14:38:30 | 20 | Amul Gold Full Cream Milk, 500 ml: ₹35; Amul Taaza Homogenised Toned Milk, 1 ltr: ₹77 |

The Blinkit exporter captured 23 cards; the parser accepted 20 supported products. Unsupported/ambiguous packs are not guessed. Instamart's ₹250 MRP was excluded from the ₹150 paneer selling price. Captures are limited to 30 cards, so these counts do not represent complete retailer inventories.

`installed-helper-live-result.json` records file sizes, original UTC capture times, sample parsed records and the verification flags. The three `*-helper-products.json` files contain the actual parsed rows. Raw downloaded captures remain local in Downloads; no browser profile, cookie, account, street address or credential was exported into Git.

The combined `research_catalog` provider consumed the fresh downloaded captures for milk, paneer and tomato queries under requested postcode 382421. Every query returned matching candidates. `live-provider-result.json` records the result with `verified=false`, `requires_human_review=true`, and location verification still required. This was a standalone research diagnostic; no actual customer ticket or payable quote was modified.

## Location checks

The user explicitly supplied postcode **382421**, then clarified the locality as **Kudasan**. Postcode input alone is not sufficient when a retailer needs a geographic area.

- **Blinkit:** its normal location selector returned Kudasan, Gandhinagar, Gujarat, India. Selecting that locality reloaded the catalogue and changed the header to Kudasan with a displayed 12-minute estimate. Amul Gold 500 ml changed from the earlier browser location's ₹36 to ₹35.
- **Instamart:** its manual area search returned Kudasan. The locality confirmation was accepted and the catalogue reloaded with a Kudasan header and a displayed 12-minute estimate. Indian Tomato 500 g changed from the location-unknown sample's ₹20 to ₹24.
- **Zepto:** its manual location search returned “Location not found” for 382421, Kudasan, and the qualified Kudasan, Gandhinagar query. No substitute location was selected. Public catalogue extraction still worked, but local Zepto pricing/coverage remains unresolved. A failed location search is not proof of an unserviceable postcode or a closed store.

No geolocation permission, precise house address, retailer login, cart addition or checkout was used. Selecting a research locality does not prove delivery to a particular customer's address. Neither selected local catalogue displayed a verified six-digit postcode. The standalone exports intentionally have no order context or staff postcode attestation and are unsuitable for importing directly into a real ticket. Actual ticket import still requires a fresh copied context and explicit staff confirmation; the existing backend enforces order ID, revision, postcode, ownership and capture age.

Screenshots: `blinkit-kudasan.png`, `instamart-kudasan.png`, and `zepto-kudasan-search.png`. The first two show the selected locality and product prices. They do not include a customer's house address.

## What changed

- Added a reproducibly built Manifest V3 toolbar helper in `SnapSave-Backend/tools/retailer-capture-extension/`. It packages the existing exporter instead of maintaining a second extraction implementation. Build output and ZIP are Git-ignored; source and instructions are committed.
- The helper requests only `activeTab` and `scripting`, runs after a toolbar click, restricts execution to supported HTTPS public product/category paths, and prevents concurrent captures on one tab. It has no persistent host permissions, cookie/storage permission, background polling, remote code or automatic SnapSave upload. The exporter requests only the current site's public robots policy without credentials and downloads bounded sanitized product markup.
- The worker reports success/error through its badge and tooltip. Export errors also show a message rather than silently appearing to work.
- Hardened the shared exporter: cancelling its context prompt now stops capture; policy retrieval has a ten-second timeout, refuses redirects and non-200 responses (including 202), and checks policy size in bytes. Location hydration and 60 KB import guards remain.
- Updated management context-copy feedback to describe the toolbar helper and existing JSON import flow. This path can be used while the server's automatic research provider is unavailable.

The browser security policy prevented agent access to Edge's internal extension-management URL. The user completed installation manually after reviewing the requested access. It was not installed through an alternate control path or policy workaround. The user clicked the toolbar on each retailer; the agent completed the open standalone capture prompts and verified the resulting files.

Official extension references: [temporary activeTab access](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab), [script execution](https://developer.chrome.com/docs/extensions/reference/api/scripting), [Edge local installation](https://learn.microsoft.com/en-us/microsoft-edge/extensions/getting-started/extension-sideloading).

## Tested routes and remaining constraints

| Route | Result |
| --- | --- |
| Existing bounded HTTP client | Morning retry recorded Instamart/Zepto 202 and Blinkit 403. No new claim that server HTTP is repaired. |
| Normal Edge navigation to robots policies | All three public policies loaded and permitted the chosen catalogue paths. |
| Normal Edge rendered public catalogues | Real names, packs and selling prices visible and independently parsed. |
| User-installed toolbar → downloaded file → capture validation/parser | Successful live captures for all three stores. |
| Fresh files → combined research provider | Matching candidates for all three diagnostic queries; review-only result retained. |
| Locality selection | Kudasan accepted on Blinkit/Instamart; Zepto search unresolved. |

No undocumented/private API combinations, session replay, identity spoofing, proxy rotation or challenge bypass were attempted. Repeating blocked requests indefinitely would not establish a reliable integration. The successful route requires a staff member's browser click and manual import; it is not scheduled background scraping. These samples cover the chosen milk/storefront pages, not arbitrary grocery searches or every product category. Live stock, checkout fees, promotions and exact-address coverage remain human review tasks. Automatic provider settings and the global AI switch were not enabled by this change.

## Verification

- **212 full regression tests passed**, including seven toolbar build/permission/export tests; one existing Starlette/httpx deprecation warning remains (`full-tests.xml`).
- **66 focused retailer/helper tests passed** (`focused-tests.xml`). They exercise all three packaged capture/download/import round trips, denied policy statuses, supported URL boundaries, error feedback, duplicate-click handling and least-privilege manifest/build outputs.
- The final management instruction edit passed its focused browser import test.
- Source validation parsed **117 Python files**, eight application JavaScript scripts and valid hosting JSON. Exporter/worker JavaScript syntax checks and Git whitespace checks passed.
- Downloaded live files and actual DOM excerpts are recorded separately from fixtures. Earlier three-card minimized DOM captures in `live-captures.json`/`parsed-live-products.json` precede locality selection; they must not be mistaken for Kudasan observations.
