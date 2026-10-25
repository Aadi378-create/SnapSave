"""Real DOM tests; Firebase and external network are replaced with test identities."""
from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import pytest
import models

FRONTEND=Path(__file__).resolve().parents[2]/"SnapSave-FRONTEND"

@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        yield browser
        browser.close()

def open_app(browser,client,actor,db,file,firebase_unavailable=False,auth_unavailable=False):
    user=db.get(models.User,actor["id"])
    user.first_name="Test";user.last_name="User";user.email=actor["id"]+"@example.com";db.commit()
    page=browser.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    token=actor["headers"]["Authorization"][7:]
    page.add_init_script("globalThis.__test_signouts=0;globalThis.__test_token="+__import__('json').dumps(token))
    def route(request_route):
        request=request_route.request
        parsed=urlparse(request.url)
        if parsed.netloc=="www.gstatic.com":
            if firebase_unavailable:
                request_route.abort('failed');return
            if "firebase-app.js" in parsed.path:
                script="export const initializeApp=()=>({});export const getApps=()=>[];"
            else:
                script='''const user={getIdToken:async(force)=>{globalThis.__forced_token_refreshes=(globalThis.__forced_token_refreshes||0)+(force?1:0);return globalThis.__test_token;}};
                export const getAuth=()=>({currentUser:user,authStateReady:async()=>{}});
                export const onAuthStateChanged=(a,cb)=>queueMicrotask(()=>cb(user));
                export const signOut=async()=>{globalThis.__test_signouts++;};export class RecaptchaVerifier{};
                export const signInWithPhoneNumber=async()=>({confirm:async()=>({user})});'''
            request_route.fulfill(body=script,content_type="application/javascript",headers={"Access-Control-Allow-Origin":"*"})
        elif parsed.path.startswith("/api/"):
            if auth_unavailable and parsed.path=='/api/auth/me':
                request_route.fulfill(status=503,body='{"detail":"Synthetic authentication outage"}',headers={"Content-Type":"application/json","Access-Control-Allow-Origin":"*"});return
            headers={k:v for k,v in request.headers.items() if k in {"authorization","content-type","idempotency-key"}}
            result=client.request(request.method,parsed.path+("?"+parsed.query if parsed.query else ""),headers=headers,content=request.post_data)
            request_route.fulfill(status=result.status_code,body=result.content,headers={"Content-Type":result.headers.get("content-type","application/json"),"Access-Control-Allow-Origin":"*"})
        elif parsed.netloc=="snapsave.test":
            name=parsed.path.lstrip("/") or file
            target=(FRONTEND/name).resolve()
            if target.is_relative_to(FRONTEND) and target.is_file():
                request_route.fulfill(body=target.read_bytes(),content_type=mimetypes.guess_type(target.name)[0] or "text/plain")
            else:request_route.fulfill(status=404,body="Not found")
        else:request_route.fulfill(status=200,body="",content_type="text/css")
    page.route("**/*",route)
    page.goto("https://snapsave.test/"+file)
    return page,errors

def test_customer_history_new_order_and_safe_chat(browser,client,actors,quoted,db):
    customer=actors["customer"]
    payload='<img src=x onerror="window.auditInjected=true">'
    client.post(f"/api/chat/{customer['id']}/send",headers=customer["headers"],json={"order_id":quoted["id"],"message":payload})
    row=db.get(models.Order,quoted["id"]);row.status="delivered";db.commit()
    second=client.post("/api/orders",headers=customer["headers"],json={"address_id":quoted["address_id"],"items":[{"name":"Eggs","quantity":6}]}).json()
    page,errors=open_app(browser,client,customer,db,"index.html")
    try:
        page.wait_for_function("document.querySelector('#dashboard-app').style.display==='flex'")
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('pending review')")
        page.evaluate("id=>window.viewHistoryOrder(id)",quoted["id"])
        page.wait_for_function("document.querySelector('#active-order-container').textContent.includes('delivered')")
        assert page.locator("#chat-stream").inner_text().find(payload)>=0
        assert page.evaluate("window.auditInjected") is None
        assert page.locator("#chat-textarea").is_disabled()
        page.evaluate("window.startNewOrder()")
        assert page.locator("#chat-textarea").is_enabled()
        assert "No active order" in page.locator("#active-order-container").inner_text()
        assert not errors,errors
    finally:page.close()

def test_moderator_sees_own_chat_and_safe_customer_text(browser,client,actors,quoted,db):
    payload='<img src=x onerror="window.auditInjected=true">'
    client.post(f"/api/chat/{actors['customer']['id']}/send",headers=actors["customer"]["headers"],json={"order_id":quoted["id"],"message":payload})
    page,errors=open_app(browser,client,actors["moderator"],db,"admin.html")
    try:
        page.locator(".queue-card").first.wait_for()
        page.locator(".queue-card").first.click()
        page.wait_for_function("document.querySelector('#chat-messages').textContent.includes('onerror')")
        assert payload in page.locator("#chat-messages").inner_text()
        assert page.locator("#composer-text").is_enabled()
        assert page.evaluate("window.auditInjected") is None
        assert not errors,errors
    finally:page.close()

def test_submitting_quote_cannot_mutate_another_selected_ticket(browser,client,actors,quoted,db):
    customer=actors["customer"]
    second=client.post("/api/orders",headers=customer["headers"],json={"address_id":quoted["address_id"],"items":[{"name":"Eggs","quantity":1}]}).json()
    client.put(f"/api/moderator/orders/{second['id']}/claim",headers=actors["moderator"]["headers"])
    page,errors=open_app(browser,client,actors["moderator"],db,"admin.html")
    try:
        page.locator(".queue-card").first.wait_for()
        page.locator(".queue-card").first.click()
        page.locator(".pi-price").first.wait_for()
        page.locator("#btn-preview-quote").click()
        page.locator("#quote-preview-block").wait_for(state="visible")
        page.evaluate('''()=>{
          const original=window.fetch;
          window.__releaseQuote=null;
          window.fetch=async(url,options)=>{
            if(String(url).endsWith('/price')) await new Promise(resolve=>window.__releaseQuote=resolve);
            return original(url,options);
          };
          window.submitPrices();
        }''')
        page.wait_for_function("window.__releaseQuote!==null")
        page.locator('.orders-tab[data-tab="queue"]').click()
        page.locator(".queue-card").nth(1).click()
        page.wait_for_function("document.querySelector('#ticket-detail-panel').textContent.includes('Eggs')")
        page.evaluate("window.__releaseQuote()")
        page.wait_for_function("!document.querySelector('#btn-submit-prices').disabled")
        assert "Eggs" in page.locator("#prices-list").inner_text()
        assert page.locator("#awaiting-customer-block").is_hidden()
        assert not errors,errors
    finally:
        page.evaluate("if(window.__releaseQuote)window.__releaseQuote()")
        page.close()

def test_admin_can_find_and_reconcile_archived_legacy_payment(browser,client,actors,order,db):
    row=db.get(models.Order,order["id"])
    row.status="cancelled";row.payment_status="reconciliation_required";row.customer_paid=205;row.confirmed_at=None
    db.commit()
    page,errors=open_app(browser,client,actors["admin"],db,"admin.html")
    try:
        page.locator("#queue-filter").wait_for(state="visible")
        page.locator("#queue-filter").select_option("cancelled")
        page.locator(".queue-card").first.wait_for()
        page.locator(".queue-card").first.click()
        page.locator("#cancelled-payment-button").wait_for(state="visible")
        answers=iter(["RECEIVED","archived-bank-receipt","205"])
        page.on("dialog",lambda dialog:dialog.accept(next(answers)))
        page.locator("#cancelled-payment-button").click()
        page.locator("#refund-verification-button").wait_for(state="visible")
        assert page.locator("#cancelled-payment-button").is_hidden()
        db.refresh(row)
        assert row.payment_status=="refund_required" and row.payment_reference=="archived-bank-receipt"
        assert not errors,errors
    finally:page.close()

def test_admin_operational_cards_show_actual_order_counts(browser,client,actors,quoted,db):
    for status,count in {"pending_review":2,"awaiting_payment":3,"delivered":4,"completed":1,"cancelled":1}.items():
        for _ in range(count):
            db.add(models.Order(user_id=actors["customer"]["id"],store="zepto",status=status,delivery_street="Test street",delivery_city="Pune",delivery_postal_code="411004",subtotal=0,delivery_fee=0,platform_fee=0,final_price=0))
    db.commit()
    page,errors=open_app(browser,client,actors["admin"],db,"admin.html")
    try:
        page.wait_for_function("document.querySelector('#metric-orders-pending')?.textContent==='2'")
        expected={"metric-orders-pending":"2","metric-orders-awaiting":"1","metric-orders-confirmed":"3","metric-orders-delivered":"4"}
        for element,value in expected.items():
            assert page.locator("#"+element).inner_text()==value
        assert not errors,errors
    finally:page.close()
