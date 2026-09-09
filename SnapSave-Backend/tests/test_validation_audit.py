import sys
import os
import threading
import time
from fastapi.testclient import TestClient

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.server import app
import database
import models

def run_audit():
    client = TestClient(app)
    results = {
        "customer_journey": "PENDING",
        "moderator_journey": "PENDING",
        "admin_journey": "PENDING",
        "security_audit": "PENDING",
        "database_audit": "PENDING",
        "concurrency_audit": "PENDING"
    }
    
    print("\n==================================================")
    print("RUNNING FULL MVP VALIDATION AUDIT")
    print("==================================================")

    # ----------------------------------------------------
    # 0. Clean database for clean audit run
    # ----------------------------------------------------
    print("Cleaning database...")
    db = database.SessionLocal()
    try:
        db.query(models.Message).delete()
        db.query(models.Order).delete()
        db.query(models.Address).delete()
        db.query(models.User).delete()
        db.query(models.SystemSetting).delete()
        db.commit()
        # Initialize default settings
        ai_setting = models.SystemSetting(key="ai_enabled", value="true")
        db.add(ai_setting)
        db.commit()
    except Exception as e:
        print(f"Error cleaning database: {e}")
        db.rollback()
    finally:
        db.close()


    # ----------------------------------------------------
    # 1. Setup Dev Users
    # ----------------------------------------------------
    print("\nSetting up test credentials...")
    # Tokens
    cust_tokens = {}
    for i in range(1, 6):
        resp = client.get(f"/api/auth/test-token?phone=%2B91111111110{i}&uid=test_uid_cust_{i}")
        cust_tokens[f"cust_{i}"] = resp.json()["idToken"]
        
    resp = client.get("/api/auth/test-token?phone=%2B912222222201&uid=test_uid_mod_1")
    mod_1_token = resp.json()["idToken"]
    resp = client.get("/api/auth/test-token?phone=%2B912222222202&uid=test_uid_mod_2")
    mod_2_token = resp.json()["idToken"]
    resp = client.get("/api/auth/test-token?phone=%2B913333333301&uid=test_uid_admin_1")
    admin_token = resp.json()["idToken"]

    # Initial me calls to register users in DB
    for k, t in cust_tokens.items():
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
    client.get("/api/auth/me", headers={"Authorization": f"Bearer {mod_1_token}"})
    client.get("/api/auth/me", headers={"Authorization": f"Bearer {mod_2_token}"})
    client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})

    # Set roles
    client.put("/api/admin/roles", json={"user_id": "test_uid_mod_1", "role": "MODERATOR"}, headers={"Authorization": f"Bearer {mod_1_token}"})
    client.put("/api/admin/roles", json={"user_id": "test_uid_mod_2", "role": "MODERATOR"}, headers={"Authorization": f"Bearer {mod_2_token}"})
    client.put("/api/admin/roles", json={"user_id": "test_uid_admin_1", "role": "ADMIN"}, headers={"Authorization": f"Bearer {admin_token}"})

    # ----------------------------------------------------
    # 2. Customer Journey Validation
    # ----------------------------------------------------
    print("\nRunning Customer Journey Audit...")
    try:
        t = cust_tokens["cust_1"]
        h = {"Authorization": f"Bearer {t}"}
        # Profile creation
        resp = client.put("/api/auth/profile", json={"first_name": "Audit", "last_name": "Customer", "email": "audit_c1@example.com"}, headers=h)
        assert resp.status_code == 200
        # Address creation
        resp = client.post("/api/addresses", json={
            "title": "Home", "street_address": "123 Main St", "city": "Pune",
            "state": "Maharashtra", "postal_code": "411001", "latitude": 1.0, "longitude": 1.0, "is_default": True
        }, headers=h)
        assert resp.status_code == 201
        addr_id = resp.json()["id"]
        # Grocery submission
        resp = client.post("/api/orders", json={"address_id": addr_id, "items_text": "bread, butter"}, headers=h)
        assert resp.status_code == 201
        order_id = resp.json()["id"]
        # Order history
        resp = client.get("/api/orders", headers=h)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        results["customer_journey"] = "PASSED"
    except Exception as e:
        import traceback
        traceback.print_exc()
        results["customer_journey"] = f"FAILED: {str(e)}"

    # ----------------------------------------------------
    # 3. Moderator Journey Validation
    # ----------------------------------------------------
    print("Running Moderator Journey Audit...")
    try:
        mh = {"Authorization": f"Bearer {mod_1_token}"}
        # Queue visibility
        resp = client.get("/api/moderator/queue", headers=mh)
        assert resp.status_code == 200
        # Claim order
        resp = client.put(f"/api/moderator/orders/{order_id}/claim", headers=mh)
        assert resp.status_code == 200
        # Enter prices
        resp = client.put(f"/api/moderator/orders/{order_id}/prices", json={
            "prices": {"zepto": 100, "blinkit": 90, "instamart": 110, "bigbasket": 95, "jiomart": 105}
        }, headers=mh)
        assert resp.status_code == 200
        # Chat
        resp = client.post(f"/api/chat/test_uid_cust_1/send", json={"message": "Moderator text"}, headers=mh)
        assert resp.status_code == 200
        # Takeover
        resp = client.put(f"/api/moderator/chat/test_uid_cust_1/takeover", json={"ai_takeover_enabled": True}, headers=mh)
        assert resp.status_code == 200
        # Release takeover
        resp = client.put(f"/api/moderator/chat/test_uid_cust_1/takeover", json={"ai_takeover_enabled": False}, headers=mh)
        assert resp.status_code == 200
        results["moderator_journey"] = "PASSED"
    except Exception as e:
        import traceback
        traceback.print_exc()
        results["moderator_journey"] = f"FAILED: {str(e)}"

    # ----------------------------------------------------
    # 4. Admin Journey Validation
    # ----------------------------------------------------
    print("Running Admin Journey Audit...")
    try:
        ah = {"Authorization": f"Bearer {admin_token}"}
        # View orders
        resp = client.get("/api/moderator/queue", headers=ah)
        assert resp.status_code == 200
        # View chats
        resp = client.get("/api/chat/test_uid_cust_1/messages", headers=ah)
        assert resp.status_code == 200
        # Assign moderator
        resp = client.post("/api/admin/assign-moderator", json={"customer_id": "test_uid_cust_1", "moderator_id": "test_uid_mod_2"}, headers=ah)
        assert resp.status_code == 200
        # Reassign moderator
        resp = client.post("/api/admin/assign-moderator", json={"customer_id": "test_uid_cust_1", "moderator_id": "test_uid_mod_1"}, headers=ah)
        assert resp.status_code == 200
        # Disable AI globally
        resp = client.put("/api/admin/settings/ai-status", json={"ai_enabled": False}, headers=ah)
        assert resp.status_code == 200
        # Enable AI globally
        resp = client.put("/api/admin/settings/ai-status", json={"ai_enabled": True}, headers=ah)
        assert resp.status_code == 200
        # Complete/confirm customer checkout
        ch = {"Authorization": f"Bearer {cust_tokens['cust_1']}"}
        client.put(f"/api/customer/orders/{order_id}/confirm", headers=ch)
        # Enter financials
        resp = client.put(f"/api/admin/orders/{order_id}/place", json={"customer_paid": 120.0, "store_cost": 90.0}, headers=ah)
        assert resp.status_code == 200
        # View metrics
        resp = client.get("/api/admin/dashboard/metrics", headers=ah)
        assert resp.status_code == 200
        results["admin_journey"] = "PASSED"
    except Exception as e:
        import traceback
        traceback.print_exc()
        results["admin_journey"] = f"FAILED: {str(e)}"

    # ----------------------------------------------------
    # 5. Security Audit
    # ----------------------------------------------------
    print("Running Security Leak Audit...")
    security_violations = []
    try:
        ch = {"Authorization": f"Bearer {cust_tokens['cust_1']}"}
        mh2 = {"Authorization": f"Bearer {mod_2_token}"}
        
        # 1. Customer accessing moderator queue
        resp = client.get("/api/moderator/queue", headers=ch)
        if resp.status_code != 403:
            security_violations.append("Customer can view moderator queue!")
            
        # 2. Customer accessing global AI toggle
        resp = client.put("/api/admin/settings/ai-status", json={"ai_enabled": False}, headers=ch)
        if resp.status_code != 403:
            security_violations.append("Customer can change global AI status!")
            
        # 3. Moderator accessing admin assign-moderator
        resp = client.post("/api/admin/assign-moderator", json={"customer_id": "test_uid_cust_1", "moderator_id": "test_uid_mod_2"}, headers=mh2)
        if resp.status_code != 403:
            security_violations.append("Moderator can assign/reassign moderators!")
            
        # 4. User reading another user's chat messages
        resp = client.get("/api/chat/test_uid_cust_2/messages", headers=ch)
        if resp.status_code != 403:
            security_violations.append("Customer can read another customer's chat messages!")
            
        # 5. Moderator reading chat of non-assigned customer
        # We assigned customer 1 to mod 1, so mod 2 is NOT assigned.
        # Check if mod 2 can read customer 1's chat.
        resp = client.get("/api/chat/test_uid_cust_1/messages", headers=mh2)
        if resp.status_code != 403:
            security_violations.append("[BUG] Moderator can read chats of non-assigned customers!")
            
        # 6. Moderator writing to chat of non-assigned customer
        resp = client.post("/api/chat/test_uid_cust_1/send", json={"message": "Unassigned mod message"}, headers=mh2)
        if resp.status_code != 403:
            security_violations.append("[BUG] Moderator can send chat messages to non-assigned customers!")

        # 7. Moderator delivering order of non-assigned customer
        # Set order to placed first via admin
        # test_uid_mod_2 is unassigned, let's see if they can mark order delivered
        resp = client.put(f"/api/moderator/orders/{order_id}/deliver", headers=mh2)
        if resp.status_code != 403:
            security_violations.append("[BUG] Moderator can deliver orders of non-assigned customers!")
            
        # Now deliver the order successfully using the assigned moderator so database audit passes
        resp = client.put(f"/api/moderator/orders/{order_id}/deliver", headers={"Authorization": f"Bearer {mod_1_token}"})
        assert resp.status_code == 200
            
        if security_violations:
            results["security_audit"] = f"FAILED: {security_violations}"
        else:
            results["security_audit"] = "PASSED"
    except Exception as e:
        results["security_audit"] = f"FAILED: {str(e)}"

    # ----------------------------------------------------
    # 6. Database Audit
    # ----------------------------------------------------
    print("Running Database Audit...")
    try:
        db = database.SessionLocal()
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        # Verify status transitions
        # From pending_review -> reviewing -> awaiting_customer -> confirmed -> placed -> delivered
        # Since mod 2 completed the deliver endpoint step, the order status should be delivered
        assert order.status == "delivered"
        # Verify calculations
        # Manual prices: zepto: 100, blinkit: 90, instamart: 110, bigbasket: 95, jiomart: 105
        # Cheapest option is blinkit for 90.
        # Savings calculation: second best (bigbasket: 95) - cheapest (blinkit: 90) + store_disc (0) + snapsave_disc (0) = 5.0
        assert float(order.savings) == 5.0
        # Profit calculation: customer_paid (120) - store_cost (90) = 30.0
        assert float(order.profit) == 30.0
        # Completed orders count
        cust = db.query(models.User).filter(models.User.id == "test_uid_cust_1").first()
        assert cust.completed_orders_count == 1
        db.close()
        results["database_audit"] = "PASSED"
    except Exception as e:
        import traceback
        traceback.print_exc()
        results["database_audit"] = f"FAILED: {str(e)}"

    # ----------------------------------------------------
    # 7. Concurrency Audit (5 customers, 2 moderators, 1 admin)
    # ----------------------------------------------------
    print("Running Multi-User Concurrency Audit...")
    concurrency_errors = []
    
    def customer_action(cust_key, index):
        try:
            c_client = TestClient(app)
            token = cust_tokens[cust_key]
            h = {"Authorization": f"Bearer {token}"}
            # Address
            addr_resp = c_client.post("/api/addresses", json={
                "title": f"Home_{index}", "street_address": "123 St", "city": "Pune",
                "state": "MH", "postal_code": "411001", "latitude": 1.0, "longitude": 1.0, "is_default": True
            }, headers=h)
            addr_id = addr_resp.json()["id"]
            # Submit order
            order_resp = c_client.post("/api/orders", json={"address_id": addr_id, "items_text": f"items_{index}"}, headers=h)
            order_id = order_resp.json()["id"]
            # Send message
            c_client.post(f"/api/chat/test_uid_cust_{index}/send", json={"message": f"Hello from customer {index}"}, headers=h)
        except Exception as err:
            concurrency_errors.append(f"Customer {index} thread error: {str(err)}")

    threads = []
    for i in range(1, 6):
        t = threading.Thread(target=customer_action, args=(f"cust_{i}", i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    if concurrency_errors:
        results["concurrency_audit"] = f"FAILED: {concurrency_errors}"
    else:
        results["concurrency_audit"] = "PASSED"

    print("\n==================================================")
    print("AUDIT RESULTS SUMMARY")
    print("==================================================")
    for k, v in results.items():
        print(f"{k.upper()}: {v}")
    print("==================================================")

if __name__ == "__main__":
    run_audit()
