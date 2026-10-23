import pytest
import models
from tests.test_browser import browser, open_app


def own_order(client, actor):
    address=client.post('/api/addresses',headers=actor['headers'],json={
        'title':'Home','street_address':'Example street','city':'Delhi',
        'state':'Delhi','postal_code':'110001'}).json()
    result=client.post('/api/orders',headers=actor['headers'],json={
        'address_id':address['id'],'items_text':'2kg sugar'})
    assert result.status_code==201,result.text
    return result.json()


@pytest.mark.parametrize('actor_name',['customer','admin','moderator'])
def test_order_owner_messages_are_customer_participation(client,actors,db,actor_name):
    actor=actors[actor_name]
    order=own_order(client,actor)
    path=f"/api/chat/{actor['id']}"
    assert client.get(f"/api/orders/{order['id']}",headers=actor['headers']).status_code==200
    for text in ['ok','what']:
        result=client.post(path+'/send',headers=actor['headers'],json={'order_id':order['id'],'message':text})
        assert result.status_code==200,result.text
        assert db.get(models.Message,result.json()['id']).sender_role=='CUSTOMER'
    messages=client.get(path+'/messages',headers=actor['headers'],params={'order_id':order['id']})
    assert messages.status_code==200,messages.text
    assert all(m['sender_role']=='CUSTOMER' for m in messages.json() if m['sender_id']==actor['id'])
    assert db.get(models.Order,order['id']).first_response_at is None
    assert client.get(path+'/messages',headers=actors['other']['headers'],params={'order_id':order['id']}).status_code==403
    # Actual staff replies in someone else's thread keep the staff identity/timing.
    if actor_name!='admin':
        response=client.post(path+'/send',headers=actors['admin']['headers'],json={'order_id':order['id'],'message':'We are checking prices'})
        assert response.status_code==200
        assert db.get(models.Message,response.json()['id']).sender_role=='ADMIN'
        db.expire_all()
        assert db.get(models.Order,order['id']).first_response_at is not None


def test_old_owner_roles_render_correctly_without_changing_staff_or_ai(client,actors,db):
    actor=actors['admin'];order=own_order(client,actor)
    legacy=models.Message(user_id=actor['id'],order_id=order['id'],sender_id=actor['id'],sender_role='ADMIN',kind='text',message='Old customer follow-up')
    bot=models.Message(user_id=actor['id'],order_id=order['id'],sender_id='system_ai',sender_role='AI',kind='quote',message='Quote')
    staff=models.Message(user_id=actor['id'],order_id=order['id'],sender_id=actors['moderator']['id'],sender_role='MODERATOR',kind='text',message='Staff reply')
    db.add_all([legacy,bot,staff]);db.commit()
    response=client.get(f"/api/chat/{actor['id']}/messages",headers=actor['headers'],params={'order_id':order['id']})
    roles={m['id']:m['sender_role'] for m in response.json()}
    assert roles[legacy.id]=='CUSTOMER'
    assert roles[bot.id]=='AI' and roles[staff.id]=='MODERATOR'
    assert db.get(models.Message,legacy.id).sender_role=='ADMIN'


def test_admin_using_customer_page_sees_own_followups_as_you(browser,client,actors,db):
    actor=actors['admin'];own_order(client,actor)
    page,errors=open_app(browser,client,actor,db,'index.html')
    try:
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        for text in ['ok','what']:
            page.locator('#chat-textarea').fill(text)
            page.locator('#btn-send-chat').click()
            page.wait_for_function('text=>[...document.querySelectorAll(".message-wrapper.customer")].some(n=>n.textContent.includes(text))',arg=text)
            assert page.locator('.message-wrapper.moderator').count()==0
        assert page.locator('.message-wrapper.customer .message-sender').all_text_contents()==['You','You','You']
        assert not errors,errors
    finally:page.close()
