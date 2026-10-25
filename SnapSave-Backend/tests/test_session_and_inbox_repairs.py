"""Regression checks for the five findings in the 25 October audit."""
import pytest
from pathlib import Path
import models
from tests.test_browser import browser, open_app
from tests.test_login_ui import guest


def test_late_session_response_cannot_reopen_customer_after_logout(browser,client,actors,order,db):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate('''()=>{const original=window.fetch;window.fetch=async(url,options)=>{
          if(String(url).endsWith('/api/auth/me'))await new Promise(resolve=>window.auditReleaseMe=resolve);
          return original(url,options);
        };void window.quickLogin().finally(()=>window.auditOldSettled=true);}''')
        page.wait_for_function('!!window.auditReleaseMe')
        page.evaluate('window.handleLogout()')
        assert page.locator('#dashboard-app').is_hidden()
        page.evaluate('window.auditReleaseMe()')
        page.wait_for_function('window.auditOldSettled')
        assert page.locator('#dashboard-app').is_hidden()
        assert page.locator('#auth-section').is_visible()
        assert not errors,errors
    finally:page.close()


@pytest.mark.parametrize('file,actor_name,dashboard',[('index.html','customer','#dashboard-app'),('admin.html','admin','#dashboard-main')])
def test_external_signout_clears_both_interfaces(browser,client,actors,order,db,file,actor_name,dashboard):
    context,page,errors,_=guest(browser,client,actors[actor_name],db,file)
    try:
        page.get_by_label('Phone number',exact=True).fill('9876543210')
        page.get_by_role('button',name='Complete test security check').click()
        page.get_by_role('button',name='Send code',exact=True).click()
        page.get_by_label('Verification code',exact=True).fill('123456')
        page.get_by_role('button',name='Verify & sign in',exact=True).click()
        page.locator(dashboard).wait_for(state='visible')
        if file=='admin.html':
            page.locator('#queue-list .queue-card').first.click()
            page.locator('#ticket-detail-panel').wait_for(state='visible')
        page.evaluate("async()=>{const sdk=await import('https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js');await sdk.signOut();}")
        page.locator(dashboard).wait_for(state='hidden')
        assert page.locator('#auth-section').is_visible()
        # A second sign-in must rebuild private UI even when the queue data is identical.
        page.get_by_label('Phone number',exact=True).fill('9876543210')
        page.get_by_role('button',name='Complete test security check').click()
        page.get_by_role('button',name='Send code',exact=True).click()
        page.get_by_label('Verification code',exact=True).fill('123456')
        page.get_by_role('button',name='Verify & sign in',exact=True).click()
        page.locator(dashboard).wait_for(state='visible')
        if file=='admin.html':
            page.locator('#queue-list .queue-card').first.wait_for()
            assert page.locator('#ticket-detail-panel').is_hidden()
        assert not errors,errors
    finally:context.close()


@pytest.mark.parametrize('file,actor_name',[('index.html','customer'),('admin.html','admin')])
def test_rejected_session_after_otp_returns_to_phone_step(browser,client,actors,db,file,actor_name):
    context,page,errors,_=guest(browser,client,actors[actor_name],db,file)
    try:
        page.route('**/api/auth/me',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"Session unavailable"}'))
        page.get_by_label('Phone number',exact=True).fill('9876543210')
        page.get_by_role('button',name='Complete test security check').click()
        page.get_by_role('button',name='Send code',exact=True).click()
        page.get_by_label('Verification code',exact=True).fill('123456')
        page.get_by_role('button',name='Verify & sign in',exact=True).click()
        page.locator('[data-auth-phone-form]').wait_for(state='visible')
        assert page.locator('[data-auth-otp-form]').is_hidden()
        assert not errors,errors
    finally:context.close()


def test_support_summary_counts_threads_and_enforces_admin_access(client,actors,db):
    url='/api/admin/help/summary'
    assert client.get(url).status_code in {401,403}
    assert client.get(url,headers=actors['moderator']['headers']).status_code==403
    assert client.get(url,headers=actors['customer']['headers']).status_code==403
    assert client.get(url,headers=actors['admin']['headers']).json()=={'total_threads':0,'open_threads':0}
    for actor_name in ['customer','customer','other']:
        client.post('/api/help',headers=actors[actor_name]['headers'],json={'message':'Support request'})
    assert client.get(url,headers=actors['admin']['headers']).json()=={'total_threads':2,'open_threads':2}
    client.put(f"/api/admin/help/{actors['customer']['id']}/resolve",headers=actors['admin']['headers'])
    assert client.get(url,headers=actors['admin']['headers']).json()=={'total_threads':2,'open_threads':1}


def test_background_poll_keeps_draft_attached_to_original_order(browser,client,actors,order,db):
    actor=actors['customer']
    page,errors=open_app(browser,client,actor,db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.locator('#chat-textarea').fill('Clarification for the original order')
        page.evaluate('''()=>{const original=window.fetch;window.fetch=async(url,options)=>{
          const response=await original(url,options);if(String(url).includes('/api/customer/workspace'))window.auditPollFinished=true;return response;};}''')
        newer=client.post('/api/orders',headers=actor['headers'],json={
            'address_id':order['address_id'],'items':[{'name':'Eggs','quantity':1}]}).json()
        page.wait_for_function('window.auditPollFinished',timeout=15000)
        assert order['id'][:8] in page.locator('#active-order-container').inner_text()
        assert page.locator('#chat-textarea').input_value()=='Clarification for the original order'
        page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#customer-chat-feedback').textContent==='Sent'")
        message=db.query(models.Message).filter_by(message='Clarification for the original order').one()
        assert message.order_id==order['id'] and message.order_id!=newer['id']
        assert not errors,errors
    finally:page.close()


def test_control_archived_admin_chat_is_protected(browser,client,actors,order,db):
    row=db.get(models.Order,order['id']);row.status='cancelled';db.commit()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-filter').wait_for(state='visible')
        page.locator('#queue-filter').select_option('cancelled')
        page.locator('.queue-card').first.click()
        assert page.locator('#composer-text').is_disabled()
        assert page.locator('#btn-send-message').is_disabled()
        result=client.post(f"/api/chat/{actors['customer']['id']}/send",headers=actors['admin']['headers'],json={'order_id':order['id'],'message':'Archived reply'})
        assert result.status_code==409
        assert not errors,errors
    finally:page.close()


def test_login_reset_is_deferred_until_verification_finishes(browser):
    page=browser.new_page()
    try:
        page.set_content('''<section id="fixture">
          <form data-auth-phone-form><input data-auth-phone><button data-auth-send>Send</button>
          <div data-auth-captcha id="audit-captcha"></div><span data-auth-captcha-hint></span>
          <button type="button" data-auth-retry-captcha>Refresh</button></form>
          <form data-auth-otp-form hidden><input data-auth-code><button data-auth-verify>Verify</button>
          <span data-auth-destination></span><button type="button" data-auth-change>Change</button>
          <button type="button" data-auth-resend>Resend</button></form><p data-auth-status></p></section>''')
        source=Path(__file__).resolve().parents[2]/'SnapSave-FRONTEND/phone-login.js'
        page.add_script_tag(path=str(source))
        page.evaluate('''()=>{window.auditLogin=createPhoneLogin(document.querySelector('#fixture'),{
          captcha:async(id,options)=>{options.callback();return {clear(){}};},
          send:async()=>({confirm:async()=>({user:{}})}),
          verified:async()=>{window.auditResetRequested=true;auditLogin.reset();}
        });const input=document.querySelector('[data-auth-phone]');input.value='9876543210';input.dispatchEvent(new Event('input'));}''')
        page.wait_for_function("!document.querySelector('[data-auth-send]').disabled")
        page.evaluate('auditLogin.send()')
        page.locator('[data-auth-code]').fill('123456')
        page.evaluate('auditLogin.verify()')
        assert page.evaluate('window.auditResetRequested')
        assert page.locator('[data-auth-otp-form]').is_hidden()
        assert page.locator('[data-auth-phone-form]').is_visible()
    finally:page.close()


def test_inbox_pages_and_badge_counts_all_open_threads(browser,client,actors,db):
    for i in range(51):
        uid=f'audit_support_{i}'
        db.add(models.User(id=uid,email=f'{uid}@example.com',password_hash='fixture',phone_number=f'+91900000{i:04d}',role='CUSTOMER'))
        db.flush()
        db.add(models.HelpMessage(user_id=uid,sender_role='CUSTOMER',message=f'Open support request {i}'))
    db.commit()
    first=client.get('/api/admin/help',headers=actors['admin']['headers']).json()
    second=client.get('/api/admin/help?offset=50',headers=actors['admin']['headers']).json()
    assert len(first)==50 and len(second)==1
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.admin-nav').wait_for(state='visible')
        page.locator('.admin-nav-item[data-section="help"]').click()
        page.wait_for_function("document.querySelectorAll('#help-thread-list .queue-card').length===50")
        assert page.locator('#help-badge').inner_text()=='51'
        page.get_by_role('button',name='Next requests',exact=True).click()
        page.wait_for_function("document.querySelectorAll('#help-thread-list .queue-card').length===1")
        assert 'Page 2' in page.locator('#help-page-label').inner_text()
        page.get_by_role('button',name='Previous requests',exact=True).click()
        page.wait_for_function("document.querySelectorAll('#help-thread-list .queue-card').length===50")
        assert not errors,errors
    finally:page.close()
