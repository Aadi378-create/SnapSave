"""Guest sign-in states with simulated Firebase; no SMS or real CAPTCHA calls."""
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse
import pytest
import models

@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        instance=runtime.chromium.launch(headless=True)
        yield instance
        instance.close()

FRONTEND=Path(__file__).resolve().parents[2]/"SnapSave-FRONTEND"
AUTH_FIXTURE=r'''
const mock=window.__authMock={sends:[],confirms:[],failSend:false,failCaptcha:false,latestCaptcha:null};
const listeners=[];
const user={getIdToken:async()=>window.__testToken};
const auth={currentUser:null,authStateReady:async()=>{}};
export const getAuth=()=>auth;
export const onAuthStateChanged=(a,cb)=>{listeners.push(cb);queueMicrotask(()=>cb(a.currentUser));return ()=>{};};
export const signOut=async()=>{auth.currentUser=null;listeners.forEach(cb=>queueMicrotask(()=>cb(null)));};
export class RecaptchaVerifier {
  constructor(a,container,options){this.container=document.getElementById(container);this.options=options;mock.latestCaptcha=options;}
  async render(){
    if(mock.failCaptcha)throw {code:'auth/network-request-failed'};
    const button=document.createElement('button');button.type='button';button.textContent='Complete test security check';
    button.style.cssText=`width:${this.options.size==='compact'?166:304}px;height:${this.options.size==='compact'?144:78}px;border:1px solid #ddd;border-radius:4px;background:#fafafa;color:#111;`;
    button.onclick=()=>this.options.callback('fixture-captcha-token');
    this.container.appendChild(button);return 1;
  }
  clear(){this.container.replaceChildren();}
}
export const signInWithPhoneNumber=async(a,phone,verifier)=>{
  mock.sends.push(phone);
  if(mock.failSend)throw {code:'auth/network-request-failed'};
  return {confirm:async(code)=>{
    mock.confirms.push(code);
    if(code!=='123456')throw {code:'auth/invalid-verification-code'};
    auth.currentUser=user;listeners.forEach(cb=>queueMicrotask(()=>cb(user)));return {user};
  }};
};
'''

def guest(browser,client,actor,db,file,width=1280):
    person=db.get(models.User,actor["id"])
    person.first_name="Test";person.last_name="User";person.email="login-fixture@example.com";db.commit()
    context=browser.new_context(viewport={"width":width,"height":900})
    page=context.new_page();errors=[];requests=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.add_init_script("window.__testToken="+json.dumps(actor["headers"]["Authorization"][7:]))
    def route(handler):
        request=handler.request;parsed=urlparse(request.url)
        if parsed.netloc=="www.gstatic.com":
            script="export const initializeApp=()=>({});export const getApps=()=>[];" if "firebase-app.js" in parsed.path else AUTH_FIXTURE
            handler.fulfill(body=script,content_type="application/javascript",headers={"Access-Control-Allow-Origin":"*"})
        elif parsed.path.startswith("/api/"):
            requests.append(parsed.path)
            headers={k:v for k,v in request.headers.items() if k in {"authorization","content-type"}}
            response=client.request(request.method,parsed.path+("?"+parsed.query if parsed.query else ""),headers=headers,content=request.post_data)
            handler.fulfill(status=response.status_code,body=response.content,headers={"Content-Type":response.headers.get("content-type","application/json"),"Access-Control-Allow-Origin":"*"})
        elif parsed.netloc=="snapsave.test":
            target=(FRONTEND/(parsed.path.lstrip("/") or file)).resolve()
            if target.is_relative_to(FRONTEND) and target.is_file():handler.fulfill(body=target.read_bytes(),content_type=mimetypes.guess_type(target.name)[0] or "text/plain")
            else:handler.fulfill(status=404,body="Not found")
        else:handler.fulfill(body="",content_type="text/css")
    page.route("**/*",route);page.goto("http://snapsave.test/"+file)
    return context,page,errors,requests

def screenshot(page,name):
    destination=os.getenv("SNAPSAVE_UI_ARTIFACTS")
    if destination:
        path=Path(destination);path.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(path/(name+".png")),full_page=True)

@pytest.mark.parametrize("file,role",[("index.html","customer"),("admin.html","admin")])
@pytest.mark.parametrize("width",[320,390,1280])
def test_phone_captcha_otp_layout_and_keyboard_sign_in(browser,client,actors,db,file,role,width):
    context,page,errors,requests=guest(browser,client,actors[role],db,file,width)
    try:
        phone=page.get_by_label("Phone number",exact=True);send=page.get_by_role("button",name="Send code",exact=True)
        assert send.is_disabled()
        phone.fill("98765 43210")
        challenge=page.get_by_role("button",name="Complete test security check")
        challenge.wait_for();assert send.is_disabled()
        card=page.locator(".login-card").bounding_box();phone_box=phone.bounding_box();captcha_box=challenge.bounding_box();send_box=send.bounding_box()
        assert phone_box["y"]+phone_box["height"]<captcha_box["y"]
        assert captcha_box["y"]+captcha_box["height"]<send_box["y"]
        assert card["x"]<=captcha_box["x"] and captcha_box["x"]+captcha_box["width"]<=card["x"]+card["width"]
        assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"),page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>window.innerWidth+1}).map(e=>({tag:e.tagName,id:e.id,class:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).slice(0,12)")
        if width in (320,1280):screenshot(page,file+f"-phone-{width}")
        challenge.click();phone.press("Enter")
        page.locator("[data-auth-otp-form]").wait_for(state="visible")
        assert page.locator("[data-auth-phone-form]").is_hidden()
        assert "+91 98765 43210" in page.locator("[data-auth-destination]").inner_text()
        code=page.get_by_label("Verification code",exact=True);verify=page.get_by_role("button",name="Verify & sign in",exact=True)
        assert verify.is_disabled()
        if width in (320,1280):screenshot(page,file+f"-otp-{width}")
        code.fill("12x456");assert verify.is_disabled()
        code_box=code.bounding_box();verify_box=verify.bounding_box()
        assert code_box["y"]+code_box["height"]<verify_box["y"]
        code.fill("123456");code.press("Enter")
        page.locator("#dashboard-app" if file=="index.html" else "#dashboard-header").wait_for(state="visible")
        assert page.evaluate("window.__authMock.sends")==["+919876543210"]
        assert page.evaluate("window.__authMock.confirms")==["123456"]
        assert requests.count("/api/auth/me")==1
        assert not errors,errors
    finally:context.close()

@pytest.mark.parametrize("file,role",[("index.html","customer"),("admin.html","admin")])
def test_login_failure_retry_resend_and_expired_challenge(browser,client,actors,db,file,role):
    context,page,errors,requests=guest(browser,client,actors[role],db,file)
    try:
        page.clock.install()
        phone=page.get_by_label("Phone number",exact=True);phone.fill("9876543210")
        challenge=page.get_by_role("button",name="Complete test security check");challenge.click()
        page.evaluate("window.__authMock.latestCaptcha['expired-callback']()")
        assert page.get_by_role("button",name="Send code",exact=True).is_disabled()
        challenge.click();page.evaluate("window.__authMock.failSend=true")
        # Repeated Enter/click callbacks must create only one in-flight request.
        callback="sendOTP" if file=="index.html" else "handleProductionLogin"
        page.evaluate(f"()=>{{window.{callback}();window.{callback}();}}")
        page.get_by_text("Could not connect. Check your connection and try again.",exact=True).wait_for()
        assert page.evaluate("window.__authMock.sends.length")==1
        page.evaluate("window.__authMock.failSend=false")
        page.get_by_role("button",name="Complete test security check").click()
        page.get_by_role("button",name="Send code",exact=True).click()
        code=page.get_by_label("Verification code",exact=True);code.wait_for(state="visible");code.fill("111111")
        page.get_by_role("button",name="Verify & sign in",exact=True).click()
        page.get_by_text("That code is incorrect. Check the SMS and try again.",exact=True).wait_for()
        assert code.get_attribute("aria-invalid")=="true"
        page.get_by_role("button",name="Change number",exact=True).click()
        assert page.get_by_role("button",name="Send again in 60s",exact=True).is_disabled()
        page.clock.fast_forward(61000)
        page.get_by_role("button",name="Complete test security check").click()
        page.get_by_role("button",name="Send code",exact=True).click()
        page.locator("[data-auth-otp-form]").wait_for(state="visible")
        page.clock.fast_forward(61000)
        page.get_by_role("button",name="Resend code",exact=True).click()
        assert page.locator("[data-auth-phone-form]").is_visible() and code.input_value()==""
        assert page.evaluate("window.__authMock.confirms")==["111111"]
        assert not errors,errors
    finally:context.close()
