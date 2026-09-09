import sys
import os
from fastapi.testclient import TestClient

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.server import app, get_test_keys
import database
import models

def test_integration_flow():
    client = TestClient(app)
    
    print("\n==================================================")
    print("STARTING SNAPSAVE AUTHENTICATION E2E TEST FLOW")
    print("==================================================")

    # 1. Simulate phone verification and get signed ID Token
    test_phone = "+919876543210"
    test_uid = "test_uid_integration_99"
    
    print(f"\nStep 1: Simulating Phone Number OTP verification for {test_phone}...")
    # Hit our helper test token generator
    resp = client.get(f"/api/auth/test-token?phone=%2B919876543210&uid={test_uid}")
    assert resp.status_code == 200, "Failed to retrieve signed mock token"
    
    token_data = resp.json()
    id_token = token_data["idToken"]
    print(f"-> Obtained Firebase ID Token: {id_token[:55]}...")
    
    # 2. Authenticate against /api/auth/me to verify token on backend and create user
    print("\nStep 2: Sending request to GET /api/auth/me (Backend Verification & User Creation)...")
    headers = {"Authorization": f"Bearer {id_token}"}
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, f"Token verification failed: {resp.text}"
    
    user_data = resp.json()
    print("-> Backend user verified and returned user profile:")
    print(f"   UID: {user_data['id']}")
    print(f"   Phone Number: {user_data['phone_number']}")
    print(f"   Membership Tier: {user_data['membership_tier']}")
    print(f"   Completed Orders: {user_data['completed_orders_count']}")
    
    assert user_data["id"] == test_uid
    assert user_data["phone_number"] == test_phone

    # 3. Create a new delivery address
    print("\nStep 3: Creating a new delivery address via POST /api/addresses...")
    address_payload = {
        "title": "Home Office",
        "street_address": "456 Kakade Plaza, Karve Road",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "411004",
        "latitude": 18.51234,
        "longitude": 73.81234,
        "is_default": True
    }
    resp = client.post("/api/addresses", json=address_payload, headers=headers)
    assert resp.status_code == 201, f"Address creation failed: {resp.text}"
    address_data = resp.json()
    address_id = address_data["id"]
    print(f"-> Address created successfully! ID: {address_id}")
    print(f"   Title: {address_data['title']}, Street: {address_data['street_address']}, City: {address_data['city']}")

    # 4. Create an optimized order using the created address
    print("\nStep 4: Placing an order via POST /api/orders (Backend calculates price & verifies)...")
    order_payload = {
        "store": "zepto",
        "address_id": address_id,
        "items_text": "1kg basmati rice, 2 packets maggi, 500ml milk"
    }
    resp = client.post("/api/orders", json=order_payload, headers=headers)
    assert resp.status_code == 201, f"Order creation failed: {resp.text}"
    order_data = resp.json()
    order_id = order_data["id"]
    print(f"-> Order placed successfully! ID: {order_id}")
    print(f"   Store: {order_data['store']}")
    print(f"   Subtotal: Rs. {order_data['subtotal']}")
    print(f"   Final Price (Backend Calculated): Rs. {order_data['final_price']}")
    print(f"   Status: {order_data['status']}")

    # 5. Retrieve Order History
    print("\nStep 5: Fetching user order history via GET /api/orders...")
    resp = client.get("/api/orders", headers=headers)
    assert resp.status_code == 200, f"Failed to retrieve order history: {resp.text}"
    history = resp.json()
    print(f"-> Order history fetched successfully! Total orders found: {len(history)}")
    assert len(history) > 0
    assert history[0]["id"] == order_id

    # 6. Complete the order and verify Completed Orders Count increments
    print(f"\nStep 6: Completing the order via POST /api/orders/{order_id}/complete...")
    resp = client.post(f"/api/orders/{order_id}/complete")
    assert resp.status_code == 200, f"Order completion failed: {resp.text}"
    complete_data = resp.json()
    print(f"-> Order status updated: {complete_data['status']}")
    print(f"   Completed At: {complete_data['completed_at']}")

    # Re-fetch profile to verify count incremented
    print("\nStep 7: Verifying user profile completed_orders_count incremented...")
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    updated_user = resp.json()
    print(f"   Previous Completed Orders count: {user_data['completed_orders_count']}")
    print(f"   New Completed Orders count: {updated_user['completed_orders_count']}")
    assert updated_user["completed_orders_count"] == user_data["completed_orders_count"] + 1

    print("\n==================================================")
    print("SUCCESS: ALL E2E AUTHENTICATION CHECKS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    test_integration_flow()
