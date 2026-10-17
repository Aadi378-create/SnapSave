import uuid
import os
from pathlib import Path
import models
from tests.test_browser import browser, open_app


def test_message_retry_is_idempotent_and_scoped(client, actors, order, db):
    url=f"/api/chat/{actors['customer']['id']}/send"
    headers=actors['customer']['headers']
    payload={"order_id":order['id'],"message":"Please check the brand", "request_id":str(uuid.uuid4())}
    first=client.post(url,headers=headers,json=payload)
    assert first.status_code==200
    assert client.post(url,headers=headers,json=payload).json()==first.json()
    assert db.query(models.Message).filter_by(id=payload['request_id']).count()==1
    assert client.post(url,headers=headers,json={**payload,"message":"Different message"}).status_code==409
    assert client.post(url,headers=actors['other']['headers'],json=payload).status_code==403
    row=db.get(models.Order,order['id']);row.status='cancelled';db.commit()
    assert client.post(url,headers=headers,json=payload).json()==first.json()
    assert client.post(url,headers=headers,json={**payload,"request_id":str(uuid.uuid4())}).status_code==409


def test_customer_message_lost_response_retries_without_dialog_or_duplicate(browser,client,actors,quoted,db):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#chat-textarea').wait_for(state='visible')
        page.wait_for_function("!document.querySelector('#chat-textarea').disabled && document.querySelector('#chat-stream').textContent.includes('Quote')",timeout=5000)
        page.evaluate('''()=>{const original=window.fetch;window.__lost=false;
          window.fetch=async(url,options)=>{const result=await original(url,options);
          if(String(url).includes('/send')&&!window.__lost){window.__lost=true;throw Error('Connection interrupted');}return result;};}''')
        page.locator('#chat-textarea').fill('Please check the milk brand')
        page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#customer-chat-feedback').dataset.error==='true'")
        assert page.locator('#chat-textarea').input_value()=='Please check the milk brand'
        assert page.evaluate("window.__lost"),page.locator("#customer-chat-feedback").inner_text()
        page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#customer-chat-feedback').textContent==='Sent'")
        assert page.locator('#chat-textarea').input_value()==''
        assert db.query(models.Message).filter_by(message='Please check the milk brand').count()==1
        assert page.locator('.conversation-event').count()>0
        if os.getenv('SNAPSAVE_UI_ARTIFACTS'):
            folder=Path(os.environ['SNAPSAVE_UI_ARTIFACTS']);folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/'conversation-desktop.png'))
        assert not errors,errors
    finally:page.close()


def test_staff_ticket_drafts_and_mobile_navigation(browser,client,actors,quoted,db):
    customer=actors['customer']
    second=client.post('/api/orders',headers=customer['headers'],json={'address_id':quoted['address_id'],'items':[{'name':'Eggs','quantity':1}]}).json()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.wait_for()
        page.locator('.queue-card').first.click()
        page.locator('#composer-text').fill('Draft for first ticket')
        page.locator('.orders-tab[data-tab="queue"]').click()
        page.locator('.queue-card').nth(1).click()
        assert page.locator('#composer-text').input_value()==''
        page.locator('#composer-text').fill('Draft for second ticket')
        page.locator('.orders-tab[data-tab="queue"]').click()
        page.locator('.queue-card').first.click()
        assert page.locator('#composer-text').input_value()=='Draft for first ticket'
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('.admin-nav').is_visible()
        page.locator('.admin-nav-item[data-section="help"]').click()
        assert page.locator('#section-help').is_visible()
        assert not errors,errors
    finally:page.close()


def test_customer_mobile_opens_conversation(browser,client,actors,quoted,db):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#dashboard-app').wait_for(state='visible')
        assert page.locator('#chat-main').is_visible()
        assert page.locator('#chat-textarea').is_visible()
        # A long conversation must scroll inside the stream, keeping Send reachable.
        page.evaluate('''()=>{const stream=document.querySelector('#chat-stream');
          for(let i=0;i<50;i++){const n=document.createElement('div');n.className='message-wrapper';n.textContent='A longer conversation message '+i;stream.append(n);}}''')
        box=page.locator('#btn-send-chat').bounding_box()
        assert box['y']+box['height']<=844
        assert page.locator('#help-modal').is_hidden()
        if os.getenv('SNAPSAVE_UI_ARTIFACTS'):
            folder=Path(os.environ['SNAPSAVE_UI_ARTIFACTS']);folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/'conversation-mobile.png'))
        assert not errors,errors
    finally:page.close()
