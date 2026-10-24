# Session and communication repairs — 25 October 2026

All five confirmed findings from AUDIT_REPORT.md have been addressed.

| Finding | Implemented repair |
| --- | --- |
| A01: stale screen after Firebase sign-out | Both interfaces observe auth-state changes and immediately clear local user/session state, private conversation UI, drafts and polling. Customer dialogs close and delivery-address UI clears. Normal Firebase restoration remains; the application's saved-token fallback was removed. Development Quick Login remains available only when enabled by the backend and no longer restores a saved application token on reload. |
| A02: draft sent to a different order after polling | Background refresh preserves the selected order instead of silently selecting the newest active order. Drafts are stored per conversation during explicit history/new-order navigation and clear on logout. A second order created elsewhere does not change the target of the existing draft. |
| A03: late session response reopens dashboard | A shared session scope invalidates generations and aborts outstanding API requests on logout/account changes. Both API wrappers reject stale token and response results. Session checks and dashboard initialization validate their generation before proceeding; old polling cannot continue into a later session. |
| A04: reset lost during OTP verification | The shared phone controller records a pending reset while busy, applies it when verification/send finishes and ignores invalidated attempts. Session rejection after OTP returns both interfaces to the phone step. |
| A05: support requests hidden beyond 50 | Added Previous/Next request controls and page/total-thread information. The admin-only `/api/admin/help/summary` endpoint returns distinct total/open thread counts independently of pagination, keeping the badge accurate. Late list responses are ignored and selection survives page changes. |

Two adjacent regressions were also prevented: the staff queue render signature resets on logout so identical queue data appears after re-login; selected ticket details clear/hide on logout. Archived/unassigned ticket write controls now apply permissions immediately during selection, throughout refresh and after send completion, removing the temporary writable state exposed by a timing-sensitive control check.

## Verification

- Full isolated suite: **103 tests passed**, with one upstream Starlette/HTTPX deprecation warning. Results: [repair-results.xml](repair-results.xml).
- Targeted checks also cover external sign-out and re-login in both interfaces, delayed session responses, original-order draft delivery after a background poll, rejected session recovery after OTP, deferred reset, archived ticket protections, 51-thread pagination and summary endpoint authorization/counting.
- Final cleanup checks and syntax evidence: [final-session-checks.xml](final-session-checks.xml), [source-verification.json](source-verification.json). Syntax checks cover 108 Python files and eight JavaScript scripts; hosting JSON and Git whitespace checks pass.

The earlier audit probes/results remain historical baseline evidence. The probe file is now `observational_probes.py` so normal pytest discovery does not collect tests that intentionally assert the old defects. Current repair regressions live in `SnapSave-Backend/tests/test_session_and_inbox_repairs.py`.

No database schema or existing message/payment records changed. Verification used disposable databases and simulated Firebase/external browser requests; it did not send live SMS, customer messages, real orders or bank transactions. Production load and real cross-device Firebase behavior are not certified by these tests. No deployment was performed. Refresh both customer and management pages to load the updated JavaScript.
