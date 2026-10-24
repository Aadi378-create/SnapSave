# SnapSave identity, session and conversation audit

Date: 25 October 2026. Reviewed baseline: `48d1e05`.

**Five additional defects were reproduced.** Three have priority P1 because they can expose a stale session view or attach a customer's draft to the wrong order. Two are P2 recovery/operational defects. This is an audit report; application code has not been changed in this pass.

## Confirmed findings

### A01 — P1: Firebase sign-out does not clear the customer screen

Source: [index.html:1165](../../SnapSave-FRONTEND/index.html#L1165), especially the null-user branch at [line 1178](../../SnapSave-FRONTEND/index.html#L1178).

When Firebase reports `user === null`, the handler only attempts saved-token restoration when there is no current user. It does not clear an already logged-in user's dashboard, cached orders or profile. The management page also lacks an equivalent auth-state subscription; its cross-page sign-out behavior needs the same treatment.

Reproduction: sign in through the customer phone/OTP UI in the simulated Firebase environment; emit SDK sign-out directly, representing a sign-out from another page; observe that the customer dashboard remains visible and the sign-in screen stays hidden. Probe `test_a01_external_signout_leaves_customer_dashboard_visible` passed by reproducing this defect.

Impact: customer information can remain visible on the device after an external sign-out. **This is a UI/session-cleanup defect, not evidence that an unauthenticated request bypasses backend authorization.**

Recommendation: centralize session teardown, subscribe both interfaces to auth changes, clear private caches and dialogs, and keep real Firebase sessions distinct from explicitly enabled development-token restoration.

### A02 — P1: Polling silently changes the order underneath a draft

Source: [index.html:1540](../../SnapSave-FRONTEND/index.html#L1540); send target captured in `handleSendChat`.

Unless a history order or new-order draft was explicitly selected, `loadOrders()` replaces the current order with `active[0]` on each refresh. The composer text is not bound to the order for which it was typed.

Reproduction: open order A, type a clarification without sending, create order B for the same customer in a separate fixture API action, wait for the normal eight-second poll, then send the original clarification. The stored message belongs to B. Probe `test_a02_background_poll_moves_draft_to_new_order` reproduced the wrong-order association.

Impact: notes, substitutions or payment explanations intended for one order can reach a different order's conversation and concierge.

Recommendation: pin the selected conversation ID until explicit navigation, store drafts per order, and never silently retarget a non-empty composer. Keep terminal-order transitions explicit too.

### A03 — P1: A late session check can reopen the dashboard after logout

Source: [customer checkUserSession:1230](../../SnapSave-FRONTEND/index.html#L1230), [customer startDashboard:1263](../../SnapSave-FRONTEND/index.html#L1263). The management equivalents at [admin.html:2112](../../SnapSave-FRONTEND/admin.html#L2112) have the same missing session-generation guard.

Session checks assign `currentUser` and open the dashboard after awaiting `/api/auth/me`, without verifying that the login session is still the one that issued the request.

Reproduction: delay a customer session-check response, log out, verify the dashboard is hidden, then release the old response. The dashboard becomes visible again. The probe triggers the shared session-check path using the development helper in an isolated fixture; the production OTP callback uses that same function. Probe `test_a03_late_session_response_reopens_customer_after_logout` reproduced the stale UI restoration.

Impact: a completed logout can be visually undone by an earlier asynchronous request. Similar account-switch contamination is a risk, but switching between two real Firebase accounts was not tested here. This probe establishes stale UI restoration, not server-side reauthentication after Firebase sign-out.

Recommendation: increment a session-generation token on logout and account changes, capture it before requests and discard obsolete responses. Abort pending requests and validate the session again after each awaited dashboard initialization step.

### A04 — P2: Login reset is silently ignored during verification

Source: [phone-login.js:95](../../SnapSave-FRONTEND/phone-login.js#L95), [reset at line 121](../../SnapSave-FRONTEND/phone-login.js#L121).

`verifyCode()` keeps `busy = true` while invoking the integration's `verified()` callback. `reset()` immediately returns when busy. Session-check failures can call logout/reset from inside that callback, so the reset request is lost.

Reproduction: use the actual shared controller with a simulated verification adapter whose `verified()` callback calls `reset()`. Verification finishes, but the OTP form remains visible instead of returning to the phone step. Probe `test_a04_login_reset_is_ignored_during_verified_callback` reproduced the ignored reset.

Impact: after backend session rejection or failure, the returned sign-in view can retain the previous OTP step and confirmation state. The user can change the number manually, but recovery is misleading.

Recommendation: defer a requested reset until verification's `finally`, or invalidate/cancel the current attempt and reset safely. Keep CAPTCHA epoch checks to reject obsolete verifier callbacks.

### A05 — P2: Help Inbox hides threads beyond page one and undercounts open requests

Sources: [server.py:733](../../SnapSave-Backend/api/server.py#L733), [admin.html:2441](../../SnapSave-FRONTEND/admin.html#L2441), [admin.html:2455](../../SnapSave-FRONTEND/admin.html#L2455).

The API paginates help threads with a default limit of 50. Both inbox loading and the badge request only the default page. The inbox offers no page-navigation control, and the badge counts only returned rows.

Reproduction: seed 51 distinct open help threads in the disposable database. The default API returns 50, `offset=50` returns the remaining thread, the UI lists 50, and its badge reports 50. Probe `test_a05_inbox_hides_threads_after_first_fifty` confirmed the cutoff.

Impact: older open requests are inaccessible through the current inbox until the first page changes, and administrators underestimate the backlog.

Recommendation: add inbox pagination or a load-more control, preserve selection across pages, and return a separate total-open count independent of the current page.

## Checks that did not establish another bug

- Archived staff conversations: `selectTicket()` briefly enables the composer, but `renderTicketDetails()` applies the final permission/status check. The cancelled-order probe confirmed disabled input/send controls and backend HTTP 409. It is not listed as a confirmed writable-chat defect.
- Previous sender identity repair: five existing regressions were rerun separately, covering customer/admin/moderator owners, legacy message normalization, actual staff replies, response timing and the customer UI.
- Support uses a fixed customer role on its customer endpoint and an admin role on its management endpoint; the original global-role chat bug does not directly recur there.
- No new backend authentication bypass was established by these probes.

## Evidence and limits

Verification: **all six observational probes passed** (five defect reproductions and one archived-chat control), and **all five existing sender regressions passed**. One upstream Starlette/HTTPX deprecation warning remains. Git whitespace checks passed.

The six observational probes comprise five defect reproductions and one archived-chat control. **A passing observational probe means the defect was reproduced, not fixed.** They live outside the normal application test suite in [test_observational_probes.py](test_observational_probes.py), with output in [observational-results.xml](observational-results.xml). The sender regression results are recorded separately in [sender-regression-results.xml](sender-regression-results.xml).

All probes use disposable SQLite databases, simulated identities and intercepted external browser requests. No live Firebase sign-in, SMS, customer message, production order or bank action was submitted. Source review covered both frontends, the shared phone controller and relevant backend policy/chat/support endpoints. It does not certify every project path, production concurrency, real account switching, store integrations or deployment behavior.

To rerun the audit probes from `SnapSave-Backend`:

```powershell
../.venv/Scripts/python.exe -m pytest -p tests.conftest ../audit/2026-10-25/test_observational_probes.py -q
```

Recommended repair order: A01 and A03 together using shared session invalidation; A02 next to prevent wrong-order messages; then A04 and A05. Additional earlier UI proposals remain in the 17 October communication report. This pass intentionally documents findings without implementing those repairs.
