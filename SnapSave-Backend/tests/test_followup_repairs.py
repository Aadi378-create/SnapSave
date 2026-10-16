"""Regression checks for legacy settlements and resource/offer failures."""
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy import text
import models
from database import engine
from migrations import migrate
from pricing.cart_split_optimizer import choose_best_cart,find_cheapest_per_item,find_single_store_best

@pytest.mark.parametrize("bad",[float("nan"),float("inf"),Decimal("NaN"),Decimal("Infinity"),-1,"not_available",None,True])
def test_invalid_store_offer_does_not_crash_or_beat_valid_offer(bad):
    offers={"milk":{"broken":bad,"valid":10}}
    result=choose_best_cart(offers)
    assert result["store"]=="valid" and result["total"]==45
    assert find_single_store_best(offers)==("valid",10)
    assert find_cheapest_per_item(offers)==({"milk":{"store":"valid","price":10}},10)

def test_missing_and_large_baskets_do_not_return_partial_allocations():
    offers={"milk":None,"bread":{"valid":10}}
    assert choose_best_cart(offers)["type"]=="unavailable"
    assert find_cheapest_per_item(offers)==({},0)
    assert find_single_store_best(offers)==(None,None)
    large={str(i):{"first":10,"second":20} for i in range(100)}
    cart,total=find_cheapest_per_item(large)
    assert len(cart)==100 and total==1000
    assert choose_best_cart(large)["type"]=="unavailable"

def test_candidate_filter_ignores_malformed_offers_before_price_comparison():
    from pricing.pivot_layer import resolve_best_candidate
    candidates=[None,"milk",{}, {"name":7,"price":1},{"name":"milk","price":"not_available"},{"name":"milk","price":float("nan")},{"name":"milk","price":10}]
    result=resolve_best_candidate("milk under 20","zepto",candidates)
    assert result["price"]==10
    assert candidates[-1]=={"name":"milk","price":10}

def test_browser_cleanup_attempts_every_resource_and_resets_state(monkeypatch):
    from core import browser_manager as manager
    calls=[]
    def fail(name):
        calls.append(name)
        raise RuntimeError(name+" cleanup failed")
    monkeypatch.setattr(manager._local,"context",SimpleNamespace(close=lambda:fail("context")),raising=False)
    monkeypatch.setattr(manager._local,"browser",SimpleNamespace(close=lambda:fail("browser")),raising=False)
    monkeypatch.setattr(manager._local,"playwright",SimpleNamespace(stop=lambda:fail("playwright")),raising=False)
    manager.close_browser()
    assert calls==["context","browser","playwright"]
    assert manager._local.context is None and manager._local.browser is None and manager._local.playwright is None
    manager.close_browser()
    assert len(calls)==3

def test_partial_browser_initialization_is_cleaned_up(monkeypatch):
    from core import browser_manager as manager
    calls=[]
    def launch(**kwargs):
        raise RuntimeError("launch failed")
    playwright=SimpleNamespace(chromium=SimpleNamespace(launch=launch),stop=lambda:calls.append("stop"))
    monkeypatch.setattr(manager,"sync_playwright",lambda:SimpleNamespace(start=lambda:playwright))
    for name in ("context","browser","playwright"):
        monkeypatch.setattr(manager._local,name,None,raising=False)
    with pytest.raises(RuntimeError,match="launch failed"):
        manager.get_browser()
    assert calls==["stop"] and manager._local.playwright is None

def test_scraper_cleanup_preserves_original_navigation_failure(monkeypatch):
    from core import store_scrapper_engine as scraper
    calls=[]
    def navigate(*args,**kwargs):
        raise TimeoutError("navigation failed")
    def close():
        raise RuntimeError("page close failed")
    page=SimpleNamespace(goto=navigate,close=close)
    monkeypatch.setattr(scraper,"get_browser",lambda:SimpleNamespace(new_page=lambda:page))
    monkeypatch.setattr(scraper,"close_browser",lambda:calls.append("cleanup"))
    with pytest.raises(TimeoutError,match="navigation failed"):
        scraper.run_scraper("https://store.invalid","input","card","name","price","milk")
    assert calls==["cleanup"]

@pytest.mark.parametrize("status",["placed","delivered","completed","cancelled"])
def test_legacy_settlement_migration_requires_review_without_inventing_receipt(client,db,order,status):
    row=db.get(models.Order,order["id"])
    row.status=status;row.customer_paid=205;row.payment_status="unpaid";row.confirmed_at=None
    db.commit()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM schema_migrations WHERE version=2"))
    migrate(engine)
    db.refresh(row)
    assert row.payment_status=="reconciliation_required" and row.payment_reference is None and row.payment_verified_at is None
    assert float(row.customer_paid)==205
    row.payment_status="unpaid";db.commit()
    migrate(engine)
    db.refresh(row)
    assert row.payment_status=="unpaid" # A restart must not undo an administrator's review.

def test_legacy_payment_survives_cancellation_and_can_be_refunded(client,actors,db,order):
    row=db.get(models.Order,order["id"])
    row.status="placed";row.customer_paid=205;row.payment_status="reconciliation_required";row.confirmed_at=None
    db.commit()
    admin=actors["admin"]["headers"]
    cancelled=client.put(f"/api/admin/orders/{row.id}/cancel",headers=admin)
    assert cancelled.json()["payment_status"]=="reconciliation_required"
    receipt=client.post(f"/api/admin/orders/{row.id}/reconcile-payment",headers=admin,json={"received":True,"reference":"legacy-bank-receipt","amount":205})
    assert receipt.status_code==200 and receipt.json()["payment_status"]=="refund_required"
    refund=client.post(f"/api/admin/orders/{row.id}/refund",headers=admin,json={"reference":"legacy-refund-receipt","amount":205})
    assert refund.status_code==200 and refund.json()["payment_status"]=="refunded"

@pytest.mark.parametrize("received",[True,False])
def test_legacy_delivered_payment_reconciliation_updates_actual_settlement(client,actors,db,order,received):
    row=db.get(models.Order,order["id"])
    row.status="delivered";row.customer_paid=205;row.store_cost=200;row.payment_status="reconciliation_required";row.confirmed_at=None
    db.commit()
    body={"received":True,"reference":"legacy-delivered-receipt","amount":205} if received else {"received":False}
    response=client.post(f"/api/admin/orders/{row.id}/reconcile-payment",headers=actors["admin"]["headers"],json=body)
    assert response.status_code==200,response.text
    assert response.json()["status"]=="delivered"
    assert response.json()["payment_status"]==("verified" if received else "unpaid")
    assert response.json()["customer_paid"]==(205 if received else 0)
    assert response.json()["profit"]==(5 if received else -200)
