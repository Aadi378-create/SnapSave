import json
from pathlib import Path
import pytest
import models
from tests.test_browser import browser,open_app
from tests.test_order_research_integration import make_order


def test_automatic_http_requests_fall_back_only_after_an_issue(client,actors,order,db,monkeypatch):
    from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
    from database import SessionLocal
    from core import autonomous_research as provider
    calls=[]
    for name in ('AUTO_RESEARCH_NEW_ORDERS','AUTONOMOUS_ORDER_RESEARCH','ENABLE_LIVE_RESEARCH'):monkeypatch.setenv(name,'true')
    monkeypatch.setenv('RESEARCH_PROVIDER','core.autonomous_research:research')
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    monkeypatch.setattr('core.catalog_research.sources',lambda:{'zepto':['https://www.zepto.com/category/milk']})
    def blocked(self,url,store):
        calls.append((url,store));raise provider.ResearchUnavailable('HTTP 202; no catalogue data accepted')
    monkeypatch.setattr(provider.AutonomousCatalogClient,'fetch',blocked)
    def run(identity):
        with SessionLocal() as worker:AI.process_ticket(identity,worker)
    monkeypatch.setattr('api.server.submit_ai',run)
    created=make_order(client,actors,order['address_id'],text='Amul milk 1 L')
    assert calls and created['mode']=='HUMAN' and created['assigned_worker_type']=='HUMAN'
    assert created['status']=='pending_review' and created['final_price']==0
    details=client.get('/api/orders/'+created['id'],headers=actors['admin']['headers']).json()
    draft=json.loads(details['manual_prices'])['research_draft']
    assert draft['autonomous_attempt'] and draft['diagnostics'][0]['status']=='unavailable'
    assert 'Automatic retailer requests' in details['ai_error']
    assert all(i['line_total'] is None for i in details['items'])


def test_blocked_retailer_is_not_hammered_by_successive_orders(monkeypatch):
    from core import autonomous_research as provider
    provider._blocked.clear();calls=[]
    def blocked(self,url,store):
        calls.append(url);raise provider.ResearchUnavailable('HTTP 403; no catalogue data accepted')
    monkeypatch.setattr(provider.PublicCatalogClient,'fetch',blocked)
    for _ in range(2):
        client=provider.AutonomousCatalogClient()
        try:
            with pytest.raises(provider.ResearchUnavailable):client.fetch('https://www.zepto.com/category/milk','zepto')
        finally:client.close()
    assert len(calls)==1
    provider._blocked.clear()


def test_reset_is_backed_up_and_preserves_accounts_and_settings(client,actors,order,db,tmp_path):
    from database import DATABASE_URL
    from reset_development_orders import reset_order_data
    result=reset_order_data(DATABASE_URL.database,tmp_path)
    assert result['after']['orders']==result['after']['order_items']==0
    assert result['after']['users']==result['before']['users']
    assert result['after']['addresses']==result['before']['addresses']
    import sqlite3
    with sqlite3.connect(result['backup_file']) as backup:
        assert backup.execute('select count(*) from orders').fetchone()[0]==result['before']['orders']
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.get(models.User,actors['admin']['id']).role=='ADMIN'
    assert db.get(models.SystemSetting,'ai_enabled') is not None


def test_failed_backup_prevents_reset(client,actors,order,monkeypatch,tmp_path):
    from database import DATABASE_URL
    import reset_development_orders as reset
    def fail(*args):raise OSError('backup unavailable')
    monkeypatch.setattr(reset,'backup_database',fail)
    with pytest.raises(OSError):reset.reset_order_data(DATABASE_URL.database,tmp_path)
    assert client.get('/api/orders/'+order['id'],headers=actors['customer']['headers']).status_code==200


def test_login_does_not_reopen_a_delivered_order(browser,client,actors,order,db):
    row=db.get(models.Order,order['id']);row.status='delivered';db.commit()
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#dashboard-app').wait_for(state='visible')
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('No active order')")
        assert page.locator('#chat-textarea').is_enabled()
        assert order['id'][:6] in page.locator('#mini-history-list').inner_text()
        assert not errors,errors
    finally:page.close()


def test_empty_history_is_loaded_once_and_admin_layout_is_compact(browser,client,actors,db,tmp_path):
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.locator('#dashboard-app').wait_for(state='visible')
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('No active order')")
        history=[]
        page.on('request',lambda request:history.append(request.url) if '/api/orders?limit=50' in request.url else None)
        page.wait_for_timeout(9000)  # Exercise the real eight-second poll with an empty history.
        assert not history and not errors
    finally:page.close()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-filter').wait_for(state='visible')
        page.wait_for_function("document.querySelector('#queue-list').textContent.includes('No active requests')")
        assert page.locator('#mode-btn-hybrid').count()==0
        assert page.locator('#queue-list').evaluate('(e)=>getComputedStyle(e).display')=='grid'
        import os
        output=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)));output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'admin-empty-queue.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.locator('#dashboard-metrics').evaluate('(e)=>getComputedStyle(e).display')=='grid'
        assert page.locator('#dashboard-metrics .metric-value').first.is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>[e.tagName,e.id,e.className]).slice(0,12)")
        page.screenshot(path=str(output/'admin-mobile.png'),full_page=True)
        assert not errors,errors
    finally:page.close()


def test_new_automatic_order_starts_in_ai_mode_without_a_manual_step(client,actors,order,db,monkeypatch):
    from tests.test_order_research_integration import automatic
    for name in ('AUTO_RESEARCH_NEW_ORDERS','AUTONOMOUS_ORDER_RESEARCH','ENABLE_LIVE_RESEARCH'):monkeypatch.setenv(name,'true')
    monkeypatch.setenv('RESEARCH_PROVIDER','core.autonomous_research:research')
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    jobs=[];monkeypatch.setattr('api.server.submit_ai',jobs.append)
    created=make_order(client,actors,order['address_id'],text='Milk 1 L')
    assert created['mode']=='AI' and created['assigned_worker_type']=='AI'
    assert jobs==[created['id']]


def test_summary_queue_omits_research_payload_but_ticket_details_remain_available(client,actors,order,db):
    row=db.get(models.Order,order['id']);row.manual_prices=json.dumps({'legacy':'x'*150000});db.commit()
    summary=client.get('/api/moderator/queue?summary_only=true',headers=actors['admin']['headers'])
    assert summary.status_code==200 and len(summary.content)<3000
    entry=next(r for r in summary.json() if r['id']==order['id'])
    assert entry['summary_only'] and 'manual_prices' not in entry and entry['items']==[]
    full=client.get('/api/moderator/queue',headers=actors['admin']['headers'])
    import os
    if os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR'):
        Path(os.environ['SNAPSAVE_TEST_ARTIFACT_DIR'],'queue-payload-comparison.json').write_text(json.dumps({'fixture':'one synthetic order with 150 KB internal draft','summary_bytes':len(summary.content),'full_bytes':len(full.content)},indent=2))
    detail=client.get('/api/orders/'+order['id'],headers=actors['admin']['headers'])
    assert len(detail.json()['manual_prices'])>150000 and len(detail.json()['items'])==2


def test_legacy_general_chat_is_retained_but_not_reopened_as_a_new_order(browser,client,actors,db):
    db.add(models.Message(user_id=actors['customer']['id'],order_id=None,sender_id=actors['customer']['id'],sender_role='CUSTOMER',message='Legacy unbound conversation'));db.commit()
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('No active order')")
        page.wait_for_timeout(300)
        assert 'Legacy unbound conversation' not in page.locator('#chat-stream').inner_text()
        assert db.query(models.Message).filter_by(order_id=None).count()==1
        assert not errors,errors
    finally:page.close()


def test_summary_queue_opens_complete_ticket_without_losing_items(browser,client,actors,order,db,tmp_path):
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.wait_for()
        import os
        output=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)))
        page.screenshot(path=str(output/'admin-queue.png'),full_page=True)
        page.locator('.queue-card').first.click()
        page.wait_for_function("document.querySelectorAll('.pi-price').length===2")
        assert 'Amul milk' in page.locator('#prices-list').inner_text()
        page.screenshot(path=str(output/'admin-ticket.png'),full_page=True)
        assert not errors,errors
    finally:page.close()


def test_autonomous_failure_panel_has_diagnostics_without_capture_steps(browser,client,actors,order,db):
    row=db.get(models.Order,order['id']);row.mode='HUMAN';row.ai_error='Retailer access blocked';row.manual_prices=json.dumps({'research_draft':{'autonomous_attempt':True,'items':[],'diagnostics':[{'store':'zepto','reason':'HTTP 202'}]}});db.commit()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.click()
        page.wait_for_function("document.querySelector('#research-evidence-panel')?.textContent.includes('Automatic store research')")
        panel=page.locator('#research-evidence-panel')
        assert 'HTTP 202' in panel.inner_text() and 'Copy research context' not in panel.inner_text()
        assert page.get_by_label('Import retailer capture JSON').count()==0
        assert not errors,errors
    finally:page.close()
