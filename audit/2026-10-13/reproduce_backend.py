"""Read-only project audit: application requests use a disposable database only."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import faulthandler
faulthandler.dump_traceback_later(30, repeat=True)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "SnapSave-Backend"))
os.chdir(ROOT / "SnapSave-Backend")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempfile.mkdtemp(prefix="isolated-", dir=Path(__file__).parent)) / "audit.db").replace("\\", "/")
os.environ["DEBUG"] = "false"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
results = {}

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    from api import server as s
    from database import Base, engine, SessionLocal
    import models
    from fastapi.testclient import TestClient
    from sqlalchemy import event, text
    from core.query_parser import parse_query
    from core.cart_builder import build_cart_from_text
    from pricing.cart_optimizer import optimize_cart, calculate_final_price
    from pricing.pivot_layer import resolve_best_candidate
    Base.metadata.create_all(engine)
    c = TestClient(s.app)

    def login(uid, phone):
        r = c.get("/api/auth/test-token", params={"uid": uid, "phone": phone})
        h = {"Authorization": "Bearer " + r.json()["idToken"]}
        me = c.get("/api/auth/me", headers=h)
        return h, me.json()

    admin, a = login("audit_admin", "+911000000001")
    cust, u = login("audit_customer", "+911000000002")
    other, v = login("audit_customer_other", "+911000000003")
    mod, m = login("audit_mod", "+911000000004")
    results["public_token_admin"] = {"role": a["role"], "debug": os.environ["DEBUG"]}
    r = c.put("/api/admin/make-admin", json={"phone": v["phone_number"]})
    results["unauthenticated_promotion"] = {"status": r.status_code, "role": r.json().get("role")}
    address = c.post("/api/addresses", json={"title": "Home", "street_address": "Audit street", "city": "Delhi", "state": "Delhi", "postal_code": "110001"}, headers=cust).json()
    results["address_coordinates"] = {"city": address["city"], "latitude": address["latitude"], "longitude": address["longitude"]}

    def order():
        return c.post("/api/orders", json={"address_id": address["id"], "items": [{"name": "milk", "quantity": 2}]}, headers=cust).json()

    o = order()
    c.put(f"/api/moderator/orders/{o['id']}/claim", headers=mod)
    quote = {"store": "zepto", "items": [{"item_id": o["items"][0]["id"], "unit_price": 100, "store": "zepto"}], "subtotal": 100, "delivery_fee": 35, "platform_fee": 5, "store_discount": 0, "snapsave_discount": 0, "profit": 10, "final_price": 150}
    r = c.post(f"/api/moderator/orders/{o['id']}/price", json=quote, headers=mod)
    msgs = c.get(f"/api/chat/{u['id']}/messages", headers=cust).json()
    qm = next(x for x in msgs if "itemised quote" in x["message"])
    results["quote_and_line_total"] = {"http": r.status_code, "stored_line_price": r.json()["items"][0]["unit_price"], "serialized_line_total": r.json()["items"][0]["line_total"], "quote_order_id": qm["order_id"]}
    bad = {**quote, "items": [], "subtotal": -100, "final_price": -999, "delivery_fee": -50}
    r = c.post(f"/api/moderator/orders/{o['id']}/price", json=bad, headers=admin)
    results["invalid_quote_accepted"] = {"http": r.status_code, "final_price": r.json().get("final_price")}
    # Restore a valid quote, then attempt placement with an unassigned moderator.
    c.post(f"/api/moderator/orders/{o['id']}/price", json=quote, headers=mod)
    c.put(f"/api/customer/orders/{o['id']}/confirm", headers=cust)
    unassigned, um = login("audit_mod_unassigned", "+911000000005")
    r = c.post(f"/api/moderator/orders/{o['id']}/place", json={"eta_mins": -10}, headers=unassigned)
    d = c.get(f"/api/orders/{o['id']}", headers=cust).json()
    results["unassigned_placement"] = {"http": r.status_code, "status": d["status"], "customer_paid": d["customer_paid"], "store_cost": d["store_cost"]}
    c.put(f"/api/moderator/orders/{o['id']}/deliver", headers=mod)
    r = c.post(f"/api/orders/{o['id']}/complete", headers=other)
    results["foreign_order_completion"] = {"http": r.status_code, "status": r.json().get("status"), "owner_completed_count": c.get("/api/auth/me", headers=cust).json()["completed_orders_count"]}
    r = c.put(f"/api/moderator/orders/{o['id']}/claim", headers=mod)
    results["terminal_order_reclaimed"] = {"http": r.status_code, "status": r.json().get("status")}
    payload = {"order_id": o["id"], "rating": 5, "would_use_again": True}
    r1 = c.post("/api/feedback", json=payload, headers=cust)
    r2 = c.post("/api/feedback", json=payload, headers=cust)
    results["premature_duplicate_feedback"] = {"first": r1.status_code, "second": r2.status_code, "order_status": c.get(f"/api/orders/{o['id']}", headers=cust).json()["status"]}
    o2 = order()
    c.post(f"/api/chat/{u['id']}/send", json={"message": "Human ticket follow-up", "order_id": o2["id"]}, headers=cust)
    msgs = c.get(f"/api/chat/{u['id']}/messages", headers=cust).json()
    results["human_ticket_ai_reply"] = {"mode": "HUMAN", "last_sender": msgs[-1]["sender_role"], "last_order_id": msgs[-1]["order_id"]}
    o3 = order()
    with SessionLocal() as db:
        row = db.get(models.Order, o3["id"])
        row.mode = "AI"
        row.assigned_worker_type = "AI"
        row.status = "cancelled"
        db.commit()
        s.AI_CONCIERGE_PROVIDER.process_ticket(row.id, db)
        db.refresh(row)
        results["ai_reopens_cancelled"] = {"status": row.status, "subtotal": float(row.subtotal), "item_price": row.items[0].unit_price, "manual_prices_type": type(json.loads(row.manual_prices)).__name__}
    r = c.put(f"/api/moderator/orders/{o3['id']}/takeover", headers=unassigned)
    results["unassigned_takeover"] = {"http": r.status_code}
    r = c.put(f"/api/admin/orders/{o2['id']}/mode", json={"mode": "HYBRID"}, headers=admin)
    results["hybrid_from_human"] = r.json()
    r = c.put(f"/api/admin/orders/{o2['id']}/mode", json={"mode": "INVALID"}, headers=admin)
    results["invalid_mode"] = {"http": r.status_code, "mode": r.json().get("mode")}
    r = c.post(f"/api/moderator/orders/{o2['id']}/preview-quote", json={"items": [{"name": "milk", "unit_price": 150, "store": "zepto"}, {"name": "bread", "unit_price": 150, "store": "blinkit"}]}, headers=admin)
    results["mixed_store_delivery"] = {"subtotal": r.json()["subtotal"], "delivery_fee": r.json()["delivery_fee"]}
    r = c.post("/optimize-cart", json={"items": "milk", "location": "Unavailable City"})
    results["public_mock_optimizer"] = {"http": r.status_code, "best": r.json().get("pricing", {}).get("cart", {}).get("best_store")}
    h1, p1 = login("fixed_customer_uid", "+911000000006")
    h2, p2 = login("fixed_customer_uid", "+911000000007")
    results["fixed_uid_phone_collision"] = {"same_user": p1["id"] == p2["id"], "phone_changed": p1["phone_number"] != p2["phone_number"]}
    results["parser"] = {q: parse_query(q) for q in ["2 packets maggi", "1 litre milk", "1.5kg rice", "2 x 500ml milk"]}
    results["and_separator"] = {"items": len(build_cart_from_text("milk and bread"))}
    results["partial_basket_wins"] = optimize_cart({"milk": [{"store": "zepto", "price": 100}, {"store": "blinkit", "price": 110}], "bread": [{"store": "blinkit", "price": 100}]})
    results["weak_match_accepted"] = resolve_best_candidate("milk", "zepto", [{"name": "Dishwashing Detergent", "price": 25}])
    results["discount_reconciliation"] = calculate_final_price("zepto", 1000)
    # Pause AI immediately after its first commit, then change the human/global state.
    def ai_race(human_edit):
        race_order = order()
        with SessionLocal() as db:
            row = db.get(models.Order, race_order["id"])
            row.mode = "AI"
            row.assigned_worker_type = "AI"
            db.commit()
        started = threading.Event()
        release = threading.Event()
        errors = []
        def worker():
            try:
                with SessionLocal() as db:
                    original_commit = db.commit
                    calls = 0
                    def paused_commit():
                        nonlocal calls
                        original_commit()
                        calls += 1
                        if calls == 1:
                            started.set()
                            if not release.wait(10):
                                raise RuntimeError("Audit synchronization timed out")
                    db.commit = paused_commit
                    s.AI_CONCIERGE_PROVIDER.process_ticket(race_order["id"], db)
            except Exception as e:
                errors.append(type(e).__name__ + ": " + str(e))
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        assert started.wait(10)
        if human_edit:
            c.put(f"/api/moderator/orders/{race_order['id']}/takeover", headers=admin)
            with SessionLocal() as db:
                row = db.get(models.Order, race_order["id"])
                row.manual_prices = '[{"human_verified": true, "unit_price": 123}]'
                row.is_ai_priced = False
                db.commit()
        else:
            c.put("/api/admin/settings/ai-status", json={"ai_enabled": False}, headers=admin)
        release.set()
        t.join(10)
        with SessionLocal() as db:
            row = db.get(models.Order, race_order["id"])
            outcome = {"mode": row.mode, "status": row.status, "is_ai_priced": row.is_ai_priced, "human_price_preserved": "human_verified" in (row.manual_prices or ""), "errors": errors}
        c.put("/api/admin/settings/ai-status", json={"ai_enabled": True}, headers=admin)
        return outcome
    results["human_override_race"] = ai_race(True)
    results["kill_switch_race"] = ai_race(False)
    with engine.connect() as conn:
        results["sqlite"] = {"foreign_keys": conn.execute(text("PRAGMA foreign_keys")).scalar(), "journal_mode": conn.execute(text("PRAGMA journal_mode")).scalar()}

    # Measure database query count and response bytes for a synthetic 100-order history.
    with SessionLocal() as db:
        for i in range(100):
            row = models.Order(user_id=u["id"], store="pending", status="completed", delivery_street="Audit", delivery_city="Delhi", delivery_postal_code="110001", subtotal=0, delivery_fee=0, platform_fee=0, final_price=0)
            db.add(row)
            db.flush()
            db.add(models.OrderItem(order_id=row.id, name="milk", quantity=1))
        db.commit()
    statements = []
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    r = c.get("/api/orders", headers=cust)
    results["history_query_cost"] = {"orders": len(r.json()), "selects": len(statements), "response_bytes": len(r.content)}
    statements.clear()
    r = c.get("/api/moderator/queue", headers=admin)
    results["queue_query_cost"] = {"orders": len(r.json()), "selects": len(statements), "response_bytes": len(r.content)}
    event.remove(engine, "before_cursor_execute", count)

out = Path(__file__).parent / "backend-results.json"
out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
faulthandler.cancel_dump_traceback_later()
print(json.dumps(results, indent=2, default=str))
