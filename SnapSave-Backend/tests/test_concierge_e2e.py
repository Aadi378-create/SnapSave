def test_concierge_workflow(client,actors,quoted):
    order_id=quoted["id"]
    customer=actors["customer"]["headers"]
    moderator=actors["moderator"]["headers"]
    messages=client.get(f"/api/chat/{actors['customer']['id']}/messages",params={"order_id":order_id},headers=customer).json()
    assert any(m["kind"]=="quote" and m["order_id"]==order_id for m in messages)
    assert client.put(f"/api/customer/orders/{order_id}/confirm",headers=customer,json={"revision":quoted["revision"]}).status_code==200
    qr=client.get(f"/api/orders/{order_id}/payment-qr",headers=customer)
    assert qr.status_code==200 and qr.content.startswith(b"\x89PNG")
    response=client.post(f"/api/moderator/orders/{order_id}/place",headers=moderator,json={"eta_mins":20,"payment_reference":"bank-reference","customer_paid":quoted["final_price"],"store_cost":200})
    assert response.status_code==200,response.text
    assert response.json()["eta_at"] and response.json()["payment_status"]=="verified"
    retry=client.post(f"/api/moderator/orders/{order_id}/place",headers=moderator,json={"eta_mins":20,"payment_reference":"bank-reference","customer_paid":quoted["final_price"],"store_cost":200})
    assert retry.status_code==200 and retry.json()["revision"]==response.json()["revision"]
    assert client.put(f"/api/moderator/orders/{order_id}/deliver",headers=moderator).status_code==200
    assert client.put(f"/api/moderator/orders/{order_id}/deliver",headers=moderator).status_code==200
    assert client.get("/api/auth/me",headers=customer).json()["completed_orders_count"]==1
    feedback={"order_id":order_id,"rating":5,"would_use_again":True}
    assert client.post("/api/feedback",headers=customer,json=feedback).status_code==201
    assert client.get(f"/api/orders/{order_id}",headers=customer).json()["status"]=="completed"
    assert client.post("/api/feedback",headers=customer,json=feedback).status_code==409
    assert client.get("/api/auth/me",headers=customer).json()["completed_orders_count"]==1
