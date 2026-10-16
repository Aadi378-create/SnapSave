from datetime import datetime, timedelta
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import event, text
import pytest
import models
from database import engine, SessionLocal
from core.order_policy import change_order
from core.cart_builder import build_cart_from_text
from core.query_parser import parse_query
from pricing.cart_optimizer import optimize_cart,calculate_final_price
from pricing.cart_split_optimizer import choose_best_cart
from pricing.pivot_layer import resolve_best_candidate
from time_utils import utcnow

def test_dev_auth_disabled_in_production(client,monkeypatch):
    monkeypatch.setenv("APP_ENV","production")
    assert client.get("/api/auth/test-token",params={"phone":"+919999999999","uid":"admin"}).status_code==404

def test_no_roles_from_uid_or_reserved_phone(client):
    token=client.get("/api/auth/test-token",params={"phone":"+919999999999","uid":"test_admin"}).json()["idToken"]
    assert client.get("/api/auth/me",headers={"Authorization":"Bearer "+token}).json()["role"]=="CUSTOMER"

def test_dev_phone_identities_distinct(client):
    users=[]
    for phone in ["+911111111111","+912222222222"]:
        token=client.get("/api/auth/test-token",params={"phone":phone}).json()["idToken"]
        users.append(client.get("/api/auth/me",headers={"Authorization":"Bearer "+token}).json()["id"])
    assert users[0]!=users[1]

def test_unknown_coordinates_not_invented(client,actors,order):
    address=client.get("/api/addresses",headers=actors["customer"]["headers"]).json()[0]
    assert address["city"]=="Delhi" and address["latitude"] is None and address["longitude"] is None

def test_unassigned_actions_denied(client,actors,quoted):
    headers=actors["unassigned"]["headers"]
    for route in ["takeover","deliver"]:
        assert client.put(f"/api/moderator/orders/{quoted['id']}/{route}",headers=headers).status_code==403
    assert client.post(f"/api/moderator/orders/{quoted['id']}/place",headers=headers,json={"eta_mins":20,"payment_reference":"test-ref","customer_paid":quoted["final_price"],"store_cost":200}).status_code==403
    assert client.get(f"/api/orders/{quoted['id']}",headers=headers).status_code==403

def test_invalid_quote_and_missing_items(client,actors,quoted):
    rows=[{"item_id":i["id"],"line_total":100,"store":"zepto"} for i in quoted["items"]]
    headers=actors["moderator"]["headers"]
    payload=client.post(f"/api/moderator/orders/{quoted['id']}/preview-quote",headers=headers,json={"items":rows}).json()
    for changes in [{"final_price":-999},{"items":[]},{"subtotal":1},{"final_price":1},{"items":[rows[0],rows[0]]},{"service_fee":float("inf")}]:
        if "service_fee" in changes:continue # JSON cannot represent Infinity portably.
        response=client.post(f"/api/moderator/orders/{quoted['id']}/price",headers=headers,json={**payload,**changes})
        assert response.status_code==422,response.text

def test_price_semantics_and_mixed_delivery(client,actors,order):
    headers=actors["admin"]["headers"]
    rows=[{"item_id":i["id"],"line_total":150,"store":store} for i,store in zip(order["items"],["zepto","blinkit"])]
    payload=client.post(f"/api/moderator/orders/{order['id']}/preview-quote",headers=headers,json={"items":rows}).json()
    assert payload["delivery_fee"]==70
    response=client.post(f"/api/moderator/orders/{order['id']}/price",headers=headers,json=payload).json()
    milk=next(i for i in response["items"] if i["quantity"]==2)
    assert milk["line_total"]==150 and milk["unit_price"]==75

def test_stale_and_expired_confirmation(client,actors,quoted,db):
    route=f"/api/customer/orders/{quoted['id']}/confirm"
    headers=actors["customer"]["headers"]
    assert client.put(route,headers=headers,json={"revision":quoted["revision"]-1}).status_code==409
    row=db.get(models.Order,quoted["id"]);row.quote_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert client.put(route,headers=headers,json={"revision":quoted["revision"]}).status_code==409

def test_order_retry_idempotent(client,actors,order):
    headers={**actors["customer"]["headers"],"Idempotency-Key":"retry-1"}
    payload={"address_id":order["address_id"],"items":[{"name":"Milk","quantity":1}]}
    first=client.post("/api/orders",headers=headers,json=payload)
    second=client.post("/api/orders",headers=headers,json=payload)
    assert first.status_code==201 and second.status_code==201
    assert first.json()["id"]==second.json()["id"]

def test_optimistic_write_rejects_stale_session(db,order):
    with SessionLocal() as first, SessionLocal() as second:
        a=first.get(models.Order,order["id"]);b=second.get(models.Order,order["id"])
        change_order(first,a,status="reviewing");first.commit()
        with pytest.raises(HTTPException) as error:change_order(second,b,status="cancelled")
        assert error.value.status_code==409

def test_feedback_requires_delivery(client,actors,order):
    assert client.post("/api/feedback",headers=actors["customer"]["headers"],json={"order_id":order["id"],"rating":5,"would_use_again":True}).status_code==409

def test_chat_is_order_scoped_and_human_sends_no_ai(client,actors,quoted):
    headers=actors["customer"]["headers"]
    customer=actors["customer"]["id"]
    assert client.post(f"/api/chat/{customer}/send",headers=headers,json={"order_id":quoted["id"],"message":"Can you check the milk brand?"}).status_code==200
    msgs=client.get(f"/api/chat/{customer}/messages",headers=headers,params={"order_id":quoted["id"]}).json()
    assert msgs and all(m["order_id"]==quoted["id"] for m in msgs) and not any(m["sender_role"]=="AI" for m in msgs)
    assert client.get(f"/api/chat/{customer}/messages",headers=actors["moderator"]["headers"],params={"order_id":quoted["id"]}).status_code==200
    after=client.get(f"/api/chat/{customer}/messages",headers=headers,params={"order_id":quoted["id"],"after_id":msgs[-1]["id"]}).json()
    assert after==[]

def test_no_mock_live_quotes(client,actors):
    assert client.post("/optimize-cart",headers=actors["customer"]["headers"],json={"items":"milk","location":"Pune"}).status_code==503

def test_parser_and_product_match():
    assert len(build_cart_from_text("milk and bread; eggs"))==3
    assert parse_query("1.5kg rice")["volume"]==1.5
    assert parse_query("1 litre milk")["unit"]=="l"
    assert resolve_best_candidate("milk","zepto",[{"name":"Dishwashing Detergent","price":25}]) is None
    assert resolve_best_candidate("Amul milk 1L","zepto",[{"name":"Amul curd 1L","price":25}]) is None
    assert resolve_best_candidate("milk 1L","zepto",[{"name":"Mango juice 1L","price":25}]) is None
    assert resolve_best_candidate("milk","zepto",[{"name":"Milk","price":float("nan")}]) is None

def test_optimizer_requires_coverage_and_counts_delivery():
    result=optimize_cart({"milk":[{"store":"zepto","price":100},{"store":"blinkit","price":110}],"bread":[{"store":"blinkit","price":100}]})
    assert result["best_store"]["store"]=="blinkit"
    result=choose_best_cart({"milk":{"zepto":150,"blinkit":170},"bread":{"zepto":170,"blinkit":150}})
    assert result["type"]=="single_store" and result["total"]==320
    assert choose_best_cart({})["type"]=="unavailable"
    p=calculate_final_price("zepto",1000)
    assert p["final_price"]==p["cart_total"]+p["delivery_fee"]+p["platform_fee"]-p["store_discount"]-p["snapsave_discount"]-p["zepto_cash"]-p["hsbc_discount"]

def test_history_query_count_bounded(client,actors,order,db):
    for n in range(60):
        row=models.Order(user_id=actors["customer"]["id"],store="pending",status="completed",delivery_street="Street",delivery_city="Delhi",delivery_postal_code="110001",subtotal=0,delivery_fee=0,platform_fee=0,final_price=0)
        db.add(row);db.flush();db.add(models.OrderItem(order_id=row.id,name="milk",quantity=1))
    db.commit()
    statements=[]
    def track(conn,cursor,statement,*args):
        if statement.lstrip().upper().startswith("SELECT"):statements.append(statement)
    event.listen(engine,"before_cursor_execute",track)
    try:
        response=client.get("/api/orders?limit=50",headers=actors["customer"]["headers"])
        assert response.status_code==200 and len(response.json())==50
        assert len(statements)<=4,len(statements)
    finally:event.remove(engine,"before_cursor_execute",track)
    with engine.connect() as conn:assert conn.execute(text("PRAGMA foreign_keys")).scalar()==1

def test_completed_revenue_retained(client,actors,order,db):
    row=db.get(models.Order,order["id"]);row.status="completed";row.customer_paid=250;row.profit=25;row.savings=10;row.payment_verified_at=utcnow();db.commit()
    metrics=client.get("/api/admin/dashboard/metrics",headers=actors["admin"]["headers"]).json()
    assert metrics["revenue"]==250 and metrics["profit"]==25 and metrics["total_savings_delivered"]==10
