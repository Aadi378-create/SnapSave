# Customer follow-up sender identity

The screenshot is explained by an account with management privileges placing an order in the customer interface. Order creation explicitly records the initial list as CUSTOMER, but subsequent chat sends copied the account's ADMIN/MODERATOR role. The customer UI therefore rendered the same person's follow-ups as Concierge Specialist.

## Repairs

- Derive chat participation from the authenticated sender and conversation owner. Sending in one's own customer thread records CUSTOMER, regardless of management privileges. Replies from staff in another customer's thread retain their staff role. Clients cannot supply or override the sender role.
- Normalize historical own-thread ADMIN/MODERATOR text messages to CUSTOMER in the authorized message response. Existing messages display correctly on refresh in both interfaces without rewriting the database. AI, system messages, actionable quotes and other staff's replies retain their identity.
- Only genuine staff chat replies set first_response_at. An administrator or moderator writing as the customer no longer counts as the concierge's first response. Previously recorded timing data is not rewritten.
- Allow authenticated owners to read their own orders even when their account is a moderator. Staff assignment checks still apply to other people's orders. Own general conversations are also readable by moderators.

## Coverage

Regression cases exercise CUSTOMER, ADMIN and MODERATOR owners sending two follow-ups; management accounts reading their own order; unrelated customer denial; real staff identity and response timing; historical normalization without database mutation; and an admin using the actual customer UI seeing both follow-ups as You.

The fix changes backend semantics, so existing client markup does not need a cosmetic workaround. Tests use disposable databases and simulated Firebase identities; no real orders or messages are created. Existing metrics and stored messages are not migrated. Verification evidence is in sender-identity-results.xml and source-verification.json.

Final verification: **93 tests passed**, with one upstream Starlette/HTTPX deprecation warning. Syntax verification passed for 107 Python files and eight JavaScript scripts; hosting JSON and Git whitespace checks passed.
