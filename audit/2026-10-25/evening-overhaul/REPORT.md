# Evening overhaul — 25 October 2026

## Delivered

- Customer startup no longer reopens a delivered order. Empty order history is fetched once per session rather than on every eight-second poll. A fresh order screen does not request or display legacy general chat. Historical records remain available through their appropriate ticket views.
- Independent customer startup requests run concurrently, followed by the selected conversation. Admin startup metrics and queue requests run concurrently, and queue/chat polling is skipped while working in unrelated admin sections. Existing hidden-tab suspension and single-flight polling remain in place. Firebase revocation verification has not been weakened or cached away.
- Admin polling uses an optional lightweight queue representation. It omits internal research payloads and item arrays, avoids loading those database fields/relationships, and fetches complete authorized ticket details only on selection or a revision change. The legacy full API representation remains for compatibility. Unclaimed moderator tickets still hide precise customer contact/location details.
- In a synthetic one-order benchmark with a 150 KB internal draft, the full queue response was **151,370 bytes** and its summary was **440 bytes** (about **99.7% smaller**). This measures payload size, not an end-to-end browser speedup. Evidence: `queue-payload-comparison.json`.
- Admin presentation now uses responsive queue cards, readable metric grids, opaque surfaces, system fonts, reduced shadows/blur/motion and viewport-contained ticket panels. Mobile header overflow and clipped metrics were corrected. Pagination buttons reflect actual page availability. Fixture screenshots show desktop queue/ticket and mobile layout; they contain no real customer data.
- Fetching ticket details asynchronously exposed two race cases. Composer drafts and old price-preview state now clear immediately when changing tickets; stale responses are guarded by selection/session identity. The preview-race regression test waits for the asynchronously loaded detail form before starting its paused request.

## Automatic research, with exception takeover

The local configuration now enables `AUTONOMOUS_ORDER_RESEARCH`, `AUTO_RESEARCH_NEW_ORDERS`, live research and the existing admin AI switch, using `core.autonomous_research:research`. New orders start in **AI** mode and initiate permitted public requests without a copy/capture/import step. One client shares a 30-second/12-request budget across the whole basket. Blocked URLs have a bounded, in-process 90-second cooldown to avoid repeatedly hitting the same restriction. No stealth, session replay, CAPTCHA bypass or private API access was introduced.

Blocked or incomplete public results transfer to **HUMAN**, with evidence/diagnostics and an explicit failure reason. Automatic tickets show this status instead of clipboard/import instructions. Hybrid is removed from the staff choices and rejected by the mode API when autonomous operation is enabled. Legacy offline-planner compatibility remains internally for historical data/tests; it is not the configured local provider.

**Successful unattended live pricing is still externally blocked.** The bounded real probe at **19:11 IST** returned BigBasket/Blinkit HTTP 403, Zepto/Instamart HTTP 202, and a JioMart response-budget failure. Zero matching products were accepted. The probe used a synthetic milk query and only the authorized 382421/Kudasan research context; no real customer address, login, cart, order or payment was submitted. Exact URLs/reasons/timestamp are in `live-research.json`.

Public catalogue data alone does not verify local stock, serviceability, exact packs or checkout fees. No API/feed account exists, and default catalogue coverage is limited. The system therefore cannot truthfully promise an automatic payable quote for arbitrary typed groceries. Existing verified-provider behavior can publish quotes when a trusted, complete verified source is supplied; browser/HTTP evidence is never relabelled verified to force success.

## Development reset and private recovery

With the API stopped, the reset utility created a private SQLite backup and verified its integrity and SHA-256 before a transaction removed **42 orders, 58 items and 61 linked messages**. Order-linked feedback/incidents were also cleared; completion counters were reset. All **16 accounts, 9 addresses, administrator roles, authentication configuration and settings were retained**. The original snapshot is in the ignored `.private-backups` directory; its filename/hash and aggregate before/after counts are in `reset-summary.json`. No database contents, credentials or environment file are committed. This is a local recovery copy, not an offline/ransomware-isolated backup.

**60 unlinked legacy conversations were retained.** Automatic approval review rejected broadening deletion to every message because unrelated conversations might be affected. No workaround deletion was performed. The safer frontend correction keeps these records off a fresh order screen, with regression coverage showing the records remain intact. Support inbox data was not reset.

The maintenance utility is a local, explicitly confirmed development operation, not an HTTP endpoint or recurring cleanup task. A failed backup prevents reset; foreign-key/integrity failures roll back the deletion transaction. API writers must be stopped before using it.

## Validation and remaining work

The first complete overhaul run passed 275 tests. Additional lightweight-queue checks passed, and subsequent race failures were reproduced and corrected. The final complete suite passed **279 tests**, with one existing Starlette/httpx deprecation warning (`final-tests.xml`). Targeted race results are in `race-regressions.xml`, and asynchronous detail-loading regressions passed in `async-detail-regressions.xml`. Syntax validation passed for 125 Python files, eight application JavaScript scripts and hosting JSON; `git diff --check` passed.

The backend and frontend were unavailable at the beginning of this scheduled run, so a live before/after latency claim cannot be made. The small 236 KB pre-reset database alone does not establish the cause of the reported severe lag. Payload reduction, fewer requests and paint/layout fixes are verified improvements; full real-device/Firebase latency profiling and higher-load deployment measurement remain useful follow-up work.

Both local servers have been started with the updated configuration. `runtime-smoke.json` records frontend/API responses, protected endpoint checks, active provider, feature flags and aggregate post-reset integrity/counts. Automated authenticated tests use disposable SQLite databases and synthetic retailer data; no real payment or new customer order was created for runtime testing. The one-shot scheduled run is removed after this attempt, so it will not repeat.

Fresh Edge verification confirmed that the real customer session opens an empty order screen with no historical chat, and the retained administrator session opens an empty queue with zero operational totals. No new SMS/CAPTCHA or real-order submission was needed. The customer welcome copy now describes automatic research and exception takeover accurately.
