def test_identity_and_auth_permissions(client,actors,order):
    headers=actors["customer"]["headers"]
    assert client.get("/api/auth/me",headers=headers).status_code==200
    assert client.post(f"/api/orders/{order['id']}/complete").status_code==401
    assert client.post(f"/api/orders/{order['id']}/complete",headers=actors["other"]["headers"]).status_code==403
    assert client.put("/api/admin/make-admin",json={"phone":actors["customer"]["phone"]}).status_code==401
    assert client.put("/api/admin/roles",json={"user_id":actors["customer"]["id"],"role":"ADMIN"},headers=headers).status_code==403
