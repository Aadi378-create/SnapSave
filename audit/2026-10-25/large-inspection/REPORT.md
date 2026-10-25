# Full regression and performance inspection — 25 October 2026

## Result

This inspection reproduced and repaired customer history overhead, a history-navigation race, excess dashboard queries, moderator financial-data exposure, silent queue failures and serial administrator startup. The backend was restarted on loopback and real customer/admin Firebase sessions restored successfully. Application data was not reset or seeded; load tests used an isolated disposable database.

This is a bounded inspection, not a guarantee that every possible defect has been found or that all latency is eliminated. Remaining measured latency and operational limits are listed below.

## Issues found and changes

| Priority | Issue | Resolution |
|---|---|---|
| High | Moderator dashboard APIs returned global revenue/profit and financial averages although the moderator UI did not need them. | Moderator metrics now return scoped operational counts; beta financial averages are null and display “Admin only.” Regression tests cover both roles. |
| High | Switching history while a detail request was pending could leave the composer associated with an unresolved order. Background refresh could supersede navigation. | Block sending while switching, guard request/session versions, cancel pending navigation on New Order, preserve drafts and recover from deleted-order 404s. Tests delay requests and delete an archived fixture. |
| High performance | Customer history fetched full item arrays and large internal order columns just to draw history rows. The 50-row sample was 666,951 bytes. | Optional summary projection selects only six order fields; customer history/active polling uses it and fetches full details only for the selected order when needed. Full legacy API behavior remains available. |
| High performance | Admin awaited six settings/assignment calls serially before starting queue requests. Live authenticated requests commonly took about 330 ms each. | Settings requests now run concurrently and no longer block queue startup. Controls remain disabled until settings arrive; failures are visible and Settings navigation retries. A delayed-settings browser test proves the queue loads independently. |
| Medium performance | Main admin metric refresh performed 15 SELECT statements. Beta metrics also issued repeated aggregate queries. | Conditional SQL aggregation reduces each endpoint to three SELECTs including authentication. Financial filtering and role restrictions remain enforced. |
| Medium | Queue fetch failures were swallowed, leaving stale cards without feedback and preventing the polling backoff from seeing failure. | Retain loaded cards, show refresh failure, propagate failure to the existing single-flight backoff, and clear feedback after recovery. Offline/recovery regression included. |
| Medium performance | Every message created a separate locale time formatter; admin appended each bubble individually. | Reuse one Intl formatter and batch admin message DOM insertion with a fragment. |
| Diagnostic gap | No optional backend request-duration evidence for the real Firebase path. | Add opt-in route-template timing logs and Server-Timing. Logs omit IDs, queries, tokens and bodies; default is disabled. Regression verifies credential/ID exclusion. |

The pre-existing research browser test also needed a null-safe wait for its asynchronously created panel. It now waits for panel text without throwing during the loading state; its final content assertions remain unchanged.

## Measurements

`before.json` and `after.json` use **500 orders, 50,000 items and 1,000 messages**, including 50 active orders with large internal draft fields. API timings are median and worst of five samples. Browser numbers are single-run observations, not percentile estimates. Firebase/external assets are mocked in this synthetic benchmark; these values do not represent internet or retailer response time.

| Measurement | Before | After history/render changes |
|---|---:|---:|
| 50-row customer history bytes | 666,951 | 7,951 (98.8% smaller) |
| Customer history median request | 155.82 ms | 10.55 ms |
| Customer history worst of five | 206.04 ms | 11.78 ms |
| Admin dashboard SELECT count, including auth | 15 | 3 |
| Admin metrics median / worst of five | 7.95 / 38.44 ms | 11.16 / 18.35 ms |
| Customer browser ready | 800.25 ms | 390.40 ms |
| Eight-character typing operation | 60.35 ms | 28.98 ms |
| Admin ticket open, 100 items and loaded chat | 160.22 ms | 137.92 ms |
| Admin browser ready | 359.06 ms | 377.96 ms |
| Observed admin long task | 64 ms | 58 ms |

These recorded browser measurements precede the final removal of the serial settings dependency. They show no uniform admin startup speedup: the ~19 ms difference is within an uncontrolled single-run sample, and a 58 ms task remains. The deterministic delayed-settings regression verifies the final dependency fix separately. Default full-history API still costs about 156 ms because it deliberately returns all item arrays; the customer UI now uses the summary route.

### Real runtime

`live-timing.json` aggregates successful GET handler-to-headers observations from real restored Firebase sessions after restart. It includes authentication and concurrent local test activity; it is not an isolated authentication microbenchmark. Typical customer history/admin queue medians were approximately **351/341 ms**; the queue had a **2,247 ms maximum**. Many unrelated authenticated routes clustered around 320–395 ms while public status was about 3 ms. This suggests external authentication/network work is significant, but the logs do not isolate its exact share. Firebase revocation validation was retained.

Parallel startup removes avoidable sequential waiting; it cannot make external services instantaneous. The optional timing flag is enabled only in the current backend process for local lag diagnosis. It is false by default in `.env.example`; a normal restart without that process environment returns it to disabled. Raw runtime logs remain private and are not committed.

## Remaining issues and limits

1. **Performance acceptance remains open:** the synthetic admin run still produced a 58 ms long task and live requests had occasional >1 second outliers. Further profiling should identify the exact main-thread phase before adding incremental rendering or virtualization. Large-ticket rendering is bounded by current message pagination but 100 product editors still create substantial DOM. No “zero lag” claim is supported.
2. **Retailer live-price access remains blocked:** previous public requests returned 202/403 or response-budget failures; the official Swiggy route still requires client allowlisting. No new live-price or account connection success was established in this inspection. Blocked data is not a verified quote, and prices must not be invented. Human takeover remains the failure path.
3. **Single-host resilience:** SQLite and the in-process research executor remain development-scale components. A crash/restart can interrupt in-memory work; multiple processes and high write contention require a durable job queue, recovery policy and a deployment database/load test before scale-out. The 500-order fixture does not prove concurrent-user capacity.
4. **Offset pagination under changing data:** inserting/changing orders between pages can shift offsets. Existing ID merging reduces duplicates, but stable cursor pagination is preferable for heavy concurrent traffic; no concurrency benchmark of that condition was performed here.
5. **External frontend dependencies:** Firebase SDK and hosted font/icon assets still depend on network availability. Browser fixture tests replace those assets and cannot establish offline or slow-network login performance.
6. **Authentication and deployment limits:** local services remain loopback-only. Public deployment needs the documented HTTPS/proxy/allowed-origin configuration, operational monitoring and an independent exposure review. Development authentication remains disabled.
7. **Security assurance limits:** enabled firewall/Defender is not a malware scan or an audit of every firewall rule. Dependency advisories do not detect unknown vulnerabilities. No new offline backup/restore or power-loss test was performed in this pass; existing private backup procedures still apply.
8. **Toolchain maintenance:** the suite reports a Starlette/httpx TestClient deprecation warning. It does not fail current tests; migrate the test transport in a separate compatible dependency update.

## Security verification

Fresh `runtime-checks.json` passed all ten probes: status, development-auth disabled, defensive headers, unauthenticated order/admin rejection, private environment/database/source denial, bad Host and bad CORS rejection. `host-security.json` confirms all Windows firewall profiles enabled; Defender antivirus, real-time, behavior and download protection enabled; API/frontend bound only to 127.0.0.1.

The earlier same-day dependency audit covered 88 installed dependencies with zero known advisories (`../security-diagnostics/dependencies.json`). No dependency changed in this pass; this result was reused, not represented as a new external advisory scan. No private databases, .env, service-account files, cookies, OAuth credentials, real customer screenshots or raw runtime logs are included in this commit.

## Validation and reproduction

Final complete suite: **310 passed**, one TestClient deprecation warning, in 143.72 seconds; recorded in `full-tests.xml`. Focused race/role/offline/startup regressions are in `regression-tests.xml`; `reproduction.xml` retains synthetic pre-fix failures. Source verification parsed 130 Python files and eight JavaScript scripts and validated hosting JSON; `git diff --check` passed.

Run from the repository root:

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pytest -q
$env:SNAPSAVE_TEST_ARTIFACT_DIR='audit/2026-10-25/large-inspection/recheck'
$env:SNAPSAVE_PROFILE_LABEL='recheck'
.venv/Scripts/python.exe -m pytest -q SnapSave-Backend/tests/test_large_inspection.py -k large_workload_profile
```

The screenshots in this directory contain synthetic fixture data. Their external fonts/icons are intentionally stubbed by the test harness; they verify structure and load behavior rather than production asset rendering. Real customer/admin dashboard restoration was checked separately through the supported Edge browser tools without sending messages, placing orders, changing customer records or transmitting addresses to retailers.
