# Live Edge verification — 17 October 2026

Started the real local services in hidden background processes:

- Customer app: http://127.0.0.1:3000/
- Management app: http://127.0.0.1:3000/admin.html
- Backend: http://127.0.0.1:8000/

All three HTTP checks returned 200, including `/api/status`. Development authentication and live research remain disabled. The API completed its normal startup migrations against the real local database; a SQLite backup was saved before startup.

## Actual authentication and application use

Used the user's existing Edge browser and Firebase console, without mocked Firebase responses. The console showed the Blaze billing plan and enabled Phone sign-in. No Firebase settings were changed.

The management app initially restored a customer session, which correctly failed the staff-role check. Signing in with the requested administrator phone reached Google's visible CAPTCHA. The user completed CAPTCHA and SMS-code entry. The real app then displayed the ADMIN dashboard for the intended existing account. Reloading retained the authenticated session and administrator role.

Opened the real customer app on the same 127.0.0.1 origin. It restored the signed-in identity and loaded the existing profile, order history and current order. Neither browser tab reported a JavaScript console error during these checks. No order, payment, refund or support message was submitted.

This successful attempt does not establish the cause of the earlier generic Firebase internal error, but it verifies that real phone authentication works on this local origin with the current project configuration.

## Fixes found by the live check

Four operational cards on the management dashboard stayed at zero because their DOM elements were never updated from the API response. Connected Pending Review, Awaiting Customer, Confirmed and Delivered to the corresponding API values. The reloaded live dashboard now shows the actual nonzero queue/delivery counts. Added a browser regression with distinct counts to prevent the missing bindings from returning.

Starting SQLite in WAL mode also exposed unignored `-wal` and `-shm` files. Added Git ignore patterns for SQLite WAL, shared-memory and rollback-journal files. `git check-ignore` confirms the real database and working files are excluded; no database working files were tracked or pushed.

## Verification and handoff

The focused browser suite passed **5 tests in 11.93 seconds**, including the new operational-card regression. The preceding full backend/browser suite passed 73 tests; this change affects only frontend card bindings and Git exclusions. Source syntax and Git whitespace checks also passed.

Both local services remain running, and the administrator and customer tabs are left open in Edge. Screenshots are stored in the local visualization directory, outside Git, to avoid publishing account/customer details. The source fixes and this report are checkpointed to the existing GitHub repository.
