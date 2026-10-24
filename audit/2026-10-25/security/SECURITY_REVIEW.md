# Security hardening and recovery review

25 October 2026, Asia/Kolkata. Baseline: `b7e5e74`.

## Confirmed issues patched

| Finding | Patch | Evidence |
| --- | --- | --- |
| API throttled mutations only; reads and development token issuance could consume unbounded authentication/database work | Per-peer read/write/auth buckets (300/120/10 per minute), bounded tracking map, admission before body processing | Rate-limit regression tests, including forwarded-header spoof attempts |
| Slow request bodies could retain a connection indefinitely | 10-second mutation-body deadline, early Content-Length cap, streaming 64 KB limit, oversized Authorization rejection | Slow-stream, body/header and existing request-limit tests |
| API accepted arbitrary Host values | Explicit `ALLOWED_HOSTS`, localhost defaults, test-only test hosts, rejected global wildcard | Host-rebinding test; deployment instructions |
| Sensitive API responses lacked explicit cache/framing controls | no-store, nosniff, DENY framing and no-referrer headers | Auth failure/response header test |
| Development static server exposed arbitrary frontend-directory files and directory listings | Approved app files and asset types only; resolved path confinement; dotfiles/source/logs denied; localhost Host validation | Real HTTP test of public pages and blocked `.env`, Python, logs, JSON and directory paths |
| Hosting builder copied every asset and could leave old private files in a reused output | Approved asset types, source path confinement, reject unexpected/symlink output entries without deleting them | Hosting build and stale-private-file regression tests |
| Frontend lacked framing/base/object policy | Local and Firebase hosting headers: nosniff, DENY, strict referrer policy and CSP frame-ancestors/base-uri/object-src | Local HTTP test, source/config checks; Firebase changes are not deployed yet |
| Four installed runtime dependencies had known advisory entries | Updated project-local PyJWT, Pillow, urllib3 and certifi; raised requirement floors; shared system copies left alone | Before/after pip-audit JSON and exact installed package inventories |
| Code commits did not protect live customer data from deletion/corruption | Added consistent online SQLite snapshot command, integrity check, SHA-256 manifest, unique output names and Git-ignored local backup directory | WAL-aware backup/restore regression; actual private database snapshot verified |

Dependency audit initially reported 56 advisory entries across four packages (entries may overlap; this is not a claim of 56 exploitable app paths). Patched versions: PyJWT 2.15.1, Pillow 13.0.0, urllib3 2.8.0, certifi 2026.10.23. The **60-package runtime closure reports zero known vulnerabilities** at this check. Inventory is installed-version evidence, not a fully hashed supply-chain lock. Future vulnerabilities remain possible. Primary release sources: [PyJWT](https://pypi.org/project/PyJWT/2.15.1/), [Pillow](https://pypi.org/project/pillow/13.0.0/), [urllib3](https://pypi.org/project/urllib3/2.8.0/), [certifi](https://pypi.org/project/certifi/2026.10.23/).

## Host protections actually checked

`windows-protection.json` records the read-only effective policy/status inspection:

- Windows Firewall enabled for Domain, Private and Public profiles; effective default inbound Block/outbound Allow.
- SnapSave frontend port 3000 and backend port 8000 bound only to `127.0.0.1`, not LAN/public interfaces.
- Defender antivirus, real-time protection, behavior monitoring and tamper protection enabled. Official signature update requested; Defender retained signatures dated 24 October 22:01 IST after the update.
- Defender quick scan completed 25 October at 04:15 IST. No active threats were reported afterward. This is not a full forensic malware clearance.
- Controlled Folder Access is disabled. It was not blindly enabled, no broad Python/antivirus exclusions were added, and no inbound firewall ports were opened. Enforcing it requires testing database/runtime writers; blanket interpreter allowlisting would weaken its protection.

Windows Firewall is a host firewall, not a web application firewall. This inspection did not certify every machine-wide firewall exception, router, cloud ingress, DNS record or production hosting configuration. Public hosting needs separately configured TLS, ingress/WAF/rate limits and least-privilege service accounts. [Microsoft's ransomware guidance](https://support.microsoft.com/en-us/windows/security/protect-your-pc-from-ransomware) recommends controlled folder protection and recovery planning; [Controlled Folder Access documentation](https://learn.microsoft.com/en-us/defender-endpoint/controlled-folders) explains its host-level role.

## Data recovery and remaining work

The actual SQLite database was backed up into the Git-ignored `.private-backups` directory with integrity result `ok`; customer data and backup bytes were not uploaded to GitHub. The backup script does not encrypt snapshots. A tested local snapshot does not provide ransomware isolation because malware with the user's permissions may delete both copies.

The user connected removable drive D: and explicitly selected a new `D:/SnapSave-Backups` folder. A fresh database snapshot and manifest were created there. Its SHA-256 was independently verified, and it was restored to a disposable local database: integrity check `ok`, all 11 tables present. The disposable restore was removed afterward. Drive encryption was not established or changed; the snapshot itself is unencrypted and must be physically protected. Safely eject and disconnect the drive after copying to make this an offline recovery copy. No recurring backup job is configured. Credentials need a separate protected recovery plan; the script backs up SQLite only.

Current tracked files and the searched `.env`/Firebase service-account history paths contained no matching private-key material or tracked secret-file history. This limited check is not a comprehensive historical secret-scanner certification. Public Firebase web configuration is not treated as a server private key. GitHub/Firebase MFA, credential rotation and account permission changes were not performed.

The new read limits are per process and peer IP; reverse proxies can aggregate customers under one IP. Local launch now disables proxy-header trust. A public reverse proxy must replace untrusted forwarded headers and configure a shared identity/rate-limit policy deliberately. A stronger script CSP would require refactoring current inline scripts and validating Firebase/reCAPTCHA domains; the new policy does not claim to block all script injection. No system can guarantee immunity from hacking, malicious software, accidental deletion or new dependency vulnerabilities.

## Validation

- Full regression suite with patched dependencies: **171 passed**, one existing Starlette/httpx deprecation warning (`security-tests.xml`).
- Security tests exercise real static HTTP serving, role/auth-related limits, slow bodies, rebinding protection, build-output refusal and WAL snapshot/restore.
- Source checks: **113 Python files**, eight JavaScript scripts, valid hosting JSON (`source-verification/source-verification.json`).
- Advisory evidence: `dependency-audit.json`, `patched-dependency-audit.json`, `installed-runtime.txt`, `patched-runtime.txt`.
- Real localhost services were restarted with patched dependencies and local proxy-header trust disabled. Backend and admin page returned 200 with protection headers; an invalid Host returned 400; frontend Python source and `.env` requests returned 404. External-drive checksum/restore and HTTP evidence are in `live-security-checks.json`. Firebase hosting changes require deployment and were not published.
