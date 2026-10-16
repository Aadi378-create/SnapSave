function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);
}
function utcDate(value) { return new Date(value && !/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value+"Z" : value); }
function singleFlightPolling(callback, interval) {
  let stopped=false, timer=null, failures=0;
  const run=async()=>{
    if(stopped) return;
    try { if(!document.hidden) { await callback(); failures=0; } }
    catch(e) { failures=Math.min(failures+1,3); }
    if(!stopped) timer=setTimeout(run,interval*Math.pow(2,failures));
  };
  timer=setTimeout(run,interval);
  return ()=>{stopped=true; clearTimeout(timer);};
}
function showAlert(containerId, msg, type="error") {
  const element=document.getElementById(containerId);
  if(element) element.textContent=msg;
}
window.SnapSaveAuth = {
  auth:null, api:null, verifier:null, confirmation:null,
  async initialize() {
    if(this.auth) return;
    const [apps,api]=await Promise.all([import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"), import("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js")]);
    const app=apps.getApps()[0] || apps.initializeApp({apiKey:"AIzaSyC2usgMofYuKhLrmERkuYgFY0WmNkfMXIY",authDomain:"snapsave-501c7.firebaseapp.com",projectId:"snapsave-501c7",appId:"1:20754709166:web:22949551e251e0e9078b3f"});
    this.api=api; this.auth=api.getAuth(app);
    await this.auth.authStateReady();
  },
  async token() { await this.initialize(); return this.auth.currentUser ? this.auth.currentUser.getIdToken() : null; },
  async send(phone) {
    await this.initialize();
    if(this.verifier) this.verifier.clear();
    document.getElementById("staff-recaptcha").replaceChildren();
    this.verifier=new this.api.RecaptchaVerifier(this.auth,"staff-recaptcha",{size:"normal"});
    this.confirmation=await this.api.signInWithPhoneNumber(this.auth,phone,this.verifier);
  },
  async verify(code) { const result=await this.confirmation.confirm(code); return result.user.getIdToken(); },
  async logout() { if(this.auth) await this.api.signOut(this.auth); }
};
