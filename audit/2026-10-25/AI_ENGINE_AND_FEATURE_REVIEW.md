# SnapSave product inspection and AI research review

25 October 2026. Inspection baseline: `a0935b5`; research implementation checkpoint: `cce1af9`.

**Follow-up:** [Website scraping validation](WEBSITE_SCRAPING_VALIDATION.md) subsequently verified browser-assisted BigBasket extraction on actual rendered pages: 33 category products and a matching ₹73 / 1 L product result. Earlier HTTP failures below remain accurate; unattended fetching remains blocked.

## Assessment

The customer-to-concierge order workflow is the project's strongest working foundation. Authenticated accounts, per-order conversations, explicit quotes, payment references, fulfillment, cancellations, refunds and support exist. Recent identity/session repairs have regression coverage. The best next step is to improve the clerk's evidence and the customer's control over their order, consistent with SnapSave's human-first, anti-cart philosophy.

**At this initial HTTP inspection, the research engine could extract and match structured evidence but had not obtained a usable retailer price. Subsequent browser-assisted validation did obtain real public prices; see the follow-up above.** Current multi-store comparisons are not postcode-verified. Beautiful Soup is an HTML parser, not a way around retailer access restrictions and not an AI model.

This review combines inspection of customer/admin flows and API policies, parser/matcher/optimizer paths, provider/worker integration, legacy store adapters, configuration, the full automated suite and bounded live HTTP probes. It is not a certification of every manual screen, production capacity, real store checkout or bank settlement.

## Beautiful Soup and what was missing

The package is named **Beautiful Soup** (`beautifulsoup4`, imported as `bs4`). It was already listed in requirements and used by a legacy helper. It parses HTML/XML supplied to it; it does not fetch pages, execute JavaScript, establish a delivery location or verify stock. Its official [documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) describes that parsing role. A dynamic site needs a permitted feed/API or a browser adapter to render data before extraction; [Playwright's locator documentation](https://playwright.dev/python/docs/locators) describes its browser interaction/waiting primitives.

The existing runtime had three disconnected pieces:

1. The concierge worker expected a separately configured research callable. The existing environment had live research disabled and no provider configured.
2. Legacy store collection was explicitly disabled in `stores/price_parallel.py`, returning `not_available`. Selecting a provider alone did not connect these legacy comparisons to real prices.
3. Several legacy adapters were unsafe to reactivate unchanged: `core/scraper_engine.py` zipped unrelated title/price lists and used integer conversion; Zepto selected the first rupee text and concatenated digits; Instamart searched generic page divs; Blinkit hard-coded a Gurgaon location while accepting an unused city argument. Those paths cannot establish an exact product or customer postcode.

These legacy paths remain disabled. The new provider does not call them.

## Implemented in this pass

Files: `core/catalog_research.py`, `research_catalog.py`, `api/ai_concierge.py`, the admin evidence view, `.env.example`, README and regression tests.

- Product-scoped JSON-LD and microdata extraction using Beautiful Soup. Titles and exact selling prices stay in the same product record; nested microdata cannot borrow another product's price. INR currency is explicit. Invalid, zero, negative, non-finite, boolean and ambiguous price values are rejected; price ranges are not treated as exact offers.
- Product-name and requested pack-size matching, including equivalent units such as 1 L and 1000 ml. Explicit out-of-stock evidence is excluded. Unknown availability remains unknown.
- Supported retailer HTTPS origin restrictions, redirect checks, robots-policy checks, response byte limits, time/request budgets, crawl delay handling and no challenge bypass. Failures are reported and cached within the job instead of repeated with another browser identity.
- Bounded per-job page/parse reuse. Evidence records the product name, price, currency, SKU when supplied, source URL, collection timestamp, stock metadata and extraction method. The diagnostic lists missing/blocked sources separately.
- A configured provider, `core.catalog_research:research_catalog`, returns `verified: false` and `requires_human_review: true`. The postcode is the requested context, not a claim that a retailer session has been set to that postcode. Catalogue unit prices are not multiplied into a payable total and delivery/checkout fees are not invented.
- The existing worker accepts these evidence drafts under its revision, assignment and global kill-switch predicates. It stores the draft for human review, switches autonomous requests to HYBRID with a human worker, and leaves line prices, totals and quote-publication state unchanged. Empty/blocked results explicitly request manual pricing.
- Admins can read candidates, collection time, stock uncertainty and source failures in the ticket. Source links are restricted to retailer HTTPS origins and displayed with safe text handling. Candidate prices do not automatically populate the quote editor.
- A read-only diagnostic CLI works without importing the API/application database. Configuration and usage are documented. Existing runtime flags and the administrator's global AI switch were not enabled.

The existing backend can also accept separately installed providers claiming fully verified quotes. This new public-catalogue provider never makes that claim. Production automatic quote publication still needs a stronger, independently validated stock/fee/serviceability evidence contract.

## Actual live results

The checked public requests used an honest `SnapSaveResearch/0.1` user agent, no login, no location cookies and no checkout. Results are specific to this environment and observation time, not a statement that those websites are unavailable to ordinary shoppers.

| Retailer | Observed result | Consequence |
| --- | --- | --- |
| BigBasket | Robots request returned HTTP 403 | Collector stopped; no catalogue price accepted. |
| Zepto | Search path was disallowed by its robots rules. A permitted public milk-category attempt returned an empty HTTP 202 response. | No usable product HTML. |
| Instamart | Public search passed the robots check but returned an empty HTTP 202 response. | No product evidence accepted. |
| JioMart | Robots returned HTTP 200; its parsed policy disallowed the tested URL for this agent. | Catalogue fetch skipped. |
| Blinkit | Separate robots connectivity check returned HTTP 403. | Not enabled as a default source. |

The new collector's repeatable four-source result is in [live-catalog-research.json](live-catalog-research.json). It correctly contains no candidates and `verified: false`. The BigBasket [public product page](https://www.bigbasket.com/pd/306926/amul-homogenised-toned-milk-1-l-carton/) is visible through web search, but a search-index result is not a locally verified, customer-postcode price. No search-snippet price was fed into an order.

The new collector parses returned HTML only. It deliberately does not launch the brittle legacy Playwright adapters. A future browser integration must establish the real delivery context, wait for actual product data, keep authorized sessions separate and stop at challenges; merely changing user agents, inventing location cookies or scraping private endpoints would not produce reliable stock/fee evidence.

Default sources are an initial diagnostic set, not full grocery coverage. In particular, the Zepto default is a milk category; other categories need explicitly configured permitted sources. A permitted product feed or merchant-supported API is the most useful dependency for making live research operational.

## Feature priorities

The following are proposals; this pass did not silently add all of them.

| Priority | Addition | Current gap / concrete benefit |
| --- | --- | --- |
| Next | Active-order switcher | History navigation is primarily for archived orders. Polling now pins the selected conversation, but customers need an explicit list of all active orders with per-order drafts and unread state. This preserves the separate-session model. |
| Next | Structured amendments and substitution approval | Follow-up chat does not change order items. Add per-item replace/remove/quantity requests, staff proposals and customer acceptance. Accepted amendments must invalidate the old quote and require confirmation of the new revision. |
| Next | Staff quote-editor draft preservation | A revision refresh can rebuild price rows and clear an unsaved preview. Preserve draft input per ticket and show a conflict notice instead of overwriting it when another worker changes the revision. Published human prices already have write protection. |
| Before live research launch | Postcode-aware stock/fees connector | Verify SKU/pack, selected delivery location, stock, quantity limits, taxes and all checkout fees from a permitted source. Public catalogue metadata alone cannot prove these. |
| Before live research launch | Evidence expiry and review record | Collection timestamps now exist. Add explicit stale-evidence indicators, refresh actions, quote-to-source provenance and a retained staff approval record. Currently a later manual quote replaces `manual_prices`; evidence is not a permanent append-only price history. |
| Before scale | Durable research jobs | Research currently uses two in-process workers and bounded outstanding work. Persist job stages, retries, cancellation and recovery so a restart cannot strand AI-assigned tickets. Add per-source quotas and shared health/circuit-breaker state. |
| Before scale | Read/unread state and message history pagination | Current polling has incremental IDs and bounded caches but no durable unread/read state or older-message navigation. Add a new-message jump action; consider server events after ordering and reconnect semantics are tested. |
| Before scale | Persistent send/outbox idempotency | Order chat retries are deduplicated while the page retains its request ID. Persist unacknowledged sends safely across reloads. Support messages still lack server-side retry deduplication. |
| Before scale | Payment/refund evidence and reconciliation workflow | References and amounts exist, but verification is manual. Add protected receipt attachments, duplicate-reference investigation and an append-only settlement/refund log. Do not treat an uploaded screenshot as bank verification. |
| Before production launch | Restore-tested backups and operational visibility | Add scheduled database backups with restore drills, alerts for failed/stuck jobs and metrics for provider latency, blocked sources, quote turnaround and human takeover. Full production load remains unmeasured. |
| Useful next | Opt-in repeat list | Let a customer request a previous list in a new session, then re-check availability and prices. Do not imply old prices are current or turn this into unsolicited upselling. |
| Useful next | Better quantity and ambiguity handling | Preserve the original request alongside structured brand, pack, unit, quantity and confidence. Ask short clarifying questions for uncertain weights, brands and alternatives. Multilingual parsing can follow; no paid LLM integration was introduced in this pass. |
| Useful next | Keyboard and mobile refinement | Finish modal focus trapping/restoration, form labels and the remaining browser prompt replacements. The admin support view's fixed two-column layout also needs a deliberate small-screen treatment. |

Recommended sequence: active-order navigation + amendments + quote-editor drafts; permitted source onboarding + evidence review; then durable jobs and notifications. This improves trust and reliability without introducing catalogue browsing or surprise purchases.

## How to exercise the implementation

From `SnapSave-Backend`, a diagnostic that does not touch the application database:

```powershell
../.venv/Scripts/python.exe research_catalog.py --query "Amul milk 1 L" --postal-code 110001 --live --output research-diagnostic.json
```

To use the review-only provider inside an eligible ticket, configure:

```dotenv
ENABLE_LIVE_RESEARCH=true
RESEARCH_PROVIDER=core.catalog_research:research_catalog
```

Restart the backend, enable the admin global AI switch and use HYBRID on an eligible pending/reviewing ticket. Current default source access still produces manual-review diagnostics, not a verified quote. A server-owned `RESEARCH_CATALOG_SOURCES` mapping can supply permitted retailer pages; arbitrary external origins are rejected. Do not enable unattended pricing on the basis of fixture success.

## Validation

**128 tests passed**, with one upstream Starlette/HTTPX deprecation warning. New coverage includes decimal/currency correctness, nested-product isolation, pack/stock matching, unsafe URLs, robots denial, challenge statuses, redirect restrictions, size/request limits, draft-only behavior, the global kill switch and admin rendering/XSS protection. Existing lifecycle, auth/session, pricing and communication regressions also passed.

Evidence: [full test results](ai-research-results.xml), [source checks](ai-research-source/source-verification.json), [live diagnostic](live-catalog-research.json). Syntax verification covered **111 Python files and eight JavaScript scripts**; hosting JSON and Git whitespace checks passed.

Fixture extraction success and blocked live-source diagnostics are separate results. No live SMS, retailer login, order placement, bank action or production deployment was performed. No actual customer's order was used for live probing; the diagnostic query/postcode were test inputs.
