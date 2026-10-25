import os
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
from pricing.research_draft import price_proposal
from tests.test_browser import browser,open_app
from tests.test_order_research_integration import automatic,make_order,import_store
from tests.test_catalog_research import zepto_card,instamart_card


def candidate(**changes):
    return {'name':'Amul milk 1 L','pack_size':'1 L','price':77,'currency':'INR',
        'store':'zepto','sku':'one','source_url':'https://www.zepto.com/pn/milk/pvid/one',
        'observed_at':datetime.now(timezone.utc).isoformat(),'availability':'unknown',
        'location_context':{'requested_postal_code':'382421','status':'staff_attested'},**changes}


def proposal(rows,quantity=2,name='Amul milk 1 L',selections=None):
    return price_proposal([{'item_id':'a','name':name,'quantity':quantity}],
        {'items':[{'item_id':'a','candidates':rows}]},'382421',selections)


def test_pack_price_is_multiplied_by_requested_quantity_without_invented_fees():
    result=proposal([candidate()])
    assert result['items'][0]['observed_pack_price']==77 and result['items'][0]['line_total']==154
    assert result['subtotal']==154 and result['complete']
    assert result['payable_total'] is None and result['fees_verified'] is False and result['requires_human_review']


@pytest.mark.parametrize('name,pack,quantity,expected',[
    ('milk 1000 ml','1 L',3,231),('rice 1 kg','1000 g',2,154),
    ('Eggs pack of 6','6 pieces',2,154),('milk 0.5 L','500 ml',1,77),
])
def test_equivalent_explicit_pack_units(name,pack,quantity,expected):
    result=proposal([candidate(name=name,pack_size=pack)],quantity,name)
    assert result['items'][0]['line_total']==expected


@pytest.mark.parametrize('changes',[
    {'pack_size':'500 ml'},{'pack_size':'2 x 500 ml'},{'pack_size':'1 L or 500 ml'},
    {'price':0},{'price':-1},{'currency':'USD'},{'availability':'out_of_stock'},
    {'observed_at':(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()},
    {'location_context':{'requested_postal_code':'110001','status':'staff_attested'}},
    {'source_url':'https://other.test/milk'},{'name':'A different product 1 L'},
])
def test_unsupported_evidence_does_not_generate_a_price(changes):
    result=proposal([candidate(**changes)])
    assert result['items'][0]['state']=='needs_fresh_evidence'
    assert result['subtotal'] is None and result['matched_subtotal']==0


def test_missing_pack_and_multiple_variants_require_a_choice():
    assert proposal([candidate()],name='milk')['items'][0]['state']=='needs_pack'
    rows=[candidate(),candidate(sku='two',price=90)]
    assert proposal(rows)['items'][0]['state']=='needs_selection'
    assert proposal(rows,selections={'a':1})['items'][0]['line_total']==180
    with pytest.raises(ValueError):proposal(rows,selections={'another-order-item':0})
    with pytest.raises(ValueError):proposal([candidate(pack_size='500 ml')],selections={'a':0})


def test_api_prices_current_order_evidence_but_does_not_publish_a_quote(client,actors,order,automatic):
    created=make_order(client,actors,order['address_id'],items=[{'name':'Amul milk 1 L','quantity':2},{'name':'Epigamia High Protein Paneer 200 g','quantity':1}])
    import_store(client,actors,created['id'],'zepto',zepto_card())
    evidence=import_store(client,actors,created['id'],'instamart',instamart_card())
    path=f"/api/moderator/orders/{created['id']}/research-price-draft"
    body={'revision':evidence['revision']}
    assert client.post(path,headers=actors['customer']['headers'],json=body).status_code==403
    assert client.post(path,headers=actors['moderator']['headers'],json=body).status_code==403
    assert client.post(path,headers=actors['admin']['headers'],json={'revision':0}).status_code==409
    response=client.post(path,headers=actors['admin']['headers'],json=body)
    assert response.status_code==200,response.text
    assert response.json()['subtotal']==304 and response.json()['payable_total'] is None
    saved=client.get(f"/api/orders/{created['id']}",headers=actors['customer']['headers']).json()
    assert saved['final_price']==0 and saved['status']=='pending_review'
    assert all(item['line_total'] is None for item in saved['items'])


def test_staff_can_fill_price_form_without_overwriting_an_edited_line(browser,client,actors,order,automatic,db):
    created=make_order(client,actors,order['address_id'],items=[{'name':'Amul milk 1 L','quantity':2},{'name':'Epigamia High Protein Paneer 200 g','quantity':1}])
    import_store(client,actors,created['id'],'zepto',zepto_card())
    import_store(client,actors,created['id'],'instamart',instamart_card())
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('.queue-card').filter(has_text=created['id'][:8]).click()
        page.get_by_role('button',name='Calculate item price draft').click()
        page.wait_for_function("[...document.querySelectorAll('.pi-price')].some(e=>e.value==='154')")
        assert sorted(page.locator('.pi-price').evaluate_all('(nodes)=>nodes.map(n=>Number(n.value))'))==[150,154]
        if os.environ.get('SNAPSAVE_TEST_ARTIFACT_DIR'):
            page.screenshot(path=str(Path(os.environ['SNAPSAVE_TEST_ARTIFACT_DIR'])/'calculated-price-draft.png'),full_page=True)
        first=page.locator('.pi-price').first;first.fill('199')
        page.get_by_role('button',name='Calculate item price draft').click()
        page.wait_for_function("document.querySelector('#research-price-feedback').textContent.includes('calculated')")
        assert first.input_value()=='199'
        assert 'checkout fees' in page.locator('#research-price-feedback').inner_text()
        assert not errors,errors
    finally:page.close()
