import json
import os
import time
import hashlib
import base64
import threading
from urllib.parse import urlsplit,parse_qs
from types import SimpleNamespace
import pytest
import requests
from core.swiggy_mcp import CredentialStore,SwiggySearchClient,SwiggyUnavailable,SwiggyAuthorizationRequired,rpc_payload,token_record


def test_json_and_sse_responses_use_only_matching_request_ids():
    assert rpc_payload('{"id":2,"result":{"ok":true}}',2)=={'ok':True}
    assert rpc_payload('event: message\ndata: {"id":1,"result":{}}\n\nevent: message\ndata: {"id":2,"result":{"ok":true}}\n\n',2)=={'ok':True}
    with pytest.raises(SwiggyUnavailable):rpc_payload('{"id":99,"result":{}}',2)
    with pytest.raises(SwiggyAuthorizationRequired):rpc_payload('{"id":2,"error":{"code":-32001}}',2)


@pytest.mark.skipif(os.name!='nt',reason='Windows-only DPAPI protection')
def test_credentials_are_encrypted_for_current_windows_user(tmp_path):
    path=tmp_path/'tokens.dpapi';store=CredentialStore(path)
    original={'access_token':'secret-fixture-access-token','refresh_token':'secret-fixture-refresh-token','expires_at':time.time()+3600,'client_id':'fixture-client'}
    store.save(original)
    assert b'secret-fixture' not in path.read_bytes()
    assert store.load()==original


@pytest.mark.parametrize('tool',['checkout','update_cart','get_addresses','confirm_order'])
def test_only_read_only_product_search_can_be_called(tool):
    client=SwiggySearchClient(SimpleNamespace(load=lambda:pytest.fail('Credentials must not be loaded for a forbidden call')))
    try:
        with pytest.raises(SwiggyUnavailable,match='Only read-only'):client.call_tool(tool,{})
    finally:client.close()


@pytest.mark.parametrize('changes',[{'latitude':True},{'latitude':91},{'longitude':float('nan')},{'addressId':'private-address'},{'offset':-1},{'query':''}])
def test_guest_search_requires_explicit_valid_coordinates_and_query(changes):
    client=SwiggySearchClient(SimpleNamespace(load=lambda:pytest.fail('Invalid input must not send an account request')))
    try:
        with pytest.raises(SwiggyUnavailable):client.call_tool('search_products',{'query':'milk','latitude':1,'longitude':2,**changes})
    finally:client.close()


def test_search_preserves_documented_raw_price_and_variant_fields(monkeypatch):
    data={'products':[{'displayName':'Amul milk','inStock':True,'isAvail':True,'variations':[{'spinId':'one','skuId':'sku','quantityDescription':'1 L','price':{'mrp':80,'offerPrice':77},'isInStockAndAvailable':True}]}]}
    store=SimpleNamespace(load=lambda:{'access_token':'fixture','expires_at':time.time()+3600},save=lambda _:None)
    client=SwiggySearchClient(store);calls=[]
    def rpc(method,params,notify=False):
        calls.append((method,params))
        return {'structuredContent':{'success':True,'data':data}} if method=='tools/call' else {}
    monkeypatch.setattr(client,'_rpc',rpc)
    try:result=client.call_tool('search_products',{'query':'milk','latitude':1,'longitude':2})
    finally:client.close()
    assert result==data
    assert calls[-1][1]['name']=='search_products' and len(calls)==3
    assert 'line_total' not in result and 'verified' not in result


def test_oauth_callback_checks_state_and_pkce_without_logging_tokens(monkeypatch,capsys):
    import connect_swiggy
    auth={};saved=[];threads=[];statuses=[]
    def exchange(path,payload):
        if path=='/auth/register':
            assert payload['token_endpoint_auth_method']=='none'
            return {'client_id':'fixture-client'}
        assert path=='/auth/token' and payload['code']=='fixture-code'
        challenge=base64.urlsafe_b64encode(hashlib.sha256(payload['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        assert challenge==auth['code_challenge'][0]
        return {'access_token':'private-fixture-token','refresh_token':'private-fixture-refresh','expires_in':3600}
    monkeypatch.setattr(connect_swiggy,'oauth_json',exchange)
    def ready(url):
        auth.update(parse_qs(urlsplit(url).query))
        def callback():
            invalid=requests.get('http://localhost:8765/oauth/callback',params={'state':'wrong-state','code':'fixture-code'},timeout=5);statuses.append(invalid.status_code)
            valid=requests.get('http://localhost:8765/oauth/callback',params={'state':auth['state'][0],'code':'fixture-code'},timeout=5);statuses.append(valid.status_code)
        thread=threading.Thread(target=callback);thread.start();threads.append(thread)
    assert connect_swiggy.connection(SimpleNamespace(save=saved.append),ready=ready,timeout=5)
    for thread in threads:thread.join(5)
    assert statuses==[400,200] and saved[0]['access_token']=='private-fixture-token'
    assert 'private-fixture' not in capsys.readouterr().out


def test_invalid_token_metadata_is_not_saved():
    with pytest.raises(SwiggyUnavailable):token_record({'access_token':'fixture','expires_in':float('nan')},'client')


def test_autonomous_source_failures_are_not_repeated_per_item(monkeypatch):
    from core import autonomous_research as provider
    diagnostic={'store':'zepto','url':'https://www.zepto.com/category/milk','status':'unavailable','reason':'HTTP 202'}
    monkeypatch.setattr(provider,'research_basket',lambda *args:{'items':[{'candidates':[]}], 'diagnostics':[diagnostic,dict(diagnostic)]})
    result=provider.research([{'item_id':'a','name':'milk','quantity':1}],'382421')
    assert len(result['diagnostics'])==1 and result['autonomous_attempt']


def test_streamed_response_returns_before_the_server_closes_the_stream():
    class Response:
        status_code=200;headers={'Content-Type':'text/event-stream'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):
            stream=b'data: {"method":"notification"}\n\ndata: {"id":1,"result":{"ok":true}}\n\n'
            for byte in stream:yield bytes([byte])
            pytest.fail('The client must return when its event completes, without waiting for EOF')
    class Session:
        def post(self,url,**kwargs):
            assert url=='https://mcp.swiggy.com/im' and kwargs['allow_redirects'] is False
            return Response()
        def close(self):pass
    client=SwiggySearchClient(None,Session());client.credentials={'access_token':'fixture'}
    assert client._rpc('initialize',{})=={'ok':True}


def test_search_reuses_its_initialized_session(monkeypatch):
    store=SimpleNamespace(load=lambda:{'access_token':'fixture','expires_at':time.time()+3600})
    client=SwiggySearchClient(store);calls=[]
    def rpc(method,params,notify=False):
        calls.append(method)
        return {'structuredContent':{'success':True,'data':{'products':[]}}} if method=='tools/call' else {}
    monkeypatch.setattr(client,'_rpc',rpc)
    try:
        for _ in range(2):client.call_tool('search_products',{'query':'milk','latitude':1,'longitude':2})
    finally:client.close()
    assert calls.count('initialize')==1 and calls.count('tools/call')==2
