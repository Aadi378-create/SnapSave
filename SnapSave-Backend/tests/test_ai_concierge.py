import threading
import pytest
import models
from database import SessionLocal
from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI

@pytest.fixture
def ai_order(db,order,monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_RESEARCH","true")
    enabled=db.get(models.SystemSetting,"ai_enabled")
    enabled.value="true"
    row=db.get(models.Order,order["id"])
    row.mode="AI";row.assigned_worker_type="AI"
    db.commit()
    def research(items,postal):
        return {"verified":True,"postal_code":postal,"source":"fixture verified catalog","items":[{**i,"line_total":100,"store":"zepto"} for i in items],"delivery_fee":0,"platform_fee":5}
    monkeypatch.setattr(AI,"research",staticmethod(research))
    monkeypatch.setattr("settings.research_provider",lambda: research)
    return row

def test_human_ticket_ai_cannot_act(db,ai_order):
    ai_order.mode="HUMAN"; db.commit()
    AI.process_ticket(ai_order.id,db);db.refresh(ai_order)
    assert not ai_order.is_ai_priced and ai_order.manual_prices is None

def test_verified_research_persists_items(db,ai_order):
    AI.process_ticket(ai_order.id,db);db.refresh(ai_order)
    assert ai_order.status=="awaiting_customer"
    assert float(ai_order.subtotal)==200
    assert all(i.line_total is not None for i in ai_order.items)

def test_human_edited_price_not_overwritten(db,ai_order):
    ai_order.manual_prices='{"items": [], "human":true}';ai_order.is_ai_priced=False;db.commit()
    AI.process_ticket(ai_order.id,db);db.refresh(ai_order)
    assert '"human":true' in ai_order.manual_prices

@pytest.mark.parametrize("action",["takeover","kill"])
def test_running_worker_loses_write_permission(client,actors,db,ai_order,monkeypatch,action):
    started=threading.Event();release=threading.Event();errors=[]
    original=AI.research
    def paused(items,postal):
        started.set()
        assert release.wait(5)
        return original(items,postal)
    monkeypatch.setattr(AI,"research",staticmethod(paused))
    identity=ai_order.id
    def worker():
        try:
            with SessionLocal() as session: AI.process_ticket(identity,session)
        except Exception as e:errors.append(e)
    t=threading.Thread(target=worker);t.start()
    try:
        assert started.wait(5)
        if action=="takeover":
            assert client.put(f"/api/moderator/orders/{identity}/takeover",headers=actors["admin"]["headers"]).status_code==200
            with SessionLocal() as session:
                row=session.get(models.Order,identity);row.manual_prices='{"human":true}';row.is_ai_priced=False;session.commit()
        else:
            assert client.put("/api/admin/settings/ai-status",headers=actors["admin"]["headers"],json={"ai_enabled":False}).status_code==200
            # Turning it on again still invalidates the previous generation.
            assert client.put("/api/admin/settings/ai-status",headers=actors["admin"]["headers"],json={"ai_enabled":True}).status_code==200
    finally:release.set();t.join(5)
    db.expire_all();row=db.get(models.Order,identity)
    assert not t.is_alive() and not errors
    assert not row.is_ai_priced and row.status=="pending_review"
    if action=="takeover":assert row.manual_prices=='{"human":true}'

@pytest.mark.parametrize("status",["cancelled","delivered","completed","awaiting_payment","placed"])
def test_ai_never_reopens_later_states(db,ai_order,status):
    ai_order.status=status;db.commit()
    AI.process_ticket(ai_order.id,db);db.refresh(ai_order)
    assert ai_order.status==status and not ai_order.is_ai_priced

def test_unavailable_research_falls_back_to_human(db,ai_order,monkeypatch):
    monkeypatch.setattr(AI,"research",staticmethod(lambda items,postal:None))
    AI.process_ticket(ai_order.id,db);db.refresh(ai_order)
    assert ai_order.mode=="HUMAN" and ai_order.ai_error and not ai_order.is_ai_priced

def test_research_requires_global_enable(client,actors,order,monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_RESEARCH","true")
    monkeypatch.setattr("settings.research_provider",lambda: lambda *_:None)
    response=client.put(f"/api/admin/orders/{order['id']}/mode",headers=actors["admin"]["headers"],json={"mode":"AI"})
    assert response.status_code==409

def test_saturated_worker_capacity_keeps_durable_ai_intent(db,ai_order):
    from api import server
    with server._ai_jobs_lock:
        server._ai_jobs.update(f"occupied-{n}" for n in range(20))
    try:
        server.submit_ai(ai_order.id)
        db.refresh(ai_order)
        assert ai_order.mode=="AI" and ai_order.assigned_worker_type=="AI"
        assert db.get(models.ResearchJob,ai_order.id).state=="queued"
    finally:
        with server._ai_jobs_lock:
            server._ai_jobs.clear()
