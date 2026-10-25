"""Reduce authenticated round trips without caching revocation or expanding scope."""
import json
import os
from pathlib import Path
import statistics
import time
import jwt
import models
import pytest
from tests.test_browser import browser,open_app


def test_workspace_bootstrap_delta_and_owned_scope(client,actors,order,db):
    headers=actors['customer']['headers']
    result=client.get('/api/customer/workspace?include_history=true&include_addresses=true',headers=headers)
    assert result.status_code==200
    body=result.json();assert body['selected_order_id']==order['id'] and body['order']['id']==order['id']
    assert body['history'] and body['addresses'] and body['messages']
    assert all('manual_prices' not in row for row in body['active'])
    cursor=body['messages'][-1]['id']
    sent=client.post('/api/chat/'+actors['customer']['id']+'/send',headers=headers,json={'order_id':order['id'],'message':'Synthetic delta message'})
    assert sent.status_code==200
    delta=client.get('/api/customer/workspace',headers=headers,params={'selected_order_id':order['id'],'known_revision':body['order']['revision'],'after_id':cursor}).json()
    assert delta['order'] is None and [row['message'] for row in delta['messages']]==['Synthetic delta message']
    assert delta['addresses'] is None and delta['history'] is None
    assert client.get('/api/customer/workspace',headers=actors['other']['headers'],params={'selected_order_id':order['id']}).status_code==403
    assert client.get('/api/customer/workspace',headers=actors['admin']['headers'],params={'selected_order_id':order['id']}).status_code==403
    assert client.get('/api/customer/workspace').status_code==401
    empty=client.get('/api/customer/workspace?draft=true',headers=headers).json()
    assert empty['order'] is None and empty['messages']==[]


def test_workspace_missing_and_invalid_message_cursor(client,actors,order):
    headers=actors['customer']['headers']
    missing=client.get('/api/customer/workspace?selected_order_id=missing',headers=headers).json()
    assert missing['missing_order_id']=='missing' and missing['selected_order_id'] is None
    assert client.get('/api/customer/workspace',headers=headers,params={'selected_order_id':order['id'],'after_id':'missing'}).status_code==422


def test_dynamic_batch_keeps_order_chat_and_help_authorization(client,actors,order):
    reads=[{'path':'/api/orders/'+order['id']},{'path':'/api/chat/'+actors['customer']['id']+'/messages','options':{'order_id':order['id']}},{'path':'/api/admin/help/summary'}]
    admin=client.post('/api/read-batch',headers=actors['admin']['headers'],json={'reads':reads}).json()
    assert [row['status'] for row in admin['results']]==[200,200,200]
    assert admin['results'][0]['data']['id']==order['id'] and admin['results'][1]['data']
    other=client.post('/api/read-batch',headers=actors['other']['headers'],json={'reads':reads}).json()
    assert [row['status'] for row in other['results']]==[403,403,403]
    moderator=client.post('/api/read-batch',headers=actors['moderator']['headers'],json={'reads':reads}).json()
    assert [row['status'] for row in moderator['results']]==[403,403,403]


def test_delayed_firebase_old_chain_vs_workspace(client,actors,order,db,monkeypatch,tmp_path):
    from api import server
    calls=[];delay=.08
    def verify(token,**options):
        assert options['check_revoked'] is True;calls.append(1);time.sleep(delay)
        return {'sub':actors['customer']['id'],'phone_number':actors['customer']['phone']}
    monkeypatch.setattr(server,'firebase_initialized',True);monkeypatch.setattr(server.auth,'verify_id_token',verify)
    token=jwt.encode({'sub':'synthetic'},'fixture-signing-key-never-used-as-a-real-credential',algorithm='HS256',headers={'kid':'network-fixture'})
    headers={'Authorization':'Bearer '+token}
    old=[];new=[]
    for _ in range(3):
        start=time.perf_counter()
        for path in ['/api/orders?active_only=true&summary_only=true','/api/orders/'+order['id'],'/api/chat/'+actors['customer']['id']+'/messages?order_id='+order['id']]:assert client.get(path,headers=headers).status_code==200
        old.append((time.perf_counter()-start)*1000)
        start=time.perf_counter();assert client.get('/api/customer/workspace',headers=headers).status_code==200;new.append((time.perf_counter()-start)*1000)
    assert len(calls)==12
    report={'scope':'Controlled local ASGI test, Firebase SDK stub adds 80 ms per verification; not an internet speed measurement','verification_delay_ms':80,'samples':3,'previous_sequential_checks':3,'workspace_checks':1,'previous_chain_median_ms':round(statistics.median(old),2),'workspace_median_ms':round(statistics.median(new),2)}
    out=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)));out.mkdir(parents=True,exist_ok=True);(out/'controlled-latency.json').write_text(json.dumps(report,indent=2))


def test_customer_bootstrap_has_one_private_workspace_read(browser,client,actors,order,db,monkeypatch):
    original=browser.new_page;requests=[]
    def instrumented(*args,**kwargs):
        page=original(*args,**kwargs);page.on('request',lambda request:requests.append(request.url));return page
    monkeypatch.setattr(browser,'new_page',instrumented)
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#chat-stream .message-wrapper').first.wait_for()
        workspace=[url for url in requests if '/api/customer/workspace?' in url]
        assert len(workspace)==1
        assert page.evaluate('window.__forced_token_refreshes')==0
        assert not [url for url in requests if any(path in url for path in ['/api/orders?','/api/addresses','/messages?','/api/read-batch'])]
        assert not errors,errors
    finally:page.close()


def test_customer_ack_needs_no_extra_read_and_does_not_skip_earlier_staff_message(browser,client,actors,order,db,monkeypatch):
    original=browser.new_page;requests=[]
    def instrumented(*args,**kwargs):
        page=original(*args,**kwargs);page.on('request',lambda request:requests.append((request.method,request.url)));return page
    monkeypatch.setattr(browser,'new_page',instrumented)
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#chat-stream .message-wrapper').first.wait_for()
        client.post('/api/chat/'+actors['customer']['id']+'/send',headers=actors['admin']['headers'],json={'order_id':order['id'],'message':'Earlier unpolled staff reply'})
        requests.clear()
        page.locator('#chat-textarea').fill('Acknowledged customer message');page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#chat-stream').textContent.includes('Acknowledged customer message')")
        assert len([r for r in requests if '/send' in r[1]])==1
        assert not [r for r in requests if '/api/' in r[1] and r[0]=='GET']
        page.evaluate('id=>{void window.viewHistoryOrder(id);}',order['id'])
        page.wait_for_function("document.querySelector('#chat-stream').textContent.includes('Earlier unpolled staff reply')")
        assert page.locator('#chat-stream .message-wrapper').filter(has_text='Acknowledged customer message').count()==1
        assert not errors,errors
    finally:page.close()


def test_admin_ticket_details_and_chat_share_one_batch(browser,client,actors,order,db,monkeypatch):
    original=browser.new_page;requests=[]
    def instrumented(*args,**kwargs):
        page=original(*args,**kwargs)
        page.on('request',lambda request:requests.append((request.method,request.url,request.post_data)))
        return page
    monkeypatch.setattr(browser,'new_page',instrumented)
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.wait_for();requests.clear();page.locator('.queue-card').first.click()
        page.wait_for_function("document.querySelectorAll('.pi-price').length===2")
        details=[json.loads(body)['reads'] for method,url,body in requests if url.endswith('/api/read-batch') and '/api/orders/'+order['id'] in (body or '')]
        assert len(details)==1 and len(details[0])==2
        assert any('/messages' in row['path'] for row in details[0])
        requests.clear();page.locator('#composer-text').fill('Acknowledged staff message');page.locator('#btn-send-message').click()
        page.wait_for_function("document.querySelector('#chat-messages').textContent.includes('Acknowledged staff message')")
        assert len([r for r in requests if '/send' in r[1]])==1
        assert not [r for r in requests if '/api/' in r[1] and r[0]=='GET']
        assert not errors,errors
    finally:page.close()
