# Review of the preceding three hours of changes

Reviewed on 25 October 2026, covering the eight commits from `366a4b0` (02:40 IST) through `881e5d3` (04:49 IST). The checkout was clean at the start. This pass reviews the combined effects of session repairs, retailer research/location evidence, request and hosting hardening, backup tooling, and role/address/privacy repairs.

## Confirmed complications and repairs

1. **Stale quote submission after editing a line (high priority).** Once a quote preview was ready, changing a price or store left the old preview available for submission. Changes now invalidate the preview and require a new calculation. A preview response arriving after another edit is discarded. Existing server revision checks remain in place.
2. **Unsaved price entries lost on evidence import or ticket refresh.** Rendering the research result rebuilt price rows from database values and erased staff input. Edited line totals and store selections now stay in a ticket-specific, memory-only draft through refreshes and ticket switching. Successful quote submission and logout clear the relevant drafts. No research candidate automatically fills prices.
3. **Unverified evidence labelled as approved pricing.** Browser evidence used the same storage column as manual quotes, causing the console to display “Verified by Human.” Evidence without priced items now explicitly says it requires human review, including evidence returned by the AI worker.
4. **Evidence import incorrectly blocked further AI research.** Mode/delegation checks and the worker interpreted any nonempty manual-pricing column as approved human prices. They now distinguish a valid evidence-only draft from human pricing. Existing human item prices and malformed or unrecognized legacy drafts still block AI replacement. Research availability, global enablement, state, ownership and revision checks remain required.

The new regression tests reproduced the failures before repair. They also cover edits while a preview request is pending, separate drafts across tickets, approved-price protection, AI evidence refresh without a customer quote, and conservative handling of malformed legacy drafts.

## Combined review and limits

- The regression run covers customer/admin authentication UI, session cancellation, customer and staff conversations, claims and assignment, order/quote/payment transitions, role restrictions, address snapshots/defaults, retailer parsing and location gates, request limits, static hosting restrictions, and SQLite snapshot recovery. It uses disposable databases and mocked identities; real customer transactions were not changed to reproduce failures.
- Normal visible customer polling makes about 23 periodic reads per minute (three requests every eight seconds); the management ticket view makes about 18 (three every ten seconds). Extra support and user actions add requests. These are individually below the 300-read/minute peer limit. Several users behind one public proxy can share that allowance; public deployment still needs deliberate trusted-proxy and shared rate-limit configuration. This was a code-path review, not a production load test.
- Browser captures remain evidence for a human to review. They do not establish exact-address delivery coverage, live stock, or final checkout fees. Unattended requests can still be rejected by retailer sites. Captures bound to an earlier order revision must be recaptured for import; delegation does not authorize reuse of stale evidence.
- Quote previews are intentionally invalidated by ticket refreshes. Line-item drafts are retained, but fee/discount adjustments in an old preview must be checked again in the new preview. Drafts are session memory, not recovery across browser restarts.
- Backup recovery was exercised by the existing disposable tests. This pass did not create another external-drive backup or replace the prior offline copy. External-drive encryption, recurring private-data backups, cloud TLS/ingress and Firebase deployment remain operational work described in the previous security reports.
- No new database migration, production deployment, account-permission change, or operating-system protection change is included. These checks do not certify the absence of every possible defect or future vulnerability.

## Validation

The full regression suite passed: **205 tests**, including 12 new interaction tests, in 93 seconds. See `tests.xml` and `source-verification/source-verification.json` for evidence. Source verification parsed 115 Python files and eight JavaScript scripts, with valid hosting JSON. One pre-existing Starlette/httpx deprecation warning remains.

The verified local backend was restarted with the repairs. Backend status and the updated management page both returned HTTP 200; API responses retained `Cache-Control: no-store`. Live runtime still reports `research_available: false` and developer authentication disabled. The worker re-entry tests use an explicitly configured test provider; this patch does not enable an unavailable live provider. See `runtime-smoke.json`.
