"""Independent trial runs of the configured engine with disposable identities/data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import time
import pytest
import models
from tests.test_browser import browser,open_app
from tests.test_order_research_integration import automatic,real_submit_ai,import_store
from tests.test_catalog_research import zepto_card,instamart_card

def wait_for_research(client,headers,identity):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        row=client.get(f'/api/orders/{identity}',headers=headers).json()
        if row.get('research',{}).get('state')=='awaiting_capture':return row
        time.sleep(0.02)
    pytest.fail('Background research did not become ready within five seconds')


def test_browser_typing_to_two_retailers_and_human_quote(browser,client,actors,order,automatic,monkeypatch,db,tmp_path):
    from api import server
    monkeypatch.setattr(server,'submit_ai',real_submit_ai)
    customer,errors=open_app(browser,client,actors['customer'],db,'index.html')
    staff=None
    evidence=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)))
    evidence.mkdir(parents=True,exist_ok=True)
    try:
        customer.locator('[onclick="startNewOrder()"]').click()
        customer.locator('#chat-textarea').fill('2x Amul milk 1 L, Epigamia High Protein Paneer 200 g')
        customer.locator('#chat-textarea').press('Enter')
        customer.locator('.research-progress').wait_for()
        history=client.get('/api/orders',headers=actors['customer']['headers']).json()
        identity=next(row['id'] for row in history if row['id']!=order['id'])
        planned=wait_for_research(client,actors['customer']['headers'],identity)
        assert planned['research']['total_items']==2 and planned['final_price']==0
        staff_plan=client.get(f'/api/orders/{identity}',headers=actors['admin']['headers']).json()
        assert staff_plan['ai_error'] is None
        customer.screenshot(path=str(evidence/'customer-plan.png'),full_page=True)

        first=import_store(client,actors,identity,'zepto',zepto_card())
        assert first['research']['matched_items']==1 and first['research']['state']=='partial'
        second=import_store(client,actors,identity,'instamart',instamart_card())
        assert second['research']['state']=='ready_for_review' and second['research']['matched_items']==2
        assert second['ai_error'] is None
        assert second['status']=='pending_review' and second['final_price']==0
        staff,staff_errors=open_app(browser,client,actors['admin'],db,'admin.html')
        staff.locator('.queue-card').filter(has_text=identity[:8]).click()
        staff.wait_for_function("document.querySelector('#research-evidence-panel').textContent.includes('2 of 2 items')")
        staff.screenshot(path=str(evidence/'admin-research.png'),full_page=True)
        assert not staff_errors,staff_errors

        prices=[{'item_id':i['id'],'line_total':154 if 'milk' in i['name'].lower() else 150,'store':'zepto' if 'milk' in i['name'].lower() else 'instamart'} for i in second['items']]
        base=f'/api/moderator/orders/{identity}'
        preview=client.post(base+'/preview-quote',headers=actors['admin']['headers'],json={'items':prices})
        assert preview.status_code==200,preview.text
        quoted=client.post(base+'/price',headers=actors['admin']['headers'],json=preview.json())
        assert quoted.status_code==200,quoted.text
        assert quoted.json()['status']=='awaiting_customer' and quoted.json()['subtotal']==304
        customer.reload()
        customer.locator('#active-order-container .quote-card').wait_for()
        assert customer.locator('.research-progress').count()==0
        customer.screenshot(path=str(evidence/'customer-quote.png'),full_page=True)
        assert not errors,errors
    finally:
        customer.close()
        if staff:staff.close()


@pytest.mark.parametrize('text',['0x milk','0 pieces bread','0 packets rice'])
def test_zero_quantity_is_not_silently_changed_into_one(client,actors,order,automatic,text):
    response=client.post('/api/orders',headers=actors['customer']['headers'],json={'address_id':order['address_id'],'items_text':text})
    assert response.status_code==422,response.text
    assert not automatic


def test_simultaneous_retries_create_one_order_and_one_research_generation(client,actors,order,automatic,monkeypatch,db):
    from api import server
    monkeypatch.setattr(server,'submit_ai',real_submit_ai)
    headers={**actors['customer']['headers'],'Idempotency-Key':'trial-concurrent-order'}
    body={'address_id':order['address_id'],'items_text':'Amul milk 1 L'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client.post('/api/orders',headers=headers,json=body),range(2)))
    assert all(response.status_code==201 for response in responses),[r.text for r in responses]
    identities={response.json()['id'] for response in responses}
    assert len(identities)==1
    identity=identities.pop()
    planned=wait_for_research(client,actors['customer']['headers'],identity)
    assert planned['revision']==2 and planned['research']['total_items']==1
    messages=client.get(f"/api/chat/{actors['customer']['id']}/messages",headers=actors['customer']['headers'],params={'order_id':identity}).json()
    assert sum(m['sender_role']=='CUSTOMER' for m in messages)==1
    assert sum('ready for retailer research' in m['message'] for m in messages)==1
