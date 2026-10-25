"""New lists -> automatic research -> multiple retailer captures -> safe review."""
import json
from datetime import datetime,timezone,timedelta
import pytest
import models
from database import SessionLocal
from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
from tests.test_browser import browser,open_app
from tests.test_catalog_research import capture,zepto_card,instamart_card
from api.server import submit_ai as real_submit_ai


@pytest.fixture
def automatic(monkeypatch,client,actors,db):
    monkeypatch.setenv('AUTO_RESEARCH_NEW_ORDERS','true')
    monkeypatch.setenv('ENABLE_LIVE_RESEARCH','true')
    monkeypatch.setenv('RESEARCH_PROVIDER','core.order_research:prepare_research')
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    calls=[]
    def run(identity):
        calls.append(identity)
        with SessionLocal() as worker:AI.process_ticket(identity,worker)
    monkeypatch.setattr('api.server.submit_ai',run)
    def no_network(*_,**__):raise AssertionError('Browser planning must not make HTTP requests')
    monkeypatch.setattr('requests.Session.get',no_network)
    return calls


def make_order(client,actors,address,text=None,items=None,key=None):
    body={'address_id':address}
    body.update({'items_text':text} if text is not None else {'items':items})
    headers={**actors['customer']['headers'],**({'Idempotency-Key':key} if key else {})}
    response=client.post('/api/orders',headers=headers,json=body)
    assert response.status_code==201,response.text
    return response.json()


@pytest.mark.parametrize('text,count',[
    ('2x Amul milk 1 L, bread',2),('eggs; sugar',2),('milk and bread',2),
    ('1x 7 Up 750 ml\n1x 5 Star chocolate',2),('दूध 1 L, अज्ञात उत्पाद',2),
    ('completely unknown grocery product',1),
])
def test_typing_a_list_starts_research_without_making_up_prices(client,actors,order,automatic,text,count):
    created=make_order(client,actors,order['address_id'],text=text)
    assert automatic==[created['id']]
    assert created['mode']=='HYBRID' and created['assigned_worker_type']=='HUMAN'
    assert created['research']=={'state':'awaiting_capture','matched_items':0,'total_items':count,'missing_items':count,'requires_human_review':True}
    assert created['status']=='pending_review' and created['final_price']==0
    assert 'manual_prices' not in created
    assert all(i['line_total'] is None for i in created['items'])
    details=client.get(f"/api/orders/{created['id']}",headers=actors['admin']['headers']).json()
    draft=json.loads(details['manual_prices'])['research_draft']
    assert len(draft['items'])==count and all(not i['candidates'] for i in draft['items'])


def test_retry_and_followup_chat_do_not_start_duplicate_orders_or_research(client,actors,order,automatic,db):
    first=make_order(client,actors,order['address_id'],text='Amul milk 1 L',key='research-retry')
    retry=make_order(client,actors,order['address_id'],text='Amul milk 1 L',key='research-retry')
    assert retry['id']==first['id'] and automatic==[first['id']]
    response=client.post(f"/api/chat/{actors['customer']['id']}/send",headers=actors['customer']['headers'],json={'order_id':first['id'],'message':'Please call before delivery'})
    assert response.status_code==200
    assert len(automatic)==1 and len(db.get(models.Order,first['id']).items)==1


def import_store(client,actors,identity,store,markup):
    headers=actors['admin']['headers'];base=f'/api/moderator/orders/{identity}'
    plan=client.get(base+'/research-location',headers=headers).json()
    urls={'zepto':'https://www.zepto.com/category/milk','instamart':'https://www.swiggy.com/instamart/','bigbasket':'https://www.bigbasket.com/pd/1/milk/'}
    entry=capture(store=store,url=urls[store],html=markup,
        research_context={k:plan[k] for k in ('order_id','revision','postal_code')},
        location_context={'staff_confirmed':True,'attested_postal_code':plan['postal_code']})
    response=client.post(base+'/research-evidence',headers=headers,json={'revision':plan['revision'],'captures':[entry]})
    assert response.status_code==200,response.text
    return response.json()


def test_retailer_imports_accumulate_and_refresh_without_losing_other_stores(client,actors,order,automatic,db):
    created=make_order(client,actors,order['address_id'],items=[{'name':'Amul milk 1 L','quantity':2},{'name':'Epigamia High Protein Paneer 200 g','quantity':1},{'name':'Unknown brand of bread','quantity':1}])
    first=import_store(client,actors,created['id'],'zepto',zepto_card())
    assert first['research']['matched_items']==1
    second=import_store(client,actors,created['id'],'instamart',instamart_card())
    assert second['research']['matched_items']==2 and second['research']['missing_items']==1
    replaced=import_store(client,actors,created['id'],'zepto',zepto_card().replace('77','79'))
    items=json.loads(replaced['manual_prices'])['research_draft']['items']
    assert next(i for i in items if i['query']=='Amul milk 1 L')['candidates'][0]['price']==79
    assert next(i for i in items if i['query'].startswith('Epigamia'))['candidates'][0]['price']==150
    # Retrying the planner must also preserve fresh imported evidence.
    row=db.get(models.Order,created['id']);db.refresh(row);row.assigned_worker_type='AI';db.commit()
    AI.process_ticket(row.id,db);db.refresh(row)
    assert sum(bool(i['candidates']) for i in json.loads(row.manual_prices)['research_draft']['items'])==2
    assert row.status=='pending_review' and float(row.final_price)==0


def test_full_hundred_item_basket_can_be_planned_and_imported(client,actors,order,automatic):
    created=make_order(client,actors,order['address_id'],items=[{'name':'Amul milk 1 L','quantity':1} for _ in range(100)])
    assert created['research']['total_items']==100
    imported=import_store(client,actors,created['id'],'zepto',zepto_card())
    assert imported['research']['matched_items']==100 and imported['research']['state']=='ready_for_review'
    assert imported['status']=='pending_review' and imported['final_price']==0


def test_expired_evidence_is_not_counted_or_retained_during_another_import(client,actors,order,automatic,db):
    created=make_order(client,actors,order['address_id'],items=[{'name':'Amul milk 1 L','quantity':1},{'name':'Epigamia High Protein Paneer 200 g','quantity':1}])
    imported=import_store(client,actors,created['id'],'instamart',instamart_card())
    stored=json.loads(imported['manual_prices'])
    for item in stored['research_draft']['items']:
        for c in item['candidates']:c['observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()
    row=db.get(models.Order,created['id']);db.refresh(row);row.manual_prices=json.dumps(stored);db.commit()
    current=client.get(f"/api/orders/{row.id}",headers=actors['customer']['headers']).json()
    assert current['research']['state']=='needs_refresh' and current['research']['matched_items']==0
    updated=import_store(client,actors,row.id,'zepto',zepto_card())
    assert updated['research']['matched_items']==1


@pytest.mark.parametrize('text',['x'*256,'1001x milk',','.join(['milk']*101)])
def test_unsupported_typed_lists_return_validation_errors(client,actors,order,automatic,text):
    response=client.post('/api/orders',headers=actors['customer']['headers'],json={'address_id':order['address_id'],'items_text':text})
    assert response.status_code==422,response.text
    assert not automatic


def test_global_kill_switch_prevents_automatic_research(client,actors,order,automatic,db):
    db.get(models.SystemSetting,'ai_enabled').value='false';db.commit()
    created=make_order(client,actors,order['address_id'],text='milk')
    assert not automatic and created['mode']=='HUMAN' and 'research' not in created


def test_customer_and_staff_see_research_progress_safely(browser,client,actors,order,automatic,db):
    created=make_order(client,actors,order['address_id'],text='Amul milk 1 L, unknown bread')
    customer,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        customer.locator('.research-progress').wait_for()
        assert '0 of 2 items' in customer.locator('.research-progress').inner_text()
        customer.locator('[onclick="startNewOrder()"]').click()
        customer.locator('#chat-textarea').fill('Rice 1 kg, never-seen grocery')
        customer.locator('#chat-textarea').press('Enter')
        customer.locator('.research-progress').wait_for()
        assert len(automatic)==2 and automatic[-1]!=created['id']
        typed=client.get(f'/api/orders/{automatic[-1]}',headers=actors['customer']['headers']).json()
        assert typed['research']['total_items']==2 and typed['research']['state']=='awaiting_capture'
        assert typed['final_price']==0
        assert not errors,errors
    finally:customer.close()
    staff,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        staff.locator('#queue-list .queue-card').filter(has_text=created['id'][:8]).click()
        staff.wait_for_function("document.querySelector('#research-evidence-panel').textContent.includes('0 of 2 items')")
        assert '0 of 2 items' in staff.locator('#research-evidence-panel').inner_text()
        assert staff.get_by_role('button',name='Copy item query').count()==2
        assert not errors,errors
    finally:staff.close()


def test_real_background_executor_completes_automatic_planning(client,actors,order,automatic,monkeypatch):
    import time
    from api import server
    monkeypatch.setattr(server,'submit_ai',real_submit_ai)
    created=make_order(client,actors,order['address_id'],text='Amul milk 1 L, a product not in the catalogue')
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        details=client.get(f"/api/orders/{created['id']}",headers=actors['customer']['headers']).json()
        with server._ai_jobs_lock:finished=created['id'] not in server._ai_jobs
        if finished and details.get('research',{}).get('state')=='awaiting_capture':break
        time.sleep(0.02)
    assert finished and details['research']['total_items']==2
    assert details['assigned_worker_type']=='HUMAN' and details['status']=='pending_review'
    assert details['final_price']==0 and not automatic
