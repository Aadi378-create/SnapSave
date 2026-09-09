import sys
import os
from fastapi.testclient import TestClient

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.server import app
import database
import models

def test_concierge_workflow():
    client = TestClient(app)
    
    print("\n==================================================")
    print("STARTING SNAPSAVE HUMAN-CONCIERGE MVP E2E FLOW")
    print("==================================================")

    # 1. Generate Firebase tokens for Customer, Moderator, Admin
    print("\nStep 1: Simulating Phone verification tokens...")
    
    cust_uid = "test_uid_customer_concierge"
    cust_phone = "+911111111111"
    resp = client.get(f"/api/auth/test-token?phone=%2B911111111111&uid={cust_uid}")
    assert resp.status_code == 200
    cust_token = resp.json()["idToken"]
    
    mod_uid = "test_uid_moderator_concierge"
    mod_phone = "+912222222222"
    resp = client.get(f"/api/auth/test-token?phone=%2B912222222222&uid={mod_uid}")
    assert resp.status_code == 200
    mod_token = resp.json()["idToken"]

    admin_uid = "test_uid_admin_concierge"
    admin_phone = "+913333333333"
    resp = client.get(f"/api/auth/test-token?phone=%2B913333333333&uid={admin_uid}")
    assert resp.status_code == 200
    admin_token = resp.json()["idToken"]

    cust_headers = {"Authorization": f"Bearer {cust_token}"}
    mod_headers = {"Authorization": f"Bearer {mod_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Initialize users in database via GET /api/auth/me
    client.get("/api/auth/me", headers=cust_headers)
    client.get("/api/auth/me", headers=mod_headers)
    client.get("/api/auth/me", headers=admin_headers)

    # 2. Assign roles
    print("\nStep 2: Assigning roles via PUT /api/admin/roles...")
    
    # Set moderator role
    resp = client.put("/api/admin/roles", json={"user_id": mod_uid, "role": "MODERATOR"}, headers=mod_headers)
    assert resp.status_code == 200, f"Failed to set moderator role: {resp.text}"
    
    # Set admin role
    resp = client.put("/api/admin/roles", json={"user_id": admin_uid, "role": "ADMIN"}, headers=admin_headers)
    assert resp.status_code == 200, f"Failed to set admin role: {resp.text}"

    # Verify admin and moderator lists
    resp = client.get("/api/admin/moderators", headers=admin_headers)
    assert resp.status_code == 200
    mods = resp.json()
    print(f"-> Active Moderators/Admins: {mods}")
    assert len(mods) >= 2

    # 3. Customer creates address
    print("\nStep 3: Creating customer address...")
    addr_resp = client.post("/api/addresses", json={
        "title": "Home",
        "street_address": "Flat 101, Kakade Residency",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411004",
        "latitude": 18.52,
        "longitude": 73.85,
        "is_default": True
    }, headers=cust_headers)
    assert addr_resp.status_code == 201
    address_id = addr_resp.json()["id"]

    # 4. Customer submits grocery list (Order)
    print("\nStep 4: Customer places order (bypassing scrapers)...")
    order_resp = client.post("/api/orders", json={
        "address_id": address_id,
        "items_text": "2kg wheat flour, 1 packet milk, 1kg sugar"
    }, headers=cust_headers)
    assert order_resp.status_code == 201, f"Order placement failed: {order_resp.text}"
    order_data = order_resp.json()
    print("ORDER DATA RECEIVED:", order_data)
    order_id = order_data["id"]
    print(f"-> Order placed successfully! ID: {order_id}, Status: {order_data['status']}")
    assert order_data["status"] == "pending_review"
    assert order_data["store"] == "pending"

    # 5. Moderator views queue and claims the ticket
    print("\nStep 5: Moderator claims the order from the queue...")
    queue_resp = client.get("/api/moderator/queue", headers=mod_headers)
    assert queue_resp.status_code == 200
    queue = queue_resp.json()
    print(f"-> Queue size: {len(queue)}. Claiming order {order_id}...")
    
    claim_resp = client.put(f"/api/moderator/orders/{order_id}/claim", headers=mod_headers)
    assert claim_resp.status_code == 200, f"Claim failed: {claim_resp.text}"
    print(f"-> Claimed order! status is now: {claim_resp.json()['status']}")
    assert claim_resp.json()["status"] == "reviewing"

    # Verify customer assigned moderator
    cust_check_resp = client.get("/api/admin/customers", headers=admin_headers)
    cust_list = cust_check_resp.json()
    customer_record = next((c for c in cust_list if c["id"] == cust_uid), None)
    assert customer_record is not None
    assert customer_record["assigned_moderator_id"] == mod_uid
    print(f"-> Verified customer assigned moderator: {customer_record['assigned_moderator_id']}")

    # 6. Moderator inputs manual prices
    print("\nStep 6: Moderator enters manual prices...")
    prices_payload = {
        "prices": {
            "zepto": 300,
            "blinkit": 280,
            "instamart": 320,
            "bigbasket": 270
        }
    }
    prices_resp = client.put(f"/api/moderator/orders/{order_id}/prices", json=prices_payload, headers=mod_headers)
    assert prices_resp.status_code == 200, f"Prices entry failed: {prices_resp.text}"
    prices_data = prices_resp.json()
    print(f"-> Prices calculated: Cheapest: {prices_data['cheapest_store']} (Rs. {prices_data['subtotal']})")
    print(f"   Final Price (after fee/discount logic): Rs. {prices_data['final_price']}")
    print(f"   Savings: Rs. {prices_data['savings']}")
    print(f"   New Order status: {prices_data['status']}")
    
    assert prices_data["cheapest_store"] == "bigbasket"
    assert prices_data["status"] == "awaiting_customer"

    # Verify a store comparison message was entered in chat
    chat_resp = client.get(f"/api/chat/{cust_uid}/messages", headers=cust_headers)
    assert chat_resp.status_code == 200
    chat_msgs = chat_resp.json()
    assert any("Store Comparison Totals" in msg["message"] for msg in chat_msgs)
    print("-> Verified store comparison totals message is present in the customer chat.")

    # 7. Customer confirms the order
    print("\nStep 7: Customer confirms the order...")
    confirm_resp = client.put(f"/api/customer/orders/{order_id}/confirm", headers=cust_headers)
    assert confirm_resp.status_code == 200
    print(f"-> Order status: {confirm_resp.json()['status']}")
    assert confirm_resp.json()["status"] == "confirmed"

    # 8. Admin places order manually & inputs actual cost details
    print("\nStep 8: Admin places order and records financials...")
    place_resp = client.put(f"/api/admin/orders/{order_id}/place", json={
        "customer_paid": 320.00,
        "store_cost": 270.00
    }, headers=admin_headers)
    assert place_resp.status_code == 200, f"Place order failed: {place_resp.text}"
    place_data = place_resp.json()
    print(f"-> Order status: {place_data['status']}, Recorded Profit: Rs. {place_data['profit']}")
    assert place_data["status"] == "placed"
    assert place_data["profit"] == 50.00

    # 9. Moderator marks order delivered
    print("\nStep 9: Moderator marks order delivered...")
    deliver_resp = client.put(f"/api/moderator/orders/{order_id}/deliver", headers=mod_headers)
    assert deliver_resp.status_code == 200, f"Delivery marking failed: {deliver_resp.text}"
    print(f"-> Order status: {deliver_resp.json()['status']}")
    assert deliver_resp.json()["status"] == "delivered"

    # Check completed_orders_count incremented
    me_resp = client.get("/api/auth/me", headers=cust_headers)
    assert me_resp.json()["completed_orders_count"] == 1
    print(f"-> Verified customer completed_orders_count is: {me_resp.json()['completed_orders_count']}")

    # 10. Test AI Takeover (Mute chat)
    print("\nStep 10: Testing Live Chat and Takeover System...")
    
    # Customer sends message (Takeover OFF, AI Enabled by default)
    send_resp = client.post(f"/api/chat/{cust_uid}/send", json={"message": "Help me find soap"}, headers=cust_headers)
    assert send_resp.status_code == 200
    
    # Check messages: there should be an automatic AI logged response
    chat_resp = client.get(f"/api/chat/{cust_uid}/messages", headers=cust_headers)
    messages = chat_resp.json()
    assert any(m["sender_role"] == "AI" and "concierge moderator will review" in m["message"] for m in messages)
    print("-> AI responded automatically when takeover was OFF.")

    # Enable takeover (Mute AI for this customer)
    takeover_resp = client.put(f"/api/moderator/chat/{cust_uid}/takeover", json={"ai_takeover_enabled": True}, headers=mod_headers)
    assert takeover_resp.status_code == 200
    print("-> Moderator enabled takeover (muted AI).")

    # Clear chat messages for cleaner assertion
    # Customer sends message again
    send_resp = client.post(f"/api/chat/{cust_uid}/send", json={"message": "I need bread"}, headers=cust_headers)
    assert send_resp.status_code == 200
    
    # Check messages: there should be NO new AI response after "I need bread"
    chat_resp = client.get(f"/api/chat/{cust_uid}/messages", headers=cust_headers)
    messages_after = chat_resp.json()
    bread_index = next(idx for idx, m in enumerate(messages_after) if "I need bread" in m["message"])
    # Any messages after "I need bread"?
    subsequent_messages = messages_after[bread_index + 1:]
    assert not any(m["sender_role"] == "AI" for m in subsequent_messages), "AI should have been muted during takeover"
    print("-> Verified AI remained silent (muted) when takeover was ON.")

    # 11. Test Global AI Switch
    print("\nStep 11: Testing Global AI Switch...")
    
    # Toggle AI globally OFF
    switch_resp = client.put("/api/admin/settings/ai-status", json={"ai_enabled": False}, headers=admin_headers)
    assert switch_resp.status_code == 200
    print("-> Admin toggled global AI switch to OFF.")

    # Verify settings endpoint returns disabled
    status_resp = client.get("/api/admin/settings/ai-status")
    assert status_resp.json()["ai_enabled"] is False

    # 12. Verify Admin Dashboard Metrics
    print("\nStep 12: Fetching Admin Dashboard metrics...")
    metrics_resp = client.get("/api/admin/dashboard/metrics", headers=admin_headers)
    assert metrics_resp.status_code == 200, f"Dashboard metrics failed: {metrics_resp.text}"
    metrics = metrics_resp.json()
    print("-> Received Dashboard Metrics:")
    print(f"   Orders Today: {metrics['orders_today']}")
    print(f"   Revenue Today: Rs. {metrics['revenue_today']}")
    print(f"   Profit Today: Rs. {metrics['profit_today']}")
    print(f"   Total Customers: {metrics['total_customers']}")
    print(f"   Total Savings: Rs. {metrics['total_savings_delivered']}")
    
    assert metrics["orders_today"] >= 1
    assert metrics["revenue_today"] == 320.00
    assert metrics["profit_today"] == 50.00
    assert metrics["total_customers"] >= 1

    print("\n==================================================")
    print("SUCCESS: ALL HUMAN-CONCIERGE MVP E2E FLOWS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    test_concierge_workflow()
