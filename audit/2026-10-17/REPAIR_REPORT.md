# SnapSave follow-up repairs — 17 October 2026

Continued the existing repair work in the same checkout. No deployment or commit was performed. The real application database, store accounts and bank were not accessed by verification.

## Changes

- **Legacy payment reconciliation:** migration version 2 flags fulfilled legacy orders without bank-verification evidence and potentially paid cancelled orders for manual review. It preserves recorded amounts and does not fabricate payment evidence. The migration runs once, so restarts do not undo later administrator decisions.
- **Cancellation/refunds:** cancelling an unreconciled legacy order preserves its review flag. Administrators can reconcile archived or fulfilled legacy orders even when old confirmation timestamps are absent. Verified receipts update actual settlement/profit; an explicit no-receipt finding clears the old payment amount and records the previous amount/reference in the audit conversation. Fulfillment status remains unchanged. Cancelled receipts require a recorded refund.
- **Archived staff workflow:** Completed and Cancelled filters make payment/refund follow-up reachable after leaving a ticket. The reconciliation action is visible for eligible legacy records without requiring a historical confirmation timestamp.
- **Malformed offers:** split optimization, raw single-store comparisons and product ranking reject invalid/non-finite/negative prices, boolean prices, missing names and malformed offer rows. Broken store data cannot defeat a valid offer or cause a numeric-comparison crash.
- **Large baskets:** independent cheapest-item selection now uses a linear pass. It handles 100 items without invoking the bounded combinatorial split solver, while still rejecting incomplete allocations.
- **Browser cleanup:** cleanup attempts every resource and clears thread-local references even when a close/stop call fails. Partial initialization is cleaned up; page-close failures do not mask the original scraper error or prevent browser cleanup.

## Verification

**69 tests passed, zero failures/skips, in 30.50 seconds**, including four headless Chromium tests. Twenty-one new regression cases cover the follow-up changes. The single warning comes from Starlette's test-client HTTPX dependency.

**102 Python files and six JavaScript scripts** passed syntax checks. Hosting JSON parsed successfully; `git diff --check` passed.

Evidence: [pytest results](regression-results.xml), [source verification](source-verification.json). Test fixtures select disposable databases before application import; browser external requests are mocked. Browser-resource failures are simulated without opening store sessions.

The root README now describes legacy reconciliation. The earlier [repair report](../2026-10-13/REPAIR_REPORT.md) remains the record of the initial audit fixes. Its live-service and deployment limitations still apply: real Firebase OTP, bank settlement, store inventory/checkout, PostgreSQL migration and production load have not been verified. Live research remains gated; this pass does not enable a scraper or perform bank transactions.

Back up the existing application database before its first updated startup. Startup applies the new additive migration; the tests have not applied it to real customer data.
