"""Regression coverage for the remaining audit findings; isolated identities only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import time
import hashlib
import sqlite3
import pytest
import jwt
import models
from database import SessionLocal
from tests.test_ai_concierge import ai_order
from tests.test_browser import browser,open_app
from core import research_jobs as jobs


def extra_orders(db,actors,count=8):
    start=datetime(2025,1,1)
    for n in range(count):
        db.add(models.Order(id=f'cursor-{n:03d}',user_id=actors['customer']['id'],store='pending',status='pending_review',mode='HUMAN',assigned_worker_type='HUMAN',delivery_street='Synthetic',delivery_city='Fixture',delivery_postal_code='382421',subtotal=0,final_price=0,delivery_fee=0,platform_fee=0,created_at=start+timedelta(seconds=n)))
    db.commit()


def test_history_cursor_resists_insert_and_removal_before_boundary(client,actors,db):
    extra_orders(db,actors)
    headers=actors['customer']['headers']
    first=client.get('/api/orders?summary_only=true&limit=3',headers=headers).json()
    assert [row['id'] for row in first]==['cursor-007','cursor-006','cursor-005']
    db.delete(db.get(models.Order,'cursor-007'));db.commit()
    newer=models.Order(id='cursor-new',user_id=actors['customer']['id'],store='pending',status='pending_review',delivery_street='Fixture',delivery_city='Fixture',delivery_postal_code='382421',subtotal=0,final_price=0,delivery_fee=0,platform_fee=0);db.add(newer);db.commit()
    second=client.get('/api/orders',params={'summary_only':True,'limit':3,'before':first[-1]['cursor']},headers=headers).json()
    assert [row['id'] for row in second]==['cursor-004','cursor-003','cursor-002']


def test_queue_cursor_resists_status_changes_before_boundary(client,actors,db):
    extra_orders(db,actors)
    headers=actors['admin']['headers']
    first=client.get('/api/moderator/queue?summary_only=true&limit=3',headers=headers).json()
    db.get(models.Order,'cursor-000').status='delivered';db.commit()
    second=client.get('/api/moderator/queue',params={'summary_only':True,'limit':3,'after':first[-1]['cursor']},headers=headers).json()
    assert [row['id'] for row in second]==['cursor-003','cursor-004','cursor-005']
    assert client.get('/api/moderator/queue',params={'status_filter':'delivered','after':first[-1]['cursor']},headers=headers).status_code==422
    assert client.get('/api/orders',params={'before':'invalid'},headers=actors['customer']['headers']).status_code==422


def test_read_batch_verifies_firebase_once_and_preserves_roles(client,actors,order,monkeypatch):
    from api import server
    calls=[]
    monkeypatch.setattr(server,'firebase_initialized',True)
    def verify(token,**options):
        calls.append(options);return {'sub':actors['customer']['id'],'phone_number':actors['customer']['phone']}
    monkeypatch.setattr(server.auth,'verify_id_token',verify)
    token=jwt.encode({'sub':'fixture'},'synthetic-key-is-not-an-authentication-secret',algorithm='HS256',headers={'kid':'real-sdk-fixture'})
    response=client.post('/api/read-batch',headers={'Authorization':'Bearer '+token},json={'reads':[{'path':'/api/orders','options':{'summary_only':True}},{'path':'/api/addresses'},{'path':'/api/admin/customers'}]})
    assert response.status_code==200
    assert [r['status'] for r in response.json()['results']]==[200,200,403]
    assert len(calls)==1 and calls[0]['check_revoked'] is True
    assert response.json()['results'][0]['data'][0]['id']==order['id']


@pytest.mark.parametrize('reads',[
    [{'path':'/api/orders','options':{'limit':1001}}],
    [{'path':'/api/orders'}]*9,
    [{'path':'/api/orders','options':{'url':'https://untrusted.invalid'}}]
])
def test_batch_bounds(client,actors,reads):
    assert client.post('/api/read-batch',headers=actors['customer']['headers'],json={'reads':reads}).status_code==422


def test_read_batch_cannot_forward_mutations_or_escalate_moderator(client,actors,order):
    response=client.post('/api/read-batch',headers=actors['moderator']['headers'],json={'reads':[{'path':'/api/admin/settings/maintenance'},{'path':'/api/admin/delivery-config'},{'path':'/api/orders/'+order['id']+'/cancel'}]})
    assert [r['status'] for r in response.json()['results']]==[403,403,422]


def test_expired_lease_recovers_and_stale_owner_cannot_finish(db,ai_order):
    identity=ai_order.id
    assert jobs.enqueue(identity)
    first,attempt=jobs.claim(identity);assert attempt==1
    assert jobs.claim(identity) is None
    job=db.get(models.ResearchJob,identity);job.lease_until=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1);db.commit()
    second,attempt=jobs.claim(identity);assert attempt==2 and first!=second
    jobs.finish(identity,first);db.expire_all()
    assert db.get(models.ResearchJob,identity).owner==second
    assert jobs.renew(identity,first) is False
    jobs.finish(identity,second);db.expire_all();assert db.get(models.ResearchJob,identity).state=='done'


def test_competing_workers_only_one_claims(db,ai_order):
    identity=ai_order.id;jobs.enqueue(identity)
    with ThreadPoolExecutor(max_workers=4) as pool:claims=list(pool.map(lambda _:jobs.claim(identity),range(4)))
    assert sum(result is not None for result in claims)==1


def test_restart_recovers_missing_intent_and_executes_once(client,db,ai_order):
    from api import server
    identity=ai_order.id
    jobs.recover_intents();jobs.recover_intents()
    assert db.query(models.ResearchJob).filter_by(order_id=identity).count()==1
    server.dispatch_ai(identity)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        db.expire_all()
        if db.get(models.ResearchJob,identity).state=='done':break
        time.sleep(.02)
    assert db.get(models.ResearchJob,identity).state=='done'
    assert db.get(models.Order,identity).status=='awaiting_customer'
    revision=db.get(models.Order,identity).revision
    server.dispatch_ai(identity);db.expire_all();assert db.get(models.Order,identity).revision==revision


def test_new_ai_generation_is_not_suppressed_by_old_lease(db,ai_order):
    identity=ai_order.id;jobs.enqueue(identity);owner,_=jobs.claim(identity)
    ai_order.revision+=3;db.commit() # Worker start, takeover, deliberate return to AI.
    jobs.enqueue(identity);jobs.finish(identity,owner);db.expire_all()
    job=db.get(models.ResearchJob,identity)
    assert job.state=='queued' and job.owner is None


def test_human_takeover_cancels_pending_job(db,ai_order):
    identity=ai_order.id;jobs.enqueue(identity);ai_order.assigned_worker_type='HUMAN';db.commit()
    assert jobs.claim(identity) is None
    db.expire_all();assert db.get(models.ResearchJob,identity).state=='cancelled'


def test_backup_restore_does_not_replace_source(tmp_path):
    from verify_backup import verify_backup
    source=tmp_path/'fixture.sqlite3'
    with sqlite3.connect(source) as db:db.execute('CREATE TABLE fixture(id INTEGER)');db.execute('INSERT INTO fixture VALUES (42)')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    assert verify_backup(source,digest)['restored'] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    with pytest.raises(ValueError,match='checksum'):verify_backup(source,'0'*64)
    bad=tmp_path/'bad.sqlite3';bad.write_bytes(b'not a database')
    with pytest.raises(sqlite3.DatabaseError):verify_backup(bad)


@pytest.mark.parametrize('file,role',[('index.html','customer'),('admin.html','admin')])
def test_firebase_outage_shows_retry_in_both_logins(browser,client,actors,db,file,role):
    page,errors=open_app(browser,client,actors[role],db,file,firebase_unavailable=True)
    try:
        page.get_by_role('button',name='Retry sign-in',exact=True).wait_for()
        assert 'Unable to connect' in page.locator('[role=alert]').last.inner_text()
        assert not errors,errors
    finally:page.close()


def test_expired_worker_cannot_publish_after_lease_replacement(db,ai_order,monkeypatch):
    from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
    identity=ai_order.id;jobs.enqueue(identity);owner,_=jobs.claim(identity)
    original=AI.research
    def lose_lease(items,postal):
        with SessionLocal() as other:
            job=other.get(models.ResearchJob,identity);job.lease_until=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1);other.commit()
        assert jobs.claim(identity) is not None
        return original(items,postal)
    monkeypatch.setattr(AI,'research',staticmethod(lose_lease))
    AI.process_ticket(identity,db,lease_owner=owner);db.expire_all()
    assert db.get(models.Order,identity).status=='pending_review'
    assert db.query(models.Message).filter_by(order_id=identity,kind='quote').count()==0


def test_automatic_order_commits_job_intent_before_dispatch(client,actors,order,db,monkeypatch):
    from api import server
    monkeypatch.setenv('AUTO_RESEARCH_NEW_ORDERS','true');monkeypatch.setenv('AUTONOMOUS_ORDER_RESEARCH','true');monkeypatch.setenv('ENABLE_LIVE_RESEARCH','true')
    monkeypatch.setattr('settings.research_provider',lambda:lambda *_:None)
    db.get(models.SystemSetting,'ai_enabled').value='true';db.commit()
    observed=[]
    def dispatch(identity):
        with SessionLocal() as reader:observed.append(reader.get(models.ResearchJob,identity).state)
    monkeypatch.setattr(server,'submit_ai',dispatch)
    created=client.post('/api/orders',headers=actors['customer']['headers'],json={'address_id':order['address_id'],'items':[{'name':'Fixture milk','quantity':1}]})
    assert created.status_code==201 and observed==['queued']


def test_stale_worker_failure_cannot_take_over_new_ai_generation(db,ai_order):
    from api import server
    identity=ai_order.id;jobs.enqueue(identity);owner,_=jobs.claim(identity)
    ai_order.revision+=3;db.commit();jobs.enqueue(identity)
    server.ai_fallback(identity,'Synthetic stale failure',lease_owner=owner);db.expire_all()
    assert db.get(models.Order,identity).assigned_worker_type=='AI'
    assert db.get(models.Order,identity).ai_error is None


def test_hosting_includes_vendor_fonts_icons_and_licenses(tmp_path):
    import importlib.util
    from pathlib import Path
    script=Path(__file__).resolve().parents[2]/'SnapSave-FRONTEND/prepare_hosting.py'
    spec=importlib.util.spec_from_file_location('vendor_hosting',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=module.prepare('https://api.example.com',tmp_path/'hosting')
    for path in module.PUBLIC_LICENSES:assert (target/path).is_file()
    assert list((target/'assets/vendor/fonts').glob('*.ttf'))
    assert list((target/'assets/vendor/fontawesome/webfonts').glob('*.woff2'))
    assert not module.public_output(Path('assets/vendor/private.txt'))


def test_parallel_reads_keep_customer_isolation(client,actors,order,tmp_path):
    import json,os,statistics
    from pathlib import Path
    def request(index):
        actor=actors['customer'] if index%2==0 else actors['other']
        start=time.perf_counter()
        response=client.post('/api/read-batch',headers=actor['headers'],json={'reads':[{'path':'/api/orders','options':{'summary_only':True}},{'path':'/api/addresses'}]})
        assert response.status_code==200
        rows=response.json()['results'][0]['data']
        assert [row['id'] for row in rows]==([order['id']] if index%2==0 else [])
        return (time.perf_counter()-start)*1000
    with ThreadPoolExecutor(max_workers=8) as pool:durations=list(pool.map(request,range(20)))
    result={'scope':'20 synthetic read batches, eight client threads, real local ASGI/SQLite, test JWTs; excludes internet/Firebase latency','median_ms':round(statistics.median(durations),2),'max_ms':round(max(durations),2),'requests':20,'client_threads':8,'all_isolated':True}
    target=Path(os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR',str(tmp_path)));target.mkdir(parents=True,exist_ok=True);(target/'parallel-reads.json').write_text(json.dumps(result,indent=2))


@pytest.mark.parametrize('failure,expected',[('timeout',503),('invalid',401)])
def test_firebase_outage_is_not_misreported_as_invalid_credentials(client,actors,monkeypatch,failure,expected):
    import requests
    from api import server
    monkeypatch.setattr(server,'firebase_initialized',True)
    def verify(*args,**kwargs):
        if failure=='timeout':raise requests.Timeout('Synthetic unavailable network')
        raise server.auth.InvalidIdTokenError('Synthetic invalid token')
    monkeypatch.setattr(server.auth,'verify_id_token',verify)
    token=jwt.encode({'sub':'fixture'},'synthetic-key-is-not-an-authentication-secret',algorithm='HS256',headers={'kid':'real-sdk-fixture'})
    response=client.get('/api/orders',headers={'Authorization':'Bearer '+token})
    assert response.status_code==expected and not isinstance(response.json(),list)


@pytest.mark.parametrize('file,role,private_view',[('index.html','customer','#dashboard-app'),('admin.html','admin','#dashboard-main')])
def test_temporary_auth_outage_hides_private_view_without_global_signout(browser,client,actors,db,file,role,private_view):
    page,errors=open_app(browser,client,actors[role],db,file,auth_unavailable=True)
    try:
        page.get_by_role('button',name='Retry sign-in',exact=True).wait_for()
        assert page.locator(private_view).is_hidden()
        assert page.evaluate('window.__test_signouts')==0
        assert not errors,errors
    finally:page.close()
