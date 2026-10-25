# Price-draft integration — 25 October 2026

## Delivered behavior

Fresh browser captures can now fill the staff pricing form with calculated item totals. The server matches explicit pack sizes, checks product relevance, source URL, INR currency, availability, location and the 15-minute freshness window, and multiplies the observed pack price by the stored order quantity using Decimal arithmetic. Equivalent mass/volume units are supported. Missing sizes, alternative packs and multipacks are left unresolved; multiple eligible candidates require an explicit staff choice.

The new authenticated `POST /api/moderator/orders/{order_id}/research-price-draft` endpoint requires administrator or assigned moderator access, an eligible order state and the current revision. Candidate indices refer only to evidence already stored for that order. Client-supplied prices are not accepted. This calculation does not write order prices, advance the order, publish a customer quote or invent checkout fees.

Importing evidence calculates the form draft automatically. Staff can recalculate or select a particular observed price. Manual edits survive automatic calculations, and asynchronous responses are guarded against changed sessions, tickets, revisions and edits. Existing human quote review remains required. Draft responses explicitly have `fees_verified: false`, `payable_total: null` and `requires_human_review: true`.

## Verification

- Complete suite: **252 passed** (`full-tests.xml`), with one existing Starlette/httpx deprecation warning.
- Subsequent browser verification: **2 passed** (`browser-verification.xml`), covering automatic form fill, preservation of manual edits and the existing typed-order-to-human-quote flow.
- Source validation: 122 Python files, eight application JavaScript scripts and hosting JSON passed (`source-verification/`). `git diff --check` passed.
- Example fixture: two 1 L packs at ₹77 produce ₹154; one 200 g pack at ₹150 produces ₹150, for a ₹304 item subtotal. The browser screenshot `calculated-price-draft.png` records this synthetic test, not a current retailer price.
- Tests reject stale/wrong-location/wrong-source/wrong-product evidence, unsupported packs, invalid prices, currency/stock mismatches, foreign item IDs, unauthorized requests and stale revisions. Calculation leaves persisted order prices unchanged.
- Ordinary browser tests now write screenshots to temporary output; explicit audit runs can select a destination through `SNAPSAVE_TEST_ARTIFACT_DIR`, preserving historical audit evidence.
- Restarted the verified local backend and checked localhost at 16:27 IST: API and staff page returned 200, the new endpoint and calculation control were present, research was available and development authentication remained disabled (`runtime-smoke.json`). No production test orders were created.

## External access remains unresolved

Bounded checks at approximately **16:16 IST on 25 October 2026** returned HTTP 202 for Zepto and Instamart catalogue requests and HTTP 403 for Blinkit's robots policy. No catalogue data was accepted from those responses. Exact URLs, stages and timestamps are in `current-access.json`. Requests stopped at these restrictions.

The user confirmed that no official retailer/partner API or licensed price-feed account is available. Fresh, supported browser captures therefore remain the working source. This implementation completes calculation and form integration from such evidence; it does **not** complete unattended live retrieval for arbitrary products. It cannot guarantee current stock, delivery coverage, discounts or checkout fees. Previously unresolved Zepto location selection for Kudasan also remains a limitation.

A permitted accessible API/feed or fresh browser evidence is needed for each requested product. Missing evidence is shown as unresolved rather than replaced with estimates. No credentials, private database or real customer records are included in this report or its fixture screenshots.
