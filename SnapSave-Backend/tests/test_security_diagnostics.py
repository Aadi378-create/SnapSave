import threading
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs
import pytest
import requests
from core.swiggy_mcp import oauth_json,token_record,SwiggyUnavailable


def test_oauth_response_is_bounded_before_reading_the_entire_body():
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @property
        def content(self):pytest.fail('OAuth must not buffer an unbounded response before enforcing the limit')
        def iter_content(self,size):
            yield b'x'*100001
    with pytest.raises(SwiggyUnavailable,match='size|Oversized'):
        oauth_json('/auth/token',{},SimpleNamespace(post=lambda *args,**kwargs:Response()))


@pytest.mark.parametrize('changes',[{'access_token':'bad\r\ntoken'},{'refresh_token':'x'*65537}])
def test_malformed_or_oversized_tokens_are_rejected(changes):
    with pytest.raises(SwiggyUnavailable):token_record({'access_token':'fixture','refresh_token':'fixture-refresh','expires_in':3600,**changes},'client')


def test_oauth_callback_rejects_untrusted_host_without_exchanging_code(monkeypatch):
    import connect_swiggy
    calls=[];saved=[];statuses=[];threads=[]
    def exchange(path,payload):
        calls.append(path)
        return {'client_id':'fixture'} if path=='/auth/register' else {'access_token':'fixture','refresh_token':'fixture','expires_in':3600}
    monkeypatch.setattr(connect_swiggy,'oauth_json',exchange)
    def ready(url):
        state=parse_qs(urlsplit(url).query)['state'][0]
        def callback():
            malformed=requests.get('http://127.0.0.1:8765/oauth/callback',headers={'Host':'localhost:8765'},params={'state':'é','code':'fixture-code'},timeout=5)
            statuses.append(malformed.status_code)
            response=requests.get('http://127.0.0.1:8765/oauth/callback',headers={'Host':'attacker.example'},params={'state':state,'code':'fixture-code'},timeout=5)
            statuses.append(response.status_code)
        thread=threading.Thread(target=callback);thread.start();threads.append(thread)
    result=connect_swiggy.connection(SimpleNamespace(save=saved.append),ready=ready,timeout=2)
    for thread in threads:thread.join(5)
    assert result is False and statuses==[400,400] and not saved
    assert calls==['/auth/register']
