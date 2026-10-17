# Focused code review follow-up

Reviewed the recent authentication/conversation changes and adjacent order, support and history code. Three confirmed bugs were fixed:

| Priority | Bug and consequence | Repair |
| --- | --- | --- |
| P1 | Support refresh captured the reply draft before awaiting the network, then replaced the entire conversation DOM. Text entered during that wait could disappear, together with input focus. Overlapping refreshes could render stale data. | Refresh only the message list for the currently rendered thread; preserve the live composer. Save drafts per thread, reject superseded responses and clear thread state on logout. |
| P2 | Order creation committed successfully, but a subsequent order-list refresh failure entered the submission-error handler. The customer could be encouraged to retry an order that already existed. | Separate successful submission from refresh failures in both chat and form-based ordering. Show the created order immediately and report that refresh is pending. |
| P2 | History offset advanced before the request succeeded. A failed request followed by Retry skipped 50 older records. Concurrent clicks could advance it multiple times. | Advance the offset only after success and guard overlapping pagination requests. |

Regression coverage deliberately delays a support response while typing, simulates a post-creation refresh failure and retries a failed history page. Tests use disposable databases and simulated external authentication; no real customer messages or orders were submitted.

The broader UI/communication proposals and limitations remain in LOGIN_AND_COMMUNICATION_REPORT.md. This was a focused regression review, not a claim that every production path is bug-free. Authentication reset during an in-flight verification and stale responses across a full sign-out/sign-in remain useful follow-up hardening areas; they were not changed in this limited pass.

**88 tests passed in 38.47 seconds**, with one upstream Starlette/HTTPX deprecation warning.

Verification evidence: code-review-results.xml and source-verification.json. Syntax checks cover 106 Python files and eight JavaScript scripts. Hosting JSON and Git whitespace checks passed.
