import json
import pytest
import models
from core.catalog_research import extract_products,matching_candidates,research_catalog,price,PublicCatalogClient,ResearchUnavailable,safe_url
from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
from tests.test_browser import browser,open_app
from core.catalog_research import RobotsPolicy, BrowserCaptureClient, USER_AGENT
from datetime import datetime, timezone, timedelta

URL='https://www.bigbasket.com/pd/1/milk/'


def rendered_card(amount='73.00',pack='1 L - Tetra Pak'):
    return f'''<div class="SKUDeck___StyledDiv-sc-example"><h3><a href="/pd/306926/amul-milk/">Amul Taaza Homogenised Toned Milk</a>
    <button>{pack}</button></h3><span>4.1</span><span class="sc-guJBdh">₹{amount}</span>
    <span class="Pricing___StyledLabel2">₹77.00</span></div>'''


def test_rendered_card_never_uses_mrp_rating_or_wrong_pack():
    rows=extract_products(rendered_card()+rendered_card('40','500 ml - Pouch'),URL,'bigbasket')
    matched=matching_candidates('Amul Taaza Homogenised Toned Milk 1 L',rows)
    assert len(matched)==1 and matched[0]['price']==73
    assert matched[0]['sku']=='306926' and matched[0]['availability']=='unknown'
    assert extract_products(rendered_card().replace('sc-guJBdh','changed-selector'),URL,'bigbasket')==[]
    assert extract_products(rendered_card().replace('</div>','<span class="sc-guJBdh">₹20</span></div>'),URL,'bigbasket')==[]


def test_rendered_product_uses_labelled_selling_price_only():
    markup='''<section><h1>Amul Taaza Milk 1 L</h1><table><tr><td>MRP:</td><td>₹77</td></tr>
    <tr><td>Price: ₹73</td><td>(₹7.3 / 100ml)</td></tr></table></section>
    <aside>Another pack ₹15 Not available</aside>'''
    rows=extract_products(markup,URL,'bigbasket')
    assert len(rows)==1 and rows[0]['price']==73 and rows[0]['availability']=='unknown'
    assert extract_products(markup.replace('Price:','MRP:'),URL,'bigbasket')==[]


def test_single_variant_card_uses_non_button_pack_selector():
    markup=rendered_card().replace('<button>','<span class="PackSelector___StyledLabel">').replace('</button>','</span>')
    rows=extract_products(markup,URL,'bigbasket')
    assert len(rows)==1 and '1 L' in rows[0]['name']


def test_capture_exporter_downloads_only_public_product_markup(browser,tmp_path):
    from pathlib import Path
    page=browser.new_page()
    try:
        page.route('https://www.bigbasket.com/**',lambda route:route.fulfill(
            status=200,content_type='text/plain; charset=utf-8' if route.request.url.endswith('/robots.txt') else 'text/html; charset=utf-8',
            body='User-agent: *\nAllow: /' if route.request.url.endswith('/robots.txt') else rendered_card()+
            '<input value="private"><script>window.privateAccount="private"</script>'))
        page.goto('https://www.bigbasket.com/pc/milk/')
        script=(Path(__file__).resolve().parents[1]/'tools/export_catalogue_capture.js').read_text(encoding='utf-8')
        with page.expect_download() as pending:page.evaluate(script)
        download=pending.value;target=tmp_path/'capture.json';download.save_as(str(target))
        captures=json.loads(target.read_text(encoding='utf-8'))
        assert 'private' not in captures[0]['html']
        client=BrowserCaptureClient(captures)
        rows=extract_products(*client.fetch(captures[0]['url'],'bigbasket'),'bigbasket')
        assert rows and rows[0]['price']==73
    finally:page.close()


def test_robots_longest_match_wildcard_anchor_and_allow_tie():
    policy=RobotsPolicy('User-agent: *\nAllow: /\nDisallow: /ps/\nDisallow: /*?page=\nAllow: /*pc*?page=2$\nDisallow: /same\nAllow: /same')
    assert not policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/ps/?q=milk')
    assert policy.can_fetch(USER_AGENT,URL)
    assert policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/pc/milk/?page=2')
    assert not policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/pc/milk/?page=20')
    assert policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/same')
    assert not policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/%70s/')


def test_robots_specific_groups_merge_and_override_wildcard():
    policy=RobotsPolicy('User-agent: *\nDisallow: /\nUser-agent: SnapSaveResearch\nAllow: /pd/\nUser-agent: SnapSaveResearch\nDisallow: /pd/private\nCrawl-delay: 4')
    assert policy.can_fetch(USER_AGENT,URL)
    assert not policy.can_fetch(USER_AGENT,'https://www.bigbasket.com/pd/private')
    assert policy.crawl_delay(USER_AGENT)==4


def capture(**changes):
    return {'url':URL,'store':'bigbasket','html':rendered_card(), 'robots':'User-agent: *\nAllow: /',
            'captured_at':datetime.now(timezone.utc).isoformat(),**changes}


@pytest.mark.parametrize('changes',[
    {'captured_at':(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()},
    {'captured_at':(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()},
    {'captured_at':'2026-10-25T12:00:00'}, {'robots':'User-agent: *\nAllow: /\nDisallow: /pd/'},
    {'robots':'<html>Access Denied</html>'}, {'url':'https://evil.test/'}, {'html':'x'*2_000_001},
])
def test_invalid_stale_or_disallowed_capture_is_rejected(changes):
    with pytest.raises(ResearchUnavailable):BrowserCaptureClient([capture(**changes)])


def test_browser_capture_enters_same_review_only_provider_and_deduplicates(monkeypatch):
    other='https://www.bigbasket.com/pc/milk/'
    client=BrowserCaptureClient([capture(),capture(url=other)])
    draft=research_catalog([{'item_id':'a','name':'Amul Taaza Homogenised Toned Milk 1 L','quantity':2}],'110001',client)
    assert draft['transport']=='browser_capture' and draft['verified'] is False
    rows=draft['items'][0]['candidates']
    assert len(rows)==1 and rows[0]['price']==73 and rows[0]['observed_at']
    assert draft['requires_human_review'] and 'delivery_fee' not in draft


def test_configured_capture_is_consumed_by_provider(monkeypatch,tmp_path):
    path=tmp_path/'public-capture.json';path.write_text(json.dumps([capture()]),encoding='utf-8')
    monkeypatch.setenv('RESEARCH_BROWSER_CAPTURE_FILE',str(path))
    result=research_catalog([{'item_id':'a','name':'Amul Taaza Homogenised Toned Milk 1 L','quantity':1}],'110001')
    assert result['transport']=='browser_capture' and result['items'][0]['candidates'][0]['price']==73


def zepto_card(pack='1 pack (1 L)',stock='false'):
    return f'''<a data-testid="product-card" href="/pn/amul/pvid/variant-one"><div data-is-out-of-stock="{stock}">
    <div data-slot-id="ProductName">Amul Taaza Homogenised Toned Milk</div><div data-slot-id="PackSize">{pack}</div>
    <div data-slot-id="EdlpPrice"><span class="cptQT7">₹<!-- -->77</span><span>₹90</span></div></div></a>'''


def instamart_card(name='Epigamia High Protein Paneer',pack='200 g',amount='150'):
    return f'''<div class="_1fi7p"><div class="_1iFYi">{name}</div><div class="_3wq_F">{pack}</div>
    <div data-testid="offer-text">40% OFF</div><div class="_2enD-"><div class="_2jn41">{amount}</div>
    <div class="_2jn41 _3eAjW _1VrXB">250</div></div></div>'''


def blinkit_card(name='Amul Taaza Homogenised Toned Milk',pack='1 ltr'):
    return f'''<div role="button" id="176"><div class="tw-line-clamp-2">{name}</div><div class="tw-line-clamp-1">{pack}</div>
    <div class="tw-text-200 tw-font-semibold">₹77</div><span class="tw-line-through">₹90</span></div>'''


@pytest.mark.parametrize('store,url,markup,amount',[
    ('zepto','https://www.zepto.com/category/milk',zepto_card(),77),
    ('instamart','https://www.swiggy.com/instamart/',instamart_card(),150),
    ('blinkit','https://blinkit.com/cn/milk/cid/14/922',blinkit_card(),77),
])
def test_three_store_rendered_prices_exclude_mrp_and_discount(store,url,markup,amount):
    rows=extract_products(markup,url,store)
    assert len(rows)==1 and rows[0]['price']==amount and rows[0]['availability']=='unknown'
    assert rows[0]['pack_size']


def test_zepto_rejects_ambiguous_packs_and_excludes_unavailable():
    url='https://www.zepto.com/category/milk'
    assert extract_products(zepto_card('475 ml or 500 ml'),url,'zepto')==[]
    rows=extract_products(zepto_card(stock='true'),url,'zepto')
    assert rows[0]['availability']=='out_of_stock'
    assert matching_candidates('Amul milk 1 L',rows)==[]


def test_selected_pack_overrides_protein_claim_and_size_in_product_name():
    rows=extract_products(instamart_card('Foodstrong 25g High Protein Milkshake','250 ml','74'),'https://www.swiggy.com/instamart/','instamart')
    assert matching_candidates('Foodstrong High Protein Milkshake 250 ml',rows)
    rows=extract_products(blinkit_card('Mother Dairy FIT Life Milk (450 ml)','400 ml'),'https://blinkit.com/cn/milk/cid/14/922','blinkit')
    assert matching_candidates('Mother Dairy FIT Life Milk 400 ml',rows)
    assert not matching_candidates('Mother Dairy FIT Life Milk 450 ml',rows)


def test_different_instamart_products_at_same_price_are_not_collapsed():
    url='https://www.swiggy.com/instamart/'
    client=BrowserCaptureClient([capture(store='instamart',url=url,html=instamart_card('Epigamia Paneer','200 g')+instamart_card('Epigamia Paneer Premium','200 g'))])
    result=research_catalog([{'item_id':'p','name':'Epigamia Paneer 200 g','quantity':1}],'110001',client)
    assert len(result['items'][0]['candidates'])==2


@pytest.mark.parametrize('context,status',[
    ({},'needs_location'),({'selected_postal_code':'110001'},'postcode_observed'),
    ({'selected_postal_code':'560001'},'mismatch'),
    ({'staff_confirmed':True,'attested_postal_code':'110001'},'staff_attested'),
])
def test_customer_location_state_never_claims_serviceability(context,status):
    from core.catalog_research import capture_location
    result=capture_location(context,'110001')
    assert result['status']==status and result['serviceability_verified'] is False


def test_mismatched_retailer_location_cannot_produce_candidates():
    client=BrowserCaptureClient([capture(location_context={'selected_postal_code':'560001'})])
    result=research_catalog([{'item_id':'a','name':'Amul Taaza Homogenised Toned Milk 1 L','quantity':1}],'110001',client)
    assert result['items'][0]['candidates']==[] and 'postcode' in result['diagnostics'][0]['reason']


def test_staff_import_is_order_bound_and_preserves_existing_prices(client,actors,order,db):
    row=db.get(models.Order,order['id'])
    row.manual_prices=json.dumps({'items':[{'retained':'manual draft'}]});db.commit()
    headers=actors['admin']['headers'];base=f"/api/moderator/orders/{row.id}"
    plan=client.get(base+'/research-location',headers=headers).json()
    assert plan['postal_code']==row.delivery_postal_code and 'street' not in json.dumps(plan)
    context={k:plan[k] for k in ('order_id','revision','postal_code')}
    entry=capture(research_context=context,location_context={'staff_confirmed':True,'attested_postal_code':plan['postal_code']})
    body={'revision':plan['revision'],'captures':[entry]}
    assert client.post(base+'/research-evidence',headers=actors['customer']['headers'],json=body).status_code==403
    bad={**entry,'research_context':{**context,'order_id':'another-order'}}
    assert client.post(base+'/research-evidence',headers=headers,json={**body,'captures':[bad]}).status_code==422
    response=client.post(base+'/research-evidence',headers=headers,json=body)
    assert response.status_code==200,response.text
    db.expire_all();row=db.get(models.Order,row.id)
    draft=json.loads(row.manual_prices)
    assert draft['items']==[{'retained':'manual draft'}] and draft['research_draft']['verified'] is False
    assert float(row.final_price)==0 and row.status=='pending_review'
    assert client.post(base+'/research-evidence',headers=headers,json=body).status_code==409


def test_staff_import_requires_location_and_blocks_other_moderators(client,actors,order):
    headers=actors['admin']['headers'];base=f"/api/moderator/orders/{order['id']}"
    plan=client.get(base+'/research-location',headers=headers).json()
    context={k:plan[k] for k in ('order_id','revision','postal_code')}
    body={'revision':plan['revision'],'captures':[capture(research_context=context)]}
    assert client.get(base+'/research-location',headers=actors['moderator']['headers']).status_code==403
    assert client.post(base+'/research-evidence',headers=headers,json=body).status_code==422
    body['captures'][0]['location_context']={'selected_postal_code':'560001'}
    assert client.post(base+'/research-evidence',headers=headers,json=body).status_code==422


def test_ai_worker_rejects_browser_context_from_another_order(monkeypatch,client,actors,order,db):
    monkeypatch.setenv('ENABLE_LIVE_RESEARCH','true')
    provider=lambda *_:{'verified':False,'requires_human_review':True,'postal_code':'110001',
        'research_contexts':[{'order_id':'another-order','revision':0,'postal_code':'110001'}],
        'items':[{'item_id':i['id'],'candidates':[]} for i in order['items']]}
    monkeypatch.setattr('settings.research_provider',lambda:provider)
    monkeypatch.setattr(AI,'research',staticmethod(provider))
    db.get(models.SystemSetting,'ai_enabled').value='true'
    row=db.get(models.Order,order['id']);row.mode='AI';row.assigned_worker_type='AI';db.commit()
    AI.process_ticket(row.id,db);db.refresh(row)
    assert row.manual_prices is None and row.mode=='HUMAN' and 'different order' in row.ai_error


@pytest.mark.parametrize('store,url,markup,amount',[
    ('zepto','https://www.zepto.com/category/milk',zepto_card(),77),
    ('instamart','https://www.swiggy.com/instamart/',instamart_card(),150),
    ('blinkit','https://blinkit.com/cn/milk/cid/14/922',blinkit_card(),77),
])
def test_three_store_export_download_roundtrip(browser,tmp_path,store,url,markup,amount):
    from pathlib import Path
    page=browser.new_page()
    context={'order_id':'test-order','revision':1,'postal_code':'110001'}
    page.on('dialog',lambda dialog:dialog.accept(json.dumps(context)) if dialog.type=='prompt' else dialog.accept())
    try:
        page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body='User-agent: *\nAllow: /' if route.request.url.endswith('/robots.txt') else markup))
        page.goto(url)
        script=(Path(__file__).resolve().parents[1]/'tools/export_catalogue_capture.js').read_text(encoding='utf-8')
        with page.expect_download() as pending:page.evaluate(script)
        path=tmp_path/'capture.json';pending.value.save_as(str(path))
        capture_rows=json.loads(path.read_text(encoding='utf-8'));entry=capture_rows[0]
        assert entry['store']==store and entry['research_context']==context
        assert entry['location_context']['staff_confirmed'] is True
        client=BrowserCaptureClient(capture_rows)
        rows=extract_products(*client.fetch(url,store),store)
        assert rows[0]['price']==amount
    finally:page.close()


def test_admin_location_controls_and_capture_import(browser,client,actors,order,db):
    headers=actors['admin']['headers'];plan=client.get(f"/api/moderator/orders/{order['id']}/research-location",headers=headers).json()
    entry=capture(research_context={k:plan[k] for k in ('order_id','revision','postal_code')},location_context={'staff_confirmed':True,'attested_postal_code':plan['postal_code']})
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        panel=page.locator('#research-evidence-panel')
        assert 'Customer postcode: '+plan['postal_code'] in panel.inner_text()
        assert panel.get_by_role('link',name='Open Instamart').count()==1
        page.get_by_label('Import retailer capture JSON').set_input_files({'name':'capture.json','mimeType':'application/json','buffer':json.dumps([entry]).encode()})
        page.wait_for_function("document.querySelector('#research-evidence-panel').textContent.includes('staff confirmed postcode')")
        assert panel.locator('a',has_text='View source').count()>=1
        assert all(value=='' for value in page.locator('.pi-price').evaluate_all('(nodes)=>nodes.map(n=>n.value)'))
        assert not errors,errors
    finally:page.close()


def test_export_stops_if_location_hydrates_during_capture(browser):
    from pathlib import Path
    page=browser.new_page()
    context={'order_id':'test-order','revision':1,'postal_code':'110001'}
    page.on('dialog',lambda dialog:dialog.accept(json.dumps(context)) if dialog.type=='prompt' else dialog.accept())
    markup=zepto_card()+'''<header>Select location</header><script>
    window.fetch=async()=>{document.querySelector('header').textContent='Other area 560001';
        return new Response('User-agent: *\\nAllow: /',{status:200});};</script>'''
    try:
        page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=markup))
        page.goto('https://www.zepto.com/category/milk')
        script=(Path(__file__).resolve().parents[1]/'tools/export_catalogue_capture.js').read_text(encoding='utf-8')
        with pytest.raises(Exception,match='location changed'):page.evaluate(script)
    finally:page.close()


def product(name='Amul milk 1 L',amount='72.50',currency='INR',stock='InStock'):
    return {'@type':'Product','name':name,'sku':'milk-1','url':URL,'offers':{'@type':'Offer','price':amount,'priceCurrency':currency,'availability':'https://schema.org/'+stock}}


def html(*rows):
    return '<html><div>Ad: ₹1, rating: 4.8, 100 ml price: ₹7.25</div><script type="application/ld+json">'+json.dumps({'@graph':list(rows)})+'</script></html>'


def test_product_scoped_price_and_pack_stock_matching():
    rows=extract_products(html(product(),product('Amul milk 500 ml','40'),product('Amul milk 1 L','1',stock='OutOfStock')),URL,'bigbasket')
    selected=matching_candidates('Amul milk 1000 ml',rows)
    assert len(selected)==1 and selected[0]['price']==72.5
    assert selected[0]['source_url']==URL and selected[0]['sku']=='milk-1'


@pytest.mark.parametrize('amount',[True,None,'NaN','-2','0','₹40 ₹60','1.234','Infinity'])
def test_invalid_or_ambiguous_prices_are_rejected(amount):
    with pytest.raises(ValueError):price(amount)
    assert extract_products(html(product(amount=amount)),URL,'bigbasket')==[]


def test_currency_and_aggregate_ranges_are_not_assumed():
    aggregate=product();aggregate['offers']={'@type':'AggregateOffer','lowPrice':'10','highPrice':'100','priceCurrency':'INR'}
    assert extract_products(html(product(currency='USD'),aggregate),URL,'bigbasket')==[]


def test_nested_microdata_cannot_borrow_another_product_price():
    content='''<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Amul milk 1 L</span>
      <aside itemscope itemtype="https://schema.org/Product"><span itemprop="name">Soap</span>
      <meta itemprop="price" content="12"><meta itemprop="priceCurrency" content="INR"></aside></div>'''
    rows=extract_products(content,URL,'bigbasket')
    assert [r['name'] for r in rows]==['Soap']


@pytest.mark.parametrize('url',['http://www.bigbasket.com/','https://127.0.0.1/','https://www.bigbasket.com.evil.test/','https://www.bigbasket.com@evil.test/','https://www.bigbasket.com:8000/','file:///etc/passwd'])
def test_source_origin_is_restricted(url):
    with pytest.raises(ResearchUnavailable):safe_url(url,'bigbasket')


class Response:
    def __init__(self,text='',status=200,headers=None):
        self.body=text.encode();self.status_code=status;self.headers=headers or {};self.encoding='utf-8'
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield self.body


class Session:
    def __init__(self,robots='User-agent: *\nAllow: /',page=None):
        self.robots=robots;self.page=page or Response(html(product()));self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(url)
        return Response(self.robots) if url.endswith('/robots.txt') else self.page
    def close(self):pass


def test_blocked_robots_never_fetches_the_catalogue():
    session=Session('User-agent: *\nDisallow: /pd/')
    client=PublicCatalogClient(session=session)
    with pytest.raises(ResearchUnavailable,match='robots'):client.fetch(URL,'bigbasket')
    assert session.calls==['https://www.bigbasket.com/robots.txt']


def test_challenge_status_is_not_retried_with_different_identity(monkeypatch):
    monkeypatch.setattr('core.catalog_research.time.sleep',lambda *_:None)
    session=Session(page=Response('',403));client=PublicCatalogClient(session=session)
    for _ in range(2):
        with pytest.raises(ResearchUnavailable,match='HTTP 403'):client.fetch(URL,'bigbasket')
    assert len(session.calls)==2


def test_redirect_cannot_escape_retailer(monkeypatch):
    monkeypatch.setattr('core.catalog_research.time.sleep',lambda *_:None)
    client=PublicCatalogClient(session=Session(page=Response('',302,{'Location':'http://127.0.0.1/private'})))
    with pytest.raises(ResearchUnavailable):client.fetch(URL,'bigbasket')
    assert client.requests==2


def test_oversized_response_and_request_budget_are_bounded(monkeypatch):
    monkeypatch.setattr('core.catalog_research.time.sleep',lambda *_:None)
    client=PublicCatalogClient(session=Session(page=Response('a'*2_000_001)))
    with pytest.raises(ResearchUnavailable,match='size/time'):client.fetch(URL,'bigbasket')
    client=PublicCatalogClient(max_requests=0,session=Session())
    with pytest.raises(ResearchUnavailable,match='budget'):client.fetch(URL,'bigbasket')


def test_draft_is_never_marked_as_postcode_verified(monkeypatch):
    monkeypatch.setenv('RESEARCH_CATALOG_SOURCES',json.dumps({'bigbasket':[URL]}))
    class FakeClient:
        def fetch(self,url,store):return html(product()),URL
    draft=research_catalog([{'item_id':'a','name':'Amul milk 1 L','quantity':2}],'110001',client=FakeClient())
    assert draft['verified'] is False and draft['requires_human_review'] is True
    assert draft['items'][0]['candidates'][0]['price']==72.5
    assert 'line_total' not in draft['items'][0] and 'delivery_fee' not in draft


def test_research_draft_enters_human_review_without_publishing_quote(monkeypatch,client,actors,order,db):
    monkeypatch.setenv('ENABLE_LIVE_RESEARCH','true')
    provider=lambda *_:{'verified':False,'requires_human_review':True,'postal_code':'110001','items':[{'item_id':i['id'],'query':i['name'],'quantity':i['quantity'],'candidates':[]} for i in order['items']]}
    monkeypatch.setattr('settings.research_provider',lambda:provider)
    monkeypatch.setattr(AI,'research',staticmethod(provider))
    db.get(models.SystemSetting,'ai_enabled').value='true'
    row=db.get(models.Order,order['id']);row.mode='AI';row.assigned_worker_type='AI';db.commit()
    AI.process_ticket(row.id,db);db.refresh(row)
    assert row.mode=='HYBRID' and row.assigned_worker_type=='HUMAN'
    assert row.status=='pending_review' and float(row.final_price)==0
    assert json.loads(row.manual_prices)['research_draft']['verified'] is False
    assert all(i.line_total is None for i in row.items)
    assert db.query(models.Message).filter_by(order_id=row.id,kind='quote').count()==0


def test_draft_cannot_write_after_global_kill(monkeypatch,client,actors,order,db):
    monkeypatch.setenv('ENABLE_LIVE_RESEARCH','true')
    def provider(*_):
        assert client.put('/api/admin/settings/ai-status',headers=actors['admin']['headers'],json={'ai_enabled':False}).status_code==200
        return {'verified':False,'requires_human_review':True,'postal_code':'110001','items':[{'item_id':i['id'],'candidates':[]} for i in order['items']]}
    monkeypatch.setattr('settings.research_provider',lambda:provider)
    monkeypatch.setattr(AI,'research',staticmethod(provider))
    db.get(models.SystemSetting,'ai_enabled').value='true'
    row=db.get(models.Order,order['id']);row.mode='AI';row.assigned_worker_type='AI';db.commit()
    AI.process_ticket(row.id,db);db.refresh(row)
    assert row.manual_prices is None and row.mode=='HUMAN'


def test_admin_evidence_is_readable_safe_and_does_not_fill_prices(browser,client,actors,order,db):
    row=db.get(models.Order,order['id']);row.mode='HYBRID';row.is_ai_priced=True
    payload='<img src=x onerror="window.auditInjected=true">'
    row.manual_prices=json.dumps({'research_draft':{'items':[{'query':payload,'candidates':[
        {'store':'bigbasket','name':'Amul milk 1 L','price':72.5,'source_url':URL,'availability':'unknown'},
        {'store':'zepto','name':payload,'price':1,'source_url':'javascript:alert(1)'}]}]}})
    db.commit()
    page,errors=open_app(browser,client,actors['admin'],db,'admin.html')
    try:
        page.locator('#queue-list .queue-card').first.click()
        panel=page.locator('#research-evidence-panel');panel.wait_for(state='visible')
        assert 'needs verification' in panel.inner_text()
        assert '72.50' in panel.inner_text() and payload in panel.inner_text()
        sources=panel.get_by_role('link',name='View source',exact=True)
        assert sources.count()==1 and sources.get_attribute('href')==URL
        assert panel.locator('a[href^="javascript:"]').count()==0
        assert panel.locator('img').count()==0 and page.evaluate('window.auditInjected') is None
        assert all(value=='' for value in page.locator('.pi-price').evaluate_all('(nodes)=>nodes.map(n=>n.value)'))
        assert not errors,errors
    finally:page.close()
