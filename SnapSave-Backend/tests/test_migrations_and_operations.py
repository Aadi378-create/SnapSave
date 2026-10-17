import json
from pathlib import Path
from sqlalchemy import create_engine,MetaData,Table,Column,inspect,text
import pytest
import models
from database import Base
from migrations import migrate

def test_old_schema_additions_and_price_conversion(tmp_path):
    legacy=create_engine("sqlite:///"+(tmp_path/"legacy.db").as_posix())
    metadata=MetaData()
    missing={"orders":{"mode","assigned_worker_type","is_ai_priced","taken_over_by","taken_over_at","ai_started_at","ai_stopped_at","revision","assigned_moderator_id","request_key","request_hash","payment_status","service_fee"},"order_items":{"line_total"}}
    for table in Base.metadata.sorted_tables:
        columns=[Column(c.name,c.type,primary_key=c.primary_key,nullable=c.nullable,default=c.default.arg if c.default is not None and not callable(c.default.arg) else None) for c in table.columns if c.name not in missing.get(table.name,set())]
        Table(table.name,metadata,*columns)
    metadata.create_all(legacy)
    with legacy.begin() as conn:
        conn.execute(text("INSERT INTO users(id,email,password_hash,role,completed_orders_count) VALUES ('customer','old@example.com','firebase','CUSTOMER',0)"))
        conn.execute(text("INSERT INTO orders(id,user_id,store,status,delivery_street,delivery_city,delivery_postal_code,subtotal,delivery_fee,platform_fee,final_price) VALUES ('order','customer','zepto','reviewing','Street','Delhi','110001',200,0,5,205)"))
        conn.execute(text("INSERT INTO order_items(id,order_id,name,quantity,unit_price,store) VALUES ('item','order','milk',2,200,'zepto')"))
    migrate(legacy)
    migrate(legacy) # Backfill must never divide legacy totals a second time.
    with legacy.connect() as conn:
        row=conn.execute(text("SELECT line_total,unit_price FROM order_items WHERE id='item'")).first()
        assert tuple(row)==(200,100)
        assert conn.execute(text("SELECT mode,revision FROM orders")).first()==("HUMAN",0)
    assert "taken_over_by" in {c["name"] for c in inspect(legacy).get_columns("orders")}
    legacy.dispose()

def test_retry_key_rejects_different_payload(client,actors,order):
    headers={**actors["customer"]["headers"],"Idempotency-Key":"different-body"}
    body={"address_id":order["address_id"],"items":[{"name":"milk","quantity":1}]}
    assert client.post("/api/orders",headers=headers,json=body).status_code==201
    body["items"][0]["name"]="bread"
    assert client.post("/api/orders",headers=headers,json=body).status_code==409

def test_refund_record_requires_actual_verified_payment(client,actors,quoted):
    oid=quoted["id"];admin=actors["admin"]["headers"]
    customer=actors["customer"]["headers"]
    client.put(f"/api/customer/orders/{oid}/confirm",headers=customer,json={"revision":quoted["revision"]})
    response=client.post(f"/api/moderator/orders/{oid}/place",headers=admin,json={"eta_mins":20,"payment_reference":"paid-ref","customer_paid":quoted["final_price"],"store_cost":200})
    assert response.status_code==200
    cancelled=client.put(f"/api/admin/orders/{oid}/cancel",headers=admin)
    assert cancelled.json()["payment_status"]=="refund_required"
    response=client.post(f"/api/admin/orders/{oid}/refund",headers=admin,json={"amount":1,"reference":"refund-ref"})
    assert response.status_code==422
    response=client.post(f"/api/admin/orders/{oid}/refund",headers=admin,json={"amount":quoted["final_price"],"reference":"refund-ref"})
    assert response.status_code==200 and response.json()["payment_status"]=="refunded"
    assert client.post(f"/api/admin/orders/{oid}/refund",headers=admin,json={"amount":quoted["final_price"],"reference":"refund-ref"}).status_code==409

def test_payment_received_before_cancellation_can_be_reconciled_and_refunded(client,actors,quoted):
    oid=quoted["id"];admin=actors["admin"]["headers"]
    client.put(f"/api/customer/orders/{oid}/confirm",headers=actors["customer"]["headers"],json={"revision":quoted["revision"]})
    cancelled=client.put(f"/api/admin/orders/{oid}/cancel",headers=admin)
    assert cancelled.json()["payment_status"]=="reconciliation_required"
    route=f"/api/admin/orders/{oid}/reconcile-payment"
    body={"received":True,"reference":"partial-bank-payment","amount":100}
    assert client.post(route,headers=actors["customer"]["headers"],json=body).status_code==403
    response=client.post(route,headers=admin,json=body)
    assert response.status_code==200 and response.json()["customer_paid"]==100 and response.json()["payment_status"]=="refund_required"
    assert client.post(route,headers=admin,json=body).status_code==200
    refund=client.post(f"/api/admin/orders/{oid}/refund",headers=admin,json={"amount":100,"reference":"partial-refund"})
    assert refund.status_code==200 and refund.json()["payment_status"]=="refunded"

def test_payment_reference_cannot_settle_two_orders(client,actors,quoted):
    admin=actors["admin"]["headers"];customer=actors["customer"]["headers"]
    client.put(f"/api/customer/orders/{quoted['id']}/confirm",headers=customer,json={"revision":quoted["revision"]})
    first=client.post(f"/api/moderator/orders/{quoted['id']}/place",headers=admin,json={"eta_mins":20,"payment_reference":"same-bank-receipt","customer_paid":quoted["final_price"],"store_cost":200})
    assert first.status_code==200
    second=client.post("/api/orders",headers=customer,json={"address_id":quoted["address_id"],"items":[{"name":"Eggs","quantity":1}]}).json()
    preview=client.post(f"/api/moderator/orders/{second['id']}/preview-quote",headers=admin,json={"items":[{"item_id":second["items"][0]["id"],"line_total":200,"store":"zepto"}]}).json()
    quote=client.post(f"/api/moderator/orders/{second['id']}/price",headers=admin,json=preview).json()
    client.put(f"/api/customer/orders/{second['id']}/confirm",headers=customer,json={"revision":quote["revision"]})
    response=client.post(f"/api/moderator/orders/{second['id']}/place",headers=admin,json={"eta_mins":20,"payment_reference":"same-bank-receipt","customer_paid":quote["final_price"],"store_cost":200})
    assert response.status_code==409
    assert client.get(f"/api/orders/{second['id']}",headers=customer).json()["status"]=="awaiting_payment"

def test_support_open_state_survives_long_threads(client,actors,db):
    customer=actors["customer"]["id"]
    db.add(models.HelpMessage(user_id=customer,sender_role="CUSTOMER",message="Unresolved original request",is_resolved=False))
    for n in range(210):db.add(models.HelpMessage(user_id=customer,sender_role="ADMIN",message=f"Reply {n}",is_resolved=True))
    db.commit()
    inbox=client.get("/api/admin/help",headers=actors["admin"]["headers"]).json()
    assert len(inbox)==1 and inbox[0]["open"]
    assert len(inbox[0]["messages"])==1

def test_cache_bounds_copy_and_quantity_keys():
    from core import price_cache as pc,result_cache as rc
    pc.clear_cache();rc.CACHE.clear()
    original=[{"price":1}]
    pc.save_price("milk","zepto",original,"110001",2)
    original[0]["price"]=99
    assert pc.get_cached_price("milk","zepto","110001",2)==[{"price":1}]
    assert pc.get_cached_price("milk","zepto","110001",1) is None
    for i in range(1100):rc.save_cache(str(i),i)
    assert len(rc.CACHE)<=rc.MAX_ENTRIES

def test_hosting_contains_only_assets_and_explicit_backend(tmp_path):
    import importlib.util
    source=Path(__file__).resolve().parents[2]/"SnapSave-FRONTEND/prepare_hosting.py"
    spec=importlib.util.spec_from_file_location("hosting",source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError):module.prepare("http://localhost:8000",tmp_path/"invalid")
    output=module.prepare("https://api.example.com",tmp_path/"dist")
    assert "https://api.example.com" in (output/"config.js").read_text()
    for asset in ("phone-login.js","phone-login.css","conversation.js","conversation.css"):
        assert (output/asset).is_file()
    assert not list(output.glob("*.py")) and not list(output.glob("*.txt"))

def test_request_body_limit(client,actors):
    response=client.post("/api/help",headers=actors["customer"]["headers"],content=json.dumps({"message":"x"*70000}))
    assert response.status_code==413

def test_empty_text_and_missing_price_are_validation_errors(client,actors,order):
    response=client.post("/api/help",headers=actors["customer"]["headers"],json={"message":"   "})
    assert response.status_code==422
    rows=[{"item_id":i["id"],"store":"zepto"} for i in order["items"]]
    response=client.post(f"/api/moderator/orders/{order['id']}/preview-quote",headers=actors["admin"]["headers"],json={"items":rows})
    assert response.status_code==422

def test_mutation_rate_limit(client,actors):
    headers=actors["customer"]["headers"]
    responses=[client.post("/api/help",headers=headers,json={"message":"Support request"}).status_code for _ in range(125)]
    assert responses[-1]==429

def test_local_json_updates_are_atomic_and_do_not_lose_thread_writes(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from core import user_preference_store as preferences
    from pricing import price_history as history
    monkeypatch.setattr(preferences,"PREF_FILE",tmp_path/"prefs.json")
    monkeypatch.setattr(history,"DB_PATH",tmp_path/"prices.json")
    def record(n):
        preferences.record_selection("milk","Amul")
        history.record_price("milk","zepto",n)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(record,range(30)))
    assert preferences.get_preferences("milk")["Amul"]==30
    assert len(history.load_db()["milk"]["zepto"])==30
    assert not list(tmp_path.glob("*.tmp"))

def test_optimizer_does_not_assume_promotions_or_drop_unserviceable_items(monkeypatch):
    from pricing.cart_optimizer import calculate_final_price
    from pricing.pricing_engine import run_pricing_engine
    monkeypatch.setenv("STORE_SERVICEABILITY",json.dumps({"110001":["zepto"]}))
    result=calculate_final_price("zepto",2000)
    assert result["final_price"]==2005 and result["snapsave_discount"]==0
    result=run_pricing_engine({"milk":[{"store":"zepto","price":100}],"bread":[{"store":"blinkit","price":100}]},"110001")
    assert result["cart"]=={} and result["savings"]==0
    from core.aggregator import build_store_totals
    assert build_store_totals([{"prices":{"zepto":100,"blinkit":110}},{"prices":{"blinkit":100}}])=={"blinkit":210}
    assert calculate_final_price("zepto",float("nan")) is None
