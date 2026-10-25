# Security and diagnostics review — 25 October 2026

## Result and scope

Local runtime, request/access controls, installed dependency advisories, Windows protection status, tracked secret-file patterns and the newly added Swiggy OAuth code were inspected. The app remained available during the checks. No account was authorized, no customer records were reset, and no purchase, cart operation or provider application was submitted.

No working unattended retailer-access workaround was established. Swiggy's live authorization page rejects the local client as not whitelisted; its access guide requires redirect allowlisting before staging, with separate production approval: https://mcp.swiggy.com/builders/docs/operate/access/. The prepared official client remains disconnected and is not activated as an order provider. Existing blocked storefront responses are not live prices. The prior unsent access-request draft is available under `../supported-retailer-route/`.

## Reproduced and patched

1. **OAuth response buffering before the cap.** The helper checked `len(response.content)` after Requests had already downloaded the body. It now streams authorization responses, enforces a 100 KB limit before extending its buffer, uses connection/read timeouts and checks elapsed time. Invalid JSON is rejected with a sanitized error, and temporary/429 failures are no longer classified as a reason to repeat account authorization.
2. **Malformed token values.** Control characters in access tokens and unbounded refresh-token strings were accepted by the token-record constructor. Access/refresh values now require bounded printable ASCII before storage or header construction. Decrypted credential files also undergo schema/type/finite-expiry validation; corrupt state requires reconnecting instead of being trusted. Credential files remain protected with Windows DPAPI.
3. **Local callback Host/origin hardening.** The OAuth callback already required random state and PKCE; a fake callback with a known valid test state nevertheless accepted an arbitrary Host header. The helper now restricts Host and Origin, bounds query/path/code input, rejects non-ASCII state safely, compares state in constant time, sets defensive response headers and limits socket-read time. This is defense in depth; the reproduction does not demonstrate an attacker obtaining the secret state or taking over a real account.
4. **Safe root test collection.** A repository-root pytest configuration now selects only the disposable-database suite. Previously, running from the root could import archived scraper scripts outside the backend test configuration. Root collection now selects exactly 301 tests, avoiding that accidental collection path.

`reproduction.xml` and `callback-reproduction.xml` preserve synthetic reproductions. The first callback reproduction was affected by localhost DNS timing; the direct-loopback reproduction confirmed the missing Host check independently. No real token or customer data appears in these fixtures.

## Verified local protections

At approximately **21:55 IST**:

- API and frontend listeners were bound to **127.0.0.1** on ports 8000 and 3000. The temporary OAuth port 8765 was not listening.
- Windows Domain, Private and Public firewall profiles were enabled. Defender antivirus, real-time, behavior and downloaded-file protections were enabled; signatures were updated earlier on 25 October. No protection was disabled or new antivirus exclusion added.
- API status returned 200, with development authentication disabled. Responses carried no-store, nosniff and DENY framing headers.
- Unauthenticated order and administrator-metric requests returned 401. Private environment, backend database and frontend Python-source probes returned 404. These probes checked status/headers without printing private response bodies.
- An untrusted Host and an untrusted CORS origin were rejected with 400. Existing rate/body/time limits, role isolation, Firebase revocation checking and text-safe rendering remain covered by regression tests.
- The tracked-name scan found no tracked environment/database/service-account/private-backup files matching its patterns. A separate bounded tracked-source scan found no obvious private-key, GitHub PAT or API-secret patterns. Pattern scans are not a proof that every possible secret is absent.

Evidence is in `host-security.json` and `runtime-checks.json`. These checks verify the inspected state; firewall/Defender enabled status is not a full firewall-rule audit or a malware scan.

## Dependencies and tests

The current installed virtual environment audit checked **88 dependencies** and reported **zero known advisories** at the time of the check (`dependencies.json`). This is version-specific and does not certify absence of unknown vulnerabilities. No dependency downgrade or security-control weakening was introduced.

Focused OAuth/security tests passed 31 cases before the final non-ASCII-state guard. The complete isolated run passed **301 tests**, with one existing Starlette/httpx deprecation warning (`full-tests.xml`). Source validation passed for 129 Python files, eight application JavaScript scripts and hosting JSON; `git diff --check` passed. All authenticated automated flows use disposable SQLite databases and synthetic credentials, not the live customer database.

## Remaining constraints

- Retailer authentication/allowlisting remains unresolved; no successful live product-price result was obtained. A proposed approach from another developer should be checked against documented access, location/price correctness, credential handling, rate limits and reproducibility before integration. Do not paste account tokens or cookies into chat or source control.
- Swiggy's upstream OAuth scope is broader than product search; the app's allowlist prevents cart/order/address tools, but a future real account consent must still disclose the upstream scope. No such account is connected now.
- This is a local development setup. Public deployment needs its own HTTPS ingress, exact trusted proxy/origin configuration, shared rate/queue infrastructure and capacity testing. Current in-process guards are not a substitute for an internet-facing edge configuration.
- Existing private snapshots and source commits provide recovery material, but this review did not verify external/offline backup freshness or perform a malware scan. A program cannot guarantee survival of malware running as its Windows user; DPAPI does not isolate secrets from every process running under the same user.

No claim of a hack-proof app, completed penetration test or fully working retailer scraper is made.
