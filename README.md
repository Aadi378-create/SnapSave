# SnapSave

SnapSave is a human-first grocery concierge. Customers send a list; staff verify store prices, send an itemised quote, then record payment, placement and delivery. Each order has a separate conversation and history, and every fee is visible before confirmation. Optional AI research requires a configured provider and cannot overwrite human work.

The apps use vanilla JavaScript/HTML; the API uses FastAPI, SQLAlchemy and SQLite by default. Manual concierge fulfillment is the supported workflow. SMS, inventory and bank settlement have not been live-tested by the regression suite.

## Setup (PowerShell)

From the project root with Python 3.11 or newer:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r SnapSave-Backend/requirements-dev.txt
Copy-Item SnapSave-Backend/.env.example SnapSave-Backend/.env
```

Only copy the example when `.env` does not already exist. Configure Firebase service-account credentials (or application default credentials) for Firebase Phone Authentication. The frontend uses the existing `snapsave-501c7` project; configure its authorized frontend domains and Phone Authentication. Verification checks revoked tokens. Initializing the SDK with a project ID alone does not supply credentials for account checks.

Customer and staff logins use Firebase OTP; roles come from the database. For an offline local demo only, set `APP_ENV=development` and `ENABLE_DEV_AUTH=true`. Development token issuance accepts loopback clients, uses distinct phone identities, and grants no staff role automatically. Disable it on public deployments. There is no reserved admin phone or public bootstrap endpoint.

Set `UPI_ID` and `UPI_PAYEE_NAME` in `.env`. Each payment QR includes the approved amount and order reference. Staff must check the bank receipt and enter its reference, paid amount, actual fulfillment cost and ETA before placement. Paid cancellations require an administrator to complete the bank refund and record its reference. Orders cancelled while awaiting payment remain flagged for bank reconciliation, including partial, excess or late receipts.

Start the backend:

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe -m uvicorn api.server:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Start the frontend in a second terminal:

```powershell
cd SnapSave-FRONTEND
../.venv/Scripts/python.exe serve.py
```

Open `http://localhost:3000/` or `http://localhost:3000/admin.html`. The static server binds to loopback and is for development.

For the first administrator, sign in through the customer app, save the profile email, then run this private command on the backend host:

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe bootstrap_admin.py person@example.com
```

The administrator can manage subsequent roles.

The private bootstrap also accepts `--phone 9876543210` for an existing Indian phone account, or an international `+countrycode` number. It promotes the existing database identity and does not bypass Firebase OTP. Relative SQLite database URLs in `.env` are resolved against the backend directory, so running this command from another folder uses the same database as the API.

## Data and order rules

Default database and environment paths are relative to the backend directory. SQLite enforces foreign keys and a busy timeout; startup enables WAL. Additive startup migrations preserve data, add missing fields, and convert legacy line totals once. Back up an existing database before the first updated startup. The repair suite uses disposable databases; it has not migrated the real development database.

Migration version 2 flags legacy fulfilled orders without payment-verification evidence for bank reconciliation. Administrators can record the actual receipt, or audit that no receipt was found, without changing fulfillment status. Cancelling an unreconciled legacy order retains its review flag. Use the Completed or Cancelled queue filter to reopen archived tickets for this follow-up. No bank receipt is inferred automatically from an old amount or delivery status.

Transitions follow `pending_review → reviewing → awaiting_customer → awaiting_payment → placed → delivered → completed`. Administrators can quote before explicitly claiming. Cancellation is limited to active states. Ticket assignment is separate from a customer's dedicated moderator. Revision checks protect claims, quotes and AI results. Order creation supports an `Idempotency-Key` and rejects its reuse for a different payload. Confirmation, placement and delivery retries cannot duplicate transitions or counters.

`line_total` is the total for the requested quantity; response `unit_price` is per unit. Preview shipping is calculated separately for each store. Current defaults are ₹35 shipping below ₹199 per store and ₹5 platform fee. Staff enter verified actual fees and discounts. Service fees are disclosed separately; the server reconciles the complete basket and final amount. Quotes expire after 15 minutes. Substitutions and new prices require customer discussion and approval.

## Optional research

Research is disabled by default; no mock prices are presented as live results. Enabling it requires:

- `ENABLE_LIVE_RESEARCH=true` and `RESEARCH_PROVIDER=module:function` naming installed backend code.
- For automatic quote publication, a provider that verifies SKU, quantity, stock, postal code, fees and promotion eligibility. The built-in public-catalogue provider instead creates review-only evidence drafts.
- The administrator's global AI switch enabled and an eligible pending/reviewing ticket in AI or HYBRID mode.

The callable accepts `(items, postal_code)`; each item contains `item_id`, `name` and `quantity`. A fully verified provider returns `verified: true`, the exact `postal_code`, a `source`, one `items` row per requested ID with `store` and `line_total`, plus verified `delivery_fee`, `platform_fee`, `service_fee`, `store_discount` and `snapsave_discount`. HYBRID drafts require staff approval; AI may publish a quote. Invalid data, saturation, failures and interrupted jobs return to human review. Takeover and the kill switch invalidate running work.

### Public catalogue research (review-only)

Beautiful Soup is already a project dependency. The built-in provider `core.catalog_research:research_catalog` reads product-scoped JSON-LD and microdata, checks exact requested pack size, and records price/currency/stock metadata and source links. It respects retailer robots policies, restricts URLs to supported HTTPS origins, stops on denied/challenge responses, and bounds request time/count/response size. It never marks public catalogue data as postcode-verified or publishes a payable quote. The AI worker stores an evidence draft for staff review; no prices are automatically filled into the quote form.

Run a read-only diagnostic without opening the application database:

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe research_catalog.py --query "Amul milk 1 L" --postal-code 110001 --live --output research-diagnostic.json
```

The postcode labels the requested delivery context; it is **not** a claim that the retailer has been set to that location. Search pages blocked by robots, HTTP 403/202 responses, missing product data, wrong packs and unavailable products produce diagnostics, not invented prices. Beautiful Soup parses HTML; it does not render JavaScript.

To try the provider in the management workflow, configure `RESEARCH_PROVIDER=core.catalog_research:research_catalog` and `ENABLE_LIVE_RESEARCH=true`, restart the backend, enable the administrator's global AI switch, then select HYBRID on an eligible ticket. Unattended HTTP requests currently fail to obtain usable default retailer prices. Browser-assisted BigBasket extraction was validated on real pages (see below). This implementation pass did not enable research in the existing environment or turn on the global AI switch.

Optional `RESEARCH_CATALOG_SOURCES` is a server-owned JSON mapping of supported store IDs to up to three HTTPS page URLs each. `{query}` is URL-encoded. Defaults include a Zepto milk category as a narrow initial catalogue source; this is not full grocery coverage. Do not configure private APIs or checkout URLs. `--live` explicitly permits public network requests; it does not place orders.

### Browser-assisted catalogue evidence

Normal Edge loaded BigBasket's public milk category and a product page during the 25 October inspection; an isolated headless browser received HTTP 403. The Beautiful Soup parser extracted **33 product cards** from the real rendered category and independently read **₹73 for Amul Taaza Homogenised Toned Milk, 1 L** from its product page. MRP ₹77 and the ₹7.30/100 ml comparison were excluded. This validates browser-assisted extraction, **not unattended fetching or postcode-specific availability**. The subsequent three-retailer validation is described below.

For repeatable captures, open a permitted public BigBasket `/pc/` category or `/pd/` product page in a normal browser. Inspect and manually run `SnapSave-Backend/tools/export_catalogue_capture.js` in its developer console. It reads the public product DOM and robots.txt, then downloads JSON. It exports no browser profile, cookies or login credentials. If robots.txt cannot be read, the exporter stops. It was tested in an isolated browser fixture; the real-page validation used DOM captures through the browser tool. Do not paste scripts from untrusted sources into your console.

Import the downloaded JSON within 15 minutes:

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe research_catalog.py --query "Amul Taaza Homogenised Toned Milk 1 L" --postal-code 110001 --browser-capture "C:/private/snapsave-catalogue-capture.json" --output research-evidence.json
```

The CLI makes no network requests in capture mode. It validates source origin, permitting robots evidence, size, timestamp, SKU/pack and selling-price scope. Both transports produce review-only drafts. Captures are supplied evidence and are not independently authenticated retailer responses. A server administrator can set `RESEARCH_BROWSER_CAPTURE_FILE` to a local capture file to feed the same AI review workflow; expired captures fail rather than silently reuse old prices. `--live` explicitly selects HTTP even if that environment variable is configured. Keep captures outside the repository and hosting folder. The default BigBasket source is the permitted milk category, not its robots-disallowed search endpoint; grocery coverage is limited to the supplied pages.

### Instamart, Zepto, Blinkit and customer location

The follow-up inspection also validated rendered public cards from **Zepto (59 products), Instamart (40) and Blinkit (28)**. The reusable exporter now supports all four retailers; it exports at most 30 visible DOM cards per capture. Raw HTTP probes still return 202 for Zepto/Instamart and 403 for Blinkit. This remains browser-assisted evidence collection, not unattended scraping, delivery verification or a working checkout engine. See `audit/2026-10-25/THREE_STORE_AND_LOCATION_VALIDATION.md` for observations and limitations.

On an eligible pending/reviewing ticket, administrators and the assigned moderator see **Research delivery location**. Copy the research context, open a retailer using the displayed links, and enter the customer's order postcode using its normal location selector. Choose the correct delivery area and wait for product data to reload. Never reuse an unrelated browser location. If the site requires an exact address, coverage is unclear, or the store is closed, stop and obtain clarification or retry when open. The application does not send customer street addresses, phone numbers or coordinates to retailers.

Run the inspected `tools/export_catalogue_capture.js` on that retailer page, paste the copied context when asked, and confirm the selected postcode only after checking it. The exporter records a postcode from the page header where available, and otherwise records the staff's explicit confirmation. It never exports the full header/address. Import the resulting JSON using the ticket's **Import retailer capture JSON** field. This upload is processed locally by the backend without retailer requests.

The authenticated import endpoint checks staff assignment, order state, revision, capture age, order ID and target postcode. Evidence from a different selected postcode is rejected. Missing location confirmation must be resolved before ticket import. A matching header postcode or staff confirmation still leaves `serviceability_verified=false`; exact-address coverage, stock and checkout fees require staff review. The existing AI review workflow consumes the same evidence format; prices are not automatically filled into a quote and manual drafts are preserved. Captures are limited to 60 KB through the management upload and expire after 15 minutes. A changed order requires copying a new context and recapturing. Standalone CLI captures may remain location-unknown and are labelled accordingly.

Legacy scraping adapters remain disabled. Configuring a research callable does not enable a functioning live scraper for `/deal` or `/optimize-cart`; they safely report unavailable/incomplete data. Provider integration and checkout require live integration validation.

Research uses two in-process workers and at most twenty outstanding orders. Use one API process with this executor; move research to a shared durable queue before using multiple API processes with AI enabled. SQLite serializes writers. JSON learning stores, caches and request limits are local to each process. Production capacity needs deployment measurements and appropriate shared database/cache/queue infrastructure.

## Verification

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe -m playwright install chromium
../.venv/Scripts/python.exe -m pytest -q
```

Tests cover access control, pricing, lifecycle, payment/refund records, migrations, concurrent writes, deterministic AI races, bounded queries and Chromium flows. Firebase, stores and payment services use fixtures. Test configuration selects a disposable database before importing the app.

The original audit and repair verification are in `audit/2026-10-13/`. Original reproduction scripts describe the old checkout; pytest is the current acceptance suite.

## Hosting

Configure an HTTPS backend, Firebase credentials, `APP_ENV=production`, `ENABLE_DEV_AUTH=false`, exact frontend `CORS_ORIGINS`, persistent storage and database backups. Add edge request/rate limits alongside the app's 64 KB body and 120 mutations/minute per-IP limits. Proxy identity handling needs deliberate configuration; the app does not trust forwarded IP headers.

Set `ALLOWED_HOSTS` to the actual API hostname (without scheme/path); the default permits only localhost/127.0.0.1. Wildcard `*` is rejected. Local launch uses `--no-proxy-headers`; production proxy trust must be limited to the actual reverse proxy, which must replace untrusted forwarded headers. App limits are 300 reads/minute, 120 writes/minute and 10 development-token requests/minute per peer IP, with a 10-second mutation-body deadline and 64 KB body cap. These are bounded, in-process safeguards; public deployment still needs HTTPS ingress, a correctly configured firewall/edge service, shared rate limits and capacity testing. Shared proxy IPs must be considered before serving many users.

API responses are marked no-store/nosniff and cannot be framed. Frontend serving is restricted to approved public files/assets, and local/Firebase hosting headers restrict framing, base URLs and embedded objects. The local file server is for development, not internet hosting. The hosting builder refuses reused output folders containing unexpected files and excludes unapproved asset types. Firebase configuration changes take effect after a hosting deployment; this work does not deploy automatically.

### Private database backups

GitHub preserves source code, not the private database, `.env` or Firebase credentials. Create a consistent SQLite snapshot while the API is running:

```powershell
cd SnapSave-Backend
../.venv/Scripts/python.exe backup_database.py
# Or use an explicitly selected, preferably encrypted external drive:
../.venv/Scripts/python.exe backup_database.py --output-dir "E:/SnapSave-Backups"
```

The default `.private-backups` directory is ignored by Git. Each unique snapshot includes committed WAL data and passes `PRAGMA integrity_check`; its manifest records SHA-256 and size. It does not overwrite the live database or older snapshots. Non-SQLite databases require vendor backup tooling. Snapshots contain private customer records and are not encrypted by this script. Keep verified copies on encrypted offline media or a separately protected versioned backup service, disconnect offline media after copying, and test restores periodically. A same-PC copy is useful recovery material but is not ransomware isolation. No automatic recurring private-data backup is configured by these commands.

Windows Firewall and Defender protect the host; an application cannot guarantee that malware will not delete files. Controlled Folder Access can help, but it must be tested with the legitimate database/runtime writers before enforcement. Avoid broad antivirus exclusions or trusting every Python script. Keep Windows and dependencies patched, use least-privilege accounts and MFA for GitHub/Firebase, and keep recovery credentials outside the hosted/Git files. Detailed inspected status and limitations: `audit/2026-10-25/security/SECURITY_REVIEW.md`.

The subsequent inspection and regression fixes are recorded in `audit/2026-10-25/followup-inspection/REPORT.md`. Restricted staff lose shared customer-data access, unclaimed moderator tickets hide precise contact/delivery and internal pricing fields, and authorized ticket views display the frozen delivery address. Role and address changes are serialized to protect the last administrator and prevent concurrent defaults. New addresses require ASCII Indian postcodes. Structured grocery item names preserve numeric brands; for free text use an explicit count such as `1x 7 Up 750 ml` when the product begins with a number.

Build the static package with the actual backend origin:

```powershell
cd SnapSave-FRONTEND
$env:API_ORIGIN='https://api.example.com'
../.venv/Scripts/python.exe prepare_hosting.py
```

Replace the example with the deployed backend origin. Firebase publishes only `dist`; the builder copies app files/assets and writes the API origin. Building does not deploy. Never host the backend folder, environment, database or service account as static assets.

The product inspection, prioritized feature roadmap and actual retailer-access results are recorded in `audit/2026-10-25/AI_ENGINE_AND_FEATURE_REVIEW.md`.
