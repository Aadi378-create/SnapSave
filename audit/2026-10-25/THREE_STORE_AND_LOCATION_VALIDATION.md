# Instamart, Zepto, Blinkit and order-location integration

25 October 2026, India time. This extends the earlier BigBasket validation.

## Live observations

Normal Edge loaded all three public storefronts despite the user's local stores being closed. Public catalogue visibility does not establish that a local delivery store is open or that an item is orderable.

| Store | Actual rendered products parsed | Example observed selling price | Source |
| --- | --- | --- | --- |
| Zepto | 59 distinct products | Amul Taaza Homogenised Toned Milk, 1 L: ₹77 | [Milk category](https://www.zepto.com/category/dairy-bread-eggs/milk) |
| Instamart | 40 products | Epigamia High Protein Paneer, 200 g: ₹150, excluding ₹250 MRP | [Public storefront](https://www.swiggy.com/instamart/) |
| Blinkit | 28 supported products | Amul Taaza Homogenised Toned Milk, 1 ltr: ₹77 | [Milk category](https://blinkit.com/cn/milk/cid/14/922) |

Captured public product markup at 2026-10-24 22:24:09 UTC, 25 October in India. `three-store-products.json` records the extracted rows with original source/capture times. `three-store-research-evidence.json` records the provider output. Blinkit's browser location hydrated from an existing location; the provider deliberately excluded its candidates for the different requested test postcode. The existing location's full address was not exported or committed. Zepto and Instamart had no confirmed customer location, and their standalone evidence correctly says location selection is needed.

`three-store-http-results.json` records real bounded HTTP probes: Zepto 202, Instamart 202 and Blinkit 403. HTTP success has not been established. No anti-bot bypass, private endpoint guessing, authenticated session replay, location permissions, login, basket or checkout actions were used. Public robots pages loaded in normal Edge and permitted the selected sources. Search paths disallowed by retailer robots policies are not used.

## Implemented extraction

All selectors were derived from actual rendered product cards. Zepto uses product-card/name/pack/price slots, Instamart uses scoped carousel name/pack/selling-price fields, and Blinkit uses numeric product-card IDs plus separate title/pack/selling-price nodes. MRP, offer percentages and unrelated prices are excluded. Missing or ambiguous fields produce no candidate. Store origin checks, capture age/size limits, robots policy and mandatory human review remain.

Selected pack labels are now stored separately from product names. This fixes two real matching hazards: a title's “25g protein” claim must not replace a 250 ml pack size, and a product title mentioning 450 ml must not override a currently selected 400 ml pack. Unsupported multipacks/alternative pack labels are excluded rather than multiplied or guessed. Instamart cards without a public product link retain the actual category/storefront source; identifiers or URLs are not invented. Different products sharing one source page and price are kept separately.

## Integrated customer-location algorithm

1. Load the order's immutable delivery postcode snapshot, not the customer's current default address. Staff authorization and an eligible pending/reviewing state are required.
2. Build a research context containing order ID, revision and postcode only. Display the target postcode and official store links in the management ticket. No street, telephone, coordinates or customer profile are included.
3. Staff open a dedicated research tab, use the retailer's normal location selector to enter that postcode, choose the appropriate area, and wait for catalogue reload. Previous browser location must be checked. This is a **staff-assisted input step**, not an unattended browser adapter.
4. If location is ambiguous or needs a precise address, stop for clarification. A closed store requires a later retry, not an in-stock assumption. The application does not infer a reopening time from public product visibility.
5. Export at most 30 public product cards. Read a unique postcode from the page header where available; never export the header's address. The staff member must explicitly confirm the selected customer postcode. An observed mismatch stops export. Recheck the header after the asynchronous robots request: location hydration or a changed postcode stops capture rather than mixing contexts. Attach the copied order context and original capture timestamp.
6. Import the JSON into the selected ticket. The backend rechecks staff assignment, state, revision, source origin, robots evidence, timestamp and size. Captures for another order/revision/postcode, missing location confirmation, or an observed postcode mismatch are rejected. No network requests are made during import.
7. Keep location states distinct: `needs_location`, `postcode_observed`, `staff_attested`, `mismatch`. All retain `serviceability_verified=false`. A postcode match does not prove exact-address coverage, live stock, fees or checkout eligibility.
8. Store review evidence alongside any existing manual draft. Invalidate an active AI write by advancing revision and returning worker ownership to human staff. No order price, payable total, quote or fulfillment status is published by import.

Management controls: **Research delivery location**, **Copy research context**, official retailer links and **Import retailer capture JSON**. The upload is bounded to 60 KB and captures expire after 15 minutes. Larger pages need a smaller category/product capture. Order changes require a new context. Source selection and parsing feed the existing AI evidence panel and provider; the manual import route is usable even when automatic research is disabled.

## Verification and follow-up

- Actual public DOM captures produced the counts above; no fixture-only claim of live success.
- Tests cover each retailer's price/pack parsing and exporter round trip, ambiguous packs, same-price products, postcode states/mismatches, role/assignment enforcement, cross-order and stale-revision rejection, preservation of manual prices, and management DOM upload.
- Complete regression suite: **161 passed** (`three-store-tests.xml`). After the final location-hydration guard, all **59 focused scraper/import tests passed** (`three-store-export-tests.xml`). One existing Starlette/httpx deprecation warning remains. Source checks: `three-store-source/source-verification.json`; the exporter also passed `node --check`.
- A single 09:00 Asia/Kolkata follow-up is scheduled for 25 October to retry public retailer checks. It is instructed to pause itself after that attempt. It must not enter a real customer's location without explicit authorization.
- Local backend and frontend were started on loopback. HTTP 200 checks confirmed the new import route in the backend schema and the updated management controls in the served admin page. No real ticket was changed during this smoke check.

Remaining limitations: unattended fetching is blocked; location selection is staff-assisted; no postcode-specific live inventory, exact-address serviceability, checkout fees or production retailer checkout has been validated. Markup can change; parsers fail closed when required selectors disappear. Production research settings and the global AI switch were not enabled.
