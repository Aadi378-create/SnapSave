"""Large synthetic workloads; never seed the configured development database."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import statistics
import time
from sqlalchemy import event
import models
from database import engine
from tests.test_browser import browser,open_app


def test_large_workload_profile(browser,client,actors,db,monkeypatch,tmp_path):
    start=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=1)
    rows=[];items=[];messages=[]
    private=json.dumps({'internal_fixture':'x'*150000})
    for n in range(500):
        identity=f'load-order-{n:04d}';active=n>=450
        rows.append({'id':identity,'user_id':actors['customer']['id'],'store':'zepto','status':'pending_review' if active else 'delivered','mode':'HUMAN','assigned_worker_type':'HUMAN','delivery_street':'Synthetic street','delivery_city':'Fixture city','delivery_postal_code':'382421','subtotal':0 if active else 100,'final_price':0 if active else 100,'delivery_fee':0,'platform_fee':0,'customer_paid':0 if active else 100,'manual_prices':private if active else None,'created_at':start+timedelta(seconds=n),'first_response_at':None if active else start+timedelta(seconds=n+120)})
        for k in range(100):items.append({'id':f'load-item-{n:04d}-{k:03d}','order_id':identity,'name':f'Synthetic product {k} 1 kg','quantity':1,'line_total':None if active else 1,'unit_price':None if active else 1,'store':None if active else 'zepto'})
    for n in (450,499):
        for k in range(500):messages.append({'id':f'load-msg-{n:04d}-{k:03d}','order_id':f'load-order-{n:04d}','user_id':actors['customer']['id'],'sender_id':actors['customer']['id'],'sender_role':'CUSTOMER','kind':'text','message':f'Synthetic message {k} '+('fixture '*20),'created_at':start+timedelta(seconds=500+k)})
    db.bulk_insert_mappings(models.Order,rows);db.bulk_insert_mappings(models.OrderItem,items);db.bulk_insert_mappings(models.Message,messages);db.commit()
    result={'fixture':{'orders':500,'items':50000,'messages':1000,'active_orders':50,'items_per_order':100,'internal_draft_bytes':len(private)},'api':{}}
    for name,path,actor in [
        ('customer_full_history','/api/orders?limit=50','customer'),
        ('customer_summary_history','/api/orders?limit=50&summary_only=true','customer'),
        ('admin_queue','/api/moderator/queue?limit=50&summary_only=true','admin'),
        ('admin_metrics','/api/admin/dashboard/metrics','admin'),
        ('admin_beta_metrics','/api/admin/dashboard/beta-metrics','admin')]:
        timings=[];queries=[];size=0
        for _ in range(5):
            selects=[]
            def record(conn,cursor,statement,*args):
                if statement.lstrip().upper().startswith('SELECT'):selects.append(1)
            event.listen(engine,'before_cursor_execute',record)
            try:
                before=time.perf_counter();response=client.get(path,headers=actors[actor]['headers']);elapsed=(time.perf_counter()-before)*1000
            finally:event.remove(engine,'before_cursor_execute',record)
            assert response.status_code==200,response.text
            timings.append(elapsed);queries.append(len(selects));size=len(response.content)
        result['api'][name]={'median_ms':round(statistics.median(timings),2),'worst_of_5_ms':round(max(timings),2),'response_bytes':size,'select_queries':max(queries)}
    original=browser.new_page
    def instrumented(*args,**kwargs):
        page=original(*args,**kwargs)
        page.add_init_script("window.__loadLongTasks=[];new PerformanceObserver(list=>window.__loadLongTasks.push(...list.getEntries().map(e=>e.duration))).observe({type:'longtask',buffered:true});")
        return page
    monkeypatch.setattr(browser,'new_page',instrumented)
    output=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)));output.mkdir(parents=True,exist_ok=True)
    for file,actor in [('index.html','customer'),('admin.html','admin')]:
        before=time.perf_counter();page,errors=open_app(browser,client,actors[actor],db,file)
        try:
            if actor=='customer':
                page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
                page.locator('#chat-stream .message-wrapper').last.wait_for()
            else:page.locator('.queue-card').nth(49).wait_for()
            ready=(time.perf_counter()-before)*1000
            if actor=='admin':
                click=time.perf_counter();page.locator('.queue-card').first.click();page.wait_for_function("document.querySelectorAll('.pi-price').length===100");page.locator('#chat-messages .chat-bubble').last.wait_for()
                result['admin_ticket_open_ms']=round((time.perf_counter()-click)*1000,2)
            page.wait_for_timeout(100)
            result[file]={'ready_ms':round(ready,2),'dom_elements':page.locator('*').count(),'long_tasks_ms':page.evaluate('window.__loadLongTasks')}
            if actor=='customer':
                typing=time.perf_counter();page.locator('#chat-textarea').press_sequentially('milk 1 L');result[file]['typing_8_chars_ms']=round((time.perf_counter()-typing)*1000,2)
            page.screenshot(path=str(output/(actor+'-large.png')),full_page=True)
            assert not errors,errors
        finally:page.close()
    label=os.environ.get('SNAPSAVE_PROFILE_LABEL','profile')
    (output/(label+'.json')).write_text(json.dumps(result,indent=2))


def test_moderator_metrics_do_not_disclose_global_financial_totals(client,actors,order,db):
    row=db.get(models.Order,order['id']);row.status='delivered';row.assigned_moderator_id=actors['unassigned']['id'];row.customer_paid=100000;row.profit=50000;db.commit()
    response=client.get('/api/admin/dashboard/metrics',headers=actors['moderator']['headers'])
    assert response.status_code==200
    assert not {'revenue','profit','revenue_today','profit_today','total_customers','total_savings_delivered'} & response.json().keys()


def test_summary_history_does_not_load_item_arrays_or_internal_drafts(client,actors,order):
    response=client.get('/api/orders?summary_only=true',headers=actors['customer']['headers'])
    assert response.status_code==200
    assert all('items' not in row and 'manual_prices' not in row and row['summary_only'] for row in response.json())


def test_customer_history_switch_blocks_sending_and_can_be_cancelled(browser,client,actors,order,db):
    archived=models.Order(id='archived-order',user_id=actors['customer']['id'],store='zepto',status='delivered',delivery_street='Fixture street',delivery_city='Fixture city',delivery_postal_code='382421',subtotal=0,final_price=0,delivery_fee=0,platform_fee=0,created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=1))
    db.add(archived);db.commit()
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate("""()=>{const original=window.fetch;window.fetch=async(url,options)=>{if(String(url).includes('active_only=true'))await new Promise(resolve=>window.releaseHistory=resolve);return original(url,options);};void window.viewHistoryOrder('archived-order');}""")
        page.wait_for_function('!!window.releaseHistory')
        assert page.locator('#chat-textarea').is_disabled() and page.locator('#btn-send-chat').is_disabled()
        page.locator('[onclick="startNewOrder()"]').click()
        page.evaluate('window.releaseHistory()')
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('No active order')")
        assert page.locator('#chat-textarea').is_enabled()
        assert not errors,errors
    finally:
        page.evaluate('if(window.releaseHistory)window.releaseHistory()');page.close()


def test_deleted_history_record_does_not_freeze_customer_dashboard(browser,client,actors,order,db):
    row=db.get(models.Order,order['id']);row.status='delivered';db.commit()
    page,errors=open_app(browser,client,actors['customer'],db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('No active order')")
        db.delete(row);db.commit()
        page.evaluate("id=>{void window.viewHistoryOrder(id);}",order['id'])
        page.wait_for_function("document.querySelector('#customer-chat-feedback').textContent.includes('no longer available')")
        assert page.locator('#chat-textarea').is_enabled()
        assert not errors,errors
    finally:page.close()


def test_beta_financial_averages_are_admin_only(client,actors,order,db):
    row=db.get(models.Order,order['id']);row.status='delivered';row.profit=20;row.savings=10;db.commit()
    moderator=client.get('/api/admin/dashboard/beta-metrics',headers=actors['moderator']['headers']).json()
    assert moderator['avg_profit_per_order'] is None and moderator['avg_savings_delivered'] is None
    admin=client.get('/api/admin/dashboard/beta-metrics',headers=actors['admin']['headers']).json()
    assert admin['avg_profit_per_order']==20 and admin['avg_savings_delivered']==10


def test_queue_refresh_failure_is_visible_and_preserves_loaded_cards(browser,client,actors,order,db):
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.wait_for()
        count=page.locator('.queue-card').count()
        page.evaluate("""async()=>{window.restoreQueueFetch=window.fetch;window.fetch=async(url,options)=>{if(String(url).includes('/api/moderator/queue'))throw new TypeError('offline fixture');return window.restoreQueueFetch(url,options);};await window.loadQueue();}""")
        assert page.locator('#queue-status').is_visible() and 'Unable to refresh' in page.locator('#queue-status').inner_text()
        assert page.locator('.queue-card').count()==count
        page.evaluate('async()=>{window.fetch=window.restoreQueueFetch;await window.loadQueue();}')
        assert page.locator('#queue-status').is_hidden() and not errors
    finally:page.close()


def test_optional_timing_uses_route_templates_without_credentials(client,actors,order,monkeypatch,caplog):
    import logging
    monkeypatch.setenv('ENABLE_REQUEST_TIMING','true')
    with caplog.at_level(logging.INFO,logger='uvicorn.error'):
        response=client.get('/api/orders/'+order['id'],headers=actors['customer']['headers'])
    assert response.status_code==200 and response.headers['server-timing'].startswith('app;dur=')
    timing=[record.message for record in caplog.records if 'SNAPSAVE_TIMING' in record.message]
    assert timing and '/api/orders/{order_id}' in timing[-1]
    assert order['id'] not in timing[-1] and actors['customer']['headers']['Authorization'] not in timing[-1]


def test_admin_queue_does_not_wait_for_slow_settings(browser,client,actors,order,db,monkeypatch):
    original=browser.new_page
    def instrumented(*args,**kwargs):
        page=original(*args,**kwargs)
        page.add_init_script("""const originalFetch=window.fetch;window.fetch=async(url,options)=>{if(String(url).includes('/api/admin/settings/orders'))await new Promise(resolve=>window.releaseSettings=resolve);return originalFetch(url,options);};""")
        return page
    monkeypatch.setattr(browser,'new_page',instrumented)
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').first.wait_for()
        assert page.locator('#order-global-switch').is_disabled()
        page.evaluate('window.releaseSettings()')
        page.wait_for_function("!document.querySelector('#order-global-switch').disabled")
        assert not errors,errors
    finally:
        page.evaluate('if(window.releaseSettings)window.releaseSettings()');page.close()
