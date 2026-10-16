# SnapSave repair report

Follow-up repairs and the latest verification are recorded in `../2026-10-17/REPAIR_REPORT.md`. The results below describe the October 13 pass.

13 October 2026. Repairs are in the current working tree; no deployment or commit was performed. The original PROJECT_AUDIT.md describes the pre-repair checkout.

## Verification

- **48 tests passed, zero failed or skipped**, including three headless Chromium flows, in 11.98 seconds.
- **101 Python files and six JavaScript scripts** passed syntax checks; Firebase hosting JSON parsed successfully.
- `git diff --check` passed. Git reports normal Windows line-ending conversion notices.
- One remaining warning originates from Starlette's test-client HTTPX dependency; no application deprecation warnings remain in this run.
- Tests use disposable SQLite databases and mocked external identity/provider services. The real development database, customer accounts, stores and bank were not modified. The supplied merchant UPI ID was saved in the ignored backend `.env`, with recipient label SnapSave.

Evidence: [pytest results](regression-results.xml), [source checks](source-verification.json), [tested dependency versions](tested-dependencies.json). Run the current acceptance suite with `python -m pytest -q` from the backend directory; see the root README for setup. Original reproduction scripts are historical evidence and expect the old behavior.

## Audit coverage

“Repaired” refers to application behavior and local verification. “Guarded” means unsafe or unsupported behavior is blocked; external integration or production scaling still requires additional evidence.

| Finding | Current disposition |
|---|---|
| A01 Development auth/staff impersonation | Repaired: production issuance/acceptance disabled; loopback development gate; real staff OTP; database roles only. |
| A02 Role promotion bypass | Repaired: administrator permission on all promotion routes; private first-admin bootstrap. |
| A03 Stored HTML injection | Repaired: escaped untrusted content and structured payment cards; customer/staff browser regressions. |
| A04 Ownership/lifecycle reversal | Repaired: centralized ownership and finite state checks; terminal orders cannot reopen. |
| A05 Assignment enforcement | Repaired: order-level assignment governs staff actions/chat; customers cannot view internal costs/profit. Customer administration requires ADMIN. |
| A06 Human override/kill-switch races | Repaired: atomic revision and policy checks; deterministic takeover and OFF/ON race tests. |
| A07 AI terminal states/item persistence | Repaired: eligible states only; complete item records and consistent draft schema. |
| A08 Invalid quote totals | Repaired: finite nonnegative money, exact item coverage, authoritative subtotal and final reconciliation. |
| A09 Line totals versus unit price | Repaired: explicit line totals and per-unit responses; legacy conversion tested twice for idempotence. |
| A10 Mixed-store shipping | Repaired: shipping calculated separately per store in previews and split optimization. |
| A11 Incomplete cheapest baskets | Repaired: complete coverage required in optimizer, aggregator and serviceability filtering. |
| A12 Mock live prices | Guarded: mock fallback removed; missing verified research returns unavailable. No live store integration is claimed. |
| A13 Unrelated product matches | Repaired: meaningful query words, category and pack-size filtering; invalid prices rejected. Ambiguous matches require human verification. |
| A14 History/New Order state | Repaired: explicit draft/history contexts; browser switching regression. |
| A15 Mixed/missing order messages | Repaired: quote, cancellation, payment and lifecycle events carry order IDs; chat is order-scoped. |
| A16 Moderator chat disabled | Repaired: assigned moderators can read/send; browser verifies enabled composer. |
| A17 Stale tokens/shared demo identity | Repaired: Firebase token retrieval per request and distinct local phone identities. Real token refresh/OTP still needs live verification. |
| A18 Hidden/non-reconciling charges | Repaired: explicit service fee and complete customer breakdown; profit recorded from actual settlement, no assumed wallet/card benefits. |
| A19 History/queue N+1 | Repaired: eager-loaded items/users, bounded pages and SQL aggregates; history test enforces at most four SELECTs. |
| A20 Overlapping/stale polling | Repaired: sequential polling, cursors, context guards, revision checks and queued queue refreshes. Browser test switches tickets during quote submission. |
| A21 Claim races/customer-wide ownership | Repaired: ticket assignment and optimistic writes; retry keys reject differing payloads. |
| A22 Unbounded AI/session lifecycle | Guarded: two workers, twenty outstanding jobs, deduplication, session cleanup, persisted failures and restart fallback. Durable multi-process research remains future infrastructure work. |
| A23 SQLite/caches/concurrency | Repaired locally: FK enforcement, WAL, busy timeout, bounded locked caches, atomic JSON replacement and locked updates. SQLite still has one writer; process-local state is not shared infrastructure. |
| A24 Payment/ETA/feedback/counters | Repaired: order-specific UPI QR, bank evidence/ETA, unique receipt references, cancelled-payment reconciliation, full refund recording, post-delivery feedback and single delivery count. Bank verification/refunds remain manual. |
| A25 Tracker/delivered feedback | Repaired: placed and delivered are distinct; delivered history/feedback remains reachable. |
| A26 Parsing | Repaired: shared basket separators, decimal volumes, litre aliases and multipliers; fresh composer treats input as a grocery list, general questions use Support. Human clarification remains necessary for ambiguous language. |
| A27 Location/store rules | Repaired/guarded: unknown coordinates remain unknown; Instamart IDs normalized; explicit serviceability configuration. Real location/stock/surge fees need a verified provider or staff checks. |
| A28 Mode/delegation policy | Repaired: enums, global availability/enable checks, consistent HUMAN/HYBRID assignment and audited takeover; no generic AI acknowledgement on human tickets. |
| A29 Migrations/transactions/paths | Repaired for tested SQLite: additive migrations, stable paths, atomic state/events, Text fields, bounded inputs and conflict responses. PostgreSQL migration has not been exercised against a real server. |
| A30 Analytics | Repaired: paid placed/delivered/completed revenue, delivered savings, business timezone and first-response timestamps; completion no longer removes revenue. Historical unknown settlement data is not invented. |
| A31 Hosting/logging/limits | Repaired locally: explicit API-origin build, deployable asset package, token logging removed, restricted CORS and body/rate limits. Real HTTPS hosting/backend origin still needs deployment configuration. |
| A32 Legacy research modules | Guarded and partly repaired: disabled main scraper entry, normalized imports, structured aggregation, bounded matching, Decimal currency helper and thread-local browser lifecycle. Old store-specific prototypes/selectors/location behavior are unverified and must not be treated as a production research provider. |
| A33 Unsafe/outdated tests | Repaired: isolated fixtures, current contracts, authorization/money/race/browser assertions and removal of destructive audit behavior. |
| A34 Drafts/support/feedback/recommendations | Repaired: drafts retained on failure, visible feedback errors, support polling, scroll preservation, logout cleanup, retired duplicate staff scripts and corrected optional add-on rules. |

## Before public release

1. Back up the existing database before the first updated startup. Startup applies migrations; inspect historical duplicate feedback/payment references, orphan records and unknown old payment amounts rather than fabricating or deleting records. Duplicate legacy rows are preserved when a uniqueness index cannot safely be added.
2. Verify Firebase service credentials, authorized domains, real customer/staff OTP, revoked-token behavior and mobile sessions. Keep development auth disabled on public deployments.
3. Verify a small real UPI payment against the merchant account, including the recipient label, bank reference and cancellation/refund process. The application records staff verification; it does not receive authenticated bank webhooks or execute refunds.
4. Configure an actual HTTPS backend origin and frontend CORS origins, then build the static package. Hosting alone does not deploy or proxy FastAPI. No deployment was performed during these repairs.
5. Keep live research disabled until a real provider proves SKU, quantity, postal-code inventory, fees, promotion eligibility and bounded network timeouts. A verified flag is a contract with trusted installed provider code, not independent proof of live store data. Store-specific checkout and multiple-store delivery records are not implemented.
6. Use one API process with the current in-process research executor. Before scaling AI, adopt a durable shared queue. Load-test the actual deployment before setting a customer capacity; SQLite, process-local limits/caches/JSON stores and fulfillment staffing still impose practical limits.

The root README and backend `.env.example` describe the secured setup, private administrator provisioning, current pricing defaults, provider contract and hosting build. These checks establish local correctness for the supported concierge workflow, not production capacity or successful live integrations.
