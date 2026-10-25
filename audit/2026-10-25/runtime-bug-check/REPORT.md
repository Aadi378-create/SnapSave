# Runtime bug check — 25 October 2026

## Inspection

The running customer frontend at `http://127.0.0.1:3000/`, admin frontend at `/admin.html` and backend at `http://127.0.0.1:8000/api/status` returned HTTP 200. Existing Firebase sessions restored on fresh Edge tabs. The customer order/history/chat view and the administrator queue and analytics rendered successfully. Customer follow-up messages in the fresh view displayed as **YOU**, rather than as concierge messages. Navigation was read-only; no real orders, quotes, messages, payments or customer records were created or changed.

The older customer tab retained an unsent draft and a historical fetch error. That tab was left untouched. Fresh tabs loaded successfully. Browser logs contained extension-style connection and language-detection messages; these were not reproduced as application exceptions in the isolated browser suite. No fresh SMS or CAPTCHA challenge was exercised during this inspection.

## Reproduced and patched

1. **Bundle pricing could understate quantities.** Structured item names such as `Amul milk 2 x 500 ml`, `500 ml x 2`, `500 ml pack of 2` or `500 ml + 500 ml` could resolve to one 500 ml pack. Pack normalization now refuses bundles and alternative sizes for automatic calculation, leaving them for staff clarification. Explicit volume packs with a count greater than one are also rejected. This applies to requested names and observed pack labels.
2. **Numeric product identity was lost.** Product matching dropped numeric words, allowing `7 Up` to match `8 Up`, and `1% fat` to match `3% fat`. It now retains identifying numeric/alphanumeric tokens while normalizing pack measurements and explicit counts. Equivalent pack units still match, and numeric brands remain searchable. The first full repair run caught a regression where `milk under 20` treated its budget as a product variant; budget and currency expressions are now normalized separately, with additional regression coverage.

The reproduction tests recorded six failing cases before the patch (`reproduction.xml`). Additional regressions cover alternate bundle wording and valid numeric brands. These changes affect evidence selection and draft calculation, not customer quote publication or checkout.

## Verification and limits

Baseline regression suite: **252 passed**. Initial focused repair suite: **104 passed**. Final complete regression suite: **268 passed**, with one existing Starlette/httpx deprecation warning (`final-tests.xml`). The intermediate budget regression is preserved in `first-repair-tests.xml`. Source validation passed for 122 Python files, eight application JavaScript scripts and hosting JSON; `git diff --check` passed.

The verified SnapSave backend was restarted with the fixes, and fresh customer/admin tabs were left open. The post-restart check at **16:55 IST** returned 200 for the API and both frontend pages, 401 for unauthenticated order access and 404 for a private `.env` request. Research remained available and development authentication remained disabled (`runtime-smoke.json`). Backend startup logs showed a normal startup with no traceback.

Automated authenticated browser and API flows use disposable databases, synthetic identities and fixture retailer evidence. They cover order submission, communication, quote review, access control, payment records, asynchronous races and price drafts without contacting real payment or retailer services. A passing suite is evidence for those covered cases, not a guarantee of absence of all bugs.

Unattended retailer data access remains blocked as documented in the previous price-completion report. These fixes do not create an official API/feed, verify live checkout fees or establish Zepto serviceability for Kudasan. Fresh browser evidence and staff verification remain required.
