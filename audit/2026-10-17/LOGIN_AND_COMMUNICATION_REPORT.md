# Login and communication review — 17 October 2026

## Implemented

- Customer and management sign-in now share a responsive phone → CAPTCHA → SMS → OTP flow. Labels, numeric input, Enter submission, inline validation, loading states, resend cooldown, changing the number and CAPTCHA expiry/retry are handled consistently. CAPTCHA is centered above Send code; narrow screens request Google's compact widget. Firebase authentication remains required.
- Replaced blocking chat/support send-error alerts with feedback next to the composer. Failed sends retain the draft; repeated clicks are guarded. A successful send followed by a failed chat refresh is reported as sent, avoiding misleading retry instructions.
- Routine system updates now appear as compact timestamped conversation events. Quotes and payment instructions retain their actionable cards. Legacy system markup is displayed as readable text without executing HTML. Old messages no longer replay entrance animations whenever another message arrives.
- Added message request UUIDs, with server-side duplicate detection scoped to the authenticated sender, customer, order and exact text. Retrying a send whose response was lost returns the original message. Reusing its UUID for different content is rejected. Existing clients can omit the field; no schema migration is needed. This protection applies to order chat; support has in-flight guards but does not yet have server-side retry deduplication.
- Concurrent poll responses merge into the latest cache by ID rather than a stale snapshot. Deduplication uses a Map rather than a nested scan, with deterministic server-compatible ordering and a bounded 500-message cache.
- Staff drafts stay with their selected ticket and clear on logout. Sending remains guarded during ticket switches. Customer order-history/new-order navigation is guarded during a pending send to avoid writing into a different conversation.
- Fixed the initially blank customer mobile workspace by selecting Chat by default. Fixed chat flex sizing so long conversations scroll within the stream and the composer stays reachable. Added mobile spacing and concise composer prompts.
- Restored admin navigation on smaller screens as a horizontally scrolling bar, including Help Inbox, Customers and Settings. Corrected the Beta view's conflicting sidebar margin. Inactive customer dialogs now use visibility hiding so invisible controls are excluded from normal interaction.
- Corrected Analytics revenue/profit labels to Total Revenue and Total Profit, matching the all-time figures actually displayed.
- Hosting preparation includes all shared login and conversation assets; a regression check verifies their inclusion.

## Review and validation

The full isolated regression suite and focused Chromium tests cover phone/OTP states at 320, 390 and 1280 pixels; lost-response retry without duplicate messages; authorization and UUID conflicts; ticket drafts; mobile navigation; long-chat composer placement; safe rendering; order lifecycle and hosting output. Tests use a disposable database and mocked Firebase/external requests. Their CAPTCHA control is a test simulation, not a live Google challenge.

Live Edge checks used the existing signed-in customer and admin sessions at 127.0.0.1:3000, inspecting the conversation, order queue, Settings and Analytics. No real messages, orders, bank actions or cloud configuration changes were submitted in this pass. The backend and frontend remain running locally. This review combines source inspection and representative browser checks; it is not an exhaustive certification of every screen or production load.

Final verification: **86 tests passed in 36.76 seconds**, with one upstream Starlette/HTTPX deprecation warning. Syntax checks passed for **105 Python files and eight JavaScript scripts**; hosting JSON and Git whitespace checks passed. Verification results are in verification-results.xml and source-verification.json. Preview screenshots remain outside Git in the local visualization directory so customer information is not published.

## Remaining refinements to agree on

1. Replace the remaining operational browser prompts with purpose-built dialogs for quote submission, cancellation, payment evidence and refund recording. These actions need distinct validation and explicit confirmation; a global alert replacement would hide meaningful differences.
2. Add older-message pagination and an unread-message indicator/jump control. Initial chat reads currently show the latest 100 records; the in-memory cache is capped at 500. Polling is bounded and backs off on failure, but has no delivery/read receipts or server push.
3. Add structured list amendments after an order is created. Subsequent customer chat messages are conversation text; they do not automatically change priced items. Any amendment flow should invalidate the old quote and require customer approval of the revised total.
4. Improve modal keyboard focus management, labels on older forms, and very small-screen admin ticket detail layout. Visibility hiding is fixed; full focus trapping/restoration has not been added.
5. Support retry deduplication across refreshes would need persistent request state; current chat request UUIDs live in the open page. Support replies also need server-side request keys before they can offer the same lost-response guarantee.

No production deployment was performed. Real OTP delivery, concurrent production traffic, bank settlement and third-party store checkout remain outside this pass's simulated regression coverage.
