# Swiggy access request — draft only, not submitted

Integration: SnapSave Read-only Product Research
Organization/contact: To be supplied by the owner
Repository: https://github.com/Aadi378-create/SnapSave
Requested server: Instamart (`/im`)
Exact development redirect: `http://localhost:8765/oauth/callback`
Authentication: OAuth 2.1 with PKCE S256 and callback state validation
Requested scope: `mcp:tools` (the published scope is broad; this client exposes product search only)
Expected daily volume: To be supplied and agreed before testing
Initial research area: Kudasan, Gandhinagar; no customer street address will be sent for the initial test

## Use case

SnapSave is a grocery concierge and price-comparison prototype. We request permission to query Instamart product names, exact variants, offer prices and availability for customer-requested grocery lists alongside other retailers. Please confirm whether this use case is permitted and any display, attribution, storage, caching or commercial restrictions. We are not requesting bulk catalogue export, cart mutation, checkout, payment or order placement for this first integration.

## Current technical readiness

The prototype has a fixed-origin, search-only MCP client with bounded responses, JSON/SSE parsing, token refresh and Windows DPAPI-protected credential storage. Cart, order and address tools are rejected by the client. Local regression tests pass with synthetic data; we have not received a successful authenticated product response or claimed live prices from this API.

Dynamic registration returned a client identifier, but the official authorization page reports “Local Application isn't whitelisted yet” for the exact redirect above. Please advise the supported client registration and redirect-allowlisting procedure and enable staging access if approved. We understand seeded staging responses cannot establish live market prices, and production access requires its own approval.

## Items the owner must complete before submission

- Technical contact email and organization name, if applicable.
- Expected search/tool-call volume and allowed request rate.
- A demo link if requested by Swiggy; do not include real customer records or credentials.
- Review and accept provider terms personally if required.

Source of access requirements: https://mcp.swiggy.com/builders/docs/operate/access/
No email, application form or GitHub issue has been sent.
