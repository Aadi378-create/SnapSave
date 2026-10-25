"""Documented Instamart MCP product search. No cart/order/address tools are exposed."""
import ctypes
import json
import math
import os
from pathlib import Path
import secrets
import time
import requests

BASE='https://mcp.swiggy.com'
CALLBACK='http://localhost:8765/oauth/callback'

class SwiggyUnavailable(ValueError):pass
class SwiggyAuthorizationRequired(SwiggyUnavailable):pass
class IncompleteRPCResponse(SwiggyUnavailable):pass


def dpapi(data,decrypt=False):
    if os.name!='nt':raise SwiggyUnavailable('Windows DPAPI is required for local credential storage')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise SwiggyUnavailable('Could not protect local Swiggy credentials')
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)


class CredentialStore:
    def __init__(self,path):self.path=Path(path)
    def load(self):
        if not self.path.is_file():raise SwiggyAuthorizationRequired('Connect Swiggy once using connect_swiggy.py')
        if self.path.stat().st_size>200000:raise SwiggyUnavailable('Invalid credential file')
        try:
            value=json.loads(dpapi(self.path.read_bytes(),True))
            if (not isinstance(value,dict) or not valid_token(value.get('access_token'))
                or (value.get('refresh_token') is not None and not valid_token(value['refresh_token']))
                or type(value.get('expires_at')) not in {int,float} or not math.isfinite(value['expires_at'])
                or not isinstance(value.get('client_id'),str) or not 1<=len(value['client_id'])<=256):
                raise ValueError('Invalid credential data')
            return value
        except (ValueError,UnicodeError) as error:raise SwiggyAuthorizationRequired('Stored Swiggy credentials are invalid; reconnect') from error
    def save(self,data):
        protected=dpapi(json.dumps(data).encode())
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_name(self.path.name+'.'+secrets.token_hex(6)+'.tmp')
        try:
            temporary.write_bytes(protected);os.replace(temporary,self.path)
        finally:temporary.unlink(missing_ok=True)


def oauth_json(path,payload,session=None):
    if path not in {'/auth/register','/auth/token'}:raise SwiggyUnavailable('Unsupported OAuth endpoint')
    try:
        with (session or requests).post(BASE+path,json=payload,timeout=(4,15),stream=True,allow_redirects=False) as response:
            if response.status_code not in {200,201}:
                if response.status_code in {400,401,403,419}:raise SwiggyAuthorizationRequired('Swiggy authorization could not be completed; HTTP '+str(response.status_code))
                raise SwiggyUnavailable('Swiggy authorization temporarily unavailable; HTTP '+str(response.status_code))
            content=bytearray();deadline=time.monotonic()+20
            for chunk in response.iter_content(8192):
                if len(content)+len(chunk)>100000 or time.monotonic()>deadline:raise SwiggyUnavailable('Oversized authorization response or time budget exceeded')
                content.extend(chunk)
            try:result=json.loads(content.decode('utf-8'))
            except (ValueError,UnicodeError) as error:raise SwiggyUnavailable('Invalid authorization response') from error
            if not isinstance(result,dict):raise SwiggyUnavailable('Invalid authorization response')
            return result
    except requests.RequestException as error:raise SwiggyUnavailable('Swiggy authorization connection failed') from error


def valid_token(value):
    return isinstance(value,str) and 1<=len(value)<=65536 and all(33<=ord(char)<=126 for char in value)


def token_record(data,client_id):
    token=data.get('access_token');refresh=data.get('refresh_token');expires=data.get('expires_in')
    if not valid_token(token) or (refresh is not None and not valid_token(refresh)) or not isinstance(client_id,str) or not 1<=len(client_id)<=256 or type(expires) not in {int,float} or not math.isfinite(expires) or not 0<expires<=31536000:
        raise SwiggyUnavailable('Swiggy returned invalid credentials')
    return {'access_token':token,'refresh_token':refresh,'expires_at':time.time()+expires,'client_id':client_id}


def rpc_payload(text,request_id):
    """Support the documented JSON-RPC transport's JSON and SSE responses."""
    try:
        candidates=[json.loads(text)]
    except ValueError:
        candidates=[]
        for event in text.replace('\r\n','\n').split('\n\n'):
            data='\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
            if data:
                try:candidates.append(json.loads(data))
                except ValueError:continue
    for payload in candidates:
        if not isinstance(payload,dict) or payload.get('id')!=request_id:continue
        if 'error' in payload:
            if isinstance(payload['error'],dict) and payload['error'].get('code')==-32001:raise SwiggyAuthorizationRequired('Swiggy session needs authorization')
            raise SwiggyUnavailable('Swiggy rejected the MCP request')
        if isinstance(payload.get('result'),dict):return payload['result']
    raise IncompleteRPCResponse('No matching MCP response was returned')


class SwiggySearchClient:
    def __init__(self,store,session=None):
        self.store=store;self.session=session or requests.Session();self.credentials=None;self.session_id=None;self.identity=0;self.initialized=False;self.protocol="2025-03-26"
    def close(self):self.session.close()
    def refresh(self):
        if not self.credentials.get('refresh_token'):raise SwiggyAuthorizationRequired('Reconnect Swiggy to continue')
        data=oauth_json('/auth/token',{'grant_type':'refresh_token','refresh_token':self.credentials['refresh_token']},self.session)
        self.credentials=token_record(data,self.credentials['client_id']);self.store.save(self.credentials);self.session_id=None;self.initialized=False
    def _rpc(self,method,params,notify=False):
        self.identity+=1;identity=self.identity
        body={'jsonrpc':'2.0','method':method,'params':params}
        if not notify:body['id']=identity
        headers={'Authorization':'Bearer '+self.credentials['access_token'],'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
        if self.session_id:headers['Mcp-Session-Id']=self.session_id
        if self.initialized:headers['MCP-Protocol-Version']=self.protocol
        try:
            with self.session.post(BASE+'/im',json=body,headers=headers,timeout=(4,15),stream=True,allow_redirects=False) as response:
                if response.status_code in {401,419}:raise SwiggyAuthorizationRequired('Swiggy session needs authorization')
                if response.status_code not in {200,202}:raise SwiggyUnavailable('Instamart MCP unavailable; HTTP '+str(response.status_code))
                session_id=response.headers.get('Mcp-Session-Id')
                if session_id:
                    if not 1<=len(session_id)<=256 or any(ord(c)<33 or ord(c)>126 for c in session_id):raise SwiggyUnavailable('Invalid MCP session')
                    self.session_id=session_id
                if notify:return {}
                content=bytearray();deadline=time.monotonic()+20;received=0
                event_stream='text/event-stream' in response.headers.get('Content-Type','')
                for chunk in response.iter_content(1 if event_stream else 16384):
                    received+=len(chunk)
                    if received>2000000 or time.monotonic()>deadline:raise SwiggyUnavailable('MCP response exceeded size/time budget')
                    content.extend(chunk)
                    if event_stream and (content.endswith(b'\n\n') or content.endswith(b'\r\n\r\n')):
                        event=content.decode('utf-8');content.clear()
                        try:return rpc_payload(event,identity)
                        except IncompleteRPCResponse:continue
                return rpc_payload(content.decode('utf-8'),identity)
        except requests.RequestException as error:raise SwiggyUnavailable('Instamart MCP connection failed') from error
    def call_tool(self,name,arguments):
        if name!='search_products':raise SwiggyUnavailable('Only read-only product search is allowed')
        if set(arguments)-{'query','latitude','longitude','offset'}:raise SwiggyUnavailable('Unsupported search arguments')
        query=arguments.get('query')
        if not isinstance(query,str) or not 1<=len(query.strip())<=255:raise SwiggyUnavailable('Supply a product query')
        for key,limit in (('latitude',90),('longitude',180)):
            value=arguments.get(key)
            if type(value) not in {int,float} or not math.isfinite(value) or not -limit<=value<=limit:raise SwiggyUnavailable('Supply verified guest coordinates')
        offset=arguments.get('offset',0)
        if type(offset) is not int or not 0<=offset<=10000:raise SwiggyUnavailable('Invalid search offset')
        loaded=self.store.load()
        if not self.credentials or loaded.get("access_token")!=self.credentials.get("access_token"):
            self.session_id=None;self.initialized=False
        self.credentials=loaded
        for attempt in range(2):
            try:
                if self.credentials.get('expires_at',0)<=time.time()+60:self.refresh()
                if not self.initialized:
                    initialization=self._rpc('initialize',{'protocolVersion':self.protocol,'capabilities':{},'clientInfo':{'name':'SnapSave-read-only-product-search','version':'0.1.0'}})
                    self.protocol=initialization.get('protocolVersion',self.protocol)
                    if self.protocol not in {'2024-11-05','2025-03-26','2025-06-18','2025-11-25'}:raise SwiggyUnavailable('Unsupported MCP protocol version')
                    self.initialized=True
                    self._rpc('notifications/initialized',{},notify=True)
                result=self._rpc('tools/call',{'name':name,'arguments':arguments})
                if result.get('isError'):raise SwiggyUnavailable('Instamart product search returned an error')
                value=result.get('structuredContent')
                if value is None:
                    for block in result.get('content',[]):
                        if block.get('type')=='text':
                            try:value=json.loads(block['text']);break
                            except (ValueError,KeyError):continue
                if not isinstance(value,dict) or value.get('success') is not True or not isinstance(value.get('data'),dict):raise SwiggyUnavailable('No structured product data was returned')
                return value['data']
            except SwiggyAuthorizationRequired:
                if attempt:raise
                self.refresh()
        raise SwiggyAuthorizationRequired('Reconnect Swiggy')
