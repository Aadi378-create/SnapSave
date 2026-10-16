# SnapSave project audit

Historical baseline: this report describes checkout `3f9fff4` before repairs. See `REPAIR_REPORT.md` for current changes, regression results and remaining live-service checks. Original line references and reproductions describe the old code.

Date: 13 October 2026 (Asia/Calcutta). Checkout: `3f9fff4`.

## Assessment

The code provides a human concierge MVP, but this checkout has release-blocking authentication, authorization, AI override, and pricing integrity problems. It should remain in controlled development until those are corrected. Customer history, moderator chat, and tracking also contain visible workflow bugs.

The supplied handoff is not an accurate description of all current behavior. Several routes differ, quote/cancellation messages still omit their order IDs, the AI provider generates mock prices, the scraper entry point is disabled, and feedback does not complete an order. An earlier “all bugs fixed” statement is not supported by this audit.

Application source was not changed. Audit scripts and results are stored beside this report. Backend requests ran in-process with FastAPI TestClient and newly created disposable SQLite databases. The real `snapsave.db`, running servers, customer accounts, Firebase project, and store sites were not modified. Sensitive token logs were discarded by the audit runners.

This is a source review with isolated reproductions, not a deployed penetration test, real payment test, live provider test, browser/device matrix, or production load benchmark. “Reproduced” means exercised locally; “source-confirmed” means the code directly establishes the defect; “risk” means a plausible future failure that was not reproduced under production conditions.

## Verification results

| Check | Result |
|---|---|
| Python syntax | 75 application/test Python files parsed; no syntax errors |
| JavaScript syntax | Inline customer/admin scripts and three standalone JS files parsed successfully |
| Existing pytest suite | 4 passed, 2 failed, 1 setup error |
| Backend audit | Reproduced privilege escalation, foreign-order completion, negative quotes, terminal-state reopening, incorrect line totals, duplicate feedback, mock pricing, weak matching, and AI control races |
| Frontend audit | Script/DOM fixtures reproduced history-switch failure, New Order retaining the current order, incorrect delivery completion, and unsanitized message HTML |
| Synthetic query measurement | 105 orders: history uses 108 SELECTs and 83,748 response bytes; queue uses 107 SELECTs and 65,415 bytes |

Evidence: [backend results](<C:/Users/Aadi Jain/Desktop/SnapSave/audit/2026-10-13/backend-results.json>), [frontend results](<C:/Users/Aadi Jain/Desktop/SnapSave/audit/2026-10-13/frontend-results.json>), [existing test results](<C:/Users/Aadi Jain/Desktop/SnapSave/audit/2026-10-13/existing-tests.json>).

## Critical findings

### A01 — Public development authentication grants real staff access

**Reproduced.** `GET /api/auth/test-token` accepts caller-supplied phone/UID without authentication or an environment gate. `get_current_user` accepts its `test_kid` tokens even with `DEBUG=false`, infers ADMIN/MODERATOR from the UID, and elevates the reserved admin phone. The audit obtained an ADMIN profile with DEBUG disabled.

The staff “production login” uses this same endpoint and asks only for a phone number. It does not perform OTP verification. Token signing does not establish ownership of the phone when anyone can request the signature.

Impact: anyone with API access can obtain staff privileges and act on orders, financials, assignments, and personal data. Remove public test issuance/verification from deployed environments and authenticate staff using verified identity with server-controlled roles.

Evidence: [server.py:648](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:648>), [role inference:459](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:459>), [staff login:2054](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2054>).

### A02 — Role promotion bypasses authentication/authorization independently

**Reproduced/source-confirmed.** `PUT /api/admin/make-admin` and `/make-moderator` have no authentication dependency. An unauthenticated promotion returned HTTP 200. `/api/admin/roles` also exempts IDs containing `test` and permits any authenticated user to bootstrap roles when no admin exists.

Impact: disabling test-token issuance alone will not close the promotion endpoints. Require ADMIN permission everywhere; provision the initial administrator through a private deployment/bootstrap mechanism.

Evidence: [server.py:1092](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1092>), [server.py:1114](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1114>).

### A03 — Stored HTML injection reaches customer and staff screens

**Source-confirmed; unsafe HTML insertion reproduced.** Message bodies, support messages, customer names, item names, feedback, and incident notes enter `innerHTML` without escaping or sanitization. The fixture preserved an HTML event attribute in a customer chat bubble. Staff rendering follows the same pattern.

Impact: a malicious customer message/profile can execute browser script when staff view it, read tokens from localStorage, change the displayed payment destination, or perform actions with the viewer's privileges. This audit did not execute an exploit in a real browser. Render user text with `textContent`; represent system payment cards as structured trusted components instead of arbitrary message HTML.

Evidence: [customer chat:1523](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1523>), [staff chat:3012](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3012>), [support:1730](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1730>).

## High-priority logic and integrity findings

### A04 — Another customer can complete an order; lifecycle transitions can reverse

**Reproduced.** `/api/orders/{id}/complete` checks neither ownership nor delivery state. A different authenticated customer completed the owner's order. Claiming that completed order then returned it to `reviewing`. Manual admin placement can also set `placed` from any prior state.

Impact: fulfillment can be skipped, cancelled/finished orders reopened, and business counters altered. Centralize allowed transitions, check object ownership/assignment, and reject transitions from terminal states unless an explicitly audited recovery operation applies.

Evidence: [completion:1055](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1055>), [claim:1357](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1357>), [manual placement:1567](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1567>).

### A05 — Moderator assignment enforcement is inconsistent

**Reproduced.** An unassigned moderator placed another moderator's order and took over its AI worker; both returned HTTP 200. Placement/takeover do not enforce the assignment checks used by pricing, delivery, and chat. Quote preview has no assignment check either.

Impact: staff can interfere with each other's tickets. Use a shared order-access dependency across all staff actions. Decide explicitly whether read access to other customers' completed orders and internal finances is appropriate.

Evidence: [placement:1542](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1542>), [takeover:1736](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1736>).

### A06 — AI can overwrite human prices after takeover and act after kill-switch shutdown

**Reproduced with controlled concurrency.** The AI worker was paused after its start commit. A human took over and saved verified prices; when resumed, AI replaced those prices and set `is_ai_priced=true`, despite HUMAN mode. In a second run, disabling global AI during that pause still allowed a customer quote and `awaiting_customer` status.

Impact: the absolute human override and emergency shutdown promises are false for work already in progress. Revalidate worker/mode/global state and a ticket generation/version immediately before an atomic write; invalidate in-flight generations on takeover and human pricing.

Evidence: [ai_concierge.py:13](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/ai_concierge.py:13>), `human_override_race` and `kill_switch_race` in backend results.

### A07 — AI can reopen cancelled orders and does not persist item prices

**Reproduced.** Processing a cancelled AI-assigned ticket changed it to `awaiting_customer`. The provider checks mode/worker/manual-price ownership but not lifecycle status. It computes a subtotal yet leaves `OrderItem.unit_price` and `.store` unset. Its `manual_prices` schema is an object, whereas human submission stores an array.

Impact: finished tickets can receive new quotes; itemized records disagree with totals; HYBRID drafts cannot consistently populate the human editor. Gate eligible states and use one validated quote schema with persisted line-item data.

Evidence: [ai_concierge.py:30](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/ai_concierge.py:30>), [human quote JSON:1456](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1456>), [price rows:3189](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3189>).

### A08 — Server trusts inconsistent, incomplete, and negative quote totals

**Reproduced.** QuoteSubmission lacks nonnegative constraints on subtotal/fees/discounts/final price, arithmetic reconciliation, and complete item validation. A quote with no submitted items and `final_price=-999` was accepted. Unknown or duplicate item references can be ignored/overwritten while the order still advances.

Impact: undercharging, unpriced products, wrong totals, and corrupted financial records. Calculate monetary totals on the server using Decimal, require each expected item exactly once, validate store/SKU identity, reject nonfinite amounts, and enforce discount bounds.

Evidence: [schema:211](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:211>), [submission:1434](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1434>).

### A09 — Line-total and unit-price semantics conflict

**Reproduced.** The moderator enters a total line cost and the preview sums that cost once. Serialization multiplies it by quantity again: quantity 2, entered cost ₹100, reported `line_total=₹200`. AI separately treats ₹50 as a unit price.

Impact: receipts, downstream calculations, integrations, and future analytics can double-charge quantities or understate AI totals. Adopt separate `unit_price` and `line_total` fields with one explicit convention across manual, AI, API, and UI.

Evidence: [serialization:778](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:778>), [preview:1384](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1384>), [editor:3209](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3209>).

### A10 — Mixed-store quote delivery costs are calculated against the combined basket

**Reproduced.** ₹150 from Zepto plus ₹150 from Blinkit received zero delivery fee because the total ₹300 clears the primary store's ₹199 threshold. Neither individual store basket clears that threshold. The preview supports item-level stores but charges for only the primary store.

Impact: SnapSave can absorb unexpected delivery charges or revise an already approved quote. If fulfillment uses multiple store orders, calculate each store basket and its fees before selecting a split. If fees are intentionally subsidized, record that subsidy separately.

Evidence: [server.py:1388](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1388>).

### A11 — Optimizer compares incomplete baskets and may recommend missing products

**Reproduced.** A store with milk only beat a store carrying milk and bread because the optimizer compared their partial totals without coverage validation. The split optimizer has the same incomplete-store issue, excludes delivery costs, and crashes on an empty price map.

Impact: “cheapest cart” may exclude requested items. Require complete coverage or an explicit accepted substitution/missing-item outcome; evaluate total landed cost for each fulfillment plan.

Evidence: [cart_optimizer.py:121](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/cart_optimizer.py:121>), [cart_split_optimizer.py:31](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/cart_split_optimizer.py:31>).

### A12 — Mock prices are returned as ordinary price results

**Reproduced.** The main scraper function always returns `not_available`, so `/optimize-cart` substitutes fixed demo prices. A request for an unsupported city returned a ₹70 “best” cart. The AI concierge uses ₹50 per unit and fixed fees. Neither result establishes live availability or price freshness.

Impact: customers or integrations may treat fabricated prices as researched quotes. Keep mock results behind explicit development flags, label provenance, and fail safely when no verified live data is available. Preserve the human MVP without promising autonomous live research.

Evidence: [disabled scraping:23](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/stores/price_parallel.py:23>), [fallback:587](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:587>), [AI mock:38](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/ai_concierge.py:38>).

### A13 — Product matching can confidently select an unrelated product

**Reproduced.** Resolving query `milk` against a sole `Dishwashing Detergent` candidate returned that product with `confidence=0.95` and `match_score=0`. Ranking falls back to the first candidates, while reported confidence comes from matching the query against the vocabulary, not the actual store SKU.

Impact: wrong brand/type/pack-size substitutions can appear highly reliable. Compute candidate-specific confidence, enforce product and pack constraints, and ask for clarification below a threshold. The clarification module exists but is not wired into the order creation path.

Evidence: [product_ranker.py:11](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/product_ranker.py:11>), [pivot_layer.py:4](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/pivot_layer.py:4>).

### A14 — History selection and New Order are blocked by signature caching

**Reproduced in frontend fixtures.** `loadOrders` returns before checking `selectedHistoryOrderId` if server orders are unchanged. `pollMessages` similarly ignores selected context when its signature is unchanged. Clicking a past order left the active order selected. New Order also retained the active order instead of creating a fresh drafting context.

Impact: history appears broken, chats can remain from the wrong view, and a new list may become a message in an existing ticket. Separate server-data caching from view state and force rendering when selection changes; keep the viewed order separate from the active order.

Evidence: [index.html:1544](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1544>), [history handlers:1617](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1617>).

### A15 — Quote and cancellation messages lose their order context; admin chats combine orders

**Reproduced/source-confirmed.** Human quote messages have `order_id=null`; cancellation and generic AI acknowledgements also omit it. Customer rendering filters strictly by active order, hiding those messages. Admin rendering displays all messages for the customer, with no selected-order filter.

Impact: the customer misses the itemized quote/cancellation, while staff can confuse messages across orders. Require an order reference for every order event and query the selected order's messages explicitly. Validate that incoming message order IDs belong to the customer thread.

Evidence: [quote message:1479](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1479>), [cancellation:1646](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1646>), [customer filter:1473](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1473>), [admin render:2983](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2983>).

### A16 — Moderator chat is disabled in the frontend

**Source-confirmed.** `pollChat` returns unless the current role is ADMIN. Background polling calls it only for admins. The backend permits assigned moderators to read/send, and the UI enables the composer, producing a contradictory workflow. The delivery button is also admin-only despite the backend allowing assigned moderators to deliver.

Impact: moderators cannot read customer clarifications needed to fulfill the human-first promise. Align the product's role policy, backend checks, and UI capabilities.

Evidence: [admin.html:2193](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2193>), [chat guard:2969](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2969>), [delivery visibility:3165](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3165>).

### A17 — Token lifetime and demo identity handling break sessions

**Reproduced/source-confirmed.** Customer quick login uses one fixed UID for every phone. Two phones with that UID resolved to the same user and changed its phone number. Staff login likewise uses the endpoint's default UID. The frontend stores one ID-token string at sign-in and does not refresh that string during API requests.

Impact: demo users can share history/accounts, role identity can bleed across staff logins, and long sessions fail after token expiry. Use unique verified identities, fetch a fresh Firebase ID token for requests or observe token changes, and handle expired demo tokens explicitly. Firebase documents that ID tokens last one hour. [Firebase session documentation](https://firebase.google.com/docs/auth/admin/manage-sessions).

Evidence: [quick login:1180](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1180>), [auth lookup:466](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:466>), [request token:1834](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1834>).

### A18 — Prices and customer charges do not transparently reconcile

**Source-confirmed; optimizer mismatch reproduced.** Staff preview adds `profit` as an extra customer charge beyond platform/delivery fees. The customer quote/card omits a distinct service-margin line and most fee/discount components. The optimizer can return a ₹950 final price for a ₹1,000 cart while listing ₹220 total discounts, because a profit-floor clamp changes the final price without changing the breakdown. Savings also mix discounts and comparisons inconsistently.

Impact: the total cannot be audited from the displayed components, contradicting the transparency principle. Make any service charge explicit; derive profit from settlement costs; ensure displayed discounts sum to the actual reduction; define savings against a comparable complete basket.

Evidence: [margin addition:3310](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3310>), [customer quote:1595](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1595>), [pricing clamp:82](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/cart_optimizer.py:70>).

## Performance and concurrency findings

### A19 — Full-history polling performs one extra query per order

**Measured.** Order history and queue eager-load the customer but not `Order.items`; serialization triggers a lazy SELECT per order. Both endpoints use `.all()` and return terminal orders without pagination by default. Chat and support also return full lifetime histories.

At 105 synthetic orders, one customer history poll performed **108 SELECTs / 83,748 bytes**; one queue poll performed **107 SELECTs / 65,415 bytes**. These are query counts and payload measurements, not latency/load claims. Signature checks happen after fetching, so they save some DOM work but none of this API/query cost.

Customer polling issues three requests every 8 seconds: 100 open customers imply approximately **37.5 requests/second**, before staff and actions. Staff queue/help/chat calls add work every 10 seconds. History length increases cost even if nothing changes.

Fix: eager-load items, paginate history, filter active queue by default, fetch messages after a cursor, return lightweight list summaries, and pause/back off polling when hidden or failing. Add notifications/SSE where justified after correctness is stable.

Evidence: [history:962](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:962>), [queue:1320](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1320>), [message fetch:1670](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1670>).

### A20 — Polling can overlap, overwrite new state, and leave stale controls

**Source-confirmed risk.** Async `setInterval` does not wait for the prior interval to finish. Customer orders/messages load concurrently even though chat rendering depends on the current order. Older ticket/quote responses can arrive after selection changes. Customer signatures omit item/fee/assignment changes; staff queue signatures omit assignment/customer/pricing fields, and selected details rerender only when status changes.

Impact: slow connections can show the wrong conversation, stale ownership/mode controls, missing updates, or a quote preview attached to a newly selected ticket. Use a single-flight polling loop, request cancellation/generation IDs, context-aware signatures, and immutable quote snapshots tied to order/version.

Evidence: [customer polling:1288](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1288>), [staff diff:2868](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2868>), [preview request:3284](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:3284>).

### A21 — Claiming is not atomic, and ownership is stored on the customer

**Source-confirmed concurrency risk.** Claim reads a customer's assignment then updates it without a conditional atomic claim. Simultaneous staff requests may both see an unassigned customer and succeed. Assignment lives on User, so reassigning one ticket also changes permissions for all of that customer's tickets and histories.

Impact: double ownership, lost assignments, and interrupted fulfillment if multiple customer orders coexist. Store ticket assignment separately from an optional dedicated customer concierge; use compare-and-set/versioning for claims and transitions. Add idempotency keys to order creation/confirmation/placement to make retries safe.

Evidence: [claim:1363](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1363>), [assignment:1620](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1620>).

### A22 — AI tasks lack bounded execution, explicit session cleanup, and durable status

**Source-confirmed risk.** Mode/delegation starts a new raw thread on each request, creates a Session outside the worker, and does not explicitly close it. There is no per-order job deduplication, retry/failure record, task cancellation protocol, or concurrency cap. Repeated actions can produce competing runs, connection-pool pressure, and lost work on restart.

Fix: create and close a session inside each worker, deduplicate per order/version, bound concurrency, and persist job status/errors. A worker queue is appropriate once processing becomes long-running. SQLAlchemy recommends a session per thread and context-managed worker scope. [SQLAlchemy session guidance](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks).

Evidence: [thread launch:1715](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1715>), [delegation:1731](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1731>).

### A23 — SQLite and in-memory state will constrain concurrent operations

**Measured configuration/source-confirmed risk.** Audit connections had `foreign_keys=0` and journal mode `delete`. There are no connection hooks enabling FK enforcement. SQLite has a single writer even with WAL; multiple request/AI writes can create contention. Cache dictionaries are unsynchronized and each worker process gets independent cache/auth keys.

Impact: orphan records, cache iteration/deletion errors, inconsistent caches, and intermittent demo-token failure across multiple workers or restarts. Enable/test FK enforcement, use deliberate transaction boundaries, and evaluate WAL for local deployment; move shared production state to an appropriate database/cache when needed. These limits do not establish a measured maximum customer capacity. [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html), [SQLite WAL](https://www.sqlite.org/wal.html).

Evidence: [database.py:13](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/database.py:13>), [cache cleanup:118](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:118>), [local test keys:326](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:326>).

## Additional defects and operational risks

### A24 — Payment, ETA, feedback, and completion records are incomplete

**Reproduced/source-confirmed.** Normal moderator placement leaves `customer_paid` and `store_cost` at zero despite claiming payment verified. Negative ETA was accepted; ETA is stored only in a chat sentence. The payment card uses one static QR image, without an order-specific amount/reference or transaction reconciliation record. Feedback is accepted before delivery and repeatedly, and does not transition to `completed`. Delivery increments the completed-order count, and explicit completion can increment it again; the audit observed count 2 for one delivered/completed order.

Impact: false payment confidence, reconciliation disputes, lost ETA/tracking data, misleading revenue, repeated feedback, and membership eligibility errors. Persist payment evidence/state and ETA timestamps, define exactly when completion/counters occur, and enforce unique post-delivery feedback. Manual UPI can remain the MVP if verification is recorded and auditable.

Evidence: [placement:1539](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1539>), [static QR:1525](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1525>), [delivery count:1598](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1598>), [feedback:2030](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:2030>).

### A25 — Tracker marks delivery complete too early and drops delivered orders

**Reproduced/source-confirmed.** “Delivered to Door” gets `completed` styling at the `placed` stage. “Order Placed & Packing” activates while awaiting payment. `loadOrders` excludes delivered orders from the active view, so the feedback button is absent there unless the customer selects history—which currently has A14.

Fix: map each stage to explicit statuses and preserve a just-delivered order until acknowledgement/feedback, or provide a reliable delivery/feedback history flow.

Evidence: [index.html:1549](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1549>), [stepper:1577](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1577>).

### A26 — Natural-language parsing does not meet the promised input model

**Reproduced/source-confirmed.** `milk and bread` becomes one item in the active cart builder, despite a separate unused parser supporting “and”. `1.5kg rice` parses volume as 5kg; `1 litre milk` does not recognize a volume. Matching output drops the parsed volume field. The frontend considers almost any message longer than five characters a grocery order, except several greeting prefixes: “thanks” can create an order, while “milk” is too short.

Impact: wrong item counts/pack sizes and accidental tickets. Use one parser across chat and list flows, preserve quantity versus pack size, and handle uncertainty through clarification rather than automatic guessing.

Evidence: [cart_builder.py:4](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/cart_builder.py:4>), [query_parser.py:4](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/query_parser.py:4>), [chat classifier:1422](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1422>).

### A27 — Location and store rules are placeholders or contradictory

**Reproduced/source-confirmed.** Saving a Delhi address without coordinates stored Pune coordinates; the frontend explicitly sends Pune coordinates for every address. Store availability ignores location and returns feature-flagged stores. Admin config uses `swiggy`, while quote entry uses `instamart`, so changing the Instamart threshold need not affect previews. Thresholds and discounts also differ among several configuration modules.

Impact: unavailable stores, wrong fees, incorrect serviceability, and misleading “best in your pin code” claims. Preserve unknown coordinates rather than inventing them, validate serviceability, normalize store IDs, and maintain one verified rules source with freshness/account eligibility.

Evidence: [address defaults:714](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:714>), [frontend coordinates:1365](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1365>), [store_availability.py:43](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/store_availability.py:43>), [admin config:2334](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2334>).

### A28 — HUMAN/HYBRID control behavior is inconsistent

**Reproduced.** Switching HUMAN to HYBRID retains HUMAN assignment, so the advertised AI draft does not start automatically. Arbitrary mode strings are accepted. Customer chat still creates an AI acknowledgement for HUMAN tickets when global AI is enabled, ignoring ticket mode and takeover state; the acknowledgement lacks an order ID. The legacy customer takeover setting read by chat has no active route updating it.

Fix: validate enums, define a consistent mode/worker transition matrix, and apply the same ticket policy to every AI entry point. If HYBRID requires manual delegation by design, make that prerequisite visible.

Evidence: [mode:1683](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1683>), [AI chat branch:1806](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1806>).

### A29 — Migration, porting, and transaction reliability gaps

**Source-confirmed risks.** Startup migrations omit the new AI columns and `taken_over_by`, so a database from before those additions will not be fully upgraded by this code. SQLite-specific ALTER definitions have no dialect guard. Database/file paths depend on the working directory. Several workflows commit state and messages separately, so failure can leave a transitioned order without its message. JSON/message fields are declared VARCHAR(1000), and many strings lack request length limits; SQLite's permissive lengths hide stricter database-porting failures. Duplicate profile emails can raise unhandled uniqueness errors.

Fix: versioned migrations, explicit paths, atomic order/event transactions, appropriate Text/JSON types, validated inputs, and clear conflict responses. Adding PostgreSQL via an environment variable does not by itself solve migration or schema portability.

Evidence: [migration list:81](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:81>), [quote commits:1465](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1465>), [models.py:77](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/models.py:77>), [profile update:1969](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1969>).

### A30 — Analytics use inconsistent states, timestamps, and amounts

**Source-confirmed.** Revenue/profit totals include awaiting-payment quotes but exclude `completed` orders. Thus completing an order can remove it from revenue/profit reporting. “Savings delivered” sums all orders, including unfinished/cancelled ones. Today is defined at UTC midnight rather than the business timezone, and response time measures claim time rather than the first customer response. Normal placement does not populate settlement amounts (A24).

Impact: GMV/revenue/profit and staff performance metrics cannot be trusted. Define booked, paid, fulfilled, refunded, and earned amounts separately; aggregate from relevant event timestamps in the business timezone.

Evidence: [server.py:1870](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1870>), [beta metrics:1984](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:1984>).

### A31 — Deployment and logging settings need production separation

**Source-confirmed/risk.** Frontends use same-origin API calls outside localhost, but Firebase hosting config has no API backend rewrite. Deploying that config alone will not route FastAPI requests. Hosting publishes the whole frontend directory, including developer scripts/output files unless excluded. The development HTTP server is single-threaded and disables caching. Backend auth logs full Authorization tokens/claims, and staff login logs the token response. API rate/size limits are absent; CORS permits every origin.

Impact: hosted API 404s, unnecessary public debug files, slow static serving, token exposure in logs, and avoidable abuse. Configure the actual API URL/proxy, package only deployable assets, scrub sensitive logging, use an appropriate static/API host, and establish bounded requests/rates. CORS restriction supplements authentication; it does not repair A01/A02.

Evidence: [hosting config](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/firebase.json>), [API base:1123](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1123>), [auth logging:349](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/api/server.py:349>), [staff logging:2079](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2079>).

### A32 — Re-enabling provider research exposes broken legacy modules

**Partly reproduced; provider execution not attempted.** `core.store_engine` cannot import `search_product` from the current adapters. The aggregator silently drops structured candidate lists because it expects numbers. Empty baskets and empty split maps raise ValueError. Shared persistent Playwright context is unsynchronized, `close_browser` does not reset globals, and page cleanup is not guaranteed on exceptions. Some adapters ignore location; decimal extraction can turn ₹40.50 into 4050 or reject it. Raw-thread basket parallelism scales with input length.

Impact: enabling scraping will not immediately produce a working production engine; expect import errors, empty results, wrong-location prices, resource leaks, and thread-affinity failures. Normalize adapter contracts, serialize/isolate browser workers, parse Decimal currency, cap work, and verify provider behavior before enabling. Playwright explicitly requires separate instances for multithreaded use. [Playwright threading guidance](https://playwright.dev/python/docs/library#threading).

Evidence: [store_engine.py:3](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/store_engine.py:3>), [aggregator.py:17](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/aggregator.py:17>), [browser_manager.py:8](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/browser_manager.py:8>), [currency parsing:38](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/core/store_scrapper_engine.py:38>).

### A33 — Tests can damage development data and currently provide limited assurance

**Reproduced/source-confirmed.** Existing tests use the configured SessionLocal without isolation. `test_validation_audit.py` directly deletes messages, orders, addresses, users, and settings when run as a script. The auth E2E test omits Authorization on completion (401); concierge E2E calls an obsolete `/prices` route (404), then assumes obsolete status/quote behavior; `test_full_flow.py::test_item` requests a nonexistent fixture. Several “test” files are print-only scripts, not assertions. The four passing AI tests are sequential and missed A06.

Fix: isolated fixtures and transaction cleanup, updated API contracts, negative authorization tests, controlled race tests, money/coverage tests, and UI flow tests. Do not run the old audit script against the real database.

Evidence: [destructive audit:31](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/tests/test_validation_audit.py:31>), [AI fixture:13](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/tests/test_ai_concierge.py:13>), [existing test results](<C:/Users/Aadi Jain/Desktop/SnapSave/audit/2026-10-13/existing-tests.json>).

### A34 — Secondary UX and dormant recommendation defects

**Source-confirmed.** Failed chat/support sends clear the user's draft before success. Feedback closes even on failure and provides no visible retry; notes persist between feedback sessions. Support replies are not polled while the customer modal remains open. Admin chat rebuilds and forces scroll every poll. Beta polling is not cleared by staff logout. Duplicate/stale standalone admin scripts contain older implementations, increasing maintenance drift. Reward/add-on modules have inconsistent `gap` versus `add_more` schemas, and the add-on selection can suggest an item too cheap to reach the promised reward.

Impact: lost messages, missed support, distracting scroll jumps, and misleading future recommendation prompts. Preserve drafts on error, show actionable failures, clean up timers, consolidate the active JS, and keep optional threshold suggestions aligned with the anti-pressure product philosophy.

Evidence: [send draft:1419](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1419>), [feedback error:1827](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/index.html:1827>), [logout:2103](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-FRONTEND/admin.html:2103>), [addon_engine.py:13](<C:/Users/Aadi Jain/Desktop/SnapSave/SnapSave-Backend/pricing/addon_engine.py:13>).

## Likely problems as the product grows

| Situation | Likely issue | Related findings |
|---|---|---|
| Public beta/API exposure | Account takeover, staff impersonation, injected browser code | A01–A03, A17, A31 |
| Multiple moderators on one ticket/customer | Conflicting claims, incorrect permissions, lost quote edits | A05, A20–A22 |
| Human intervenes while AI is working | Human prices overwritten, shutdown ignored | A06–A07 |
| Customers with long order histories | Growing payloads/query counts, slow polling and rendering | A14–A15, A19–A20 |
| One list split across stores | Unbudgeted delivery fees, incomplete carts, multiple deliveries | A10–A11, A24 |
| Store stock/price changes after quote | Quote cannot be fulfilled at approved total; no quote expiry/version or substitution approval protocol | A08, A12–A13, A20, A27 |
| Paid order cancelled or partially fulfilled | Manual refund/reconciliation disputes; no payment/refund ledger or store-level fulfillment records | A24, A30 |
| More than one backend worker/restart | Process-specific demo signing keys and caches; non-durable AI jobs | A22–A23 |
| Re-enabling scrapers | Adapter/import failures, selector changes, location/session mismatch, unavailable prices | A12–A13, A27, A32 |
| Migrating or deploying | Missing columns, length failures, incorrect API routing, working-directory surprises | A29, A31 |

External provider availability, anti-bot behavior, and price volatility were not live-tested. Treat them as operational uncertainties, not verified current outages. There is no reliable capacity number yet; measure actual deployment latency, p95 response time, write contention, and fulfillment load after correctness fixes.

## Recommended repair order

1. Close public test authentication and role-promotion bypasses; escape user content; remove token logs. Add authorization regression tests.
2. Centralize lifecycle/ownership rules, atomic claims, idempotency, and AI generation checks. Protect human prices and kill-switch behavior under concurrency.
3. Standardize quote/line-price schemas and server money calculations. Fix mixed-store coverage/fees, payment records, completion counters, and savings transparency.
4. Repair history/view state, order-linked messages, moderator chat, tracking, feedback, and token refresh.
5. Reduce polling query/payload costs; introduce migrations, deployment configuration, and a bounded worker lifecycle.
6. Enable live research only after adapter, SKU/quantity, location, freshness, and failure behavior pass integration checks. Keep human review as the default until that evidence exists.

## Reproducing this audit

From the project root, use `python audit/2026-10-13/reproduce_backend.py`, `node audit/2026-10-13/reproduce_frontend.cjs`, and `python audit/2026-10-13/run_existing_tests.py`. Python runners create fresh audit databases under this directory. Windows sandbox restrictions may prevent TestClient's local socket-pair setup; these checks succeeded outside that restriction. The frontend fixture is not a substitute for real browser visual/mobile tests.
