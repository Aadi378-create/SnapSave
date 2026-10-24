from concurrent.futures import ThreadPoolExecutor
import pytest
import models
from tests.test_browser import browser


def test_blacklisted_moderator_loses_shared_order_and_chat_access(client,actors,order,db):
    moderator=actors['moderator'];headers=moderator['headers']
    assert client.put(f"/api/moderator/orders/{order['id']}/claim",headers=headers).status_code==200
    target=db.get(models.User,moderator['id']);target.is_blacklisted=True;db.commit()
    assert client.get(f"/api/orders/{order['id']}",headers=headers).status_code==403
    assert client.get(f"/api/chat/{actors['customer']['id']}/messages",headers=headers,params={'order_id':order['id']}).status_code==403
    row=db.get(models.Order,order['id']);row.status='delivered';db.commit()
    assert client.post(f"/api/orders/{order['id']}/complete",headers=headers).status_code==403
    assert client.post('/api/help',headers=headers,json={'message':'Please review my restriction'}).status_code==200


def test_restricted_staff_cannot_be_assigned_or_inherited_by_new_orders(client,actors,order,db):
    staff=db.get(models.User,actors['moderator']['id']);staff.is_blacklisted=True
    customer=db.get(models.User,actors['customer']['id']);customer.assigned_moderator_id=staff.id;db.commit()
    admin=actors['admin']['headers']
    assert client.post('/api/admin/assign-moderator',headers=admin,json={'customer_id':customer.id,'moderator_id':staff.id}).status_code==400
    assert client.put(f"/api/admin/orders/{order['id']}/assign",headers=admin,json={'moderator_id':staff.id}).status_code==422
    response=client.post('/api/orders',headers=actors['customer']['headers'],json={'address_id':order['address_id'],'items':[{'name':'Bread','quantity':1}]})
    assert response.status_code==201 and response.json()['assigned_moderator_id'] is None


@pytest.mark.parametrize('restricted',[False,True])
def test_staff_own_customer_history_excludes_unassigned_staff_fields(client,actors,order,db,restricted):
    owner=db.get(models.User,actors['customer']['id']);owner.role='MODERATOR';owner.is_blacklisted=restricted;db.commit()
    response=client.get(f"/api/orders/{order['id']}",headers=actors['customer']['headers'])
    assert response.status_code==200
    assert not {'store_cost','profit','manual_prices','ai_error'} & response.json().keys()


def test_unclaimed_queue_redacts_contacts_address_and_internal_prices(client,actors,order):
    response=client.get('/api/moderator/queue',headers=actors['moderator']['headers'])
    assert response.status_code==200
    entry=next(row for row in response.json() if row['id']==order['id'])
    assert entry['requires_claim'] and entry['customer_phone'] is None
    assert not {'delivery_street','delivery_postal_code','address_id','manual_prices','store_cost','profit','payment_reference'} & entry.keys()
    client.put(f"/api/moderator/orders/{order['id']}/claim",headers=actors['moderator']['headers'])
    entry=client.get(f"/api/orders/{order['id']}",headers=actors['moderator']['headers']).json()
    assert not entry['requires_claim'] and entry['delivery_street'] and 'store_cost' in entry


def test_claim_reveals_safe_delivery_snapshot_in_management_ui(browser,client,actors,order,db):
    from tests.test_browser import open_app
    street='Test delivery <img src=x onerror="window.deliveryInjected=true">'
    row=db.get(models.Order,order['id']);row.delivery_street=street;db.commit()
    page,errors=open_app(browser,client,actors['moderator'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        panel=page.locator('#delivery-address-panel')
        assert 'Claim this ticket' in panel.inner_text() and street not in panel.inner_text()
        page.locator('#btn-claim-order').click()
        page.wait_for_function("street=>document.querySelector('#delivery-address-panel').textContent.includes(street)",arg=street)
        assert panel.locator('img').count()==0 and page.evaluate('window.deliveryInjected') is None
        assert 'Claim ticket' not in page.locator('#chat-header-title').inner_text()
        assert not errors,errors
    finally:page.close()


def test_unknown_legacy_role_does_not_get_implicit_admin_chat_access(client,actors,db):
    user=db.get(models.User,actors['other']['id']);user.role='LEGACY';db.commit()
    response=client.get(f"/api/chat/{actors['customer']['id']}/messages",headers=actors['other']['headers'])
    assert response.status_code==403


@pytest.mark.parametrize('postcode',['000001','012345','١١٠٠٠١','11000x'])
def test_invalid_postcodes_cannot_create_unresearchable_addresses(client,actors,postcode):
    response=client.post('/api/addresses',headers=actors['customer']['headers'],json={
        'title':'Home','street_address':'Test street','city':'Delhi','state':'Delhi','postal_code':postcode})
    assert response.status_code==422


def test_concurrent_first_addresses_have_one_default(client,actors):
    headers=actors['customer']['headers']
    def create(n):
        return client.post('/api/addresses',headers=headers,json={'title':f'Address {n}',
            'street_address':'Test street','city':'Delhi','state':'Delhi','postal_code':'110001'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(create,range(2)))
    assert statuses==[201,201]
    rows=client.get('/api/addresses',headers=headers).json()
    assert len(rows)==2 and sum(row['is_default'] for row in rows)==1


def test_delete_default_preserves_order_snapshot_and_promotes_one_fallback(client,actors,order):
    headers=actors['customer']['headers']
    second=client.post('/api/addresses',headers=headers,json={'title':'Other','street_address':'Other street',
        'city':'Delhi','state':'Delhi','postal_code':'110002'}).json()
    before=client.get(f"/api/orders/{order['id']}",headers=headers).json()
    assert client.delete(f"/api/addresses/{order['address_id']}",headers=headers).status_code==200
    rows=client.get('/api/addresses',headers=headers).json()
    assert len(rows)==1 and rows[0]['id']==second['id'] and rows[0]['is_default'] is True
    after=client.get(f"/api/orders/{order['id']}",headers=headers).json()
    assert after['delivery_postal_code']==before['delivery_postal_code'] and after['delivery_street']==before['delivery_street']


def test_concurrent_administrators_cannot_demote_each_other_and_leave_none(client,actors,db):
    other=db.get(models.User,actors['other']['id']);other.role='ADMIN';db.commit()
    changes=[(actors['admin'],actors['other']['id']),(actors['other'],actors['admin']['id'])]
    def demote(change):
        actor,target=change
        return client.put('/api/admin/roles',headers=actor['headers'],json={'user_id':target,'role':'CUSTOMER'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(demote,changes))
    assert 200 in statuses and all(status in {200,403,409} for status in statuses)
    db.expire_all()
    assert db.query(models.User).filter_by(role='ADMIN',is_blacklisted=False).count()>=1


def test_robots_repeated_wildcards_do_not_backtrack_exponentially():
    from core.catalog_research import RobotsPolicy,USER_AGENT
    policy=RobotsPolicy('User-agent: *\nDisallow: /'+'*a'*80+'b$')
    assert policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/'+'a'*200)
    assert not policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/'+'a'*200+'b')


def test_long_content_length_is_rejected_without_integer_conversion_error(client):
    assert client.post('/api/help',content='{}',headers={'Content-Length':'9'*5000}).status_code==413


def test_structured_order_names_preserve_numeric_brands(client,actors,order):
    names=['7 Up 750 ml','5 Star chocolate','2xylitol candy']
    response=client.post('/api/orders',headers=actors['customer']['headers'],json={
        'address_id':order['address_id'],'items':[{'name':name,'quantity':2} for name in names]})
    assert response.status_code==201,response.text
    assert sorted(row['name'] for row in response.json()['items'])==sorted(names)


@pytest.mark.parametrize('name,quantity,expected',[
    ('2 xylitol candy',2,'xylitol candy'),('1x milk',1,'milk'),('2× milk',2,'milk'),
    ('7 Up',2,'7 Up'),('2 kg sugar',2,'2 kg sugar'),
])
def test_text_quantity_cleanup_respects_boundaries(name,quantity,expected):
    from api.server import clean_item_name
    assert clean_item_name(name,quantity)==expected
