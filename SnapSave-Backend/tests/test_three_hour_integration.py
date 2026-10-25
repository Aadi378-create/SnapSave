"""Interactions between research evidence, manual pricing and refreshed ticket UI."""
import json
import pytest
import models
from tests.test_browser import browser, open_app
from tests.test_catalog_research import capture


def evidence(client, actors, order):
    plan=client.get(f"/api/moderator/orders/{order['id']}/research-location",headers=actors['admin']['headers']).json()
    context={k:plan[k] for k in ('order_id','revision','postal_code')}
    return {'revision':plan['revision'],'captures':[capture(research_context=context,
        location_context={'staff_confirmed':True,'attested_postal_code':plan['postal_code']})]}


def test_import_keeps_unsaved_line_prices_and_labels_evidence_as_unverified(browser,client,actors,order,db):
    body=evidence(client,actors,order)
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        page.locator('.pi-price').first.fill('123.45')
        page.locator('.pi-store').first.select_option('zepto')
        page.get_by_label('Import retailer capture JSON').set_input_files({'name':'capture.json','mimeType':'application/json','buffer':json.dumps(body['captures']).encode()})
        page.wait_for_function("document.querySelector('#research-evidence-panel').textContent.includes('staff confirmed postcode')")
        assert page.locator('.pi-price').first.input_value()=='123.45'
        assert page.locator('.pi-store').first.input_value()=='zepto'
        assert 'requires human review' in page.locator('#ai-pricing-label').inner_text()
        assert not errors,errors
    finally:page.close()


@pytest.mark.parametrize('field',['price','store'])
def test_editing_line_invalidates_quote_preview(browser,client,actors,quoted,db,field):
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        page.locator('#btn-preview-quote').click()
        page.locator('#quote-preview-block').wait_for(state='visible')
        if field=='price':page.locator('.pi-price').first.fill('321')
        else:page.locator('.pi-store').first.select_option('blinkit')
        assert page.locator('#quote-preview-block').is_hidden()
        page.evaluate('window.submitPrices()')
        db.expire_all()
        assert float(db.get(models.Order,quoted['id']).subtotal)==float(quoted['subtotal'])
        assert not errors,errors
    finally:page.close()


def test_imported_evidence_does_not_count_as_approved_human_prices(client,actors,order,db,monkeypatch):
    body=evidence(client,actors,order)
    headers=actors['admin']['headers'];base=f"/api/moderator/orders/{order['id']}"
    assert client.post(base+'/research-evidence',headers=headers,json=body).status_code==200
    monkeypatch.setattr('api.server.research_enabled',lambda:True)
    monkeypatch.setattr('api.server.submit_ai',lambda *_:None)
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    response=client.put(f"/api/admin/orders/{order['id']}/mode",headers=headers,json={'mode':'HYBRID'})
    assert response.status_code==200,response.text
    row=db.get(models.Order,order['id']);db.refresh(row)
    row.manual_prices=json.dumps({'items':[{'item_id':order['items'][0]['id'],'line_total':123}],
        'research_draft':json.loads(row.manual_prices)['research_draft']})
    row.is_ai_priced=False;db.commit()
    assert client.put(f"/api/admin/orders/{order['id']}/delegate",headers=headers,json={'assigned_worker_type':'AI'}).status_code==409


def test_edits_during_preview_request_discard_the_stale_response(browser,client,actors,quoted,db):
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        page.wait_for_function("document.querySelectorAll('.pi-price').length>0")
        page.evaluate('''()=>{
            const original=window.fetch;
            window.fetch=async(url,options)=>{
                if(String(url).endsWith('/preview-quote'))await new Promise(resolve=>window.releasePreview=resolve);
                return original(url,options);
            };
            window.previewQuote();
        }''')
        page.wait_for_function('!!window.releasePreview')
        page.locator('.pi-price').first.fill('321')
        page.evaluate('window.releasePreview()')
        page.wait_for_function("!document.querySelector('#btn-preview-quote').disabled")
        assert page.locator('#quote-preview-block').is_hidden()
        assert not errors,errors
    finally:page.close()


def test_price_drafts_stay_with_their_ticket_and_clear_on_logout(browser,client,actors,order,db):
    second=client.post('/api/orders',headers=actors['customer']['headers'],json={
        'address_id':order['address_id'],'items':[{'name':'Eggs','quantity':1}]}).json()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        page.locator('.pi-price').first.fill('111')
        page.locator('.pi-store').first.select_option('zepto')
        firstTitle=page.locator('.price-item-row').first.inner_text()
        page.locator('.orders-tab[data-tab="queue"]').click()
        page.locator('#queue-list .queue-card').nth(1).click()
        page.wait_for_function("title=>{const row=document.querySelector('.price-item-row');return row && row.innerText!==title;}",arg=firstTitle)
        assert page.locator('.pi-price').first.input_value()==''
        page.locator('.pi-price').first.fill('222')
        page.locator('.orders-tab[data-tab="queue"]').click()
        page.locator('#queue-list .queue-card').first.click()
        page.wait_for_function("title=>document.querySelector('.price-item-row')?.innerText===title",arg=firstTitle)
        assert page.locator('.pi-price').first.input_value()=='111'
        assert page.locator('.pi-store').first.input_value()=='zepto'
        page.evaluate('window.handleLogout()')
        assert page.locator('#dashboard-main').is_hidden()
        assert not errors,errors
    finally:page.close()


def test_worker_can_refresh_evidence_without_overwriting_approved_prices(client,actors,order,db,monkeypatch):
    from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
    body=evidence(client,actors,order)
    assert client.post(f"/api/moderator/orders/{order['id']}/research-evidence",headers=actors['admin']['headers'],json=body).status_code==200
    row=db.get(models.Order,order['id']);db.refresh(row)
    row.mode='HYBRID';row.assigned_worker_type='AI'
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    calls=[]
    def provider(items,location):
        calls.append(location)
        return {'verified':False,'requires_human_review':True,'postal_code':location,
            'items':[{'item_id':i['item_id'],'candidates':[]} for i in items]}
    monkeypatch.setattr('api.ai_concierge.research_enabled',lambda:True)
    monkeypatch.setattr(AI,'research',staticmethod(provider))
    AI.process_ticket(row.id,db);db.refresh(row)
    assert calls==['110001'] and row.status=='pending_review' and float(row.final_price)==0
    assert json.loads(row.manual_prices)['research_draft']['verified'] is False


@pytest.mark.parametrize('stored',['broken','[]','{}','{"research_draft":{}}','{"items":[],"research_draft":{}}'])
def test_unrecognized_legacy_pricing_drafts_fail_closed(stored):
    from types import SimpleNamespace
    from core.order_policy import has_human_prices
    assert has_human_prices(SimpleNamespace(manual_prices=stored,is_ai_priced=False))
