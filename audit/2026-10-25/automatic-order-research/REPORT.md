# Automatic grocery-list research and browser evidence integration

25 October 2026, Asia/Kolkata.

## Result

Submitting a new valid typed or structured grocery list can now automatically start research through the existing background AI executor. The local installation is enabled with `AUTO_RESEARCH_NEW_ORDERS=true`, `ENABLE_LIVE_RESEARCH=true`, provider `core.order_research:prepare_research`, and the existing database AI switch enabled. The restarted backend reports research available; developer authentication remains disabled. The customer and management pages both return HTTP 200 with their new research controls (`runtime-smoke.json`). Only these local settings were changed; private environment values were not committed.

The configured provider is an order research planner, **not unattended retailer scraping or a general conversational language model**. It prepares each submitted item for browser research without issuing retailer HTTP requests, fabricating a price, reusing a previous customer's captures or publishing a quote. The working toolbar capture/import flow supplies actual product evidence. Nothing in this change claims arbitrary products can be fetched automatically from retailers that still reject server requests.

## Integrated workflow

1. A customer submits a new list through the normal text or structured form. Comma, newline, semicolon and `and` separators use the existing parser. Valid orders have 1–100 items. Research starts automatically only while the configured provider, auto-start flag and global AI switch are enabled.
2. Creation remains idempotent: retrying the same request does not enqueue another job. Lists start in HYBRID mode. The real executor prepares a review-only item plan and returns worker ownership to human staff. Follow-up chat stays on that order without silently adding items, repricing it or starting another order.
3. The customer tracker shows preparation, missing-match counts, partial coverage, readiness for human review or expired evidence. No raw staff research/pricing details are exposed to customers.
4. The staff ticket displays all requested research items, including items absent from a milk category or current capture. **Copy item query** helps staff locate the relevant product/category on the retailer using its normal supported interface. Missing evidence is explicitly distinguished from out-of-stock status. All 100 supported order items can be reviewed; the earlier 20-item display/import limit no longer truncates larger lists.
5. Staff select the order delivery area, copy the ticket's current research context, run the installed toolbar helper on relevant retailer pages, and import its JSON. Existing ownership, assignment, state, order ID, revision, postcode, robots, size and timestamp checks remain in place. The helper is still an explicit browser action and JSON import remains manual.
6. Import now goes through order-level research batching. A 100-item basket is processed in at most five 20-item batches using the same supplied capture client. No live HTTP fallback is made during import.
7. Importing another store's evidence no longer discards earlier fresh evidence. Candidate provenance includes the original capture URL. Recapturing a source replaces that source's candidates, while unrelated sources retain fresh, order-compatible and location-confirmed evidence. Wrong-postcode and expired retained candidates are excluded. Re-running the planner also preserves valid fresh browser evidence.
8. Candidate age remains tied to the original retailer observation, not a later merge/import timestamp. Coverage ignores expired candidates and the management view marks them for recapture. Human prices, confirmed quotes and payment states retain their existing protection. Candidate prices are not automatically entered into line totals or sent as a customer quote.

## Typed input and limitations

The planner accepts all valid item names for research, including unknown products and Unicode text. Unknown inputs remain unresolved items; this does not assert that arbitrary names, spelling errors, regional language phrases or conversational instructions can already be matched to English retailer catalogues. Existing exact product/pack checks still apply. Staff must clarify vague items or research them manually when needed.

Oversized item names, quantities above 1000 and lists over 100 items now receive HTTP 422 instead of leaking an internal Pydantic validation exception as HTTP 500. The request length cap and authorization remain unchanged. A plain number at the start of a free-text brand can still be ambiguous; use explicit counts such as `1x 7 Up 750 ml` or the structured list form.

Submit a **new grocery list** to exercise automatic research. Typing another message inside an existing order continues its conversation. The app does not treat every chat message as permission to change an order.

Locality selection from the preceding pass remains valid only as research evidence: Blinkit and Instamart accepted Kudasan, while Zepto's location search did not. This integration does not resolve Zepto's search or prove exact-address delivery, inventory, fees or promotions. New products require fresh relevant-page captures; old milk/storefront samples cannot price an arbitrary basket. No actual customer test order, paid order or historical quote was modified in the live database. Enabling the existing global AI switch was the only database configuration change.

## Verification

- The full regression suite passed **227 tests** (`full-tests.xml`).
- The 15 new focused tests cover automatic typed/structured planning, several list formats, Unicode/unknown products, duplicate requests and follow-up chat, successive retailer imports, source replacement, preserved evidence during planner retries, a 100-item basket, expiry, invalid input, the global kill switch and both browser UIs (`focused-tests.xml`).
- One additional test then exercised the **actual background executor**, rather than the deterministic synchronous test dispatcher: a newly submitted list completed planning and returned to human review without HTTP requests, a price or a customer quote (`real-executor-test.xml`). That makes **228 distinct passing tests across the two regression commands**, including 16 new integration cases.
- The customer browser check was then strengthened and passed again for the precise input flow: clicking **New Order**, filling the chat composer with a new rice/unknown-product list, and pressing **Enter** created a separate research request with two items and no invented price. The staff view still selected the correct ticket (`composer-browser-test.xml`).
- All test customer records, captures, identities and settings use disposable databases. The live local smoke check was read-only after configuration/restart.
- Syntax validation parsed **119 Python files**, eight application JavaScript scripts and valid hosting JSON. Git whitespace checks passed. One existing Starlette/httpx deprecation warning remains.

The earlier live toolbar results are documented in `../retailer-browser-resolution/REPORT.md`; this pass validates their connection to submitted orders without pretending fixture captures are fresh live retailer inventory.
