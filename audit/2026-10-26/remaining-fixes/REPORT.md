# Remaining-issue repairs — 26 October 2026

## Outcome

**334 isolated tests passed in 159.26 seconds, without warnings.** The final source parses cleanly (133 Python files, eight JavaScript scripts and hosting JSON); whitespace checks passed. Backend and frontend were restarted on 127.0.0.1, and real Firebase customer/admin sessions restored successfully. No orders or customer records were reset, and no retailer purchase, message, cart or new account connection was made.

The code defects and recovery gaps identified in the previous inspection were repaired. This does not establish zero latency, unlimited SQLite capacity, malware immunity or retailer permission. Those distinctions matter because the prior report included external dependencies and deployment limits alongside code defects.

## Changes and evidence

| Previous finding | Repair / verified state |
|---|---|
| Large admin ticket render produced >50 ms tasks. | Product editors and chat messages render in batches of 20, yielding between batches. Generation/session guards cancel stale rendering after selection changes. Offscreen editors defer layout/paint; subtotal calculation no longer repeats a document query for every item. Quote preview is disabled while editors are incomplete. Final large-workload profile recorded no tasks over 50 ms in either page. |
| Repeated authenticated requests added external work. | A strict `/api/read-batch` allowlist combines simultaneous configuration or workspace GETs into at most eight read operations. One Firebase verification is reused only inside that HTTP request; no identity/revocation/response cache is introduced. Each operation still checks its original role and ownership rules. Configuration batches remain separate from the operational queue, avoiding a settings dependency. Batches reserve eight read-limit units and retain the body/time/Host/CORS limits. Tests verify one SDK call with `check_revoked=True`, role rejection, malformed inputs and mutation/URL forwarding rejection. |
| Authentication stalls / outages. | Firebase Admin's per-network-request HTTP timeout is eight seconds instead of its long SDK default. Transient certificate/network/service failures return retriable 503; invalid credentials remain 401. Client SDK loading/readiness has a 15-second timeout, and both logins show a retry action. Temporary session-check failures hide private views without globally signing out the Firebase account. This is a failure bound, not an eight-second end-to-end login SLA: SDK/network retries may add time. |
| In-memory research jobs disappeared across restarts. | `research_jobs` persists work intent. New automatic orders save it atomically with the order. A scheduler recovers missing intents and expired leases, with two execution slots per process. Full workers leave work queued. Claims are atomic, leases last 120 seconds and renew every 20 seconds; three interrupted execution attempts are allowed before takeover. Lease owner and order revision are checked in final AI writes and failure handoffs, so stale work cannot publish or take over a newer generation. Providers remain read-only; blocked data is not retried to bypass restrictions. |
| Offset pages skipped records when earlier rows changed. | Customer history uses descending timestamp/ID `before` cursors; the admin queue uses ascending `after` cursors and a previous-page cursor stack. Composite indexes support the reads. Scope checks reject inappropriate/malformed cursors; user/role filters still apply. Deleting an earlier row, changing its status or inserting a newer order no longer shifts the next-page offset. Legacy offset arguments remain for API compatibility. |
| Fonts/icons depended on render-blocking CDNs. | Existing Font Awesome 6.4.0 and Google Fonts assets are served locally. Vendor source URLs/hashes and licenses are retained. Hosting and the development server expose only the specific public license files, without allowing arbitrary text/JSON files. Firebase and OTP/CAPTCHA remain online services with explicit failure feedback. |
| Backup recovery was not recently exercised. | A fresh consistent snapshot was created in the previously authorized `D:/SnapSave-Backups`. Its SHA-256 was verified, then restored into a temporary database; integrity and foreign-key checks passed. `verify_backup.py` provides a bounded disposable restore check without replacing application data. Backup contents and private manifests remain outside Git. |
| Test transport emitted a deprecation warning. | Development requirements include `httpx2`; the installed supported transport is 2.16.0. The complete suite now emits no warnings. [Starlette's official TestClient guidance](https://starlette.dev/testclient/) recommends this transport. |

Cursor tokens are opaque positioning data, not authorization credentials or signed snapshots. Changing filters/refreshing the first page can reveal newly eligible records; records that stop matching between pages naturally disappear. This is stable traversal, not transaction-wide snapshot isolation.

## Performance evidence

The workload contains **500 orders, 50,000 items and 1,000 messages**. Five-sample API timings include the local test client and test authentication; browser observations are one-run samples. Production Firebase and retailer latency are excluded from this synthetic workload.

| Final measurement | Observation |
|---|---:|
| Customer summary-history request median / worst of five | 4.87 / 7.80 ms |
| Summary-history payload, including per-row cursor | 12,451 bytes |
| Legacy full-history payload | 666,951 bytes |
| Admin queue request median / worst of five | 11.64 / 14.73 ms |
| Admin metrics request median / worst of five | 11.08 / 19.00 ms |
| Customer browser ready / eight-character typing operation | 408.56 / 26.93 ms |
| Admin browser ready / opening 100-item ticket with 100 loaded messages | 277.82 / 148.63 ms |
| Browser tasks over 50 ms, customer / admin | 0 / 0 observed |
| 20 parallel synthetic read batches, eight client threads | 29.75 ms median, 48.67 ms maximum |

The fresh pre-chunking run in `baseline/profile.json` recorded a 73 ms admin task after ticket selection. The intermediate chunked run in `after/profile.json` and the finished asset-inclusive run in `final-profile/profile.json` recorded none. Font assets changed between baseline and final runs, so these are not controlled percent-improvement estimates. Cursor strings increase summary payload size compared with the prior 7,951-byte projection, while remaining approximately 98.1% smaller than full history. No percentile or zero-jank guarantee is inferred from a small sample.

The concurrent-read check used 20 requests alternating two disposable customers and verified their histories remained isolated. This exercises local concurrent reads; it is not a production capacity or high-contention write benchmark.

### Real sessions

Supported Edge navigation verified the real administrator queue and customer dashboard after restart. Successful `/api/read-batch` samples had a **393.64 ms median** (three observations); a six-operation settings group now uses one Firebase check rather than six. The request timing includes authentication and database work; it is not a pure Firebase measurement. Live history still had a **1,647 ms maximum**, and initial authentication had a **1,076 ms maximum** in this window. External latency/outliers therefore remain; the repairs reduce redundant work and bound/report failures rather than claim it has disappeared. Raw runtime logs and real customer screens were not committed.

## Security and recovery checks

- All **14 runtime probes passed**: authenticated data remains protected, read batches require authentication and reject GET, Host/CORS checks reject untrusted origins, private environment/database/source paths return 404, and local fonts/icons/licenses return 200. Defensive response headers and disabled development auth were verified.
- Installed dependency advisory scan: **91 packages, zero known advisories** at the time of this scan. The sanitized result is in `dependencies.json`; the raw audit is private. Unknown vulnerabilities are outside this assurance.
- Windows firewall profiles and Defender antivirus, real-time, behavior and download protections remained enabled. Services listen only on 127.0.0.1. No public port or security exemption was added.
- D: backup checksum, disposable restoration, integrity and foreign keys passed (`backup-check.json`). The USB remains attached; it is not physically isolated from ransomware while connected. This pass did not encrypt the entire drive, alter unrelated drive data or run a full malware scan.
- The schema addition creates the job table and cursor indexes without deleting application data. Existing order/payment data and authentication/administrator configuration remain intact.

## External / deployment requirements that remain

1. **Retailer access:** this pass did not establish an approved, connected live price source. The prior Swiggy attempt was rejected for missing client allowlisting; official provider approval/feed access is still a prerequisite to activating that route. Prior 202/403 storefront failures are not prices. No challenge bypass, client impersonation, fabricated price or unsupported live-automation success is claimed. Existing permitted order-triggered research still hands off when evidence is blocked or unverifiable.
2. **Network and device performance:** Firebase verification, OTP/CAPTCHA and retailer services need working internet. The local workload passed without >50 ms tasks, but real authenticated requests still showed outliers. Those cannot be guaranteed away by local code.
3. **Public deployment / scale:** localhost remains the supported running environment. No deployment hostname, production database or reverse proxy was supplied or exposed. The durable queue now protects job intent and claims, but SQLite write serialization and per-process limits/caches still require production capacity testing and shared infrastructure before scaling. Test claims cover competing database-backed workers, not a multi-host production deployment.
4. **Provider contract:** lease fencing prevents stale writes, but Python threads cannot forcibly terminate an arbitrary hanging custom provider. The built-in HTTP provider already enforces request/time budgets; any added provider must do likewise or run in an isolated worker process. At-least-once recovery can repeat a read request after a crash; it is not exactly-once external execution.
5. **Host recovery:** verified snapshots do not make a connected USB immune to malware. Full host malware diagnosis, drive-wide encryption, public infrastructure changes and independent penetration testing are separate operations; no evidence from this bounded inspection certifies their outcomes.

## Reproduction

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pytest -q
$env:SNAPSAVE_TEST_ARTIFACT_DIR='audit/2026-10-26/remaining-fixes/recheck'
$env:SNAPSAVE_PROFILE_LABEL='profile'
.venv/Scripts/python.exe -m pytest -q SnapSave-Backend/tests/test_large_inspection.py SnapSave-Backend/tests/test_remaining_issues.py -k 'large_workload_profile or parallel_reads_keep_customer_isolation'
```

`full-tests.xml` is the final complete result; `performance-tests.xml` records the separate post-suite measurement. Earlier focused/render XML files are intermediate checks. Screenshots in this directory contain synthetic identities and product/chat fixtures. Refresh existing open pages once to load the new JavaScript; restored sessions do not require another OTP when Firebase remains valid.
