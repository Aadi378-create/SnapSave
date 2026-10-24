# Follow-up error and security inspection

25 October 2026, India time. Baseline: `7467daa`.

## Confirmed findings and repairs

| Finding | Result |
| --- | --- |
| Blacklisted moderators could still read assigned customer orders/chats through shared authenticated routes | Shared staff authorization now rejects restricted accounts; private order fields are also removed from restricted staff's own customer views. Their own history and Support remain available. |
| Unexpected legacy role values implicitly passed the unscoped chat branch intended for administrators | Non-owner legacy chats explicitly require ADMIN; other roles fail closed. |
| Restricted or demoted workers could be selected or inherited from a customer's saved assignment | Both assignment routes reject restricted workers. New orders inherit only an active ADMIN/MODERATOR, otherwise entering the unassigned queue. |
| Two administrators could each observe another admin and concurrently demote both | Role changes serialize on the persistent application-setting row, refresh actor authorization after acquiring the lock, and protect the last unrestricted administrator. |
| Concurrent first-address creation could mark both addresses default | Address create/default/delete operations serialize on the owning account before reading/modifying defaults. |
| Default-address deletion committed before choosing its fallback | Deletion and deterministic fallback selection now commit together. Frozen order delivery snapshots stay unchanged. |
| Address validation accepted Unicode decimal digits or leading-zero postcodes that research could not use | Address input now requires six ASCII digits with a nonzero first digit, consistent with research validation. |
| Imported robots wildcards were compiled into potentially exponential regexes | Ordered literal searches handle `*`/end anchors without regex backtracking. Adversarial repeated-wildcard policies have regression coverage. |
| An extremely long numeric Content-Length could exceed Python integer conversion limits | The guard normalizes leading zeroes and checks digit length before converting a bounded value. This hardens ASGI handling; front-end HTTP parsers may already reject such malformed requests. |
| Structured item names were cleaned as though their numeric brand were a quantity | Structured names are preserved. Text-parsed prefixes must match the parsed quantity and token boundaries; `1x` and `×` are handled without truncating “xylitol.” |
| Unclaimed queue entries exposed addresses, phone numbers, payment data and internal prices to moderators before claiming | Unclaimed, non-owned moderator tickets retain queue context but omit precise delivery/contact/payment/internal-cost fields. Administrators and assigned staff retain authorized access. Staff buying as customers do not gain unassigned internal pricing fields. |
| The management page did not display the frozen delivery address | Added a safe text-only delivery panel for authorized ticket views and a claim-first placeholder for unclaimed moderators. The panel clears on session reset. The chat heading updates after a claim without double-escaping names. |

## Coverage and verification

Reviewed authentication and shared authorization paths, role/blacklist changes, order assignment and creation, address changes, quote/payment lifecycle and serialization, research imports/matching/robots handling, request boundaries, frontend rendering and the previously added static-hosting/backup controls. Existing role gates, idempotency, payment reference checks, order revisions, quote-expiry checks and human review controls were retained.

The full regression suite passed **193 tests**, with one existing Starlette/httpx deprecation warning (`tests.xml`). New cases include concurrent address creation and administrator demotion, restricted staff read/assignment checks, invalid postcodes, wildcard worst cases, malformed length headers, numeric grocery brands, queue redaction, and a browser claim-to-delivery-address flow with an HTML injection payload. Source checks passed for 114 Python files, eight JavaScript scripts and hosting JSON (`source-verification/source-verification.json`).

The installed 60-package runtime inventory was re-audited: **zero known dependency vulnerabilities reported** (`dependencies.json`). Development authentication and automatic research were verified disabled on the running local app. Windows Firewall/Defender status was rechecked without changing settings (`windows-status.json`). No new malware scan was necessary following the previously completed quick scan and no new malware evidence was established.

Tests use disposable databases and browser fixtures. Real customer records, paid orders and historical role/address data were not edited to create these reproductions. This pass does not claim to exhaust every possible error or certify an internet deployment against attack.

## Remaining limits and operational risks

- Public deployment still needs TLS, correctly configured ingress/WAF/shared rate limits, trusted proxy policy and least-privilege service accounts. Local firewall and loopback binding do not certify cloud configuration.
- Controlled Folder Access remains unenforced; backups on the external drive are not encrypted by the backup script. Keep that drive protected and disconnected when not backing up; no recurring private-data backup is scheduled.
- Existing active tickets assigned to a newly restricted/demoted worker may require administrator reassignment. This pass prevents new invalid assignments and blocks revoked access; it does not silently move existing paid/active work between staff.
- Existing inconsistent address/default data is not silently rewritten; the new API serialization prevents new concurrent-default races, and choosing a default resets that account's default selection.
- Natural-language input with a bare leading number can be ambiguous: use an explicit count such as `1x 7 Up 750 ml` for a numeric brand. Structured item input now preserves the name exactly.
- Moderators retain access to shared queue customer names/item lists and global aggregate dashboard metrics under the existing business permissions. Further minimization of those fields needs an explicit product permission policy.
- Legacy `unit_price` quote input remains a documented alias for total line cost; current clients should send `line_total`. Changing that legacy contract silently would break compatibility.
- Browser-assisted retailer captures remain unverified for exact-address serviceability, stock and checkout fees. Unattended retailer fetching still encounters access restrictions. These repairs do not turn the research engine into an automatic checkout system.
- One existing Starlette/httpx deprecation warning remains. No dependency or source audit can guarantee immunity from future vulnerabilities, account compromise or malicious software.
