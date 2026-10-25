# Supported retailer route — 25 October 2026

The screenshot shows the existing public-HTML request route failing. A cooldown prevents repeated requests; it cannot repair access restrictions. Repeating the same failed URLs or hiding those errors is not a working pricing solution.

## Official Instamart alternative found

Swiggy publishes an official Instamart MCP endpoint at `https://mcp.swiggy.com/im`. Its documented `search_products` tool accepts a product query and guest coordinates and returns product families, pack variations, offer prices and stock fields. OAuth is required even for this guest-location search. The docs describe self-serve localhost development through OAuth with PKCE and Dynamic Client Registration; production access has separate onboarding requirements.

A bounded live check confirmed HTTP 200 from the documented OAuth and protected-resource metadata endpoints and HTTP 401 with an OAuth challenge from the Instamart initialization endpoint. This establishes an accessible official authentication route, not successful product data yet. No customer address, account token, retailer cart, order or payment was submitted. The check is recorded in `endpoint-check.json`.

Primary sources:

- https://mcp.swiggy.com/builders/docs/reference/instamart/search_products/
- https://mcp.swiggy.com/builders/docs/start/authenticate/
- https://mcp.swiggy.com/builders/docs/start/developer/
- https://modelcontextprotocol.io/specification/2025-03-26/basic/transports

## Prepared implementation

`core/swiggy_mcp.py` implements a bounded, fixed-origin product-search-only client with JSON/SSE handling, MCP session initialization, request-ID matching, protocol/session headers, token refresh and no redirects. Its public tool interface rejects cart, checkout, order and address tools before loading credentials. Search requires explicit valid guest coordinates; it never substitutes an arbitrary customer location or invents a saved address ID.

`connect_swiggy.py` prepares a one-time official OAuth flow using PKCE and random callback state on a loopback-only server. The callback does not log authorization codes. Access and rotating refresh tokens are encrypted using Windows DPAPI for the current user, under the ignored `.private-backups` directory. No account has been authorized by this implementation or its tests.

The no-authorization `--prepare` check passed. Focused tests cover Windows encryption, callback state/PKCE, forbidden tool rejection, input validation, raw variant/price preservation, JSON/SSE responses, returning after a completed event rather than waiting for an endless stream, token metadata and session reuse. OAuth tests use fake tokens and an isolated localhost callback; they do not log in to Swiggy.

Swiggy's scope is broad (`mcp:tools`), not a read/write-split grant. It can include account cart/order capabilities at the upstream account level, even though this SnapSave client permits only product search. The user was explicitly asked before opening account authorization. No consent has been assumed from silence.

## What remains before engine activation

The official client is prepared, **not yet activated in the order worker**. A user-approved Swiggy connection and a successful search at verified coordinates are required next. A real response must be inspected for selling-price units, exact packs, stock and location before mapping it into SnapSave evidence. Search prices are not checkout totals; no missing fee is treated as zero and no raw response is labelled a verified customer quote.

Zepto, Blinkit and BigBasket are not solved by this Instamart integration. No equivalent supported product-search route was established for them during this inspection. No anti-bot bypass, session spoofing or private API replay was added. The prior blocked HTTP provider remains in use until a supported replacement is validated.

## Diagnostics cleanup and validation

Repeated source errors are deduplicated across basket items and in the staff display. Automatic failures with zero candidates no longer repeat a second catalogue-verification heading and empty item instructions. These presentation changes do not turn failure into success.

The focused client checks passed **18 tests**. The complete isolated regression suite passed **297 tests**, with one existing Starlette/httpx deprecation warning (`full-tests.xml`). Source validation passed for 128 Python files, eight application JavaScript scripts and hosting JSON. An initial full-suite command from the repository root picked up archived scraper scripts outside the configured test suite; it failed during collection. The full regression command was corrected to run from `SnapSave-Backend`, where `pytest.ini` restricts collection to the isolated `tests` directory. No archived scraper request succeeded or database reset was performed in this turn.


## Live sign-in attempt after owner approval

The owner approved opening the official Swiggy sign-in. The helper completed documented public client registration and opened the authorization URL using its own random state and PKCE challenge. A transient DNS failure delayed loading; no network settings were changed. The page eventually loaded and explicitly reported **“Local Application isn't whitelisted yet”**. It did not present a usable phone/OTP form for this client. No account was linked, no phone/OTP was submitted, and no account token or product data was received. The unused loopback callback listener was stopped.

The developer quickstart's self-serve wording did not establish usable live access for this custom client. Swiggy's more specific access/onboarding guide states that redirect allowlisting is required for staging, which uses seeded data, and that production has separate approval. See https://mcp.swiggy.com/builders/docs/operate/access/. Do not spoof an approved client's identity or claim staging prices are live retailer prices.

`live-signin-result.json` and `swiggy-client-blocked.png` record this result without OAuth state, verifier, authorization code, account information or tokens. `SWIGGY_ACCESS_REQUEST_DRAFT.md` is an unsent draft for the owner to review and complete. No application, email or GitHub issue was submitted. The official route remains blocked on provider allowlisting; the client is not activated in SnapSave's order worker.
