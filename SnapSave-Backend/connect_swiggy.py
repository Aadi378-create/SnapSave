"""One-time official Swiggy consent setup. Does not call carts, payments or orders."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlencode,urlsplit,parse_qs
from core.swiggy_mcp import BASE,CALLBACK,CredentialStore,oauth_json,token_record,SwiggyUnavailable


def connection(store,ready=None,timeout=600):
    verifier=secrets.token_urlsafe(48);state=secrets.token_urlsafe(32)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    finished=threading.Event();outcome=[]
    client_id=None
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # Never log authorization codes or tokens.
        def do_GET(self):
            host=self.headers.get('Host','').lower()
            origin=self.headers.get('Origin')
            if host not in {'localhost:8765','127.0.0.1:8765'} or origin not in {None,BASE,'http://localhost:8765'} or len(self.path)>16384:
                self.send_error(400,'Invalid callback origin');return
            try:
                parsed=urlsplit(self.path);query=parse_qs(parsed.query,max_num_fields=8)
            except ValueError:self.send_error(400,'Invalid authorization callback');return
            states=query.get('state',[])
            state_valid=len(states)==1 and states[0].isascii() and secrets.compare_digest(states[0],state)
            valid=(parsed.path=='/oauth/callback' and state_valid and len(query.get('code',[]))==1 and 1<=len(query['code'][0])<=8192)
            if not valid:self.send_error(400,'Invalid authorization callback');return
            try:
                data=oauth_json('/auth/token',{'grant_type':'authorization_code','code':query['code'][0],'code_verifier':verifier,'redirect_uri':CALLBACK,'client_id':client_id})
                store.save(token_record(data,client_id));outcome.append(True)
                message=b'Swiggy connected securely. You may close this tab.'
            except Exception:
                outcome.append(False);message=b'Connection failed. Restart the connection setup; no tokens were logged.'
            self.send_response(200 if outcome[-1] else 502);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(message);finished.set()
    class CallbackServer(HTTPServer):
        def get_request(self):
            connection,address=super().get_request();connection.settimeout(5);return connection,address
    server=CallbackServer(('127.0.0.1',8765),Callback);server.timeout=1
    try:
        registration=oauth_json('/auth/register',{'client_name':'SnapSave Read-only Product Research','redirect_uris':[CALLBACK],'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'token_endpoint_auth_method':'none'})
        client_id=registration.get('client_id')
        if not isinstance(client_id,str) or not client_id:raise SwiggyUnavailable('Swiggy client registration failed')
        url=BASE+'/auth/authorize?'+urlencode({'response_type':'code','client_id':client_id,'redirect_uri':CALLBACK,'code_challenge':challenge,'code_challenge_method':'S256','state':state,'scope':'mcp:tools'})
        (ready or print)(url)
        deadline=time.monotonic()+timeout
        while not finished.is_set() and time.monotonic()<deadline:server.handle_request()
        return bool(outcome and outcome[-1])
    finally:server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    store=CredentialStore(Path(__file__).resolve().parents[1]/'.private-backups/swiggy-oauth.dpapi')
    if args.prepare:
        print('Ready: localhost callback 8765, PKCE/state validation, Windows DPAPI storage, product-search-only client. No account authorization has been granted.');return
    if not connection(store):raise SystemExit('Swiggy connection incomplete. No account credentials were printed.')
    print('Swiggy connection saved with Windows DPAPI. No product/cart/order calls were made.')

if __name__=='__main__':main()
