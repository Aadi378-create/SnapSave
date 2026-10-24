import json
import pytest
import models
from core.catalog_research import extract_products,matching_candidates,research_catalog,price,PublicCatalogClient,ResearchUnavailable,safe_url
from api.ai_concierge import AI_CONCIERGE_PROVIDER as AI
from tests.test_browser import browser,open_app

URL='https://www.bigbasket.com/pd/1/milk/'


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
        assert panel.locator('a').count()==1 and panel.locator('a').get_attribute('href')==URL
        assert panel.locator('img').count()==0 and page.evaluate('window.auditInjected') is None
        assert all(value=='' for value in page.locator('.pi-price').evaluate_all('(nodes)=>nodes.map(n=>n.value)'))
        assert not errors,errors
    finally:page.close()
