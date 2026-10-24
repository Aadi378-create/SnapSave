"""Audit probes: PASS means the documented defect was reproduced, not repaired.

Run from SnapSave-Backend with pytest -p tests.conftest pointing at this file.
External requests and identities are simulated; the application DB is never used.
"""
from pathlib import Path
import models
from tests.test_browser import browser, open_app
from tests.test_login_ui import guest


def test_a03_late_session_response_reopens_customer_after_logout(browser,client,actors,order,db):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate('''()=>{const original=window.fetch;window.fetch=async(url,options)=>{
          if(String(url).endsWith('/api/auth/me'))await new Promise(resolve=>window.auditReleaseMe=resolve);
          return original(url,options);
        };void window.quickLogin();}''')
        page.wait_for_function('!!window.auditReleaseMe')
        page.evaluate('window.handleLogout()')
        assert page.locator('#dashboard-app').is_hidden()
        page.evaluate('window.auditReleaseMe()')
        page.locator('#dashboard-app').wait_for(state='visible')
        assert page.locator('#auth-section').is_hidden()
        assert not errors,errors
    finally:page.close()


def test_a01_external_signout_leaves_customer_dashboard_visible(browser,client,actors,order,db):
    context,page,errors,_=guest(browser,client,actors['customer'],db,'index.html')
    try:
        page.get_by_label('Phone number',exact=True).fill('9876543210')
        page.get_by_role('button',name='Complete test security check').click()
        page.get_by_role('button',name='Send code',exact=True).click()
        page.get_by_label('Verification code',exact=True).fill('123456')
        page.get_by_role('button',name='Verify & sign in',exact=True).click()
        page.locator('#dashboard-app').wait_for(state='visible')
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate("async()=>{const sdk=await import('https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js');await sdk.signOut();}")
        assert page.locator('#dashboard-app').is_visible()
        assert page.locator('#auth-section').is_hidden()
        assert not errors,errors
    finally:context.close()


def test_a02_background_poll_moves_draft_to_new_order(browser,client,actors,order,db):
    actor=actors['customer']
    page,errors=open_app(browser,client,actor,db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.locator('#chat-textarea').fill('Clarification for the original order')
        newer=client.post('/api/orders',headers=actor['headers'],json={
            'address_id':order['address_id'],'items':[{'name':'Eggs','quantity':1}]}).json()
        page.wait_for_function("id=>document.querySelector('#active-order-container').textContent.includes(id.slice(0,8))",arg=newer['id'],timeout=15000)
        assert page.locator('#chat-textarea').input_value()=='Clarification for the original order'
        page.locator('#btn-send-chat').click()
        page.wait_for_function("document.querySelector('#customer-chat-feedback').textContent==='Sent'")
        message=db.query(models.Message).filter_by(message='Clarification for the original order').one()
        assert message.order_id==newer['id'] and message.order_id!=order['id']
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


def test_a04_login_reset_is_ignored_during_verified_callback(browser):
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
        assert page.locator('[data-auth-otp-form]').is_visible()
        assert page.locator('[data-auth-phone-form]').is_hidden()
    finally:page.close()


def test_a05_inbox_hides_threads_after_first_fifty(browser,client,actors,db):
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
        assert page.locator('#help-badge').inner_text()=='50'
        assert not page.locator('#section-help').get_by_role('button',name='Next').count()
        assert not errors,errors
    finally:page.close()
