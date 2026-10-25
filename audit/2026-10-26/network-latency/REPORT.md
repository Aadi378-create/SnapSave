# Network-wait repairs — 26 October 2026

## Result

**341 tests passed in 182.25 seconds, without warnings.** Customer and administrator pages restored their real Firebase sessions through supported Edge navigation after the backend restart. No customer messages/orders were created in the real database for this inspection; send/retry/race tests used disposable fixtures. Source validation parsed 134 Python files, eight JavaScript scripts and hosting JSON; whitespace checks passed.

The avoidable latency was primarily serial authenticated reads and extra token/message refreshes. The changes reduce those round trips while retaining fresh server-side Firebase revocation verification. Internet/provider latency itself remains observable.

## Changes

- **One customer workspace read:** `/api/customer/workspace` returns active summaries, optional history/addresses, the selected order when its revision changes, and conversation deltas. Customer startup no longer fetches addresses, lists, order details and chat through a chain of separate authenticated requests. Routine order/chat refresh uses one verification. Missing/deleted orders retain the previous recovery behavior; selecting a new draft does not reopen an old order.
- **Admin reads together:** ticket details and its initial chat are requested concurrently through the bounded read-batch endpoint. Queue/chat/help-count polling on the Orders view also runs together and can share a verification. Original role, claim and chat ownership rules are applied to each read. A stale ticket selection cannot render another selection's final details.
- **No fetch after successful chat sends:** the server returns its persisted message in `message_data`, including on idempotent replay. Both interfaces render that acknowledged record directly. They retain separate fetch cursors so an acknowledged outgoing message cannot advance past an earlier, not-yet-fetched incoming reply. A browser regression reproduces that interleaving and verifies the reply is recovered without duplicate outgoing messages.
- **No forced token refresh during customer restoration/sign-in:** use the SDK's normal token refresh behavior, with the existing client timeout, rather than force another identity-provider round trip. Firebase documents that normal `getIdToken()` refreshes expired or soon-expiring tokens ([official User API](https://firebase.google.com/docs/reference/js/auth.user.md)). Server verification still sets `check_revoked=True` on every authenticated HTTP request; database roles are read afresh. No server authentication/revocation cache or network-security bypass was added.

The workspace endpoint is strictly scoped to the authenticated account, even when the account is an administrator. Staff inspection of other customers continues through the staff APIs. The read batch still allows at most eight operations, reserves eight read-limit units and rejects mutations/unknown paths/unsupported parameters. New dynamic order/chat read patterns are bounded and call the existing authorization handlers. All legacy standalone API routes remain available.

## Measurements

### Controlled external-verification delay

`profile/controlled-latency.json` injects **80 ms per SDK verification** into a disposable local ASGI test. Three samples compare a serial active-list → order-detail → chat chain with the workspace read:

| Measurement | Previous chain | Workspace |
|---|---:|---:|
| Authenticated round trips / verification calls | 3 | 1 |
| Median elapsed time | 254.31 ms | 87.05 ms |

That is approximately **66% less waiting in this controlled test**. It demonstrates removal of serial overhead; it is not an ISP, Firebase availability or retailer-speed benchmark. Browser tests additionally verify one private workspace read during customer bootstrap, one batch containing admin ticket details/chat, and no extra GET after successful customer/staff chat acknowledgments.

### Real restored sessions

`live-timing.json` records sanitized handler-to-headers observations after restart:

- Customer workspace: **349.66 ms median**, 17 samples, **1,307.39 ms maximum**.
- Read batch: **345.19 ms median**, 15 samples, **1,639.62 ms maximum**.
- Initial `/api/auth/me`: **328.67 ms median**, two samples.
- Public status: **3.21 ms median**, 18 samples.

Each workspace/batch response covers multiple reads using one authentication check. Timings include database and Firebase work; they do not isolate the exact internet share. Other pre-existing browser tabs remained open, so this is an observational window rather than a controlled before/after live experiment. External spikes still exist; no zero-delay claim is supported.

### Rendering regression

The separate final workload still uses 500 orders, 50,000 items and 1,000 messages. It recorded **no browser tasks over 50 ms** on either page. Customer ready time was 430.00 ms and admin ticket opening 167.63 ms in this local mocked-Firebase run. Those single-run local numbers do not measure the removed internet round trips or establish a universal performance bound. Synthetic screenshots are saved under `profile/`; real customer screens and raw runtime logs are not committed.

## Security / verification

- New workspace and batch endpoints reject unauthenticated probes with 401 (`access-probes.json`).
- Tests reject another customer's workspace even for an administrator using this customer-only endpoint. Batched staff reads retain claim restrictions; customers/unassigned moderators cannot read another customer's details/chat or administrator help counts.
- Idempotent send replay, sender-role normalization, archived conversations, delayed navigation, logout races, missing records and concurrent message arrival remain covered by the full suite.
- Backend network/TLS settings, CAPTCHA/OTP, role policy and retailer-access controls were not weakened. The existing eight-second SDK request timeout and temporary-outage handling remain in effect.
- No schema reset, credential change or purchase was performed. Existing pages need one refresh to load the new JavaScript. Local backend remains bound to 127.0.0.1:8000 and frontend to 127.0.0.1:3000.

## Limits

Firebase, OTP/CAPTCHA and retailer services still need functioning internet. A provider outage, distance, congestion or blocked retailer access cannot be removed by combining local API reads. This pass reduces exposure to repeated waits; it does not establish retailer approval, fresh live prices or an unlimited capacity guarantee. Support inbox, payment and other less frequent standalone actions still authenticate when requested; no cross-request identity cache is used.

## Reproduction

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pytest -q
$env:SNAPSAVE_TEST_ARTIFACT_DIR='audit/2026-10-26/network-latency/recheck'
.venv/Scripts/python.exe -m pytest -q SnapSave-Backend/tests/test_network_latency.py
```

`full-tests.xml` is the final complete-suite result; `performance-tests.xml` records the separate post-suite benchmark. `focused-tests.xml` covers the seven targeted network regressions.
